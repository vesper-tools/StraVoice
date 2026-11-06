"""Task recovery, cache correctness, lexicon and safe chunking regressions."""
import asyncio
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import wave

import numpy as np

from dubbing_tasks import TaskStore, render_task
from pauses import read_cues
from pronunciation import apply, validate
from segmentation import split_text, sentence_segments, prepare_join, missing_pause
from subtitles import write_srt


class TaskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = TaskStore(Path(self.temp.name))
        self.task = self.store.create("甲" * 240 + "乙" * 20, "online-test", "测试", 1, 100)
        self.calls = []

    async def render(self, text, voice, speed, volume, path, **kwargs):
        self.calls.append(text)
        with wave.open(str(path), "wb") as source:
            source.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
            source.writeframes(np.full(4800, 1500, dtype="<i2").tobytes())
        write_srt(path, [(0, .2, text)])
        return path

    def run_task(self, task=None, **kwargs):
        return asyncio.run(render_task(self.store, task or self.task, render=self.render, **kwargs))

    def test_failure_restart_reuses_finished_segments(self):
        async def fail(text, *args, **kwargs):
            if text.startswith("乙"):
                raise RuntimeError("断网")
            return await self.render(text, *args, **kwargs)
        with self.assertRaisesRegex(RuntimeError, "断网"):
            asyncio.run(render_task(self.store, self.task, render=fail))
        loaded = TaskStore(self.store.root).load(self.task["id"])
        self.assertEqual(loaded["status"], "failed")
        result = self.run_task(loaded)
        self.assertEqual(len(self.calls), 2)
        self.assertTrue(result.is_file())
        self.assertEqual(loaded["status"], "complete")

    def test_failed_edit_can_be_retried_and_saved(self):
        original = self.task["segments"][0]["text"]
        with patch.object(self.store, "save", side_effect=OSError("磁盘写入失败")):
            with self.assertRaises(OSError):
                self.store.edit(self.task, 0, "重试保存的文字")
        self.assertEqual(self.store.load(self.task["id"])["segments"][0]["text"], original)
        self.store.edit(self.task, 0, "重试保存的文字")
        self.assertEqual(self.store.load(self.task["id"])["segments"][0]["text"], "重试保存的文字")

    def test_task_list_skips_invalid_task_structure(self):
        broken_id = "f" * 32
        folder = self.store.folder(broken_id)
        folder.mkdir()
        valid = dict(self.task, id=broken_id)
        missing_updated = dict(valid)
        del missing_updated["updated"]
        for payload in ([], missing_updated, dict(valid, segments=[]),
                        dict(valid, segments=[None]), dict(valid, speed="invalid")):
            with self.subTest(payload=payload):
                (folder / "task.json").write_text(json.dumps(payload), encoding="utf-8")
                self.assertEqual([task["id"] for task in self.store.list()], [self.task["id"]])

    def test_edit_regenerates_only_changed_segment_and_keeps_old_output(self):
        previous = self.run_task()
        self.calls.clear()
        self.store.edit(self.task, 1, "新的台词")
        result = self.run_task(only=1)
        self.assertEqual(self.calls, ["新的台词"])
        self.assertNotEqual(previous, result)
        self.assertTrue(previous.is_file())
        cues = read_cues(result)
        self.assertEqual(cues[-1][2], "新的台词")
        self.assertGreaterEqual(cues[-1][0], cues[0][1])

    def test_single_segment_does_not_generate_other_pending_segments(self):
        self.assertIsNone(self.run_task(only=1))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.task["status"], "draft")

    def test_force_regeneration_replaces_cached_segment(self):
        self.run_task()
        self.calls.clear()
        self.run_task(only=0)
        self.assertEqual(len(self.calls), 1)

    def test_unchanged_task_makes_no_synthesis_calls(self):
        self.run_task()
        self.calls.clear()
        self.run_task()
        self.assertEqual(self.calls, [])

    def test_cancellation_persists_finished_segments_and_removes_temp(self):
        cancel = threading.Event()
        async def stop(*args, **kwargs):
            result = await self.render(*args, **kwargs)
            if len(self.calls) == 2:
                cancel.set()
            return result
        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(render_task(self.store, self.task, render=stop, cancel=cancel))
        loaded = self.store.load(self.task["id"])
        self.assertEqual(loaded["status"], "stopped")
        self.assertEqual(loaded["segments"][0]["status"], "done")
        self.assertFalse(list(self.store.root.glob("*/render-*")))
        self.calls.clear()
        self.run_task(loaded)
        self.assertEqual(len(self.calls), 1)

    def test_corrupt_cached_audio_regenerates(self):
        self.run_task()
        folder = self.store.folder(self.task["id"])
        (folder / (self.task["segments"][0]["id"] + ".wav")).write_bytes(b"broken")
        self.calls.clear()
        self.run_task()
        self.assertEqual(len(self.calls), 1)

    def test_settings_change_invalidates_cache(self):
        self.run_task()
        self.calls.clear()
        self.task["speed"] = 1.5
        self.run_task()
        self.assertEqual(len(self.calls), 2)

    def test_lexicon_only_invalidates_affected_segments_and_preserves_captions(self):
        self.run_task()
        self.calls.clear()
        self.task["lexicon"] = {"乙": "一"}
        result = self.run_task()
        self.assertEqual(self.calls, ["一" * 20])
        self.assertEqual(read_cues(result)[-1][2], "乙" * 20)

    def test_explicit_pause_is_exact_and_not_spoken(self):
        self.store.set_script(self.task, "甲【停顿0.5秒】乙")
        result = self.run_task()
        self.assertEqual(self.calls, ["甲", "乙"])
        cues = read_cues(result)
        self.assertAlmostEqual(cues[1][0], .7, places=3)

    def test_identifiers_cannot_escape_task_directory(self):
        for key in ("../other", "C:\\other", "a/../b", ""):
            with self.assertRaises(ValueError):
                self.store.folder(key)

    def test_edited_whole_script_reuses_unchanged_parts(self):
        self.run_task()
        self.calls.clear()
        self.store.set_script(self.task, "甲" * 240 + "丙" * 20)
        self.run_task()
        self.assertEqual(self.calls, ["丙" * 20])

    def test_pruning_preserves_current_and_pending_export(self):
        previous = self.run_task()
        self.store.edit(self.task, 1, "新的台词")
        current = self.run_task()
        folder = self.store.folder(self.task["id"])
        orphan = folder / ("f" * 32 + ".wav")
        orphan.write_bytes(b"orphan")
        unrelated = folder / "notes.txt"
        unrelated.write_text("保留")
        self.store.prune(self.task, (previous,))
        self.assertTrue(previous.is_file())
        self.assertTrue(current.is_file())
        self.assertFalse(orphan.exists())
        self.assertTrue(unrelated.is_file())
        self.store.prune(self.task)
        self.assertFalse(previous.exists())
        self.assertTrue(current.is_file())


