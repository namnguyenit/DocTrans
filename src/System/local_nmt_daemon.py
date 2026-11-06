#!/usr/bin/env python3
"""Local English–Vietnamese pipeline: VinAI preview and contextual refinement."""

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
from collections import OrderedDict, Counter
from pathlib import Path
from functools import wraps
from types import MethodType

sys.path.insert(0, str(Path(__file__).resolve().parent))
from local_cuda_server import LocalCudaServer, find_server

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
        gguf = MODELS_ROOT / "polish/Qwen3.5-4B-GGUF/Qwen3.5-4B-Q6_K.gguf"
        if (gguf.is_file() and gguf.stat().st_size > 3_000_000_000
                and (gguf.parent / "tokenizer.json").is_file()
                and (gguf.parent / "config.json").is_file()
                and (gguf.parent / "tokenizer_config.json").is_file()
                and find_server(MODELS_ROOT)):
            return str(gguf.resolve())
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
POLISH_BATCH_SIZE = max(1, int(os.environ.get("READDOC_POLISH_BATCH_SIZE", "24")))
POLISH_TOKEN_BUDGET = max(256, int(os.environ.get("READDOC_POLISH_TOKEN_BUDGET", "12288")))
POLISH_MAX_NEW_TOKENS = max(24, int(os.environ.get("READDOC_POLISH_MAX_NEW_TOKENS", "384")))
POLISH_METRICS = os.environ.get("READDOC_POLISH_METRICS", "0") == "1"
# Context is source-only and supplied by the document, never by queue order.
POLISH_CONTEXT_CHARS = 600
FUSED_RMSNORM = os.environ.get("READDOC_FUSED_RMSNORM", "1") == "1"
POLISH_TASK = os.environ.get("READDOC_POLISH_TASK", "refine")
CACHE_CAPACITY = int(os.environ.get("READDOC_NMT_CACHE_SIZE", "4096"))
CACHE_SCHEMA_VERSION = "6"
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
polish_status = "loading"
polish_backend = "none"
polish_profile = "vylinh"
polish_model_name = "none"
polish_fingerprint = "uninitialized"
polish_metrics = Counter()
polish_metrics_lock = threading.Lock()


def count_polish_metric(name, value=1):
    with polish_metrics_lock:
        polish_metrics[name] += value


def snapshot_polish_metrics(reset=False):
    with polish_metrics_lock:
        result = dict(polish_metrics)
        if reset:
            polish_metrics.clear()
        return result
polish_queue = queue.Queue(maxsize=POLISH_QUEUE_MAX)   # Bounded to prevent memory bloat
polish_thread = None
stdout_lock = threading.Lock()
# Both models share one GPU: bound simultaneous activation/KV allocations.
gpu_lock = threading.RLock()
polish_load_lock = threading.Lock()
cache_lock = threading.RLock()
request_state_lock = threading.RLock()
active_requests = set()
cancelled_requests = set()


def emit_json(obj):
    terminal = [row.get("id", 0) for row in obj.get("results", [])
                if row.get("stage") == "polish"]
    terminal.extend(row.get("id", 0) for row in obj.get("failures", []))
    with request_state_lock:
        active_requests.difference_update(terminal)
        cancelled_requests.difference_update(terminal)
    with stdout_lock:
        print(json.dumps(obj, ensure_ascii=False), flush=True)


