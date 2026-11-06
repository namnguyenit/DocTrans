"""Polish scheduling and failure handling without loading model weights."""
import importlib.util
import pathlib
import queue
import threading
import unittest
from unittest import mock

import torch

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("daemon", ROOT / "src/System/local_nmt_daemon.py")
daemon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(daemon)


class CpuInputs(dict):
    def to(self, device):
        return self


class Tokenizer:
    pad_token_id = 0
    eos_token_id = 2

    def encode(self, text, **kwargs):
        return list(range(len(text.split())))

    def __call__(self, prompts, **kwargs):
        width = max(len(p.split()) for p in prompts)
        ids = [[0] * (width - len(p.split())) + [1] * len(p.split()) for p in prompts]
        return CpuInputs(input_ids=torch.tensor(ids), attention_mask=torch.tensor(ids))

    def batch_decode(self, tokens, **kwargs):
        return ["Bản dịch: Câu đã được hiệu đính đầy đủ." for _ in tokens]


class Model:
    def generate(self, input_ids, **kwargs):
        suffix = torch.tensor([[7, 8, 2]] * input_ids.shape[0])
        return torch.cat((input_ids, suffix), dim=1)


class PolishPipelineTests(unittest.TestCase):
    def setUp(self):
        self.patches = mock.patch.multiple(
            daemon, torch=torch, polish_ready=True, polish_tokenizer=Tokenizer(),
            polish_model=Model(), POLISH_BATCH_SIZE=4, POLISH_TOKEN_BUDGET=2048,
            cache_db=None, cache_get=mock.Mock(return_value=None), cache_put=mock.Mock(),
            polish_queue=queue.Queue(), emit_json=mock.Mock(),
            active_requests=set(), cancelled_requests=set(), polish_status="ready",
        )
        self.patches.start()
        self.addCleanup(self.patches.stop)
        self.items = [(i, f"The driver handles request {i}.",
                       f"Trình điều khiển xử lý yêu cầu thứ {i}.") for i in range(8)]

    def test_real_batch_preserves_ids_and_uses_one_generation(self):
        items = [(i, "The driver handles requests.", "Trình điều khiển xử lý các yêu cầu.") for i in range(4)]
        with mock.patch.object(daemon.polish_model, "generate", wraps=daemon.polish_model.generate) as generate:
            result = daemon.polish_batch(items)
        self.assertEqual([row[0] for row in result], [0, 1, 2, 3])
        self.assertTrue(all(row[1] == "Câu đã được hiệu đính đầy đủ." for row in result))
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(generate.call_args.kwargs["input_ids"].shape[0], 4)

    def test_cache_hit_and_code_do_not_go_to_model(self):
        daemon.cache_get.side_effect = lambda key: "Bản đã lưu." if 'request 0.' in key else None
        items = [self.items[0], (10, "class Device:", "Đây là một lớp thiết bị.")]
        with mock.patch.object(daemon.polish_model, "generate") as generate:
            self.assertEqual(daemon.polish_batch(items), [(0, "Bản đã lưu."), (10, items[1][2])])
        generate.assert_not_called()

    def test_oom_splits_and_retries_every_request(self):
        calls = []

        def generate(entries):
            calls.append(len(entries))
            if len(entries) > 1:
                raise torch.cuda.OutOfMemoryError("synthetic allocation failure")
            return [(entries[0][0][0], "Bản hoàn chỉnh.")]

        with mock.patch.object(daemon, "generate_polish_batch", side_effect=generate), \
                mock.patch.object(torch.cuda, "empty_cache"):
            result = daemon.polish_batch(self.items[:4])
        self.assertEqual([i for i, _ in result], [0, 1, 2, 3])
        self.assertEqual([text for _, text in result], ["Bản hoàn chỉnh."] * 4)
        self.assertIn(4, calls)
        self.assertEqual(calls.count(1), 4)

    def test_token_budget_limits_padded_batches(self):
        daemon.POLISH_TOKEN_BUDGET = 310
        sizes = []

        def generate(entries):
            sizes.append(len(entries))
            self.assertLessEqual((max(e[3] for e in entries) + max(e[2] for e in entries)) * len(entries), 310)
            return [(e[0][0], e[0][2]) for e in entries]

        with mock.patch.object(daemon, "generate_polish_batch", side_effect=generate):
            result = daemon.polish_batch(self.items)
        self.assertEqual(len(result), 8)
        self.assertGreater(len(sizes), 1)

    def test_truncated_generation_returns_raw_and_does_not_cache(self):
        def truncated(input_ids, **kwargs):
            return torch.cat((input_ids, torch.tensor([[7, 8]] * input_ids.shape[0])), dim=1)

        with mock.patch.object(daemon.polish_model, "generate", side_effect=truncated):
            self.assertEqual(daemon.polish_batch(self.items[:1]), [(0, self.items[0][2])])
        daemon.cache_put.assert_not_called()

    def test_native_truncated_response_also_retains_raw(self):
        engine = mock.Mock(context_per_slot=2048)
        engine.complete_batch.return_value = [{"content": "Câu bị cắt ngang", "stop_type": "limit", "truncated": False}]
        with mock.patch.object(daemon, "polish_backend", "llama_server_cuda"), \
                mock.patch.object(daemon, "polish_model", engine):
            self.assertEqual(daemon.polish_batch(self.items[:1]), [(0, self.items[0][2])])
        daemon.cache_put.assert_not_called()

    def test_native_short_preview_does_not_cut_a_longer_translation(self):
        def complete(prompts, limit):
            # The old estimate from a three-word preview allowed < 50 tokens.
            self.assertGreaterEqual(limit, 160)
            self.assertLessEqual(limit, 384)
            return [{"content": "Bản dịch đầy đủ theo đúng ngữ cảnh.", "stop_type": "eos"}]
        engine = mock.Mock(context_per_slot=2048)
        engine.complete_batch.side_effect = complete
        item = (42, "The driver checks permissions before mapping the physical buffer.", "Bản thô ngắn.")
        with mock.patch.object(daemon, "polish_backend", "llama_server_cuda"), \
                mock.patch.object(daemon, "polish_model", engine):
            self.assertEqual(daemon.polish_batch([item]), [(42, "Bản dịch đầy đủ theo đúng ngữ cảnh.")])

    def test_model_codes_and_email_are_protected_and_validated(self):
        source = "QCS6490 uses LPDDR4X; send reports to docs@example.com."
        protected, replacements = daemon.protect_technical_text(source)
        self.assertNotIn("QCS6490", protected)
        self.assertNotIn("docs@example.com", protected)
        self.assertEqual(daemon.restore_technical_text(protected, replacements), source)
        self.assertFalse(daemon.preserves_source_literals(source, "QCS6490Name uses LPDDR4X; docs@example.com."))
        self.assertFalse(daemon.preserves_source_literals(source, "QCS6490 uses LPDDR4X; another@example.com."))

    def test_pdf_leaders_are_short_model_inputs_and_restored_exactly(self):
        source = "1 Getting started " + ". " * 60 + "30"
        compact, leaders = daemon.protect_dot_leaders(source)
        self.assertLess(len(compact), 60)
        self.assertEqual(len(leaders), 1)
        encoded, replacements = daemon.protect_technical_text(source)
        self.assertNotIn(". . . . .", encoded)
        self.assertEqual(daemon.restore_technical_text(encoded, replacements), source)
        raw = "Bản dịch thô được giữ nguyên."
        entry = ((8, source, raw), "prompt", 384, 100)
        with mock.patch.object(daemon, "polish_profile", "qwen35"):
            result = daemon.finish_polish(entry, "1 Bắt đầu __LEADER0__ 30", True)[1]
            self.assertEqual(result, "1 Bắt đầu " + next(iter(leaders.values())) + " 30")
            self.assertEqual(daemon.finish_polish(entry, "1 Bắt đầu 30", True)[1], raw)
        self.assertNotIn("__LEADER", result)

    def test_native_queue_does_not_use_pytorch_padded_batch_cost(self):
        daemon.POLISH_TOKEN_BUDGET = 1024
        sizes = []
        def generate(entries):
            sizes.append(len(entries))
            return [(entry[0][0], entry[0][2]) for entry in entries]
        with mock.patch.object(daemon, "polish_backend", "llama_server_cuda"), \
                mock.patch.object(daemon, "polish_model", mock.Mock(context_per_slot=2048)), \
                mock.patch.object(daemon, "generate_polish_batch", side_effect=generate):
            result = daemon.polish_batch(self.items[:4])
        self.assertEqual(len(result), 4)
        self.assertEqual(sizes, [4])

    def test_native_crash_drains_waiting_work_and_reports_model_failure(self):
        engine = mock.Mock()
        engine.process.poll.return_value = 1
        engine.complete_batch.side_effect = RuntimeError("synthetic native process exit")
        daemon.polish_queue.put(self.items[1])
        prepared = [(self.items[0], "prompt", 50, 10)]
        with mock.patch.object(daemon, "polish_backend", "llama_server_cuda"), \
                mock.patch.object(daemon, "polish_model", engine):
            self.assertEqual(daemon.run_polish_batch(prepared), [(0, self.items[0][2])])
        self.assertFalse(daemon.polish_ready)
        self.assertEqual(daemon.polish_status, "crashed")
        self.assertEqual(daemon.polish_queue.unfinished_tasks, 0)
        engine.close.assert_called_once()

    def test_worker_failure_still_emits_results_and_balances_queue(self):
        for item in self.items[:3]:
            daemon.polish_queue.put(item)
        daemon.polish_queue.put(None)
        with mock.patch.object(daemon, "polish_batch", side_effect=RuntimeError("synthetic failure")):
            daemon.polish_worker_loop()
        self.assertEqual(daemon.polish_queue.unfinished_tasks, 0)
        self.assertEqual(len(daemon.emit_json.call_args.args[0]["results"]), 3)

    def test_busy_loader_does_not_load_second_copy(self):
        with mock.patch.object(daemon, "polish_load_lock", threading.Lock()), \
                mock.patch.object(daemon, "_load_polish_model") as load:
            with daemon.polish_load_lock:
                daemon._init_polish_model_background()
        load.assert_not_called()

    def test_polish_cache_depends_on_raw_translation(self):
        self.assertNotEqual(daemon.polish_cache_key("same source", "bản dịch A"),
                            daemon.polish_cache_key("same source", "bản dịch B"))

    def test_context_is_part_of_cache_identity(self):
        self.assertNotEqual(daemon.polish_cache_key("The port is blocked.", "Cảng bị chặn.", "TCP firewall"),
                            daemon.polish_cache_key("The port is blocked.", "Cảng bị chặn.", "Cargo ships"))

    def test_interleaved_document_context_stays_with_each_request(self):
        items = [(0, "The port is blocked.", "Cổng đã bị chặn.", "DOCUMENT_A TCP firewall"),
                 (1, "The port is blocked.", "Cảng đã bị chặn.", "DOCUMENT_B Cargo ships")]
        captured = []
        def generate(entries):
            captured.extend(entries)
            return [(e[0][0], e[0][2]) for e in entries]
        with mock.patch.object(daemon, "generate_polish_batch", side_effect=generate):
            daemon.polish_batch(items)
        for item, prompt, *_ in captured:
            own = "DOCUMENT_A" if item[0] == 0 else "DOCUMENT_B"
            other = "DOCUMENT_B" if item[0] == 0 else "DOCUMENT_A"
            self.assertIn(own, prompt)
            self.assertNotIn(other, prompt)

    def test_literal_guard_rejects_changed_number_identifier_or_language(self):
        self.assertTrue(daemon.preserves_source_literals(
            "Set `max_connections` to 64 and keep {user_id}.",
            "Đặt `max_connections` thành 64 và giữ {user_id}."))
        self.assertFalse(daemon.preserves_source_literals("Keep 3 retries.", "Giữ 5 lần thử lại."))
        self.assertFalse(daemon.preserves_source_literals("Set the offset to -3.5.", "Đặt độ lệch là 3.5."))
        self.assertFalse(daemon.preserves_source_literals("Keep ${user_id}.", "Giữ {user_id}."))
        self.assertFalse(daemon.preserves_source_literals("Keep {{name}}.", "Giữ {name}."))
        self.assertFalse(daemon.preserves_source_literals("Keep {user_id}.", "Giữ {id}."))
        self.assertFalse(daemon.preserves_source_literals("The plant stopped operating.", "Nhà máy停止运作."))

    def test_avoid_in_normal_prose_is_not_mistaken_for_void_code(self):
        self.assertTrue(daemon.is_polish_eligible(
            "Use separate queues to avoid blocking requests.",
            "Sử dụng hàng đợi riêng để tránh chặn yêu cầu."))

    def test_loading_keeps_raw_translation_waiting_for_real_polish(self):
        daemon.polish_ready = False
        daemon.polish_status = "loading"
        daemon.enqueue_polish(*self.items[0])
        self.assertEqual(daemon.polish_queue.get_nowait(), self.items[0])
        daemon.polish_queue.task_done()
        daemon.emit_json.assert_not_called()

    def test_full_queue_waits_and_does_not_drop_polish(self):
        entered = threading.Event()

        class ObservedQueue(queue.Queue):
            def put(self, item, *args, **kwargs):
                if self.full():
                    entered.set()
                return super().put(item, *args, **kwargs)

        daemon.polish_queue = ObservedQueue(maxsize=1)
        daemon.polish_queue.put(self.items[0])
        producer = threading.Thread(target=daemon.enqueue_polish, args=self.items[1], daemon=True)
        producer.start()
        self.assertTrue(entered.wait(2))
        self.assertTrue(producer.is_alive())
        self.assertEqual(daemon.polish_queue.get_nowait(), self.items[0])
        daemon.polish_queue.task_done()
        producer.join(2)
        self.assertFalse(producer.is_alive())
        self.assertEqual(daemon.polish_queue.get_nowait(), self.items[1])
        daemon.polish_queue.task_done()
        daemon.emit_json.assert_not_called()

    def test_cancelled_document_does_not_cancel_other_document(self):
        daemon.active_requests.update([0, 1])
        daemon.cancel_request_ids([0])
        for item in self.items[:2]:
            daemon.polish_queue.put(item)
        daemon.polish_queue.put(None)
        with mock.patch.object(daemon, "polish_batch", side_effect=lambda items: [(i[0], "Đã sửa.") for i in items]) as polish:
            daemon.polish_worker_loop()
        self.assertEqual([i[0] for i in polish.call_args.args[0]], [1])
        results = daemon.emit_json.call_args.args[0]["results"]
        self.assertEqual(sorted(row["id"] for row in results), [0, 1])
        self.assertEqual(daemon.polish_queue.unfinished_tasks, 0)

    def test_raw_is_emitted_before_immediate_polish(self):
        def immediate(req_id, source, raw):
            daemon.emit_json({"results": [{"id": req_id, "stage": "polish", "translated": raw}]})

        with mock.patch.object(daemon, "token_count", return_value=10), \
                mock.patch.object(daemon, "translate_text_batch", return_value=[self.items[0][2]]), \
                mock.patch.object(daemon, "enqueue_polish", side_effect=immediate):
            daemon.stream_request_batch([{"id": 0, "text": self.items[0][1]}])
        self.assertEqual([call.args[0]["results"][0]["stage"] for call in daemon.emit_json.call_args_list],
                         ["raw", "polish"])

    def test_source_context_survives_raw_translation_stage(self):
        requests = [{"id": 0, "text": "The port is blocked.", "context": "TCP firewall"},
                    {"id": 1, "text": "The port is blocked.", "context": "Cargo ships"}]
        with mock.patch.object(daemon, "token_count", return_value=10), \
                mock.patch.object(daemon, "translate_text_batch", return_value=["Cổng đã bị chặn."] * 2), \
                mock.patch.object(daemon, "enqueue_polish") as enqueue:
            daemon.stream_request_batch(requests)
        self.assertEqual([call.args[3] for call in enqueue.call_args_list], ["TCP firewall", "Cargo ships"])

    def test_failed_loader_finishes_waiting_requests(self):
        daemon.polish_queue.put(self.items[0])
        daemon.finish_waiting_polish()
        self.assertEqual(daemon.polish_queue.unfinished_tasks, 0)
        self.assertEqual(daemon.emit_json.call_args.args[0]["results"][0]["translated"], self.items[0][2])

    def test_clearing_translation_memory_keeps_pending_documents(self):
        daemon.polish_queue.put(self.items[0])
        daemon.clear_translation_memory()
        self.assertEqual(daemon.polish_queue.get_nowait(), self.items[0])
        daemon.polish_queue.task_done()


if __name__ == "__main__":
    unittest.main()
