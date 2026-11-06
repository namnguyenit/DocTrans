"""Offline GPU benchmark; run with the same Python environment as readDoc.

Uses synthetic technical sentences, never user document text. Loads both models
to include VinAI's resident VRAM, and disables the translation memory for timing.
"""
import argparse
import importlib.util
import json
import pathlib
import statistics
import time
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SAMPLES = [
    ("The driver allocates a buffer before starting the DMA transfer.",
     "Trình điều khiển phân bổ một bộ đệm trước khi bắt đầu truyền DMA."),
    ("Restart the service after updating the configuration file.",
     "Khởi động lại dịch vụ sau khi cập nhật tệp cấu hình."),
    ("The kernel checks access permissions before mapping physical memory into the process address space.",
     "Nhân kiểm tra quyền truy cập trước khi ánh xạ bộ nhớ vật lý vào không gian địa chỉ tiến trình."),
    ("A timeout does not necessarily mean that the remote device has failed.",
     "Hết thời gian chờ không nhất thiết có nghĩa là thiết bị từ xa đã hỏng."),
    ("Use a separate queue for each connection to prevent blocking unrelated requests.",
     "Sử dụng một hàng đợi riêng cho mỗi kết nối để tránh chặn các yêu cầu không liên quan."),
    ("The interrupt handler must release the lock before returning control to the scheduler.",
     "Trình xử lý ngắt phải giải phóng khóa trước khi trả lại quyền điều khiển cho bộ lập lịch."),
    ("This setting reduces memory usage but may increase latency under heavy load.",
     "Cài đặt này giảm sử dụng bộ nhớ nhưng có thể tăng độ trễ khi tải nặng."),
    ("Verify that all pending writes have completed before disconnecting the storage device.",
     "Xác minh rằng tất cả các lần ghi đang chờ đã hoàn tất trước khi ngắt kết nối thiết bị lưu trữ."),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--daemon", type=pathlib.Path,
                        default=ROOT / "src/System/local_nmt_daemon.py")
    parser.add_argument("--batch-sizes", default="1,2,4,8")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--long-samples", action="store_true")
    parser.add_argument("--include-long", action="store_true",
                        help="Also measure four-sentence blocks with the same loaded models")
    parser.add_argument("--pipeline", action="store_true",
                        help="Also check raw and polish responses through the live worker queue")
    parser.add_argument("--compare-fused", action="store_true",
                        help="Compare PyTorch fused RMSNorm on the same loaded weights")
    parser.add_argument("--copies", type=int, default=1,
                        help="Repeat the synthetic corpus to test batches larger than eight")
    parser.add_argument("--context", action="store_true",
                        help="Attach the same bounded neighbouring passages as the UI")
    parser.add_argument("--compare-daemon", type=pathlib.Path,
                        help="Run an old polish implementation on the same loaded model for comparison")
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1 or args.copies < 1 or any(int(s) < 1 for s in args.batch_sizes.split(",")):
        parser.error("repeats and batch sizes must be positive")
    spec = importlib.util.spec_from_file_location("polish_benchmark_daemon", args.daemon)
    daemon = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(daemon)
    daemon.cache_get = lambda text: None
    daemon.cache_put = lambda text, result: None
    daemon.init_model()
    if not daemon.is_ready or not daemon.torch.cuda.is_available():
        raise RuntimeError("CUDA VinAI is required for a representative benchmark")
    daemon.translate_text_batch(["Hello world"])
    daemon._init_polish_model_background()
    if not daemon.polish_ready:
        raise RuntimeError("VyLinh did not load")
    if daemon.polish_backend == "llama_server_cuda" and (args.compare_daemon or args.compare_fused):
        parser.error("Kernel/old-daemon comparison requires READDOC_POLISH_MODEL pointing to a PyTorch checkpoint")
    torch = daemon.torch
    long_samples = [(" ".join(SAMPLES[(i+j) % len(SAMPLES)][0] for j in range(4)),
                     " ".join(SAMPLES[(i+j) % len(SAMPLES)][1] for j in range(4)))
                    for i in range(len(SAMPLES))]
    samples = long_samples if args.long_samples else SAMPLES
    samples = samples * args.copies
    long_samples = long_samples * args.copies
    def make_items(rows):
        items = [(i, en, vi) for i, (en, vi) in enumerate(rows)]
        if args.context:
            items = [item + (rows[(i-1) % len(rows)][0][-270:] + "\n" +
                             rows[(i+1) % len(rows)][0][:270],) for i, item in enumerate(items)]
        return items
    items = make_items(samples)
    daemon.polish_batch(items[:1])  # Warm kernels before measurement.
    report = {"gpu": torch.cuda.get_device_name(0), "daemon": str(args.daemon),
              "torch": torch.__version__, "long_samples": args.long_samples,
              "repeats": args.repeats, "measurements": []}
    if args.compare_daemon:
        old_spec = importlib.util.spec_from_file_location("old_daemon", args.compare_daemon)
        old_daemon = importlib.util.module_from_spec(old_spec)
        old_spec.loader.exec_module(old_daemon)
        for name in ("torch", "polish_ready", "polish_model", "polish_tokenizer"):
            setattr(old_daemon, name, getattr(daemon, name))
        old_daemon.cache_get = lambda text: None
        old_daemon.cache_put = lambda text, result: None
        report["comparison_daemon"] = str(args.compare_daemon)
        measure(old_daemon, items, 1, args, report, "baseline-short")
    for size in map(int, args.batch_sizes.split(",")):
        measure(daemon, items, size, args, report, "long" if args.long_samples else "short")
    if args.include_long and not args.long_samples:
        items = make_items(long_samples)
        for size in map(int, args.batch_sizes.split(",")):
            measure(daemon, items, size, args, report, "long")
    if args.compare_fused:
        report["fused_norm_layers"] = daemon.enable_fused_rmsnorm(daemon.polish_model)
        items = make_items(samples)
        daemon.polish_batch(items)
        for size in map(int, args.batch_sizes.split(",")):
            measure(daemon, items, size, args, report, "fused-short")
        if args.include_long:
            items = make_items(long_samples)
            daemon.polish_batch(items)
            for size in map(int, args.batch_sizes.split(",")):
                measure(daemon, items, size, args, report, "fused-long")
    if args.pipeline:
        events = []
        daemon.emit_json = events.append
        started = time.perf_counter()
        daemon.stream_request_batch([{"id": i, "text": en} for i, (en, _) in enumerate(SAMPLES)])
        daemon.polish_queue.join()
        rows = [row for event in events for row in event.get("results", [])]
        raw = {row["id"] for row in rows if row.get("stage") == "raw"}
        polished = {row["id"] for row in rows if row.get("stage") == "polish"}
        failures = [row for event in events for row in event.get("failures", [])]
        report["pipeline"] = {"seconds": round(time.perf_counter() - started, 3),
                              "raw_ids": sorted(raw), "polish_ids": sorted(polished),
                              "failures": failures, "events": events}
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if raw != set(range(len(SAMPLES))) or polished != raw or failures:
            raise RuntimeError("Incomplete pipeline responses")
        print("Pipeline check passed: all raw and polish responses received", flush=True)
    report["complete"] = True
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Benchmark complete", flush=True)