def cache_guard(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        with cache_lock:
            return function(*args, **kwargs)
    return guarded


@cache_guard
def commit_cache():
    if cache_db is not None:
        cache_db.commit()
        secure_cache_permissions()


@cache_guard
def clear_translation_memory():
    cache.clear()
    if cache_db is not None:
        cache_db.execute("DELETE FROM translations")
        cache_db.commit()
        cache_db.execute("VACUUM")
        secure_cache_permissions()


def is_cancelled(req_id):
    with request_state_lock:
        return req_id in cancelled_requests


def cancel_request_ids(ids):
    with request_state_lock:
        cancelled_requests.update(set(ids) & active_requests)
        finished = set(ids) - active_requests
    if finished:
        emit_json({"results": [{"id": i, "translated": "", "stage": "polish", "cancelled": True}
                               for i in finished]})


def finish_waiting_polish():
    """Release waiting jobs if the optional model cannot load."""
    while True:
        try:
            item = polish_queue.get_nowait()
        except queue.Empty:
            break
        if item is not None:
            emit_json({"results": [{"id": item[0], "translated": item[2], "stage": "polish"}]})
        polish_queue.task_done()


def enqueue_polish(req_id, source, raw, context=""):
    with request_state_lock:
        active_requests.add(req_id)
    if is_cancelled(req_id) or not is_polish_eligible(source, raw):
        emit_json({"results": [{"id": req_id, "translated": raw, "stage": "polish"}]})
        return
    # Retain raw results during startup. A full queue applies backpressure;
    # it must never silently label an unpolished sentence as polished.
    while polish_ready or polish_status == "loading":
        if is_cancelled(req_id):
            break
        try:
            item = (req_id, source, raw, context) if context else (req_id, source, raw)
            polish_queue.put(item, timeout=0.2)
            if not polish_ready and polish_status in ("disabled", "crashed"):
                finish_waiting_polish()
            return
        except queue.Full:
            continue
    emit_json({"results": [{"id": req_id, "translated": raw, "stage": "polish"}]})


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
    r"\.(?:[ \t]*\.){4,}|"
    r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b|"
    r"\b(?=[A-Za-z0-9]*[0-9])[A-Za-z][A-Za-z0-9]+\b|"
    r"(?<!\w)--?[a-zA-Z][\w-]*|"
    r"(?:[/~.]?[\w.-]+/)+[\w.-]+|"
    r"\b(?:0x[0-9a-fA-F]+|[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+)\b|"
    r"\b[a-zA-Z][a-zA-Z0-9]*_[a-zA-Z0-9_]+(?:\(\))?\b|"
    r"`[^`]+`"
)
PLACEHOLDER_RE = re.compile(r"__TECH\d+__")
DOT_LEADER_RE = re.compile(r"\.(?:[ \t]*\.){4,}")
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


@cache_guard
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


@cache_guard
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


@cache_guard
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

        with gpu_lock, torch.inference_mode():
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
        with gpu_lock:
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
            commit_cache()
        except Exception:
            pass

    return results


# =========================================================================
# Polish worker: bounded, length-bucketed CUDA batches.
# =========================================================================

def is_polish_eligible(en_text, vi_raw):
    if not vi_raw or len(vi_raw.strip()) < 8:
        return False
    words = vi_raw.strip().split()
    if len(words) < 3:
        return False
    if re.search(r"\b(?:class|def|void)\s|#include", en_text):
        return False
    return True


def protect_dot_leaders(text):
    leaders = {}
    def replace(match):
        marker = f"__LEADER{len(leaders)}__"
        leaders[marker] = match.group(0)
        return marker
    return DOT_LEADER_RE.sub(replace, text), leaders


def polish_prompt(en_text, vi_raw, context=""):
    context = context[-POLISH_CONTEXT_CHARS:]
    if polish_profile == "qwen35":
        en_text, _ = protect_dot_leaders(en_text)
        context = DOT_LEADER_RE.sub(" … ", context)
    if polish_profile in ("qwen", "qwen35"):
        return polish_tokenizer.apply_chat_template([
            {"role": "system", "content":
             "Bạn là biên dịch viên Anh–Việt. Dịch chính xác phần Source Text sang tiếng Việt tự nhiên. "
             "Dùng Background Information chỉ để chọn nghĩa của từ; không chèn chi tiết chỉ có trong ngữ cảnh. "
             "Vietnamese Draft là bản tham khảo cách diễn đạt, có thể sai nghĩa; sửa nó theo Source Text và ngữ cảnh. "
             "Giữ nguyên ý nghĩa, phủ định, điều kiện, số liệu, tên biến và ký hiệu. "
             "Chỉ trả về bản dịch, không giải thích."},
            {"role": "user", "content":
             (f"[Background Information]\n{context}\n" if context else "") + f"[Source Text]\n{en_text}"
             + (f"\n[Vietnamese Draft]\n{vi_raw}" if POLISH_TASK == "refine" and polish_profile != "qwen35" else "")}
        ], tokenize=False, add_generation_prompt=True, enable_thinking=False)
    if polish_profile == "hymt":
        prompt = (
            (f"[Background Information]\n{context}\n" if context else "")
            + "Translate only the [Source Text] into Vietnamese, taking any background "
            "information into consideration. Only output the translation without explanation. "
            "Preserve numbers, identifiers and placeholders.\n"
            f"[Source Text]\n{en_text}"
        )
        return polish_tokenizer.apply_chat_template(
            [{"role": "user", "content": prompt}], tokenize=False, add_generation_prompt=True)
    background = (f"- Ngữ cảnh tham khảo (không dịch phần này): {context}\n" if context else "")
    return (
        f"<|im_start|>system\n"
        f"Bạn là chuyên gia dịch thuật và biên tập văn phong tiếng Việt. "
        f"Hiệu đính bản dịch dựa trên câu gốc tiếng Anh. Giữ đúng ý nghĩa, phủ định, "
        f"điều kiện, số liệu và thuật ngữ. Ngữ cảnh chỉ giúp chọn nghĩa của từ; "
        f"không đưa thông tin từ ngữ cảnh vào bản dịch. Không thêm giải thích, "
        f"không suy diễn. Chỉ trả về bản dịch của câu gốc.<|im_end|>\n"
        f"<|im_start|>user\n"
        f"{background}"
        f"- Câu gốc: {en_text}\n"
        f"- Bản dịch thô: {vi_raw}\n"
        f"Viết lại câu hoàn chỉnh:<|im_end|>\n"
        f"<|im_start|>assistant\n"
    )


