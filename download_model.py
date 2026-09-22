#!/usr/bin/env python3
"""Script to download the VinAI translation model, RapidOCR models, and Arcee-VyLinh GGUF polish model for portable offline use."""

import os
import shutil
import sys
from pathlib import Path

MODEL_ID = "vinai/vinai-translate-en2vi"
POLISH_REPO_ID = "QuantFactory/Arcee-VyLinh-GGUF"
POLISH_FILENAME = "Arcee-VyLinh.Q6_K.gguf"

SCRIPT_DIR = Path(__file__).resolve().parent
MODELS_DIR = SCRIPT_DIR / "models"
NMT_DIR = MODELS_DIR / "vinai-translate-en2vi"
OCR_DIR = MODELS_DIR / "ocr"
POLISH_DIR = MODELS_DIR / "polish"


def download_vinai():
    os.makedirs(NMT_DIR, exist_ok=True)
    if (NMT_DIR / "model.safetensors").exists() and (NMT_DIR / "config.json").exists():
        print(f"1. VinAI translation model already present in {NMT_DIR} [SKIP]")
        return

    print(f"1. Downloading VinAI translation model ({MODEL_ID}) -> {NMT_DIR} ...")
    try:
        from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
    except ImportError:
        print("Please install transformers: pip install transformers", file=sys.stderr)
        return

    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    tokenizer.save_pretrained(NMT_DIR)
    print("   [OK] Tokenizer saved.")

    model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_ID)
    model.save_pretrained(NMT_DIR)
    print("   [OK] Model weights saved.")


def download_ocr():
    os.makedirs(OCR_DIR, exist_ok=True)
    print(f"2. Exporting RapidOCR models -> {OCR_DIR} ...")
    try:
        import rapidocr_onnxruntime
        pkg_dir = Path(rapidocr_onnxruntime.__file__).parent
        for f in pkg_dir.rglob("*.onnx"):
            dst = OCR_DIR / f.name
            shutil.copy2(f, dst)
            print(f"   [OK] Copied {f.name}")
    except Exception as e:
        print(f"   [Notice] Could not auto-copy OCR models: {e}")


def download_polish_model():
    os.makedirs(POLISH_DIR, exist_ok=True)
    dest_path = POLISH_DIR / POLISH_FILENAME
    if dest_path.exists() and dest_path.stat().st_size > 1000000000:
        print(f"3. Arcee-VyLinh polish model already present: {dest_path} [SKIP]")
        return

    print(f"3. Downloading Arcee-VyLinh GGUF ({POLISH_FILENAME}) from {POLISH_REPO_ID} ...")
    try:
        from huggingface_hub import hf_hub_download
        downloaded = hf_hub_download(
            repo_id=POLISH_REPO_ID,
            filename=POLISH_FILENAME,
            local_dir=str(POLISH_DIR),
            local_dir_use_symlinks=False,
        )
        print(f"   [OK] Downloaded polish model to {downloaded}")
    except Exception as e:
        print(f"   [Warning] Could not download Arcee-VyLinh: {e}", file=sys.stderr)


def download():
    print(f"=== Downloading models for readDoc portable offline use ===")
    os.environ.pop("HF_HUB_OFFLINE", None)
    os.environ.pop("TRANSFORMERS_OFFLINE", None)

    download_vinai()
    download_ocr()
    download_polish_model()

    print("\nAll done! Models are saved in './models/' folder.")
    print("You can copy the 'models/' folder to any other computer for 100% offline usage.")


if __name__ == "__main__":
    download()
