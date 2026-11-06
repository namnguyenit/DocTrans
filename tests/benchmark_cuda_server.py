"""Compare a continuous CUDA batch on synthetic context translation cases."""
import argparse
import importlib.util
import json
import pathlib
import statistics
import sys
import time
from benchmark_context_models import CASES, ROOT

sys.path.insert(0, str(ROOT / "src/System"))
from local_cuda_server import LocalCudaServer, find_server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=pathlib.Path, required=True)
    parser.add_argument("--slots", type=int, default=4)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("cuda_probe", ROOT / "src/System/local_nmt_daemon.py")
    daemon = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(daemon)
    daemon.cache_get = lambda _: None
    daemon.cache_put = lambda *_: None
    daemon.init_model()
    drafts = daemon.translate_text_batch([row[1] for row in CASES])
    if not daemon.is_ready or not daemon.torch.cuda.is_available():
        raise RuntimeError("CUDA VinAI must be resident")
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(args.model.parent, local_files_only=True)
    daemon.polish_tokenizer = tok
    daemon.polish_profile = "qwen"
    daemon.POLISH_TASK = "translate"
    engine = LocalCudaServer(args.model.resolve(), find_server(ROOT / "models"), slots=args.slots)
    try:
        prompts = [daemon.polish_prompt(row[1], drafts[i], row[2]) for i, row in enumerate(CASES)]
        engine.complete_batch(prompts[:2], 384, cache_prompt=False)
        timings = []
        for _ in range(3):
            start = time.perf_counter()
            outputs = engine.complete_batch(prompts, 384, cache_prompt=False)
            timings.append(time.perf_counter() - start)
        cases = [{"case": row[0], "source": row[1], "context": row[2], "vinai": drafts[i],
                  "translated": outputs[i]["content"].strip(), "stop_type": outputs[i].get("stop_type"),
                  "index": outputs[i].get("index"), "truncated": outputs[i].get("truncated"),
                  "timings": outputs[i].get("timings")}
                 for i, row in enumerate(CASES)]
        report = {"model": str(args.model), "slots": args.slots, "runs_seconds": timings,
                  "seconds": statistics.median(timings), "cases": cases}
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"seconds": report["seconds"], "runs": timings}))
    finally:
        engine.close()


if __name__ == "__main__":
    main()
