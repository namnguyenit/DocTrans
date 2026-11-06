"""Measure the real reader/model process tree on a local PDF (no uploads)."""
import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

import psutil

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--requests", type=int, default=1024)
    parser.add_argument("--seconds", type=int, default=600)
    parser.add_argument("--fake", action="store_true", help="Only test structural capacity, without model weights")
    args = parser.parse_args()
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["READDOC_RESOURCE_DIR"] = str(ROOT / "build" / ("test_resources" if args.fake else "resources"))
    env["READDOC_PYTHON"] = sys.executable
    if not args.fake:
        env["READDOC_STRESS_REQUIRE_CUDA"] = "1"
    else:
        env.pop("READDOC_STRESS_REQUIRE_CUDA", None)
    if os.name == "nt":
        env["PATH"] = r"C:\msys64\ucrt64\bin;C:\msys64\usr\bin;" + env["PATH"]
    command = [str(ROOT / "build" / ("large_pdf_stress.exe" if os.name == "nt" else "large_pdf_stress")),
               "--input", str(args.input), "--report", str(args.report), "--requests", str(args.requests),
               "--seconds", str(args.seconds), "--screenshot", str(args.report.with_suffix(".png"))]
    readings = []
    started = time.monotonic()
    with args.report.with_suffix(".log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, env=env, stdout=log, stderr=log)
        owner = psutil.Process(process.pid)
        try:
            while process.poll() is None:
                try:
                    tree = [owner, *owner.children(recursive=True)]
                    rss = sum(p.memory_info().rss for p in tree if p.is_running()) / 2**20
                    free = psutil.virtual_memory().available / 2**20
                    gpu = subprocess.check_output(
                        ["nvidia-smi", "--query-gpu=memory.used,utilization.gpu", "--format=csv,noheader,nounits"],
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0, text=True)
                    memory, utilization = map(int, gpu.strip().split(","))
                    readings.append((rss, free, memory, utilization))
                except (OSError, psutil.Error, ValueError):
                    pass
                if time.monotonic() - started > args.seconds + 30:
                    raise TimeoutError("Reader did not exit after its time budget")
                time.sleep(0.5)
        finally:
            if process.poll() is None:
                # Only processes created by this benchmark are stopped.
                for child in reversed(owner.children(recursive=True)):
                    try:
                        child.kill()
                    except psutil.Error:
                        pass
                process.kill()
            process.wait(timeout=10)
    if not args.report.is_file():
        raise RuntimeError(f"Reader exited {process.returncode} without a report")
    report = json.loads(args.report.read_text(encoding="utf-8"))
    report.update({"test_mode": "structural_fake" if args.fake else "real_cuda",
                   "exit_code": process.returncode,
                   "process_tree_peak_rss_mib": max((r[0] for r in readings), default=0),
                   "system_min_available_mib": min((r[1] for r in readings), default=0),
                   "gpu_peak_total_mib": max((r[2] for r in readings), default=0),
                   "gpu_utilization_mean_including_startup": statistics.mean(r[3] for r in readings) if readings else 0})
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)
    if process.returncode:
        raise SystemExit(process.returncode)


if __name__ == "__main__":
    main()
