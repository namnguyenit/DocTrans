"""Compare local decoding policies on actual early PDF units and body text."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import time

ROOT = Path(__file__).resolve().parents[1]
PROFILES = {
    "greedy": {"temperature": 0.0, "repeat_penalty": 1.0, "presence_penalty": 0.0, "seed": 42},
    "qwen_recommended": {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "min_p": 0.0,
                         "presence_penalty": 1.5, "repeat_penalty": 1.0, "seed": 42},
    "conservative": {"temperature": 0.2, "top_p": 0.8, "top_k": 20, "min_p": 0.0,
                     "presence_penalty": 1.0, "repeat_penalty": 1.0, "seed": 42},
}


def split_units(text):
    chunks, current = [], ""
    for sentence in re.split(r"(?<=[.!?])\s+(?=[A-ZÀ-Ỹ0-9])", text.strip()):
        part = sentence.strip()
        while len(part) > 300:
            if current:
                chunks.append(current); current = ""
            cut = part.rfind(" ", 0, 301)
            if cut < 150:
                cut = 300
            chunks.append(part[:cut].strip()); part = part[cut:].strip()
        if current and len(current) + len(part) + 1 > 300:
            chunks.append(current); current = ""
        current = (current + " " + part).strip()
    if current:
        chunks.append(current)
    return chunks


def corpus(layout, count):
    pages = json.loads(layout.read_text(encoding="utf-8"))["pages"]
    units = [part for page in pages for block in page["blocks"]
             if not block.get("is_watermark") and block["text"].strip()
             for part in split_units(block["text"])]
    candidates = []
    for i, text in enumerate(units):
        remaining = re.sub(r"\b0[xX][0-9A-Fa-f]+\b|\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b", "", text)
        if not any(c.isalpha() for c in remaining) or re.search(r"\b(?:void|class|def|import)\s|#include|public:", text):
            continue
        context = ("Previous passage: " + units[i-1][-270:] + "\n") if i else ""
        if i+1 < len(units):
            context += "Next passage: " + units[i+1][:270]
        candidates.append((text, context))
    head = candidates[:count]
    body = [pair for pair in candidates[count:] if len(pair[0]) >= 50 and len(pair[0].split()) >= 5]
    return head + [body[i * len(body) // count] for i in range(count)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--each", type=int, default=64)
    parser.add_argument("--profiles", default=",".join(PROFILES))
    args = parser.parse_args()
    selected = corpus(args.layout, args.each)
    spec = importlib.util.spec_from_file_location("daemon", ROOT / "src/System/local_nmt_daemon.py")
    daemon = importlib.util.module_from_spec(spec); spec.loader.exec_module(daemon)
    daemon.cache_get = lambda _: None; daemon.cache_put = lambda *_: None
    daemon.init_model(); daemon._load_polish_model()
    if not daemon.polish_ready:
        raise RuntimeError("CUDA model is required")
    drafts = daemon.translate_text_batch([pair[0] for pair in selected])
    items = [(i, pair[0], drafts[i], pair[1]) for i, pair in enumerate(selected)]
    engine = daemon.polish_model
    original = engine.complete_batch
    audit, rows = [], []
    def complete(prompts, limit):
        result = original(prompts, limit, cache_prompt=False)
        audit.extend(result)
        return result
    engine.complete_batch = complete
    try:
        for name in args.profiles.split(","):
            engine.generation_options = PROFILES[name].copy()
            daemon.polish_batch(items[-8:])
            audit.clear(); daemon.snapshot_polish_metrics(reset=True)
            start = time.perf_counter(); outputs = daemon.polish_batch(items)
            elapsed = time.perf_counter() - start
            row = {"profile": name, "settings": engine.generation_options, "units": len(items),
                   "head_units": args.each, "seconds": elapsed, "units_per_second": len(items)/elapsed,
                   "metrics": daemon.snapshot_polish_metrics()}
            rows.append(row)
            args.output.write_text(json.dumps({"profiles": rows}, indent=2), encoding="utf-8")
            # Audit stays local; never upload PDF text or full model responses.
            args.output.with_name(args.output.stem + "_local_audit.json").write_text(
                json.dumps({"profile": name, "samples": [dict(source=item[1], raw=item[2], final=dict(outputs)[item[0]])
                for item in items], "native_responses": audit}, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(row), flush=True)
    finally:
        engine.close()


if __name__ == "__main__":
    main()
