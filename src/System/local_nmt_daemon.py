#!/usr/bin/env python3
"""Private, local-only English to Vietnamese translation daemon with 2-Stage Pipeline (VinAI Fast NMT + Arcee-VyLinh Background LLM Polish)."""

import json
import hashlib
import os
import queue
import re
import sqlite3
import sys
import platform
import threading
import time
import warnings
from collections import OrderedDict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")

# Privacy is a hard requirement: model loading must never contact the Hub.
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_DATASETS_OFFLINE"] = "1"
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
warnings.filterwarnings("ignore")

# Ensure CUDA DLLs are found on Windows for llama-cpp
if platform.system() == "Windows":
    try:
        import torch
        torch_lib = os.path.join(os.path.dirname(torch.__file__), "lib")
        if os.path.exists(torch_lib):
            os.add_dll_directory(torch_lib)
    except Exception:
        pass


def find_models_root():
    if "READDOC_MODELS_DIR" in os.environ:
        p = Path(os.environ["READDOC_MODELS_DIR"])
        if p.exists() and p.is_dir():
            return p

    search_roots = [
        Path(__file__).resolve().parent,
        Path.cwd(),
    ]
    for root in search_roots:
        curr = root.resolve()
        for _ in range(7):
            if (curr / "models").exists() and (curr / "models").is_dir():
                return (curr / "models").resolve()
            if curr.parent == curr:
                break
            curr = curr.parent
    return None


MODELS_ROOT = find_models_root()


def resolve_model_path():
    if "READDOC_NMT_MODEL" in os.environ:
        return os.environ["READDOC_NMT_MODEL"]
    
    if MODELS_ROOT:
        c = MODELS_ROOT / "vinai-translate-en2vi"
        if (c / "config.json").exists():
            return str(c.resolve())
    
    script_dir = Path(__file__).resolve().parent
    candidates = [
        script_dir / "../../../../models/vinai-translate-en2vi",
        script_dir / "../../../models/vinai-translate-en2vi",
        script_dir / "../../models/vinai-translate-en2vi",
        script_dir / "../models/vinai-translate-en2vi",
        script_dir / "models/vinai-translate-en2vi",
        Path.cwd() / "models/vinai-translate-en2vi",
        script_dir / "model",
    ]
    for c in candidates:
        if (c / "config.json").exists():
            return str(c.resolve())
    return "vinai/vinai-translate-en2vi"


def resolve_polish_model_path():
    if "READDOC_POLISH_MODEL" in os.environ:
        p = Path(os.environ["READDOC_POLISH_MODEL"])
        if p.exists():
            return str(p.resolve())
    
    if MODELS_ROOT:
        c0 = MODELS_ROOT / "polish" / "Arcee-VyLinh"
        if c0.is_dir() and (c0 / "config.json").exists():
            return str(c0.resolve())
        c1 = MODELS_ROOT / "polish" / "Arcee-VyLinh.Q6_K.gguf"
        if c1.exists() and c1.stat().st_size > 100000000:
            return str(c1.resolve())
        c2 = MODELS_ROOT / "Arcee-VyLinh.Q6_K.gguf"
        if c2.exists() and c2.stat().st_size > 100000000:
            return str(c2.resolve())
        if (MODELS_ROOT / "polish").exists():
            for f in (MODELS_ROOT / "polish").glob("*.gguf"):
                if f.stat().st_size > 100000000:
                    return str(f.resolve())
        for f in MODELS_ROOT.glob("*.gguf"):
            if f.stat().st_size > 100000000:
                return str(f.resolve())
    
    script_dir = Path(__file__).resolve().parent
    search_dirs = [
        script_dir / "../../../../models/polish/Arcee-VyLinh",
        script_dir / "../../../models/polish/Arcee-VyLinh",
        script_dir / "../../models/polish/Arcee-VyLinh",
        script_dir / "../models/polish/Arcee-VyLinh",
        script_dir / "models/polish/Arcee-VyLinh",
        Path.cwd() / "models/polish/Arcee-VyLinh",
        script_dir / "../../../../models/polish",
        script_dir / "../../../models/polish",
        script_dir / "../../models/polish",
        script_dir / "../models/polish",
        script_dir / "models/polish",
        Path.cwd() / "models/polish",
        script_dir / "../../../../models",
        script_dir / "../../../models",
        script_dir / "../../models",
        script_dir / "../models",
        script_dir / "models",
        Path.cwd() / "models",
    ]
    for d in search_dirs:
        if d.is_dir() and (d / "config.json").exists():
            return str(d.resolve())
        if d.is_dir():
            for f in d.glob("*.gguf"):
                if f.stat().st_size > 100000000:
                    return str(f.resolve())
    return None