def measure(daemon, items, size, args, report, profile):
    torch = daemon.torch
    daemon.POLISH_BATCH_SIZE = size
    # Warm this exact batch shape; then measure sustained performance.
    daemon.polish_batch(items[:size])
    torch.cuda.reset_peak_memory_stats()
    generation_sizes = []
    completed_rows = 0

    native = daemon.polish_backend == "llama_server_cuda"
    method = "complete_batch" if native else "generate"
    original_generate = getattr(daemon.polish_model, method)
    if native:
        def tracked_generate(prompts, max_tokens, **kwargs):
            nonlocal completed_rows
            rows = original_generate(prompts, max_tokens, cache_prompt=False)
            generation_sizes.append(len(rows))
            completed_rows += sum(row.get("stop_type") in ("eos", "word") and not row.get("truncated") for row in rows)
            return rows
    else:
        def tracked_generate(**kwargs):
            nonlocal completed_rows
            output = original_generate(**kwargs)
            generation_sizes.append(output.shape[0])
            tokens = output[:, kwargs["input_ids"].shape[1]:]
            completed_rows += int((tokens == daemon.polish_tokenizer.eos_token_id).any(dim=1).sum())
            return output

    timings = []
    with mock.patch.object(daemon.polish_model, method, side_effect=tracked_generate):
        for _ in range(args.repeats):
            torch.cuda.synchronize()
            started = time.perf_counter()
            results = []
            for start in range(0, len(items), size):
                results.extend(daemon.polish_batch(items[start:start + size]))
            torch.cuda.synchronize()
            timings.append(time.perf_counter() - started)
    elapsed = statistics.median(timings)
    row = {"profile": profile, "batch_size": size, "sentences": len(items), "seconds": round(elapsed, 3),
           "sentences_per_second": round(len(items) / elapsed, 3),
           "runs_seconds": [round(t, 3) for t in timings],
           "generated_rows": sum(generation_sizes), "completed_rows": completed_rows,
           "generation_batch_sizes": generation_sizes,
           "peak_allocated_mib": round(torch.cuda.max_memory_allocated() / 2**20),
           "peak_reserved_mib": round(torch.cuda.max_memory_reserved() / 2**20),
           "results": results}
    report["measurements"].append(row)
    print(json.dumps(row, ensure_ascii=False), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if sum(generation_sizes) != len(items) * args.repeats:
        raise RuntimeError("Benchmark skipped eligible input rows; inspect the report before comparing timings")


if __name__ == "__main__":
    main()
