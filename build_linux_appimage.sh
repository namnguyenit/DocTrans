#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
OUTPUT_DIR="$PROJECT_DIR/dist/linux-x86_64"
MODEL_DIR="$OUTPUT_DIR/model"
SNAPSHOT_ID=13af6b73fdb5b7dbb770c96d13a871fba13a87d4
TOKENIZER_SNAPSHOT="${READDOC_HF_MODEL_SNAPSHOT:-$HOME/.cache/huggingface/hub/models--vinai--vinai-translate-en2vi/snapshots/$SNAPSHOT_ID}"
TOKENIZER_DIR="$OUTPUT_DIR/tokenizer-source"

if ! command -v docker >/dev/null 2>&1; then
    echo "Docker is required to build the Linux x86_64 AppImage." >&2
    exit 1
fi
if [[ ! -f "$MODEL_DIR/model.bin" ]]; then
    echo "Missing converted INT8 model: $MODEL_DIR/model.bin" >&2
    echo "Run the model conversion step before packaging." >&2
    exit 1
fi
if [[ ! -f "$TOKENIZER_SNAPSHOT/config.json" || \
      ! -f "$TOKENIZER_SNAPSHOT/sentencepiece.bpe.model" ]]; then
    echo "Missing local VinAI tokenizer snapshot: $TOKENIZER_SNAPSHOT" >&2
    exit 1
fi

mkdir -p "$OUTPUT_DIR" "$TOKENIZER_DIR"
cp -L "$TOKENIZER_SNAPSHOT/config.json" "$TOKENIZER_DIR/config.json"
cp -L "$TOKENIZER_SNAPSHOT/sentencepiece.bpe.model" \
    "$TOKENIZER_DIR/sentencepiece.bpe.model"
docker build --platform linux/amd64 \
    -t readdoc-linux-builder:22.04 \
    -f "$PROJECT_DIR/packaging/linux/Dockerfile" \
    "$PROJECT_DIR/packaging/linux"
docker run --rm --platform linux/amd64 \
    -e "HOST_UID=$(id -u)" \
    -e "HOST_GID=$(id -g)" \
    -v "$PROJECT_DIR:/src:ro" \
    -v "$MODEL_DIR:/model-src:ro" \
    -v "$TOKENIZER_DIR:/tokenizer-src:ro" \
    -v "$OUTPUT_DIR:/out" \
    readdoc-linux-builder:22.04

echo "Linux package ready:"
ls -lh "$OUTPUT_DIR/readDoc-1.0.0-Linux-x86_64.AppImage" \
    "$OUTPUT_DIR/readDoc-1.0.0-Linux-x86_64.AppImage.sha256"