class SpeechTests(unittest.TestCase):
    def test_short_script_still_has_individually_editable_sentences(self):
        text = "欢迎使用。这是第二段。\n这是第三段。"
        chunks = sentence_segments(text)
        self.assertEqual(len(chunks), 3)
        self.assertEqual("".join(chunks), text)

    def test_cancel_waits_for_native_cleanup_before_returning(self):
        import offline
        ready, finished = threading.Event(), threading.Event()
        def native(*args, cancel=None, **kwargs):
            ready.set()
            cancel.wait(3)
            finished.set()
        async def run():
            with patch.object(offline, "generate_local", side_effect=native):
                pending = asyncio.create_task(offline.synthesize_local("甲", "local:clone:test", 1, 100, "unused.wav"))
                await asyncio.to_thread(ready.wait, 3)
                pending.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await pending
                self.assertTrue(finished.is_set())
        asyncio.run(run())

    def test_chunking_preserves_words_text_and_limit(self):
        for text in ("Hello wonderful world. " * 10, "中文测试，" * 30,
                     "版本 v3.5.1 和 example.com 都应保留。" * 6):
            chunks = split_text(text)
            self.assertEqual("".join(chunks), text)
            self.assertTrue(all(len(c) <= 60 for c in chunks))
            for left, right in zip(chunks, chunks[1:]):
                self.assertFalse(left[-1:].isascii() and left[-1:].isalnum()
                                 and right[:1].isascii() and right[:1].isalnum())

    def test_dictionary_longest_first_no_recursive_replacement_and_boundaries(self):
        self.assertEqual(apply("重庆银行 cat category", {"重庆": "崇庆", "重庆银行": "崇庆银航", "崇庆": "错误", "cat": "凯特"}),
                         "崇庆银航 凯特 category")
        self.assertEqual(apply("甲【停顿0.5秒】", {"0": "零", "甲": "假"}), "假【停顿0.5秒】")
        with self.assertRaises(ValueError):
            validate({"a": "【停顿1秒】"})

    def test_join_preserves_quiet_tail_and_does_not_stack_pause(self):
        speech = np.concatenate((np.full(2400, .1), np.full(2400, .002)))
        result = prepare_join(speech, 24000)
        self.assertEqual(len(result), len(speech))
        padded = np.concatenate((speech, np.zeros(12000)))
        result = prepare_join(padded, 24000)
        self.assertGreaterEqual(len(result), len(speech) + 1900)
        self.assertLess(len(result), len(padded))
        self.assertEqual(missing_pause(padded, 24000, "结束。"), 0)

    def test_decoded_reference_cache_uses_content_and_is_bounded(self):
        import qwen_backend as qwen
        with tempfile.TemporaryDirectory() as temp, patch("offline._decode_audio", return_value=(np.zeros(2400), 24000)) as decode:
            path = Path(temp) / "reference.wav"
            path.write_bytes(b"first")
            qwen._REFERENCE_CACHE.clear()
            qwen.reference_audio(path)
            qwen.reference_audio(path)
            self.assertEqual(decode.call_count, 1)
            path.write_bytes(b"other")
            qwen.reference_audio(path)
            self.assertEqual(decode.call_count, 2)
            for index in range(12):
                path.write_bytes(str(index).encode())
                qwen.reference_audio(path)
            self.assertLessEqual(len(qwen._REFERENCE_CACHE), 8)
            qwen._REFERENCE_CACHE.clear()


if __name__ == "__main__":
    unittest.main()
