"""Reference imports must work without FFmpeg installed on the user's PATH."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import wave

import numpy as np
import offline


class FFmpegImportTests(unittest.TestCase):
    def test_m4a_and_wma_import_without_system_ffmpeg(self):
        ffmpeg = Path(__file__).resolve().parent / "bin/ffmpeg.exe"
        if not ffmpeg.is_file():
            self.skipTest("Bundled FFmpeg is required for the integration test")
        with tempfile.TemporaryDirectory(prefix="voice-format-test-") as temp:
            root = Path(temp)
            wav = root / "参考录音.wav"
            samples = (np.sin(np.arange(48000) * 2 * np.pi * 440 / 24000) * 10000).astype("<i2")
            with wave.open(str(wav), "wb") as output:
                output.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                output.writeframes(samples.tobytes())
            with patch.dict(os.environ, {"PATH": ""}):
                for suffix, codec in [("m4a", "aac"), ("wma", "wmav2")]:
                    with self.subTest(format=suffix):
                        source = root / ("参考录音." + suffix)
                        subprocess.run([str(ffmpeg), "-v", "error", "-i", str(wav),
                                        "-c:a", codec, str(source)], check=True,
                                       capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                        decoded, rate = offline.read_audio(source, max_seconds=3)
                        self.assertEqual(rate, 24000)
                        self.assertGreater(len(decoded) / rate, 1.5)

    def test_frozen_app_prefers_its_own_ffmpeg(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundled = root / "bin/ffmpeg.exe"
            bundled.parent.mkdir()
            bundled.touch()
            def convert(command, **kwargs):
                self.assertEqual(command[0], str(bundled))
                with wave.open(command[-1], "wb") as output:
                    output.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                    output.writeframes(bytes(4800))
                return subprocess.CompletedProcess(command, 0)
            with patch.object(offline.sys, "frozen", True, create=True), \
                    patch.object(offline.sys, "executable", str(root / "星悦配音.exe")), \
                    patch.object(offline.shutil, "which", side_effect=AssertionError("must prefer bundled tool")), \
                    patch("subprocess.run", side_effect=convert):
                samples, rate = offline._decode_with_ffmpeg(root / "input.m4a")
                self.assertEqual((len(samples), rate), (2400, 24000))

    def test_missing_bundle_uses_path_or_requests_repair(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(offline, "__file__", str(Path(temp) / "offline.py")), \
                    patch.object(offline.sys, "frozen", False, create=True), \
                    patch.object(offline.shutil, "which", return_value=None) as search:
                with self.assertRaisesRegex(ValueError, "修复安装"):
                    offline._decode_with_ffmpeg(Path(temp) / "input.m4a")
                search.assert_called_once_with("ffmpeg")


if __name__ == "__main__":
    unittest.main()