def polish_cache_key(en_text, vi_raw, context=""):
    # Include the raw translation and polish model, not only the English source.
    return "polish-context-v5::" + json.dumps(
        [str(POLISH_MODEL_PATH), polish_fingerprint, polish_profile, polish_backend,
         FUSED_RMSNORM, POLISH_TASK, en_text, vi_raw, context[-POLISH_CONTEXT_CHARS:]], ensure_ascii=False)


def preserves_source_literals(source, result):
    """Reject observable corruption; this is not a semantic accuracy metric."""
    numbers = lambda text: Counter(re.findall(r"(?<![\w.])[-+]?\d+(?:[.,]\d+)*\b", text.replace("−", "-")))
    if numbers(source) != numbers(result):
        return False
    source_literals = Counter(TECH_TOKEN_RE.findall(source))
    result_literals = Counter(TECH_TOKEN_RE.findall(result))
    if any(result_literals[token] < count for token, count in source_literals.items()):
        return False
    literals = re.findall(
        r"\{\{[\w.]+\}\}|\$?\{[\w.]+\}|%\([\w]+\)s|%[sd]|%\d+", source)
    if any(token not in result for token in literals):
        return False
    if not re.search(r"[\u3400-\u9fff]", source) and re.search(r"[\u3400-\u9fff]", result):
        return False
    return True


def generate_polish_batch(prepared):
    """One actual GPU generate call. Own tensors here so OOM retries free them."""
    prompts = [entry[1] for entry in prepared]
    max_new = max(entry[2] for entry in prepared)
    count_polish_metric("model_rows", len(prepared))
    if polish_backend == "llama_server_cuda":
        # llama.cpp refills a finished slot immediately while other slots decode.
        with gpu_lock:
            rows = polish_model.complete_batch(prompts, max_new)
        return [finish_polish(entry, row.get("content", ""),
                              row.get("stop_type") in ("eos", "word") and not row.get("truncated", False))
                for entry, row in zip(prepared, rows)]
    with gpu_lock, torch.inference_mode():
        inputs = polish_tokenizer(prompts, return_tensors="pt", padding=True).to("cuda")
        width = inputs["input_ids"].shape[1]
        outputs = polish_model.generate(
            **inputs, max_new_tokens=max_new, do_sample=False,
            pad_token_id=polish_tokenizer.pad_token_id,
            eos_token_id=polish_tokenizer.eos_token_id, use_cache=True,
        )
        generated = outputs[:, width:].cpu()
    texts = polish_tokenizer.batch_decode(generated, skip_special_tokens=True)
    results = []
    truncated = 0
    for entry, tokens, text in zip(prepared, generated.tolist(), texts):
        # A budget-limited response can end mid-sentence; retain the raw text.
        complete = polish_tokenizer.eos_token_id in tokens
        truncated += not complete
        results.append(finish_polish(entry, text, complete))
    if truncated:
        print(f"[polish] {truncated}/{len(prepared)} responses reached the output limit; "
              "keeping raw translations", file=sys.stderr, flush=True)
    return results


