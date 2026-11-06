"""Regression checks without loading model weights or writing permanent audio."""
import asyncio
from contextlib import ExitStack
from pathlib import Path
import tempfile
import threading
import unittest
import wave
from unittest.mock import Mock, patch

import numpy as np
import offline
import qwen_backend as qwen


class QwenTests(unittest.TestCase):
    def test_default_number_reading_reaches_qwen_without_changing_captions(self):
        text = "2026年，编号MD56，共56个。"
        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            folder = Path(temp)
            for owner, name, value in [
                (qwen, "package_installed", True), (qwen, "package_dir", folder),
                (qwen, "_device", "none"),
                (offline, "clones", [{"id": "test", "wav": "unused"}]),
                (offline, "_decode_audio", (np.zeros(2400), 24000)),
                (offline, "read_wave", (np.zeros(2400), 24000)),
            ]:
                stack.enter_context(patch.object(owner, name, return_value=value))
            def run(command, *args):
                spoken = (folder / command[command.index("-f") + 1]).read_text(encoding="utf-8")
                self.assertEqual(spoken, "二零二六年，编号MD五六，共五十六个。")
                return 0, "generated 20 frames"
            stack.enter_context(patch.object(qwen, "_run", side_effect=run))
            cues = []
            stack.enter_context(patch("subtitles.write_srt", side_effect=lambda target, items: cues.extend(items)))
            qwen.generate(text, "local:qwen3_q8:clone:test", 1, 100, folder / "result.wav")
            self.assertEqual("".join(cue[2] for cue in cues), text)

    def test_reference_trims_edge_silence_without_changing_original_or_internal_pause(self):
        rate = 24000
        sound = np.full(rate, .05, dtype=np.float32)
        samples = np.concatenate((np.zeros(rate), sound, np.zeros(rate // 2), sound, np.zeros(rate)))
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "reference.wav"
            source.write_bytes(b"original recording")
            qwen._REFERENCE_CACHE.clear()
            try:
                with patch.object(offline, "_decode_audio", return_value=(samples, rate)) as decode:
                    pcm, actual_rate, key = qwen.reference_audio(source)
                    self.assertEqual(qwen.reference_audio(source), (pcm, actual_rate, key))
                    decode.assert_called_once()
                result = np.frombuffer(pcm, dtype="<i2")
                self.assertAlmostEqual(len(result) / rate, 2.66, places=2)
                self.assertTrue(np.all(result[round(rate * 1.08):round(rate * 1.58)] == 0))
                self.assertEqual(source.read_bytes(), b"original recording")
            finally:
                qwen._REFERENCE_CACHE.clear()

    def test_single_chunk_removes_long_edge_silence_and_updates_subtitles(self):
        rate = 24000
        speech = np.sin(np.arange(rate * 2) * 2 * np.pi * 440 / rate) * .1
        samples = np.concatenate((np.zeros(rate * 3), speech, np.zeros(rate)))
        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            folder = Path(temp)
            for owner, name, value in [
                (qwen, "package_installed", True), (qwen, "package_dir", folder),
                (qwen, "_device", "none"), (qwen, "_run", (0, "generated 20 frames")),
                (offline, "clones", [{"id": "test", "wav": "unused"}]),
                (offline, "_decode_audio", (np.zeros(2400), rate)),
                (offline, "read_wave", (samples, rate)),
            ]:
                stack.enter_context(patch.object(owner, name, return_value=value))
            cues = []
            stack.enter_context(patch("subtitles.write_srt", side_effect=lambda target, items: cues.extend(items)))
            target = folder / "result.wav"
            qwen.generate("你好，欢迎试听。", "local:qwen3_q8:clone:test", 1, 100, target)
            with wave.open(str(target), "rb") as audio:
                pcm = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2")
            active = np.flatnonzero(np.abs(pcm) > 32)
            self.assertLess(active[0] / rate, .1)
            self.assertAlmostEqual(len(pcm) / rate, 2.16, places=2)
            self.assertAlmostEqual(cues[0][1], len(pcm) / rate)
            self.assertEqual(cues[0][0], 0)

    def test_native_failure_without_logs_has_action_and_exit_code(self):
        for code, expected in [(0xC0000135, "运行库"), (0xC000007B, "架构"),
                               (0xC0000139, "版本"), (0xC000001D, "处理器"),
                               (0xC0000017, "内存"), (0xC000012D, "内存"),
                               (0xC0000005, "异常退出")]:
            with self.subTest(code=code):
                for value in (code, code - 2**32):
                    detail = qwen._failure_detail(value, "")
                    self.assertIn(expected, detail)
                    self.assertIn(f"0x{code:08X}", detail)

    def test_failed_fallback_preserves_worker_error(self):
        command = ["llama-tts", "-f", "job-test/text.txt", "--device", "none"]
        with patch.object(qwen, "_WORKER", None), \
                patch.object(qwen, "_ResidentWorker", side_effect=OSError("worker failed")), \
                patch.object(Path, "is_file", return_value=True), \
                patch.object(qwen, "_run_once", return_value=(0xC0000135, "")):
            code, log = qwen._run(command, Path("."), None, None)
        self.assertEqual(code, 0xC0000135)
        self.assertIn("worker failed", log)

    def test_limit_retry_preserves_text_and_progress(self):
        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            folder = Path(temp)
            text = "试听测试文字" * 16 + "最后四字"
            cues, progress = [], []
            def run(command, *args):
                current = (folder / command[command.index("-f") + 1]).read_text(encoding="utf-8")
                return 0, "generated 512 frames" if len(current) > 30 else "generated 20 frames"
            for owner, name, value in [
                (qwen, "package_installed", True), (qwen, "package_dir", folder),
                (qwen, "_device", "none"),
                (offline, "clones", [{"id": "test", "wav": "unused"}]),
                (offline, "_decode_audio", (np.zeros(2400), 24000)),
                (offline, "read_wave", (np.zeros(2400), 24000)),
            ]:
                stack.enter_context(patch.object(owner, name, return_value=value))
            stack.enter_context(patch.object(qwen, "_run", side_effect=run))
            stack.enter_context(patch("subtitles.write_srt", side_effect=lambda target, items: cues.extend(items)))
            target = folder / "result.mp3"
            qwen.generate(text, "local:qwen3_q8:clone:test", 1, 100, target,
                          on_progress=progress.append)
            self.assertEqual("".join(cue[2] for cue in cues), text)
            self.assertTrue(all(len(cue[2]) <= 30 for cue in cues))
            self.assertEqual(progress, sorted(progress))
            self.assertGreater(target.stat().st_size, 0)
            self.assertFalse(list(folder.glob("job-*")))
            self.assertFalse(target.with_suffix(".part").exists())

    def test_cancel_stops_worker_without_compatibility_retry(self):
        worker = Mock()
        worker.wait.side_effect = asyncio.CancelledError()
        command = ["llama-tts", "-f", "job-test/text.txt", "--device", "none"]
        with patch.object(qwen, "_WORKER", None), patch.object(qwen, "_ResidentWorker", return_value=worker), \
                patch.object(Path, "is_file", return_value=True), patch.object(qwen, "_run_once") as fallback:
            with self.assertRaises(asyncio.CancelledError):
                qwen._run(command, Path("."), threading.Event(), None)
            worker.stop.assert_called_once()
            fallback.assert_not_called()
            self.assertIsNone(qwen._WORKER)

    def test_short_chunk_recovery_and_explicit_stop_reason(self):
        cases = [
            (["generated 512 frames; stop=eos"], [42], False),
            (["generated 512 frames; stop=limit", "generated 24 frames; stop=eos"], [42, 43], False),
            (["generated 512 frames", "generated 24 frames"], [42, 43], False),
            (["generated 512 frames; stop=limit"] * 2, [42, 43], True),
        ]
        for logs, seeds, fails in cases:
            with self.subTest(logs=logs), tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
                folder = Path(temp)
                for owner, name, value in [
                    (qwen, "package_installed", True), (qwen, "package_dir", folder),
                    (qwen, "_device", "none"),
                    (offline, "clones", [{"id": "test", "wav": "unused"}]),
                    (offline, "_decode_audio", (np.zeros(2400), 24000)),
                    (offline, "read_wave", (np.zeros(2400), 24000)),
                ]:
                    stack.enter_context(patch.object(owner, name, return_value=value))
                seen = []
                def run(command, *args):
                    seen.append(int(command[command.index("--seed") + 1]))
                    self.assertEqual((folder / command[command.index("-f") + 1]).read_text(encoding="utf-8"), "没")
                    return 0, logs[len(seen) - 1]
                stack.enter_context(patch.object(qwen, "_run", side_effect=run))
                cues = []
                stack.enter_context(patch("subtitles.write_srt", side_effect=lambda target, items: cues.extend(items)))
                target = folder / "result.wav"
                if fails:
                    with self.assertRaisesRegex(RuntimeError, "问题文字：'没'"):
                        qwen.generate("没", "local:qwen3_q8:clone:test", 1, 100, target)
                    self.assertFalse(target.exists())
                else:
                    qwen.generate("没", "local:qwen3_q8:clone:test", 1, 100, target)
                    self.assertEqual([cue[2] for cue in cues], ["没"])
                    self.assertTrue(target.exists())
                self.assertEqual(seen, seeds)
                self.assertFalse(target.with_suffix(".part").exists())
                self.assertFalse(list(folder.glob("job-*")))

    def test_worker_preserves_end_reason_in_protocol(self):
        for message, expected in [("DONE 512 eos", "generated 512 frames; stop=eos"),
                                  ("DONE 512 limit", "generated 512 frames; stop=limit"),
                                  ("DONE 20", "generated 20 frames")]:
            worker = Mock()
            worker.process.poll.return_value = None
            worker.closed.is_set.return_value = False
            worker.key = (".", ("--device", "none"), "zh")
            worker.wait.return_value = message
            with self.subTest(message=message), patch.object(qwen, "_WORKER", worker), \
                    patch.object(Path, "is_file", return_value=True):
                self.assertEqual(qwen._run(["tts", "-f", "job-test/text.txt", "--device", "none"],
                                          Path("."), None, None), (0, expected))

    def test_worker_failure_uses_compatibility_process(self):
        command = ["llama-tts", "-f", "job-test/text.txt", "--device", "none"]
        with patch.object(qwen, "_WORKER", None), \
                patch.object(qwen, "_ResidentWorker", side_effect=OSError("unavailable")), \
                patch.object(Path, "is_file", return_value=True), \
                patch.object(qwen, "_run_once", return_value=(0, "generated 20 frames")) as fallback:
            self.assertEqual(qwen._run(command, Path("."), None, None), (0, "generated 20 frames"))
            fallback.assert_called_once()

    def test_language_switch_restarts_resident_worker(self):
        command = ["llama-tts", "--tts-lang", "en", "-f", "job-test/text.txt", "--device", "none"]
        previous = Mock()
        previous.process.poll.return_value = None
        previous.closed.is_set.return_value = False
        previous.key = (str(Path(".")), ("--device", "none"), "zh")
        replacement = Mock()
        replacement.wait.side_effect = ["READY", "DONE 20"]
        with patch.object(qwen, "_WORKER", previous), \
                patch.object(qwen, "_ResidentWorker", return_value=replacement) as create, \
                patch.object(Path, "is_file", return_value=True):
            self.assertEqual(qwen._run(command, Path("."), None, None), (0, "generated 20 frames"))
        previous.stop.assert_called_once()
        create.assert_called_once()

    def test_generation_uses_matching_chinese_and_english_parameters(self):
        for text, expected in [("Hello, this is a test.", "en"), ("你好，这是测试。", "zh"), ("你好 hello", "zh")]:
            with self.subTest(text=text), tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
                folder = Path(temp)
                for owner, name, value in [
                    (qwen, "package_installed", True), (qwen, "package_dir", folder),
                    (qwen, "_device", "none"),
                    (offline, "clones", [{"id": "test", "wav": "unused"}]),
                    (offline, "_decode_audio", (np.zeros(2400), 24000)),
                    (offline, "read_wave", (np.zeros(2400), 24000)),
                ]:
                    stack.enter_context(patch.object(owner, name, return_value=value))
                run = stack.enter_context(patch.object(qwen, "_run", return_value=(0, "generated 20 frames")))
                qwen.generate(text, "local:qwen3_q8:clone:test", 1, 100, folder / "result.mp3")
                for call in run.call_args_list:
                    command = call.args[0]
                    self.assertEqual(command[command.index("--tts-lang") + 1], expected)
                    self.assertEqual(command[command.index("--min-p") + 1], "0.0")

    def test_idle_worker_releases_only_between_requests(self):
        worker = qwen._ResidentWorker.__new__(qwen._ResidentWorker)
        worker.closed = Mock()
        worker.closed.wait.side_effect = [False, True]
        worker.last_used = 0
        worker.stop = Mock()
        with patch.object(qwen.time, "monotonic", return_value=qwen._IDLE_SECONDS + 1):
            worker._idle()
        worker.stop.assert_called_once()
        worker.stop.reset_mock()
        worker.closed.wait.side_effect = [False, True]
        with qwen._LOCK, patch.object(qwen.time, "monotonic", return_value=qwen._IDLE_SECONDS + 1):
            worker._idle()
        worker.stop.assert_not_called()

    def test_live_worker_reuses_device_without_probe(self):
        worker = Mock()
        worker.process.poll.return_value = None
        worker.closed.is_set.return_value = False
        worker.key = (str(Path("models")), ("--device", "Vulkan1"))
        with patch.object(qwen, "_WORKER", worker), patch.object(qwen, "_native_popen") as probe:
            self.assertEqual(qwen._device(Path("tts.exe"), Path("models")), "Vulkan1")
            probe.assert_not_called()

    def test_idle_worker_stays_loaded_during_short_break(self):
        worker = qwen._ResidentWorker.__new__(qwen._ResidentWorker)
        worker.closed = Mock()
        worker.closed.wait.side_effect = [False, True]
        worker.last_used = 0
        worker.stop = Mock()
        with patch.object(qwen.time, "monotonic", return_value=180):
            worker._idle()
        worker.stop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
