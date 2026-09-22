#!/usr/bin/env python3
"""Convert the private VinAI MBART checkpoint to a CPU-friendly CT2 model.

The published checkpoint contains more embedding rows than tokenizer entries.
CTranslate2 validates these sizes strictly, so the unused tail is represented by
stable placeholder tokens. Existing token IDs are never reordered or changed.
"""

import argparse
from pathlib import Path

from ctranslate2.converters import TransformersConverter
from ctranslate2.converters.transformers import BartLoader, MBartLoader


def padded_mbart_vocabulary(self, model, tokenizer):
    tokens = BartLoader.get_vocabulary(self, model, tokenizer)
    embedding_rows = int(model.model.shared.weight.shape[0])
    if len(tokens) > embedding_rows:
        return tokens[:embedding_rows]
    existing = set(tokens)
    index = 0
    while len(tokens) < embedding_rows:
        candidate = f"<unused_readdoc_{index:04d}>"
        index += 1
        if candidate not in existing:
            tokens.append(candidate)
            existing.add(candidate)
    return tokens


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    source = Path(args.source).resolve()
    output = Path(args.output).resolve()
    if not (source / "pytorch_model.bin").is_file():
        raise SystemExit(f"Missing model weights in {source}")
    if not (source / "sentencepiece.bpe.model").is_file():
        raise SystemExit(f"Missing tokenizer model in {source}")

    MBartLoader.get_vocabulary = padded_mbart_vocabulary
    converter = TransformersConverter(
        str(source),
        low_cpu_mem_usage=False,
    )
    converter.convert(str(output), quantization="int8", force=True)
    print(f"Converted INT8 model: {output}", flush=True)


if __name__ == "__main__":
    main()
