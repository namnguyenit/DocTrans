"""Managed, loopback-only llama.cpp CUDA engine. Never downloads anything."""
import atexit
import ctypes
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request


def find_server(models_root=None):
    configured = os.environ.get("READDOC_LLAMA_SERVER")
    if configured:
        path = Path(configured)
        return path.resolve() if path.is_file() else None
    if os.name != "nt":
        return None
    roots = [Path.cwd(), *Path(__file__).resolve().parents]
    if models_root:
        roots.insert(0, Path(models_root).parent)
    for root in roots:
        path = root / "tools/llama-cpp/b11739/llama-server.exe"
        if path.is_file():
            return path.resolve()
    return None


def attach_kill_job(process):
    """Windows closes this job handle even if Qt force-kills the Python daemon."""
    if os.name != "nt":
        return None
    from ctypes import wintypes as w
    class Basic(ctypes.Structure):
        _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                    ("flags", w.DWORD), ("min_working_set", ctypes.c_size_t),
                    ("max_working_set", ctypes.c_size_t), ("active_processes", w.DWORD),
                    ("affinity", ctypes.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]
    class IO(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in
                    ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]
    class Extended(ctypes.Structure):
        _fields_ = [("basic", Basic), ("io", IO), ("process_memory", ctypes.c_size_t),
                    ("job_memory", ctypes.c_size_t), ("peak_process_memory", ctypes.c_size_t),
                    ("peak_job_memory", ctypes.c_size_t)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
    kernel.CreateJobObjectW.restype = w.HANDLE
    kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    info = Extended()
    info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if (not kernel.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
            or not kernel.AssignProcessToJobObject(job, w.HANDLE(int(process._handle)))):
        error = ctypes.get_last_error()
        kernel.CloseHandle(job)
        raise ctypes.WinError(error)
    return kernel, job


class LocalCudaServer:
    def __init__(self, model_path, executable, slots=8, context_per_slot=2048, cache_ram_mib=0):
        self.process = None
        self.job = None
        self.log = tempfile.TemporaryFile(mode="w+b")
        self.context_per_slot = context_per_slot
        self.slots = slots
        self.cache_ram_mib = max(0, min(1024, int(cache_ram_mib)))
        # A small presence penalty prevents Qwen3.5 from looping on PDF leaders.
        self.generation_options = {"temperature": 0.2, "top_p": 0.8, "top_k": 20, "min_p": 0.0,
                                   "presence_penalty": 1.0, "repeat_penalty": 1.0, "seed": 42}
        self.key = secrets.token_urlsafe(32)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.base_url = f"http://127.0.0.1:{port}"
        env = os.environ.copy()
        env["LLAMA_API_KEY"] = self.key
        command = [str(executable), "--model", str(model_path), "--host", "127.0.0.1", "--port", str(port),
                   "--device", "CUDA0", "--n-gpu-layers", "all", "--fit", "off", "--flash-attn", "on",
                   "--parallel", str(slots), "--ctx-size", str(slots * context_per_slot),
                   "--batch-size", "512", "--ubatch-size", "256", "--threads", "4",
                   "--cache-ram", str(self.cache_ram_mib),
                   "--ctx-checkpoints", "0",
                   "--cont-batching", "--no-context-shift", "--no-webui", "--offline"]
        try:
            self.process = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL,
                                            stdout=self.log, stderr=subprocess.STDOUT,
                                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            self.job = attach_kill_job(self.process)
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError("CUDA engine exited during startup: " + self.log_tail())
                try:
                    if self.request("/health", timeout=1).get("status") == "ok":
                        atexit.register(self.close)
                        return
                except (OSError, urllib.error.URLError):
                    pass
                time.sleep(0.15)
            raise RuntimeError("CUDA engine startup timed out: " + self.log_tail())
        except BaseException:
            self.close()
            raise

    def request(self, path, payload=None, timeout=120):
        if self.process is not None and self.process.poll() is not None:
            raise RuntimeError("Local CUDA engine stopped")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(self.base_url + path, body,
                                         {"Content-Type": "application/json", "Authorization": "Bearer " + self.key})
        with self.opener.open(request, timeout=timeout) as response:
            return json.load(response)

    def complete_batch(self, prompts, max_tokens, cache_prompt=False):
        result = self.request("/completion", {"prompt": prompts, "n_predict": max_tokens,
                                              **self.generation_options,
                                              "cache_prompt": cache_prompt, "stream": False,
                                              "stop": ["<|im_end|>"]})
        rows = result if isinstance(result, list) else [result]
        if len(rows) != len(prompts):
            raise RuntimeError("CUDA engine returned an incomplete batch")
        indices = [row.get("index") for row in rows]
        if not all(isinstance(i, int) for i in indices) or set(indices) != set(range(len(prompts))):
            raise RuntimeError("CUDA engine returned invalid response indices")
        rows.sort(key=lambda row: row["index"])
        return rows

    def log_tail(self):
        self.log.seek(0, os.SEEK_END)
        size = self.log.tell()
        self.log.seek(max(0, size - 4000))
        return self.log.read().decode("utf-8", errors="replace")

    def close(self):
        atexit.unregister(self.close)
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.job is not None:
            kernel, handle = self.job
            kernel.CloseHandle(handle)
            self.job = None
        if not self.log.closed:
            self.log.close()
