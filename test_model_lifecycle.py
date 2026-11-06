"""Model integrity and clone save behavior without loading model weights."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app import App
import offline


class ModelLifecycleTests(unittest.TestCase):
    def test_clone_download_entry_opens_picker_without_starting_download(self):
        for model in ("zipvoice", "qwen3_q8"):
            with self.subTest(model=model):
                window = SimpleNamespace(busy=False, clone_model=model, show_page=Mock(), model_action=Mock())
                App.install_empty_provider(window)
                window.show_page.assert_called_once_with("models")
                window.model_action.assert_not_called()

    def test_empty_download_entry_shows_progress_without_cancelling(self):
        window = SimpleNamespace(
            empty_install_btn=Mock(), provider="zipvoice", download_key="qwen3_q8",
            clone_model="zipvoice", download_state={}, installing=True, busy=False)
        App.update_empty_install(window)
        window.empty_install_btn.configure.assert_called_once_with(text="查看下载进度", state="normal")

    def test_missing_required_files_mark_zipvoice_uninstalled(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            required = ("tokens.txt", "encoder.int8.onnx", "decoder.int8.onnx", offline.VOCODER)
            with patch.object(offline, "registrations", return_value={"zipvoice": temp}):
                self.assertFalse(offline.installed())
                for name in required:
                    (folder / name).write_bytes(b"model-placeholder")
                self.assertTrue(offline.installed())
                for name in required:
                    path = folder / name
                    path.unlink()
                    self.assertFalse(offline.installed(), name)
                    path.write_bytes(b"model-placeholder")

    def test_damaged_install_requires_explicit_removal_without_deleting_files(self):
        with tempfile.TemporaryDirectory() as temp:
            models = Path(temp)
            damaged = models / offline.CATALOG["zipvoice"][1]
            damaged.mkdir()
            survivor = damaged / "keep.txt"
            survivor.write_text("keep", encoding="utf-8")
            with patch.object(offline, "MODELS", models), patch.object(offline, "_download_zipvoice") as download:
                with self.assertRaisesRegex(ValueError, "模型文件不完整"):
                    offline.install("zipvoice")
            self.assertTrue(survivor.exists())
            download.assert_not_called()

    def test_save_clone_selects_voice_without_preview(self):
        dialog = Mock()
        dialog.winfo_exists.return_value = True
        window = SimpleNamespace(
            clone_dialog=dialog, clone_pick=Mock(), clone_save=Mock(),
            clone_name=Mock(), clone_gender=Mock(), clone_text=Mock(),
            provider="zipvoice", clone_model="qwen3_q8", reload_voice_catalog=Mock(),
            filter_voices=Mock(), select_voice=Mock(), preview_voice=Mock(), status=Mock())
        App.finish_clone_event(window, "clone_save", (dialog, "qa", None))
        dialog.destroy.assert_called_once()
        window.select_voice.assert_called_once_with("local:qwen3_q8:clone:qa")
        window.preview_voice.assert_not_called()
        window.clone_save.configure.assert_called_with(state="normal", text="保存")


if __name__ == "__main__":
    unittest.main()
