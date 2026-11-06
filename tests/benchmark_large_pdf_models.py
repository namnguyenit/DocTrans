"""Real-document CUDA tuning. Input and inference stay on this machine."""
import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import statistics
import subprocess
import threading
import time
import psutil

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=128)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--profiles", default="4:2048,8:1024,8:2048")
    args = parser.parse_args()
    pages = json.loads(args.layout.read_text(encoding="utf-8"))["pages"]
    corpus = []
    for page in pages:
        blocks = [b["text"].strip() for b in page["blocks"] if not b.get("is_watermark") and b["text"].strip()]
        for i, text in enumerate(blocks):
            if len(text) < 50 or len(re.findall(r"[A-Za-z]{3,}", text)) < 5:
                continue
            # Same bounded fragments and source neighbours as the PDF viewer.
            remaining = text
            parts = []
            while len(remaining) > 300:
                cut = remaining.rfind(" ", 0, 301)
                if cut < 150:
                    cut = 300
                parts.append(remaining[:cut].strip())
                remaining = remaining[cut:].strip()
            if remaining:
                parts.append(remaining)
            context = (("Previous passage: " + blocks[i-1][-270:] + "\n") if i else "")
            if i+1 < len(blocks):
                context += "Next passage: " + blocks[i+1][:270]
            corpus.extend((part, context) for part in parts)
    count = min(args.samples, len(corpus))
    samples = [corpus[math.floor(i * len(corpus) / count)] for i in range(count)]
    spec = importlib.util.spec_from_file_location("large_pdf_daemon", ROOT / "src/System/local_nmt_daemon.py")
    daemon = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(daemon)
    daemon.cache_get = lambda _: None
    daemon.cache_put = lambda *_: None
    daemon.init_model()
    if not daemon.is_ready or not daemon.torch.cuda.is_available():
        raise RuntimeError("CUDA VinAI required")
    source = [row[0] for row in samples]
    drafts = daemon.translate_text_batch(source)
    items = [(i, source[i], drafts[i], row[1]) for i, row in enumerate(samples)]
    report = {"pages_loaded": len(pages), "candidate_fragments": len(corpus), "samples": count,
              "source_chars": sum(len(s) for s in source), "profiles": []}
    for profile in args.profiles.split(","):
        slots, context_size = map(int, profile.split(":"))
        if daemon.polish_backend == "llama_server_cuda":
            daemon.polish_model.close()
        daemon.torch.cuda.empty_cache()
        os.environ["READDOC_LLAMA_SLOTS"] = str(slots)
        os.environ["READDOC_LLAMA_CONTEXT_PER_SLOT"] = str(context_size)
        daemon.polish_ready = False
        daemon._load_polish_model()
        if not daemon.polish_ready:
            raise RuntimeError("CUDA engine failed to load")
        engine = daemon.polish_model
        original_complete = engine.complete_batch
        engine.complete_batch = lambda prompts, limit: original_complete(prompts, limit, cache_prompt=False)
        daemon.polish_batch(items[:24])
        daemon.snapshot_polish_metrics(reset=True)
        readings = []
        stopped = threading.Event()
        def monitor():
            process = psutil.Process()
            while not stopped.is_set():
                try:
                    gpu = subprocess.check_output(
                        ["nvidia-smi", "--query-gpu=memory.used,utilization.gpu", "--format=csv,noheader,nounits"],
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0, text=True)
                    memory, utilization = map(int, gpu.strip().split(","))
                    rss = sum(p.memory_info().rss for p in [process, *process.children(recursive=True)] if p.is_running())
                    readings.append((memory, utilization, rss / 2**20))
                except (OSError, psutil.Error, ValueError):
                    pass
                stopped.wait(0.5)
        thread = threading.Thread(target=monitor, daemon=True)
        thread.start()
        nmt_started = time.perf_counter()
        daemon.translate_text_batch(source)  # Also measure with native weights resident.
        nmt_seconds = time.perf_counter() - nmt_started
        runs = []
        try:
            for _ in range(args.repeats):
                started = time.perf_counter()
                outputs = daemon.polish_batch(items)
                runs.append(time.perf_counter() - started)
                if len(outputs) != count or {r[0] for r in outputs} != set(range(count)):
                    raise RuntimeError("Missing or misrouted response")
        finally:
            stopped.set()
            thread.join(3)
        row = {"slots": slots, "context_per_slot": context_size, "prompt_cache_ram_mib": engine.cache_ram_mib,
               "nmt_seconds": nmt_seconds,
               "seconds": statistics.median(runs), "runs_seconds": runs,
               "units_per_second": count / statistics.median(runs), "metrics": daemon.snapshot_polish_metrics(),
               "gpu_peak_total_mib": max((r[0] for r in readings), default=0),
               "gpu_utilization_mean": statistics.mean(r[1] for r in readings) if readings else 0,
               "process_tree_peak_rss_mib": max((r[2] for r in readings), default=0)}
        report["profiles"].append(row)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(row), flush=True)
    daemon.polish_model.close()


if __name__ == "__main__":
    main()