MODEL_NAME = resolve_model_path()
TOKENIZER_NAME = os.environ.get("READDOC_NMT_TOKENIZER", MODEL_NAME)
REQUESTED_BACKEND = os.environ.get("READDOC_NMT_BACKEND", "pytorch").lower()
POLISH_MODEL_PATH = resolve_polish_model_path()

MAX_SOURCE_TOKENS = int(os.environ.get("READDOC_NMT_MAX_SOURCE_TOKENS", "96"))
MICRO_BATCH_SIZE = int(os.environ.get("READDOC_NMT_BATCH_SIZE", "32"))          # RTX 4070 safe
TOKEN_BATCH_BUDGET = int(os.environ.get("READDOC_NMT_TOKEN_BUDGET", "3072"))     # KV-cache safe
REQUEST_TOKEN_BUDGET = int(os.environ.get("READDOC_NMT_REQUEST_TOKEN_BUDGET", "3072"))
RESPONSE_GROUP_SIZE = int(os.environ.get("READDOC_NMT_RESPONSE_GROUP_SIZE", "32"))  # Smaller JSON batches
POLISH_QUEUE_MAX    = int(os.environ.get("READDOC_POLISH_QUEUE_MAX", "512"))       # Stop queue bloat
CACHE_CAPACITY = int(os.environ.get("READDOC_NMT_CACHE_SIZE", "4096"))
CACHE_SCHEMA_VERSION = "5"
TARGET_LANGUAGE = "vi_VN"
SEGMENTATION_VERSION = "page-units-300-v2"

cache = OrderedDict()
is_ready = False
model = None
tokenizer = None
torch = None
device = None
backend_name = "uninitialized"
cache_db = None
model_fingerprint = "uninitialized"

## Polish LLM state
polish_model = None
polish_tokenizer = None
polish_ready = False
polish_backend = "none"
polish_model_name = "none"
polish_queue = queue.Queue(maxsize=POLISH_QUEUE_MAX)   # Bounded to prevent memory bloat
polish_thread = None
stdout_lock = threading.Lock()


def emit_json(obj):
    with stdout_lock:
        print(json.dumps(obj, ensure_ascii=False), flush=True)


def cache_database_path():
    override = os.environ.get("READDOC_CACHE_DB")
    if override:
        return Path(override)
    if platform.system() == "Darwin":
        root = Path.home() / "Library/Application Support"
    else:
        root = Path(os.environ.get(
            "XDG_DATA_HOME", Path.home() / ".local/share"
        ))
    return root / "readDoc/translation_memory.sqlite3"


CACHE_DB_PATH = cache_database_path()


def load_glossary():
    glossary_path = Path(__file__).with_name("technical_glossary.json")
    try:
        with glossary_path.open("r", encoding="utf-8") as stream:
            data = json.load(stream)
            return sorted(data.items(), key=lambda item: len(item[0]), reverse=True)
    except (OSError, ValueError) as exc:
        print(f"Glossary disabled: {exc}", file=sys.stderr, flush=True)
        return []


GLOSSARY = load_glossary()
GLOSSARY_FINGERPRINT = hashlib.sha256(
    json.dumps(GLOSSARY, ensure_ascii=False, sort_keys=True).encode("utf-8")
).hexdigest()[:16]

