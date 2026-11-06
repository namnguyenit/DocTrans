"""Local transport routing and native process cleanup; no GPU/model required."""
import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import unittest
import urllib.request
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/System"))
from local_cuda_server import LocalCudaServer


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.seen = []
        outer = self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_POST(self):
                if self.headers.get("Authorization") != "Bearer test-session":
                    self.send_error(401)
                    return
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.seen.append(payload)
                rows = [{"index": i, "content": text} for i, text in enumerate(payload["prompt"])]
                data = json.dumps(list(reversed(rows))).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        self.http = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.http.server_close)
        self.addCleanup(lambda: self.thread.join(2))
        self.addCleanup(self.http.shutdown)
        self.client = LocalCudaServer.__new__(LocalCudaServer)
        self.client.process = None
        self.client.key = "test-session"
        self.client.generation_options = {"temperature": 0.0, "repeat_penalty": 1.0, "seed": 42}
        self.client.base_url = f"http://127.0.0.1:{self.http.server_port}"
        self.client.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def test_proxy_settings_do_not_redirect_document_text_and_responses_are_reordered(self):
        with mock.patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:1", "NO_PROXY": ""}):
            rows = self.client.complete_batch(["Document A: TCP port", "Document B: shipping port"], 80)
        self.assertEqual([row["content"] for row in rows], ["Document A: TCP port", "Document B: shipping port"])
        self.assertEqual(self.seen[0]["n_predict"], 80)
        self.assertFalse(self.seen[0]["cache_prompt"])

    def test_duplicate_or_missing_indices_are_rejected(self):
        for rows in ([{"index": 0}, {"index": 0}], [{"index": 0}], [{}, {}]):
            with self.subTest(rows=rows), mock.patch.object(self.client, "request", return_value=rows):
                with self.assertRaises(RuntimeError):
                    self.client.complete_batch(["A", "B"], 80)


@unittest.skipUnless(os.name == "nt", "Windows process ownership")
class ProcessOwnershipTests(unittest.TestCase):
    def test_force_killing_owner_terminates_native_child(self):
        from ctypes import WinDLL, wintypes
        kernel = WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        # Use the base interpreter to avoid testing the venv launcher instead of
        # the Python process that owns the native server's job handle.
        python = getattr(sys, "_base_executable", sys.executable)
        source = (
            "import sys,subprocess,time; "
            f"sys.path.insert(0,{str(ROOT / 'src/System')!r}); "
            "from local_cuda_server import attach_kill_job; "
            "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],creationflags=0x08000000); "
            "job=attach_kill_job(p); print(p.pid,flush=True); time.sleep(60)"
        )
        owner = subprocess.Popen([python, "-c", source], stdout=subprocess.PIPE, text=True,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        handle = None
        try:
            child_pid = int(owner.stdout.readline().strip())
            handle = kernel.OpenProcess(0x00100000, False, child_pid)
            self.assertTrue(handle)
            owner.kill()
            owner.wait(timeout=5)
            self.assertEqual(kernel.WaitForSingleObject(handle, 5000), 0, "native child must not retain GPU after owner dies")
        finally:
            if owner.poll() is None:
                owner.kill()
                owner.wait(timeout=5)
            if handle:
                kernel.CloseHandle(handle)
            owner.stdout.close()


if __name__ == "__main__":
    unittest.main()
