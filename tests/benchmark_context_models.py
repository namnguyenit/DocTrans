"""Offline contextual translation probe; synthetic examples, no quality leaderboard.

Run once per model in a fresh process using READDOC_POLISH_MODEL. Keeps VinAI
resident to reflect the app's actual GPU memory requirement. Outputs all drafts
and final translations so semantic correctness can be reviewed, not inferred
from speed or keyword matching. --profile records actual CUDA operator usage.
"""
import argparse
import importlib.util
import json
import pathlib
import statistics
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
CASES = [
    ("software-driver", "The driver must be restarted.",
     "This chapter describes a GPU device driver in the operating system. The graphics card stopped responding."),
    ("vehicle-driver", "The driver must be rested.",
     "The truck driver has been driving all night. Fatigue causes road accidents."),
    ("network-port", "The port is blocked.",
     "A firewall controls incoming TCP connections to the web server. Check port 443."),
    ("shipping-port", "The port is blocked.",
     "Cargo ships cannot enter the harbour because a damaged vessel obstructs the shipping channel."),
    ("electric-charge", "The charge was reduced.",
     "The capacitor stores electrical energy. An engineer discharged it through a resistor."),
    ("service-charge", "The charge was reduced.",
     "The bank agreed to lower its monthly account service fee after the customer complained."),
    ("manufacturing-plant", "The plant stopped operating.",
     "The factory produces steel. A power outage interrupted the entire production line."),
    ("negation", "A timeout does not necessarily mean that the remote device has failed.",
     "A congested network may delay a response even when the hardware is working normally."),
    ("numbers", "Reduce the timeout from 250 ms to 125 ms, but do not change the 3 retries.",
     "These are network configuration parameters. Preserve all numeric values and units."),
    ("placeholder", "Set `max_connections` to 64 and keep {user_id} unchanged.",
     "This is a configuration manual. Backticked identifiers and placeholders must remain unchanged."),
    ("condition", "The buffer may be reused only after all pending writes have completed.",
     "Reusing the memory too early causes data corruption in asynchronous storage operations."),
    ("pronoun", "It must release the lock before returning.",
     "The interrupt handler acquired a spinlock. The scheduler is waiting to run another thread."),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--repeats", type=int, default=2)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("context_daemon", ROOT / "src/System/local_nmt_daemon.py")
    daemon = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(daemon)
    daemon.cache_get = lambda _: None
    daemon.cache_put = lambda *_: None
    daemon.init_model()
    if not daemon.is_ready or not daemon.torch.cuda.is_available():
        raise RuntimeError("CUDA VinAI must load")
    drafts = daemon.translate_text_batch([row[1] for row in CASES])
    daemon._init_polish_model_background()
    if not daemon.polish_ready:
        raise RuntimeError("Context model did not load")
    torch = daemon.torch
    report = {"model": daemon.polish_model_name, "path": daemon.POLISH_MODEL_PATH,
              "torch": torch.__version__, "gpu": torch.cuda.get_device_name(0),
              "greedy": True, "cases": [], "measurements": []}
    outputs = {}
    for mode in ("without_context", "with_context"):
        items = [(i, row[1], drafts[i], row[2] if mode == "with_context" else "")
                 for i, row in enumerate(CASES)]
        daemon.polish_batch(items[:2])
        timings = []
        torch.cuda.reset_peak_memory_stats()
        for _ in range(args.repeats):
            torch.cuda.synchronize()
            start = time.perf_counter()
            outputs[mode] = dict(daemon.polish_batch(items))
            torch.cuda.synchronize()
            timings.append(time.perf_counter() - start)
        report["measurements"].append({"mode": mode, "seconds": statistics.median(timings),
                                       "runs_seconds": timings,
                                       "peak_allocated_mib": torch.cuda.max_memory_allocated() / 2**20,
                                       "peak_reserved_mib": torch.cuda.max_memory_reserved() / 2**20})
    for i, row in enumerate(CASES):
        report["cases"].append({"case": row[0], "source": row[1], "context": row[2],
                                "vinai": drafts[i], **{mode: values[i] for mode, values in outputs.items()}})
    if args.profile:
        with torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CPU,
                                                 torch.profiler.ProfilerActivity.CUDA]) as profile:
            daemon.polish_batch(items[:2])
        ops = profile.key_averages()
        report["cuda_operators"] = [{"name": op.key, "calls": op.count,
                                       "device_time_us": op.device_time_total}
                                      for op in ops if any(term in op.key.lower() for term in
                                                           ("attention", "gemm", "matmul", "linear", "4bit"))]
        report["profiler_table"] = ops.table(sort_by="self_device_time_total", row_limit=18)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"model": report["model"], "measurements": report["measurements"]}))


if __name__ == "__main__":
    main()
