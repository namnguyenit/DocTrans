"""Install the tested Windows CUDA refinement profile; never reads documents.

Run with readDoc's Python environment. Downloads pinned public model/tokenizer
files and the official llama.cpp CUDA runtime into this project only.
"""
import argparse
import hashlib
from pathlib import Path
import urllib.request
import zipfile
from huggingface_hub import hf_hub_download, snapshot_download

ROOT = Path(__file__).resolve().parent
RUNTIME_ASSETS = {
    "llama-b11739-bin-win-cuda-12.4-x64.zip": "8b92d285dbd4a1378861a3466996b194a91cd984c2ec1ee9db2d4672cf2c30e1",
    "cudart-llama-bin-win-cuda-12.4-x64.zip": "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-only", action="store_true")
    args = parser.parse_args()
    if not args.runtime_only:
        target = ROOT / "models/polish/Qwen3.5-4B-GGUF"
        hf_hub_download("unsloth/Qwen3.5-4B-GGUF", "Qwen3.5-4B-Q6_K.gguf",
                        revision="e87f176479d0855a907a41277aca2f8ee7a09523", local_dir=target)
        snapshot_download("Qwen/Qwen3.5-4B", revision="851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a",
                          local_dir=target, allow_patterns=["tokenizer*.json", "special_tokens_map.json",
                                                           "chat_template.jinja", "config.json", "LICENSE"])
    destination = ROOT / "tools/llama-cpp/b11739"
    destination.mkdir(parents=True, exist_ok=True)
    downloads = ROOT / "build/downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    for name, expected in RUNTIME_ASSETS.items():
        archive = downloads / name
        if not archive.is_file():
            partial = archive.with_suffix(".partial")
            urllib.request.urlretrieve(f"https://github.com/ggml-org/llama.cpp/releases/download/b11739/{name}", partial)
            partial.replace(archive)
        with archive.open("rb") as file:
            actual = hashlib.file_digest(file, "sha256").hexdigest()
        if actual != expected:
            raise RuntimeError(f"SHA256 mismatch for {archive.name}")
        with zipfile.ZipFile(archive) as bundle:
            for entry in bundle.infolist():
                if not (destination / entry.filename).resolve().is_relative_to(destination.resolve()):
                    raise RuntimeError("Archive path escapes runtime directory")
            bundle.extractall(destination)
    urllib.request.urlretrieve("https://raw.githubusercontent.com/ggml-org/llama.cpp/b11739/LICENSE",
                               destination / "LICENSE-llama.cpp")
    print("CUDA refinement profile installed. Restart readDoc to load it.")


if __name__ == "__main__":
    main()