def finish_polish(entry, text, complete):
    req_id, en_text, vi_raw = entry[0][:3]
    context = entry[0][3] if len(entry[0]) > 3 else ""
    text = text.strip()
    for prefix in ["- ", "Bản dịch hoàn thiện:", "Viết lại:", "Câu hoàn chỉnh:", "Bản dịch:"]:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    text = text.strip(' "\'')
    leaders_valid = True
    if polish_profile == "qwen35":
        _, leaders = protect_dot_leaders(en_text)
        for marker, original in leaders.items():
            text = text.replace(f"`{marker}`", marker)
            leaders_valid = leaders_valid and text.count(marker) == 1
            text = text.replace(marker, original)
    accepted = complete and leaders_valid and len(text) >= 4 and preserves_source_literals(en_text, text)
    count_polish_metric("complete_rows" if complete else "truncated_rows")
    if accepted:
        count_polish_metric("accepted_rows")
        cache_put(polish_cache_key(en_text, vi_raw, context), text)
    elif complete:
        count_polish_metric("literal_rejections" if len(text) >= 4 else "empty_rejections")
    return req_id, text if accepted else vi_raw


def run_polish_batch(prepared):
    global polish_ready, polish_status
    try:
        return generate_polish_batch(prepared)
    except Exception as exc:
        oom = isinstance(exc, torch.cuda.OutOfMemoryError)
        count_polish_metric("generation_failures")
        print(f"[polish] {'CUDA OOM' if oom else 'Generation failed'}: {exc}",
              file=sys.stderr, flush=True)
        # Release traceback references to failed CUDA tensors before retrying.
        exc.__traceback__ = None
        if (polish_backend == "llama_server_cuda" and polish_model.process.poll() is not None):
            polish_ready = False
            polish_status = "crashed"
            emit_json({"polish_available": False, "polish_status": "crashed",
                       "polish_error": "The local CUDA engine stopped; raw translations were retained"})
            finish_waiting_polish()
            polish_model.close()
    if oom:
        count_polish_metric("oom_retries")
        with gpu_lock:
            torch.cuda.empty_cache()
        if len(prepared) > 1:
            middle = len(prepared) // 2
            return run_polish_batch(prepared[:middle]) + run_polish_batch(prepared[middle:])
    return [(entry[0][0], entry[0][2]) for entry in prepared]


def polish_batch(batch_items):
    """Batch independent prompts, bucket lengths and bound padded token usage."""
    if not polish_ready or not batch_items:
        return [(item[0], item[2]) for item in batch_items]
    results = {}
    prepared = []
    for item in batch_items:
        req_id, en_text, vi_raw = item[:3]
        context = item[3] if len(item) > 3 else ""
        if not is_polish_eligible(en_text, vi_raw):
            count_polish_metric("skipped_rows")
            results[req_id] = vi_raw
            continue
        cached = cache_get(polish_cache_key(en_text, vi_raw, context))
        if cached is not None:
            count_polish_metric("cache_hits")
            results[req_id] = cached
            continue
        prompt = polish_prompt(en_text, vi_raw, context)
        input_tokens = len(polish_tokenizer.encode(prompt))
        raw_tokens = len(polish_tokenizer.encode(vi_raw, add_special_tokens=False))
        if polish_profile in ("hymt", "qwen", "qwen35"):
            # A weak/short NMT draft must not constrain a direct translation.
            raw_tokens = max(raw_tokens, len(polish_tokenizer.encode(en_text, add_special_tokens=False)))
        max_new = min(POLISH_MAX_NEW_TOKENS, max(24, int(raw_tokens * 1.35) + 16))
        if polish_backend == "llama_server_cuda":
            # Each native slot stops on EOS independently. Give Vietnamese the
            # full bounded allowance; a weak/short preview must not cut it off.
            max_new = POLISH_MAX_NEW_TOKENS
        # Do not silently truncate source/translation to fit the context budget.
        context_limit = polish_model.context_per_slot if polish_backend == "llama_server_cuda" else POLISH_TOKEN_BUDGET
        if input_tokens + max_new > min(POLISH_TOKEN_BUDGET, context_limit):
            count_polish_metric("context_rejections")
            results[req_id] = vi_raw
            continue
        prepared.append((item, prompt, max_new, input_tokens))
    prepared.sort(key=lambda entry: entry[3] + entry[2])
    cursor = 0
    started = time.perf_counter()
    while cursor < len(prepared):
        batch = []
        longest_input = longest_output = 0
        while cursor < len(prepared) and len(batch) < POLISH_BATCH_SIZE:
            entry = prepared[cursor]
            new_input = max(longest_input, entry[3])
            new_output = max(longest_output, entry[2])
            if (batch and polish_backend != "llama_server_cuda"
                    and (new_input + new_output) * (len(batch) + 1) > POLISH_TOKEN_BUDGET):
                break
            batch.append(entry)
            cursor += 1
            longest_input, longest_output = new_input, new_output
        results.update(run_polish_batch(batch))
    if cache_db is not None:
        try:
            commit_cache()
        except sqlite3.Error as exc:
            print(f"[polish] Cache commit failed: {exc}", file=sys.stderr, flush=True)
    if POLISH_METRICS and prepared:
        print(f"[polish] items={len(prepared)} elapsed={time.perf_counter()-started:.3f}s "
              f"batch_limit={POLISH_BATCH_SIZE} queue={polish_queue.qsize()}",
              file=sys.stderr, flush=True)
    return [(item[0], results[item[0]]) for item in batch_items]


