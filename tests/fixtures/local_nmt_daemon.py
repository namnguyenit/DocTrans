"""Deterministic test-only protocol peer. Never loads or downloads model weights."""
import json
import os
import queue
import sys
import threading
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.stdin.reconfigure(encoding="utf-8")
output_lock = threading.Lock()
jobs = queue.Queue()
cancelled = set()
verbatim = os.environ.get("READDOC_TEST_VERBATIM") == "1"


def emit(value):
    with output_lock:
        print(json.dumps(value, ensure_ascii=False), flush=True)


def worker():
    time.sleep(0.15)  # Exercise documents arriving before the polish model is ready.
    emit({"polish_available": True, "polish_status": "ready", "polish_model": "test-only"})
    while True:
        batch = [jobs.get()]
        while len(batch) < 8:
            try:
                batch.append(jobs.get_nowait())
            except queue.Empty:
                break
        time.sleep(0.01)
        # Out-of-order responses expose request-id collisions between tabs.
        emit({"results": [{"id": item["id"], "translated": item["text"] if verbatim else "VI_RESULT: " + item["text"],
                           "stage": "polish", "cancelled": item["id"] in cancelled}
                          for item in reversed(batch)]})
        for _ in batch:
            jobs.task_done()


emit({"available": True, "polish_available": False, "polish_status": "loading", "model": "test-only"})
threading.Thread(target=worker, daemon=True).start()
for line in sys.stdin:
    request = json.loads(line)
    action = request.get("action")
    if action == "cancel":
        cancelled.update(request["ids"])
        emit({"results": [{"id": i, "translated": "", "stage": "polish", "cancelled": True}
                          for i in request["ids"]]})
    elif action == "clear_cache":
        emit({"cache_cleared": True})
    elif action == "status":
        emit({"action": "status_response", "nmt_ready": True, "polish_ready": True, "polish_status": "ready"})
    else:
        batch = request.get("items" if action == "polish_batch" else "batch", [request])
        failures = [item for item in batch if "FAIL_MODEL" in item.get("text", "")]
        batch = [item for item in batch if item not in failures]
        if failures:
            emit({"failures": [{"id": item["id"], "error": "synthetic document failure"} for item in failures]})
        if action != "polish_batch":
            emit({"results": [{"id": item["id"], "translated": item["text"] if verbatim else "RAW_RESULT: " + item["text"], "stage": "raw"}
                              for item in batch]})
        for item in batch:
            jobs.put(item)
