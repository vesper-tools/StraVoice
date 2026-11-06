"""Cancellation must finish cleanup, restore controls, and preserve prior audio."""
import asyncio
from pathlib import Path
import queue
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app import App
from engine import synthesize


class GenerationCancelTests(unittest.TestCase):
    def window(self):
        window = SimpleNamespace(
            busy=True, closing=threading.Event(), generation_cancel=threading.Event(),
            worker_lock=threading.Lock(), worker_threads=[], worker_tasks={},
            audio_worker=None, events=queue.Queue(), filter_buttons={},
            latest=Path("previous.mp3"), generate=Mock(), update_model_ui=Mock(),
            update_selected_label=Mock(),
            set_generation_state=Mock(), animate_generation=Mock(),
            update_playback=Mock(), after=Mock(), poll=Mock(), show_error=Mock())
        for name in ("generate_btn", "preview_btn", "provider_menu", "locale",
                     "status", "generation_detail"):
            setattr(window, name, Mock())
        return window

    def test_stop_online_wait_cleans_partial_and_restores_ui(self):
        window = self.window()
        waiting = threading.Event()

        async def stream():
            yield {"type": "audio", "data": b"partial audio"}
            waiting.set()
            await asyncio.sleep(60)

        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "cancel.mp3"

            async def operation():
                return await synthesize("测试", "zh-CN-XiaoxiaoNeural", 1, 100, target,
                                        cancel=window.generation_cancel)

            with patch("engine.edge_tts.Communicate") as communicate:
                communicate.return_value.stream = stream
                App.worker(window, "audio", operation)
                self.assertTrue(waiting.wait(5))
                App.stop_generation(window)
                window.worker_threads[0].join(5)
                self.assertFalse(window.worker_threads[0].is_alive())
            self.assertFalse(target.exists())
            self.assertFalse(target.with_suffix(".part").exists())
        App.poll(window)
        self.assertFalse(window.busy)
        self.assertEqual(window.latest, Path("previous.mp3"))
        window.show_error.assert_not_called()
        window.set_generation_state.assert_called_with("已停止生成", "可以修改文稿或重新生成")
        self.assertEqual(window.generate_btn.configure.call_args.kwargs["text"], "生成配音")

    def test_stop_local_waits_for_native_cleanup(self):
        window = self.window()
        started, cleaned = threading.Event(), threading.Event()

        def native():
            started.set()
            window.generation_cancel.wait(5)
            cleaned.set()
            raise asyncio.CancelledError()

        async def operation():
            await asyncio.to_thread(native)

        App.worker(window, "audio", operation)
        self.assertTrue(started.wait(5))
        App.stop_generation(window)
        window.worker_threads[0].join(5)
        self.assertFalse(window.worker_threads[0].is_alive())
        self.assertTrue(cleaned.is_set())
        task, result, error = window.events.get_nowait()
        self.assertEqual(task, "audio")
        self.assertIsInstance(error, asyncio.CancelledError)

    def test_stop_wins_over_queued_completion_and_late_progress(self):
        window = self.window()
        window.events.put(("audio_stage", "旧进度", None))
        window.events.put(("audio_progress", 0.5, None))
        window.events.put(("audio", (Path("new.mp3"), "新音色", False), None))
        App.stop_generation(window)
        App.poll(window)
        self.assertEqual(window.latest, Path("previous.mp3"))
        window.generation_detail.configure.assert_not_called()
        window.show_error.assert_not_called()

    def test_repeated_stop_is_ignored(self):
        window = self.window()
        App.stop_generation(window)
        App.stop_generation(window)
        self.assertTrue(window.generation_cancel.is_set())
        window.generate_btn.configure.assert_called_once()


if __name__ == "__main__":
    unittest.main()