def polish_worker_loop():
    while True:
        batch = []
        stop = False
        try:
            item = polish_queue.get()
            if item is None:
                polish_queue.task_done()
                break
            batch = [item]
            while len(batch) < POLISH_BATCH_SIZE:
                try:
                    next_item = polish_queue.get_nowait()
                    if next_item is None:
                        polish_queue.task_done()
                        stop = True
                        break
                    else:
                        batch.append(next_item)
                except queue.Empty:
                    break

            skipped = [item for item in batch if is_cancelled(item[0])]
            skipped_ids = {item[0] for item in skipped}
            runnable = [item for item in batch if item[0] not in skipped_ids]
            results = polish_batch(runnable)
            results.extend((item[0], item[2]) for item in skipped)
            res_json = [{"id": r[0], "translated": r[1], "stage": "polish"} for r in results]
            emit_json({"results": res_json})
        except Exception as exc:
            print(f"Polish worker loop error: {exc}", file=sys.stderr, flush=True)
            emit_json({"results": [
                {"id": item[0], "translated": item[2], "stage": "polish"}
                for item in batch]})
        finally:
            for _ in batch:
                polish_queue.task_done()
        if stop:
            break


def _init_polish_model_background():
    # A restart during loading must not create two 3B models or two workers.
    if not polish_load_lock.acquire(blocking=False):
        return
    try:
        if polish_ready:
            emit_json({"polish_available": True, "polish_status": "ready",
                       "polish_model": polish_model_name})
            return
        _load_polish_model()
    finally:
        if not polish_ready and polish_status in ("disabled", "crashed"):
            finish_waiting_polish()
        polish_load_lock.release()


def fused_rmsnorm_forward(module, hidden_states):
    return torch.nn.functional.rms_norm(
        hidden_states, module.weight.shape, module.weight, module.variance_epsilon)


def enable_fused_rmsnorm(mdl):
    """Use PyTorch's CUDA RMSNorm kernel for known equivalent inference layers.

    No third-party CUDA extension or checkpoint mutation. Restrict to audited
    Qwen norms: other architectures can use offset weights or a different formula.
    """
    count = 0
    if not hasattr(torch.nn.functional, "rms_norm"):
        return count
    for module in mdl.modules():
        if (type(module).__name__ in ("Qwen2RMSNorm", "Qwen3RMSNorm")
                and module.weight.device.type == "cuda"):
            module.forward = MethodType(fused_rmsnorm_forward, module)
            count += 1
    return count


