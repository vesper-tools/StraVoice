"""Audio encoding, bounded reference reads, and preview eviction regressions."""
import asyncio
from contextlib import ExitStack
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import wave

import lameenc
import miniaudio
import numpy as np
import offline
import qwen_backend
from app import trim_clone_previews
from engine import synthesize
from pauses import read_cues


class AudioOptimizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="voice-audio-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_md5_defaults_to_chinese_five_in_chinese_text(self):
        for text, expected in [
            ("这是MD5的一个文字说明", "这是MD五的一个文字说明"),
            ("比较 md5 和 MP3、MP4、M4A", "比较 md五 和 MP三、MP四、M四A"),
            ("Check the MD5 hash.", "Check the MD5 hash."),
            ("这是 XMD5、MD50、MD5_test", "这是 XMD五、MD五零、MD5_test"),
        ]:
            with self.subTest(text=text):
                self.assertEqual(offline._normalize_chinese_numbers(text), expected)

    def test_mixed_identifiers_read_digits_individually_in_chinese(self):
        for text, expected in [
            ("这是MD56", "这是MD五六"),
            ("比较AB123、B2B、H265和56MD。", "比较AB一二三、B二B、H二六五和五六MD。"),
            ("编号MD56，共56个，2026年使用。", "编号MD五六，共五十六个，二零二六年使用。"),
            ("Check MD56, AB123 and B2B.", "Check MD56, AB123 and B2B."),
            ("版本V2.1.0，文件MD56.txt，编号MD56。", "版本V2.1.0，文件MD56.txt，编号MD五六。"),
            ("编号MD56.", "编号MD五六."),
        ]:
            with self.subTest(text=text):
                self.assertEqual(offline._normalize_chinese_numbers(text), expected)

    def test_md5_default_reading_reaches_zipvoice_and_preserves_captions(self):
        text = "2026年，这是MD5和MD56的一个文字说明，测试一下看看。"
        target = self.root / "result.wav"
        pcm = np.full(2400, 1000, dtype="<i2")
        with patch.object(offline, "load_engine", return_value=SimpleNamespace(sample_rate=24000, max_workers=1)), \
                patch.object(offline, "reference_for", return_value=("参考", pcm, 24000)), \
                patch.object(offline, "_render_chunk", return_value=pcm) as render, \
                patch.object(offline, "_steady_tempo", side_effect=lambda chunks, audio, *args: iter(audio)):
            offline.generate_local(text, "local:clone:test", 1, 100, target)
        self.assertIn("MD五", render.call_args.args[1])
        self.assertIn("MD五六", render.call_args.args[1])
        self.assertIn("二零二六年", render.call_args.args[1])
        self.assertEqual("".join(cue[2] for cue in read_cues(target)), text)

    def test_years_are_read_digit_by_digit_but_quantities_are_not(self):
        for text, expected in [
            ("现在是2026年。", "现在是二零二六年。"),
            ("2000年到2026 年，共26年。", "二零零零年到二零二六 年，共二十六年。"),
            ("2026年收入2026元。", "二零二六年收入二千零二十六元。"),
            ("今年有365天，增长5%。", "今年有三百六十五天，增长百分之五。"),
        ]:
            with self.subTest(text=text):
                self.assertEqual(offline._normalize_chinese_numbers(text), expected)

    def test_local_pauses_encode_mp3_once_and_shift_subtitles(self):
        target = self.root / "result.mp3"
        pcm = np.full(2400, 1000, dtype="<i2")
        with patch.object(offline, "load_engine", return_value=SimpleNamespace(sample_rate=24000, max_workers=1)), \
                patch.object(offline, "reference_for", return_value=("参考", pcm, 24000)), \
                patch.object(offline, "_render_chunk", return_value=pcm), \
                patch.object(offline, "_steady_tempo", side_effect=lambda chunks, audio, *args: iter(audio)), \
                patch("lameenc.Encoder", wraps=lameenc.Encoder) as encoder:
            asyncio.run(synthesize("甲【停顿0.5秒】乙", "local:clone:test", 1, 100, target))
        self.assertEqual(encoder.call_count, 1)
        cues = read_cues(target)
        self.assertEqual([cue[2] for cue in cues], ["甲", "乙"])
        self.assertAlmostEqual(cues[1][0], .78, places=2)  # .1 speech + .18 tail + .5 pause
        decoded = miniaudio.decode(target.read_bytes(), nchannels=1, sample_rate=24000)
        self.assertGreater(len(decoded.samples) / 24000, 1.0)
        self.assertFalse(target.with_suffix(".part").exists())

    def test_qwen_wav_intermediate_does_not_create_mp3_encoder(self):
        def run(command, folder, *args):
            with wave.open(str(folder / command[command.index("-o") + 1]), "wb") as output:
                output.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                output.writeframes(bytes(4800))
            return 0, "generated 20 frames"
        with ExitStack() as stack:
            for owner, name, result in [
                (qwen_backend, "package_installed", True), (qwen_backend, "package_dir", self.root),
                (qwen_backend, "_device", "none"),
                (offline, "clones", [{"id": "test", "wav": "unused"}]),
                (offline, "_decode_audio", (np.zeros(2400), 24000)),
            ]:
                stack.enter_context(patch.object(owner, name, return_value=result))
            stack.enter_context(patch.object(qwen_backend, "_run", side_effect=run))
            encoder = stack.enter_context(patch("lameenc.Encoder", side_effect=AssertionError("unexpected MP3 encoding")))
            target = self.root / "片段.wav"
            qwen_backend.generate("测试", "local:qwen3_q8:clone:test", 1, 100, target)
        encoder.assert_not_called()
        with wave.open(str(target), "rb") as source:
            self.assertEqual(source.getnframes(), 2400)

    def test_unicode_reference_streams_in_bounded_reads_and_rejects_long_audio(self):
        encoder = lameenc.Encoder()
        encoder.set_in_sample_rate(24000)
        encoder.set_channels(1)
        encoder.silence()
        path = self.root / "中文录音.mp3"
        path.write_bytes(encoder.encode(bytes(24000 * 2 * 22)) + encoder.flush())
        with patch.object(Path, "read_bytes", side_effect=AssertionError("whole file read")):
            with self.assertRaises(offline.ReferenceTooLong):
                offline._decode_audio(path, max_seconds=20)
            samples, rate = offline._decode_audio(path, max_seconds=25)
        self.assertEqual(rate, 24000)
        self.assertGreater(len(samples), 20 * rate)
        with path.open("ab") as source:
            source.truncate(33 * 1024 * 1024)
        with patch.object(offline, "_decode_audio") as decode:
            with self.assertRaisesRegex(ValueError, "文件过大"):
                offline.read_audio(path, max_seconds=20)
        decode.assert_not_called()

    def preview(self, number, size=10):
        path = self.root / "preview-cache" / ("a" * 64) / f"{number:064x}.mp3"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bytes(size))
        path.with_suffix(".srt").write_text("字幕", encoding="utf-8")
        os.utime(path, (number, number))
        return path

    def test_preview_eviction_preserves_current_export_and_unrelated_files(self):
        current, exporting, old, recent = [self.preview(i) for i in range(1, 5)]
        unrelated = current.parent / "recording.mp3"
        unrelated.write_bytes(b"keep")
        trim_clone_previews(self.root, [current, exporting], max_entries=3)
        self.assertFalse(old.exists())
        self.assertFalse(old.with_suffix(".srt").exists())
        self.assertTrue(all(path.exists() for path in [current, exporting, recent, unrelated]))
        trim_clone_previews(self.root, [current, exporting], max_bytes=1)
        self.assertFalse(recent.exists())
        self.assertTrue(current.exists() and exporting.exists() and unrelated.exists())


if __name__ == "__main__":
    unittest.main()