# Identifiers, commands, paths, URLs and numeric constants should remain verbatim.
TECH_TOKEN_RE = re.compile(
    r"https?://\S+|"
    r"(?<!\w)--?[a-zA-Z][\w-]*|"
    r"(?:[/~.]?[\w.-]+/)+[\w.-]+|"
    r"\b(?:0x[0-9a-fA-F]+|[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+)\b|"
    r"\b[a-zA-Z][a-zA-Z0-9]*_[a-zA-Z0-9_]+(?:\(\))?\b|"
    r"`[^`]+`"
)
PLACEHOLDER_RE = re.compile(r"__TECH\d+__")
SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9`\[])")


def protect_technical_text(text):
    replacements = []
    def repl(m):
        idx = len(replacements)
        token = m.group(0)
        replacements.append(token)
        return f"__TECH{idx}__"
    return TECH_TOKEN_RE.sub(repl, text), replacements


def restore_technical_text(text, replacements):
    def repl(m):
        try:
            idx = int(m.group(0)[6:-2])
            return replacements[idx] if idx < len(replacements) else m.group(0)
        except (ValueError, IndexError):
            return m.group(0)
    return PLACEHOLDER_RE.sub(repl, text)


def token_count(text):
    if not text:
        return 0
    return len(text.split())


def split_long_text(text, max_tokens=MAX_SOURCE_TOKENS):
    if not text or token_count(text) <= max_tokens:
        return [text] if text else []
    sentences = SENTENCE_BOUNDARY_RE.split(text)
    chunks = []
    current = []
    current_tokens = 0
    for sentence in sentences:
        sentence_tokens = token_count(sentence)
        if current and current_tokens + sentence_tokens > max_tokens:
            chunks.append(" ".join(current))
            current = [sentence]
            current_tokens = sentence_tokens
        else:
            current.append(sentence)
            current_tokens += sentence_tokens
    if current:
        chunks.append(" ".join(current))
    return chunks or [text]


def clean_output(text):
    if not text:
        return ""
    return text.replace("«", "").replace("»", "").replace("_BAR_", "").strip()


def secure_cache_permissions():
    paths = (
        CACHE_DB_PATH,
        Path(str(CACHE_DB_PATH) + "-wal"),
        Path(str(CACHE_DB_PATH) + "-shm"),
    )
    for path in paths:
        try:
            if path.exists():
                os.chmod(path, 0o600)
        except OSError:
            pass


def init_cache_db():
    global cache_db
    try:
        cache_dir = CACHE_DB_PATH.parent
        cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(cache_dir, 0o700)
        cache_db = sqlite3.connect(CACHE_DB_PATH, check_same_thread=False)
        cache_db.execute("PRAGMA journal_mode=WAL")
        cache_db.execute("PRAGMA synchronous=NORMAL")
        cache_db.execute(
            "CREATE TABLE IF NOT EXISTS translations ("
            "cache_key TEXT PRIMARY KEY, translated TEXT NOT NULL, "
            "updated_at INTEGER NOT NULL DEFAULT 0)"
        )
        cache_db.commit()
        secure_cache_permissions()
    except (OSError, sqlite3.Error) as exc:
        cache_db = None
        print(f"Persistent cache disabled: {exc}", file=sys.stderr, flush=True)


def make_cache_key(text):
    material = "\0".join((
        CACHE_SCHEMA_VERSION,
        backend_name,
        MODEL_NAME,
        model_fingerprint,
        TARGET_LANGUAGE,
        SEGMENTATION_VERSION,
        GLOSSARY_FINGERPRINT,
        text,
    ))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def cache_get(text):
    key = make_cache_key(text)
    value = cache.get(key)
    if value is not None:
        cache.move_to_end(key)
        return value
    if cache_db is None:
        return None
    try:
        row = cache_db.execute(
            "SELECT translated FROM translations WHERE cache_key = ?", (key,)
        ).fetchone()
        if row is not None:
            cache[key] = row[0]
            cache.move_to_end(key)
            if len(cache) > CACHE_CAPACITY:
                cache.popitem(last=False)
            return row[0]
    except sqlite3.Error:
        pass
    return None


def cache_put(text, translation):
    key = make_cache_key(text)
    cache[key] = translation
    cache.move_to_end(key)
    if len(cache) > CACHE_CAPACITY:
        cache.popitem(last=False)
    if cache_db is not None:
        try:
            cache_db.execute(
                "INSERT OR REPLACE INTO translations(cache_key, translated, updated_at) "
                "VALUES(?, ?, ?)",
                (key, translation, int(time.time()))
            )
        except sqlite3.Error:
            pass


def make_length_bucket(chunks):
    indexed = [(token_count(ch), idx, ch) for idx, ch in enumerate(chunks)]
    indexed.sort(key=lambda item: item[0])
    return indexed


def generate_chunks_pytorch(chunks):
    if not chunks:
        return []
    indexed = make_length_bucket(chunks)
    translated = [""] * len(chunks)

    start = 0
    while start < len(indexed):
        batch = []
        longest = 0
        while start + len(batch) < len(indexed) and len(batch) < MICRO_BATCH_SIZE:
            candidate = indexed[start + len(batch)]
            candidate_longest = max(longest, candidate[0])
            if batch and candidate_longest * (len(batch) + 1) > TOKEN_BATCH_BUDGET:
                break
            batch.append(candidate)
            longest = candidate_longest
        start += len(batch)
        texts = [item[2] for item in batch]
        inputs = tokenizer(
            texts,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=MAX_SOURCE_TOKENS + 8,
        )
        inputs = {key: value.to(device, non_blocking=True) for key, value in inputs.items()}
        longest_source = max(item[0] for item in batch)
        max_new_tokens = min(384, max(64, int(longest_source * 1.6) + 24))

        with torch.inference_mode():
            output = model.generate(
                **inputs,
                decoder_start_token_id=tokenizer.lang_code_to_id[TARGET_LANGUAGE],
                max_length=max_new_tokens,
                num_beams=1,
                use_cache=True,
            )
        decoded = tokenizer.batch_decode(output, skip_special_tokens=True)
        for (_, original_index, _), result in zip(batch, decoded):
            translated[original_index] = clean_output(result)

    return translated


def generate_chunks_ctranslate2(chunks):
    if not chunks:
        return []
    indexed = make_length_bucket(chunks)
    translated = [""] * len(chunks)
    target_id = tokenizer.lang_code_to_id[TARGET_LANGUAGE]
    target_token = tokenizer.convert_ids_to_tokens(target_id)

    start = 0
    while start < len(indexed):
        batch = []
        longest = 0
        while start + len(batch) < len(indexed) and len(batch) < MICRO_BATCH_SIZE:
            candidate = indexed[start + len(batch)]
            candidate_longest = max(longest, candidate[0])
            if batch and candidate_longest * (len(batch) + 1) > TOKEN_BATCH_BUDGET:
                break
            batch.append(candidate)
            longest = candidate_longest
        start += len(batch)

        source_tokens = [
            tokenizer.convert_ids_to_tokens(tokenizer.encode(item[2]))
            for item in batch
        ]
        prefixes = [[target_token] for _item in batch]
        max_decoding_length = min(384, max(64, int(longest * 1.6) + 24))
        outputs = model.translate_batch(
            source_tokens,
            target_prefix=prefixes,
            beam_size=1,
            max_decoding_length=max_decoding_length,
            return_scores=False,
        )
        for item, output in zip(batch, outputs):
            tokens = output.hypotheses[0]
            if tokens and tokens[0] == target_token:
                tokens = tokens[1:]
            token_ids = tokenizer.convert_tokens_to_ids(tokens)
            translated[item[1]] = clean_output(tokenizer.decode(
                token_ids, skip_special_tokens=True
            ))
    return translated


def generate_chunks(chunks):
    if backend_name == "ctranslate2":
        return generate_chunks_ctranslate2(chunks)
    return generate_chunks_pytorch(chunks)


def translate_text_batch(texts):
    if not is_ready or not texts:
        return list(texts)

    results = [None] * len(texts)
    pending = {}
    for index, text in enumerate(texts):
        cached = cache_get(text)
        if cached is not None:
            results[index] = cached
        else:
            pending.setdefault(text, []).append(index)

    prepared = []
    flat_chunks = []
    for original in pending:
        protected, replacements = protect_technical_text(original)
        chunks = split_long_text(protected)
        start = len(flat_chunks)
        flat_chunks.extend(chunks)
        prepared.append((original, replacements, start, len(chunks)))

    translated_chunks = generate_chunks(flat_chunks)
    for original, replacements, start, count in prepared:
        translated = " ".join(translated_chunks[start:start + count])
        translated = restore_technical_text(translated, replacements)
        cache_put(original, translated)
        for index in pending[original]:
            results[index] = translated
    if cache_db is not None:
        try:
            cache_db.commit()
            secure_cache_permissions()
        except Exception:
            pass

    return results


# =========================================================================
# Polish Worker & LLM Handling (100% CUDA GPU, 0% CPU, Dynamic Batching)
# =========================================================================

def is_polish_eligible(en_text, vi_raw):
    if not vi_raw or len(vi_raw.strip()) < 8:
        return False
    words = vi_raw.strip().split()
    if len(words) < 3:
        return False
    if any(tag in en_text for tag in ["class ", "def ", "#include", "void "]):
        return False
    return True
def polish_batch(batch_items):
    """Polish on GPU 4-bit NF4 with VRAM safety checks."""
    if not polish_ready or not batch_items:
        return [(item[0], item[2]) for item in batch_items]

    results = []
    to_process = []
    for item in batch_items:
        req_id, en_text, vi_raw = item
        if not is_polish_eligible(en_text, vi_raw):
            results.append((req_id, vi_raw))
            continue
        to_process.append(item)

    if not to_process:
        return results

    for i, (req_id, en_text, vi_raw) in enumerate(to_process):
        cache_key = f"polish::{en_text}"
        cached = cache_get(cache_key)
        if cached:
            results.append((req_id, cached))
            continue

        # Periodic VRAM cleanup to prevent fragmentation
        if i % 4 == 0 and torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()
            # VRAM safety guard: if >90% used, skip remaining and return raw
            total = torch.cuda.get_device_properties(0).total_memory
            used  = torch.cuda.memory_allocated()
            if used / total > 0.90:
                print(f"[polish] VRAM {used/1024**3:.2f}GB/{total/1024**3:.2f}GB >90% — skipping polish",
                      file=sys.stderr, flush=True)
                results.append((req_id, vi_raw))
                continue

        prompt = (
            f"<|im_start|>system\n"
            f"Bạn là chuyên gia dịch thuật và biên tập văn phong tiếng Việt. "
            f"Hãy viết lại câu dịch sau sao cho tự nhiên, mượt mà và thuần Việt nhất, "
            f"nhưng phải giữ nguyên vẹn ý nghĩa của câu tiếng Anh và các thuật ngữ chuyên ngành. "
            f"Không thêm bớt thông tin. Trả về duy nhất câu đã viết lại.<|im_end|>\n"
            f"<|im_start|>user\n"
            f"- Câu gốc: {en_text}\n"
            f"- Bản dịch thô: {vi_raw}\n"
            f"Viết lại câu hoàn chỉnh:<|im_end|>\n"
            f"<|im_start|>assistant\n"
        )

        try:
            inputs = polish_tokenizer(prompt, return_tensors="pt").to("cuda")
            input_len = inputs["input_ids"].shape[1]
            max_new = min(96, max(24, int(len(vi_raw.split()) * 1.5) + 10))
            with torch.inference_mode():
                outputs = polish_model.generate(
                    **inputs,
                    max_new_tokens=max_new,
                    do_sample=False,
                    pad_token_id=polish_tokenizer.eos_token_id,
                    use_cache=True,
                )
            gen = polish_tokenizer.decode(outputs[0][input_len:], skip_special_tokens=True).strip()
            for prefix in ["- ", "Bản dịch hoàn thiện:", "Viết lại:", "Câu hoàn chỉnh:", "Bản dịch:"]:
                if gen.startswith(prefix):
                    gen = gen[len(prefix):].strip()
            gen = gen.strip(' "\'')
            final_text = gen if gen and len(gen) >= 4 else vi_raw
            cache_put(cache_key, final_text)
            results.append((req_id, final_text))
            if cache_db is not None:
                try:
                    cache_db.commit()
                except Exception:
                    pass
        except Exception as exc:
            print(f"CUDA Polish generation failed: {exc}", file=sys.stderr, flush=True)
            if torch is not None and torch.cuda.is_available():
                torch.cuda.empty_cache()
            results.append((req_id, vi_raw))

    return results


def polish_worker_loop():
    while True:
        try:
            item = polish_queue.get()
            if item is None:
                break
            batch = [item]
            # Drain up to 1 more item (keep batch tiny for 4-bit stability)
            if len(batch) < 2:
                try:
                    next_item = polish_queue.get_nowait()
                    if next_item is None:
                        polish_queue.task_done()
                    else:
                        batch.append(next_item)
                except queue.Empty:
                    pass

            results = polish_batch(batch)
            res_json = [{"id": r[0], "translated": r[1], "stage": "polish"} for r in results]
            emit_json({"results": res_json})
            for _ in batch:
                polish_queue.task_done()
        except Exception as exc:
            print(f"Polish worker loop error: {exc}", file=sys.stderr, flush=True)
            if torch is not None and torch.cuda.is_available():
                torch.cuda.empty_cache()


def _init_polish_model_background():
    """Load Arcee-VyLinh 4-bit in background after VinAI is ready.
    Emits a status update over stdout once the model is loaded."""
    global polish_model, polish_tokenizer, polish_ready, polish_thread, polish_model_name, polish_backend, polish_status
    polish_path = resolve_polish_model_path()
    if not polish_path:
        print("Polish model path not found. Running Stage 1 only.", file=sys.stderr, flush=True)
        polish_status = "disabled"
        emit_json({"polish_available": False, "polish_status": "disabled", "error": "Model path not found"})
        return

    p_path = Path(polish_path)
    # Prefer directory (PyTorch 4-bit NF4 CUDA — 2.5 GB VRAM, safe alongside VinAI)
    if p_path.is_dir() or (p_path.parent / "Arcee-VyLinh").is_dir():
        model_dir = str(p_path if p_path.is_dir() else (p_path.parent / "Arcee-VyLinh"))
        try:
            from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
            print(f"[bg] Initializing Polish Model 4-bit NF4 CUDA ({Path(model_dir).name}) ...",
                  file=sys.stderr, flush=True)
            bnb_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_use_double_quant=True,
            )
            tok = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
            if tok.pad_token is None:
                tok.pad_token = tok.eos_token
            mdl = AutoModelForCausalLM.from_pretrained(
                model_dir,
                quantization_config=bnb_config,
                device_map="cuda",
                local_files_only=True,
            )
            polish_tokenizer = tok
            polish_model = mdl
            polish_backend = "torch_bnb4"
            polish_model_name = "Arcee-VyLinh (4-bit NF4 CUDA)"
            polish_ready = True
            polish_status = "ready"
            polish_thread = threading.Thread(target=polish_worker_loop, daemon=True)
            polish_thread.start()
            vram_mb = 0
            if torch is not None and torch.cuda.is_available():
                vram_mb = int(torch.cuda.memory_allocated() / 1024 / 1024)
            print(f"[bg] Polish Model (4-bit NF4 CUDA) ready. VRAM: {vram_mb} MB",
                  file=sys.stderr, flush=True)
            # Notify Qt that polish is now available
            emit_json({"polish_available": True, "polish_status": "ready", "polish_model": polish_model_name})
            return
        except Exception as exc:
            polish_ready = False
            polish_status = "crashed"
            print(f"[bg] Could not load 4-bit Polish Model: {exc}", file=sys.stderr, flush=True)
            emit_json({"polish_available": False, "polish_status": "crashed", "polish_error": str(exc)})
            return

    polish_status = "disabled"
    print("[bg] No compatible polish model found.", file=sys.stderr, flush=True)
    emit_json({"polish_available": False, "polish_status": "disabled", "error": "No compatible model"})


def init_polish_model():
    """Schedule Arcee-VyLinh loading in a background daemon thread."""
    global polish_ready, polish_status
    polish_ready = False
    polish_status = "loading"
    emit_json({"polish_available": False, "polish_status": "loading", "polish_model": "loading"})
    bg = threading.Thread(target=_init_polish_model_background, daemon=True, name="polish-loader")
    bg.start()


# =========================================================================
# Request Batch Handling & Output
# =========================================================================

def stream_request_batch(batch_requests):
    """Translate groups with VinAI and emit immediately, then queue for polish."""
    if not batch_requests:
        emit_json({"results": []})
        return

    cursor = 0
    while cursor < len(batch_requests):
        group = []
        group_tokens = 0
        while cursor < len(batch_requests) and len(group) < RESPONSE_GROUP_SIZE:
            candidate = batch_requests[cursor]
            candidate_tokens = min(token_count(candidate.get("text", "")), MAX_SOURCE_TOKENS)
            if group and group_tokens + candidate_tokens > REQUEST_TOKEN_BUDGET:
                break
            group.append(candidate)
            group_tokens += candidate_tokens
            cursor += 1

        texts = [value.get("text", "") for value in group]
        try:
            translations = translate_text_batch(texts)
            response = []
            immediate_polish = []
            for index, value in enumerate(group):
                req_id = value.get("id", 0)
                translated = translations[index] if index < len(translations) else ""
                text_src = value.get("text", "")
                response.append({"id": req_id, "translated": translated, "stage": "raw"})

                # Queue for background polishing — non-blocking put, drop if full
                if polish_ready:
                    if is_polish_eligible(text_src, translated):
                        try:
                            polish_queue.put_nowait((req_id, text_src, translated))
                        except queue.Full:
                            # Queue full → emit as-is without polish
                            immediate_polish.append({"id": req_id, "translated": translated, "stage": "polish"})
                    else:
                        immediate_polish.append({"id": req_id, "translated": translated, "stage": "polish"})
                else:
                    immediate_polish.append({"id": req_id, "translated": translated, "stage": "polish"})

            emit_json({"results": response})
            if immediate_polish:
                emit_json({"results": immediate_polish})
        except Exception as exc:
            print(f"Translation failed: {exc}", file=sys.stderr, flush=True)
            failures = [
                {"id": value.get("id", 0), "error": str(exc)} for value in group
            ]
            emit_json({"failures": failures})


def init_ctranslate2_model():
    global tokenizer, model, device, is_ready, model_fingerprint, backend_name
    import ctranslate2
    from transformers import AutoTokenizer

    intra_threads = int(os.environ.get(
        "READDOC_NMT_INTRA_THREADS",
        str(max(1, min(16, (os.cpu_count() or 4) // 2))),
    ))
    inter_threads = int(os.environ.get("READDOC_NMT_INTER_THREADS", "1"))
    tokenizer = AutoTokenizer.from_pretrained(
        TOKENIZER_NAME, src_lang="en_XX", local_files_only=True
    )
    device_type = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
    compute_type = "float16" if device_type == "cuda" else "int8"
    model = ctranslate2.Translator(
        MODEL_NAME,
        device=device_type,
        compute_type=compute_type,
        intra_threads=intra_threads,
        inter_threads=inter_threads,
    )
    model_file = Path(MODEL_NAME) / "model.bin"
    identity = (
        f"ctranslate2:{model_file.stat().st_mtime_ns if model_file.exists() else 'none'}"
    )
    model_fingerprint = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    device = f"{device_type}-{compute_type}" if device_type == "cuda" else f"cpu-int8/{intra_threads}t"
    backend_name = "ctranslate2"
    is_ready = True


def init_pytorch_model():
    global torch, tokenizer, model, device, is_ready, model_fingerprint, backend_name
    import gc
    import torch as torch_module
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    torch = torch_module
    try:
        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
    except Exception:
        pass
    if torch.cuda.is_available():
        device = torch.device("cuda")
    elif torch.backends.mps.is_available():
        device = torch.device("mps")
    else:
        device = torch.device("cpu")

    tokenizer = AutoTokenizer.from_pretrained(
        TOKENIZER_NAME,
        src_lang="en_XX",
        local_files_only=True,
    )
    
    if device.type == "cuda":
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
        torch.backends.cudnn.benchmark = True
        torch.set_float32_matmul_precision("high")
        try:
            model = AutoModelForSeq2SeqLM.from_pretrained(
                MODEL_NAME,
                dtype=torch.float16,
                low_cpu_mem_usage=True,
                local_files_only=True,
            ).to(device).eval()
        except Exception:
            model = AutoModelForSeq2SeqLM.from_pretrained(
                MODEL_NAME,
                dtype=torch.float16,
                local_files_only=True,
            ).to(device).eval()
        torch.cuda.empty_cache()
    else:
        model = AutoModelForSeq2SeqLM.from_pretrained(
            MODEL_NAME,
            dtype=torch.float32,
            local_files_only=True,
        ).to(device).eval()
    
    gc.collect()

    revision = getattr(model.config, "_commit_hash", None)
    identity = revision or model.config.to_json_string()
    model_fingerprint = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    backend_name = "pytorch"
    is_ready = True


def init_model():
    global is_ready
    try:
        if REQUESTED_BACKEND == "ctranslate2":
            init_ctranslate2_model()
        else:
            init_pytorch_model()
    except Exception as exc:
        print(f"Local model unavailable: {exc}", file=sys.stderr, flush=True)
        is_ready = False


def main():
    init_cache_db()
    init_model()          # Load VinAI (fast, ~1s)

    if is_ready:
        translate_text_batch(["Hello world"])   # Warm-up VinAI

    # ---- Emit ready IMMEDIATELY so Qt can start VinAI translations ----
    # Arcee-VyLinh will load in background and send its own update when done.
    emit_json({
        "status": "ready",
        "available": is_ready,
        "model": MODEL_NAME,
        "backend": backend_name,
        "device": str(device) if device is not None else "none",
        "polish_available": False,   # will be updated when bg load completes
        "polish_model": "loading",
    })

    init_polish_model()   # Starts background thread — non-blocking

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            if request.get("action") == "clear_cache":
                cache.clear()
                while not polish_queue.empty():
                    try:
                        polish_queue.get_nowait()
                        polish_queue.task_done()
                    except Exception:
                        break
                if cache_db is not None:
                    try:
                        cache_db.execute("DELETE FROM translations")
                        cache_db.execute("VACUUM")
                        cache_db.commit()
                    except Exception:
                        pass
                emit_json({"cache_cleared": True})
                continue

            if request.get("action") == "status":
                emit_json({
                    "action": "status_response",
                    "nmt_ready": is_ready,
                    "polish_ready": polish_ready,
                    "polish_status": polish_status,
                    "polish_model": polish_model_name,
                    "queue_size": polish_queue.qsize() if polish_queue else 0,
                })
                continue

            if request.get("action") == "restart_polish":
                print("[daemon] Received restart_polish command", file=sys.stderr, flush=True)
                init_polish_model()
                continue

            if request.get("action") == "polish_batch":
                items = request.get("items", [])
                response_fallback = []
                for it in items:
                    req_id = it.get("id", 0)
                    text_src = it.get("text", "")
                    vi_raw = it.get("raw", "")
                    if polish_ready and is_polish_eligible(text_src, vi_raw):
                        try:
                            polish_queue.put_nowait((req_id, text_src, vi_raw))
                        except queue.Full:
                            response_fallback.append({"id": req_id, "translated": vi_raw, "stage": "polish"})
                    else:
                        response_fallback.append({"id": req_id, "translated": vi_raw, "stage": "polish"})
                if response_fallback:
                    emit_json({"results": response_fallback})
                continue

            batch_requests = request.get("batch")
            if batch_requests is not None:
                stream_request_batch(batch_requests)
            else:
                request_id = request.get("id", 0)
                text = request.get("text", "")
                try:
                    res_list = translate_text_batch([text]) if text.strip() else [text]
                    translated = res_list[0] if res_list else text
                    emit_json({"results": [{"id": request_id, "translated": translated, "stage": "raw"}]})
                    if polish_ready:
                        if is_polish_eligible(text, translated):
                            try:
                                polish_queue.put_nowait((request_id, text, translated))
                            except queue.Full:
                                emit_json({"results": [{"id": request_id, "translated": translated, "stage": "polish"}]})
                        else:
                            emit_json({"results": [{"id": request_id, "translated": translated, "stage": "polish"}]})
                    else:
                        emit_json({"results": [{"id": request_id, "translated": translated, "stage": "polish"}]})
                except Exception as exc:
                    print(f"Translation failed: {exc}", file=sys.stderr, flush=True)
                    emit_json({"failures": [{"id": request_id, "error": str(exc)}]})
        except Exception as exc:
            print(f"Invalid translation request: {exc}", file=sys.stderr, flush=True)
            emit_json({"error": str(exc)})


if __name__ == "__main__":
    main()