def _load_polish_model():
    """Load a local refinement checkpoint after VinAI is ready.
    Emits a status update over stdout once the model is loaded."""
    global torch, polish_model, polish_tokenizer, polish_ready, polish_thread, polish_model_name, polish_backend, polish_status, polish_profile, polish_fingerprint, POLISH_MODEL_PATH
    polish_path = resolve_polish_model_path()
    if not polish_path:
        print("Polish model path not found. Running Stage 1 only.", file=sys.stderr, flush=True)
        polish_status = "disabled"
        emit_json({"polish_available": False, "polish_status": "disabled", "error": "Model path not found"})
        return

    p_path = Path(polish_path)
    POLISH_MODEL_PATH = polish_path
    if p_path.suffix.lower() == ".gguf":
        engine = None
        try:
            if torch is None:
                import torch as torch_module
                torch = torch_module
            if not torch.cuda.is_available():
                raise RuntimeError("The CUDA refinement engine requires an NVIDIA GPU")
            executable = find_server(MODELS_ROOT)
            if executable is None:
                raise RuntimeError("Local llama.cpp CUDA runtime not found")
            from transformers import AutoConfig, AutoTokenizer
            config = AutoConfig.from_pretrained(p_path.parent, local_files_only=True)
            if config.model_type != "qwen3_5":
                raise RuntimeError("The GGUF refinement profile requires a Qwen3.5 tokenizer/config")
            tok = AutoTokenizer.from_pretrained(p_path.parent, local_files_only=True)
            slots = max(1, min(8, int(os.environ.get("READDOC_LLAMA_SLOTS", "8"))))
            context_size = max(1024, min(4096, int(os.environ.get("READDOC_LLAMA_CONTEXT_PER_SLOT", "2048"))))
            cache_ram_mib = max(0, min(1024, int(os.environ.get("READDOC_LLAMA_CACHE_RAM_MIB", "0"))))
            with gpu_lock:
                engine = LocalCudaServer(p_path, executable, slots=slots, context_per_slot=context_size,
                                         cache_ram_mib=cache_ram_mib)
            polish_tokenizer = tok
            polish_model = engine
            polish_backend = "llama_server_cuda"
            polish_profile = "qwen35"
            identity = (f"{p_path.name}:{p_path.stat().st_size}:{p_path.stat().st_mtime_ns}:"
                        + json.dumps(engine.generation_options, sort_keys=True))
            polish_fingerprint = hashlib.sha256(identity.encode()).hexdigest()[:16]
            polish_model_name = f"{p_path.stem} (CUDA, {slots} slots)"
            polish_ready = True
            polish_status = "ready"
            if polish_thread is None or not polish_thread.is_alive():
                polish_thread = threading.Thread(target=polish_worker_loop, daemon=True)
                polish_thread.start()
            print(f"[bg] {polish_model_name} ready; Flash Attention, continuous batching, "
                  "all layers on GPU; thinking disabled", file=sys.stderr, flush=True)
            emit_json({"polish_available": True, "polish_status": "ready", "polish_model": polish_model_name})
            return
        except Exception as exc:
            if engine is not None:
                engine.close()
            polish_ready = False
            polish_status = "crashed"
            print(f"[bg] Could not start CUDA engine: {exc}", file=sys.stderr, flush=True)
            emit_json({"polish_available": False, "polish_status": "crashed", "polish_error": str(exc)})
            return
    # Load directly onto CUDA; do not silently offload layers into system RAM.
    if p_path.is_dir():
        model_dir = str(p_path)
        try:
            if torch is None:
                import torch as torch_module
                torch = torch_module
            if not torch.cuda.is_available():
                raise RuntimeError("Refinement requires a CUDA-enabled PyTorch installation")
            from transformers import AutoConfig, AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
            config = AutoConfig.from_pretrained(model_dir, local_files_only=True)
            if config.model_type not in ("qwen2", "qwen3", "hunyuan_v1_dense"):
                raise RuntimeError(f"Unsupported refinement architecture: {config.model_type}")
            polish_profile = {"hunyuan_v1_dense": "hymt", "qwen3": "qwen"}.get(config.model_type, "vylinh")
            native = polish_profile == "hymt"
            compute_dtype = torch.bfloat16 if native and torch.cuda.is_bf16_supported() else torch.float16
            precision = "BF16" if compute_dtype == torch.bfloat16 else "FP16"
            print(f"[bg] Initializing Polish Model ({Path(model_dir).name}) ...",
                  file=sys.stderr, flush=True)
            bnb_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_use_double_quant=True,
            )
            tok = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
            tok.padding_side = "left"
            if tok.pad_token is None:
                tok.pad_token = tok.eos_token
            load_options = {} if native else {"quantization_config": bnb_config}
            mdl = AutoModelForCausalLM.from_pretrained(
                model_dir, **load_options,
                device_map="cuda",
                dtype=compute_dtype,
                attn_implementation="sdpa",
                local_files_only=True,
            ).eval()
            fused_count = enable_fused_rmsnorm(mdl) if FUSED_RMSNORM else 0
            polish_tokenizer = tok
            polish_model = mdl
            files = sorted(Path(model_dir).glob("*.safetensors"))
            identity = config.to_json_string() + repr(
                [(f.name, f.stat().st_size, f.stat().st_mtime_ns) for f in files])
            polish_fingerprint = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
            polish_backend = "torch_" + precision.lower() if native else "torch_bnb4"
            polish_model_name = f"{Path(model_dir).name} ({precision if native else '4-bit NF4'} CUDA)"
            polish_ready = True
            polish_status = "ready"
            if polish_thread is None or not polish_thread.is_alive():
                polish_thread = threading.Thread(target=polish_worker_loop, daemon=True)
                polish_thread.start()
            vram_mb = 0
            if torch is not None and torch.cuda.is_available():
                vram_mb = int(torch.cuda.memory_allocated() / 1024 / 1024)
            print(f"[bg] {polish_model_name} ready. VRAM: {vram_mb} MB, fused norms={fused_count}",
                  file=sys.stderr, flush=True)
            print(f"[bg] Polish config: batch<={POLISH_BATCH_SIZE}, "
                  f"tokens<={POLISH_TOKEN_BUDGET}, output<={POLISH_MAX_NEW_TOKENS}, "
                  f"dtype={precision}, attention=sdpa", file=sys.stderr, flush=True)
            # Notify Qt that polish is now available
            emit_json({"polish_available": True, "polish_status": "ready", "polish_model": polish_model_name})
            return
        except Exception as exc:
            polish_ready = False
            polish_status = "crashed"
            print(f"[bg] Could not load refinement model: {exc}", file=sys.stderr, flush=True)
            emit_json({"polish_available": False, "polish_status": "crashed", "polish_error": str(exc)})
            return

    polish_status = "disabled"
    print("[bg] No compatible polish model found.", file=sys.stderr, flush=True)
    emit_json({"polish_available": False, "polish_status": "disabled", "error": "No compatible model"})


def init_polish_model():
    """Schedule local refinement loading in a background daemon thread."""
    global polish_ready, polish_status
    if (polish_ready and polish_backend == "llama_server_cuda"
            and polish_model.process.poll() is not None):
        polish_model.close()
        polish_ready = False
    if polish_ready:
        emit_json({"polish_available": True, "polish_status": "ready",
                   "polish_model": polish_model_name})
        return
    if polish_load_lock.locked():
        return
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
    with request_state_lock:
        active_requests.update(value.get("id", 0) for value in batch_requests)

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
            pending_polish = []
            for index, value in enumerate(group):
                req_id = value.get("id", 0)
                translated = translations[index] if index < len(translations) else ""
                text_src = value.get("text", "")
                response.append({"id": req_id, "translated": translated, "stage": "raw"})

                context = str(value.get("context", ""))[-POLISH_CONTEXT_CHARS:]
                pending_polish.append((req_id, text_src, translated, context) if context else
                                      (req_id, text_src, translated))
            # Strict raw-before-polish ordering, even on an immediate cache hit.
            emit_json({"results": response})
            for item in pending_polish:
                enqueue_polish(*item)
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
    # The selected refinement model sends its own update after background load.
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
            if request.get("action") == "cancel":
                cancel_request_ids(request.get("ids", []))
                continue
            if request.get("action") == "clear_cache":
                clear_translation_memory()
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
                    "polish_metrics": snapshot_polish_metrics(),
                })
                continue

            if request.get("action") == "restart_polish":
                print("[daemon] Received restart_polish command", file=sys.stderr, flush=True)
                init_polish_model()
                continue

            if request.get("action") == "polish_batch":
                items = request.get("items", [])
                for it in items:
                    enqueue_polish(it.get("id", 0), it.get("text", ""), it.get("raw", ""),
                                   str(it.get("context", ""))[-POLISH_CONTEXT_CHARS:])
                continue

            batch_requests = request.get("batch")
            if batch_requests is not None:
                stream_request_batch(batch_requests)
            else:
                stream_request_batch([request])
        except Exception as exc:
            print(f"Invalid translation request: {exc}", file=sys.stderr, flush=True)
            emit_json({"error": str(exc)})


if __name__ == "__main__":
    main()
