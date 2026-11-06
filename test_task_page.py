"""Embedded task navigation preserves edits and keeps stop within reach."""
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch
import wave

import customtkinter as ctk
import app as ui


class TaskPageTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.temp = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.stack.enter_context(patch.object(ui, "DATA", Path(self.temp)))
        for owner, method in ((ui.App, "refresh_voices"), (ui.App, "warm_up")):
            self.stack.enter_context(patch.object(owner, method))
        self.window = ui.App()
        self.window.withdraw()
        self.addCleanup(self.window.close)

    def task(self):
        task = self.window.task_store.create("第一句。第二句。", "online-test", "测试", 1, 100)
        self.window.current_task_id = task["id"]
        return task

    def completed_task(self):
        task = self.task()
        task["status"] = "complete"
        for segment in task["segments"]:
            segment["status"] = "done"
        self.window.task_store.save(task)
        self.window.task_store.output(task).write_bytes(b"combined audio")
        self.window.open_tasks()
        return task

    def test_task_list_excludes_legacy_history(self):
        legacy = ui.TaskStore(Path(self.temp) / "tasks")
        task = legacy.create("历史任务。", "online-test", "旧任务", 1, 100)
        self.window.open_tasks()
        self.assertFalse(self.window.task_page.options)
        self.assertEqual(self.window.task_store.list(), [])
        self.assertTrue((legacy.folder(task["id"]) / "task.json").is_file())

    def test_completed_task_disables_continue_until_text_changes(self):
        self.completed_task()
        page = self.window.task_page
        button = page.buttons[-1]
        self.assertEqual(button.cget("text"), "已全部生成")
        self.assertEqual(button.cget("state"), "disabled")

        original = page.editor.get("1.0", "end-1c")
        page.editor.insert("end", "修改内容")
        self.window.update()
        self.assertEqual(button.cget("text"), "继续生成任务")
        self.assertEqual(button.cget("state"), "normal")
        page.editor.delete("1.0", "end")
        page.editor.insert("1.0", original)
        self.window.update()
        self.assertEqual(button.cget("text"), "已全部生成")
        self.assertEqual(button.cget("state"), "disabled")

    def test_delayed_startup_refresh_preserves_unsaved_edit(self):
        task = self.completed_task()
        page = self.window.task_page
        page.editor.insert("end", "尚未保存的编辑")
        page.initial_refresh()
        self.assertEqual(self.window.task_store.load(task["id"])["status"], "complete")
        self.assertTrue(page.editor.get("1.0", "end-1c").endswith("尚未保存的编辑"))

    def test_missing_complete_audio_reenables_continue(self):
        task = self.completed_task()
        self.window.task_store.output(task).unlink()
        self.window.task_page.refresh()
        self.assertEqual(self.window.task_page.buttons[-1].cget("text"), "继续生成任务")
        self.assertEqual(self.window.task_page.buttons[-1].cget("state"), "normal")

    def test_dictionary_change_reenables_completed_task(self):
        self.completed_task()
        from pronunciation import save
        save(Path(self.temp) / "pronunciation.json", {"第一句": "新读法"})
        self.window.task_page.apply_dictionary()
        button = self.window.task_page.buttons[-1]
        self.assertEqual(button.cget("text"), "继续生成任务")
        self.assertEqual(button.cget("state"), "normal")

    def test_same_size_configure_reuses_background_image(self):
        self.window.deiconify()
        self.window.update_idletasks()
        image = self.window.ambient_image
        width, height = self.window.ambient_size
        self.window.workbench._canvas.event_generate("<Configure>", width=width, height=height)
        self.assertIs(self.window.ambient_image, image)

    def test_size_change_rebuilds_background_image(self):
        self.window.deiconify()
        self.window.update_idletasks()
        image = self.window.ambient_image
        width, height = self.window.ambient_size
        self.window.workbench._canvas.event_generate("<Configure>", width=width + 1, height=height)
        self.assertIsNot(self.window.ambient_image, image)
        self.assertEqual(self.window.ambient_size, (width + 1, height))

    def test_task_entry_opens_frame_in_main_window(self):
        self.task()
        self.window.open_tasks()
        self.assertEqual(self.window.current_page, "tasks")
        self.assertIs(self.window.task_page.master, self.window)
        self.assertIsInstance(self.window.task_page, ctk.CTkFrame)
        self.assertFalse(any(isinstance(child, ctk.CTkToplevel) for child in self.window.winfo_children()))
        self.assertTrue(self.window.task_page.grid_info())
        self.assertTrue(self.window.dock.grid_info())
        self.assertFalse(self.window.workbench.grid_info())

    def test_leaving_and_reopening_keeps_segment_edits(self):
        task = self.task()
        self.window.open_tasks()
        page = self.window.task_page
        page.editor.delete("1.0", "end")
        page.editor.insert("1.0", "修改后的第一句。")
        self.window.show_page("workbench")
        self.window.open_tasks()
        self.assertEqual(page.editor.get("1.0", "end-1c"), "修改后的第一句。")
        self.assertEqual(self.window.task_store.load(task["id"])["segments"][0]["text"], "修改后的第一句。")

    def test_stop_stays_available_on_embedded_page(self):
        self.task()
        self.window.open_tasks()
        page = self.window.task_page
        self.window.busy = True
        page.set_busy()
        self.window.stop_generation = Mock()
        self.assertEqual(page.buttons[-1].cget("text"), "停止生成")
        self.assertEqual(page.buttons[-1].cget("state"), "normal")
        page.buttons[-1].invoke()
        self.window.stop_generation.assert_called_once()
        self.assertEqual(page.buttons[-1].cget("state"), "disabled")
        self.assertEqual(page.buttons[-1].kind, "stop")
        self.window.busy = False
        page.finished()
        self.assertEqual(page.buttons[-1].cget("text"), "继续生成任务")
        self.assertEqual(page.buttons[-1].kind, "primary")

    def test_action_click_runs_on_release_and_cancels_outside(self):
        self.task()
        self.window.open_tasks()
        button = self.window.task_page.buttons[0]
        command = Mock()
        button.configure(command=command)
        self.window.update_idletasks()
        inside = SimpleNamespace(x_root=button.winfo_rootx() + 1, y_root=button.winfo_rooty() + 1)
        outside = SimpleNamespace(x_root=button.winfo_rootx() - 1, y_root=button.winfo_rooty() - 1)
        button._press()
        command.assert_not_called()
        button._on_release(outside)
        command.assert_not_called()
        button._press()
        button._on_release(inside)
        command.assert_called_once()
        button._on_release(inside)
        command.assert_called_once()

    def test_action_keyboard_and_disabled_state(self):
        self.task()
        self.window.open_tasks()
        button = self.window.task_page.buttons[1]
        command = Mock()
        button.configure(command=command)
        button._press()
        button._key_release()
        command.assert_called_once()
        button._press()
        button.configure(state="disabled")
        button._key_release()
        button.invoke()
        command.assert_called_once()

    def test_regeneration_saves_edit_and_stops_when_save_fails(self):
        self.task()
        self.window.open_tasks()
        page = self.window.task_page
        self.window.run_saved_task = Mock(return_value=False)
        with patch.object(page, "save_edit", return_value=False):
            page.buttons[0].invoke()
        self.window.run_saved_task.assert_not_called()
        page.editor.delete("1.0", "end")
        page.editor.insert("1.0", "已修改的文稿。")
        page.buttons[0].invoke()
        self.window.run_saved_task.assert_called_once_with(page.task, 0)
        self.assertEqual(self.window.task_store.load(page.task["id"])["segments"][0]["text"], "已修改的文稿。")

    def test_task_picker_switches_task_and_saves_current_edit(self):
        first = self.task()
        second = self.window.task_store.create("另一个任务。", "online-test", "测试二", 1, 100)
        self.window.open_tasks()
        page = self.window.task_page
        page.editor.delete("1.0", "end")
        page.editor.insert("1.0", "切换前修改。")
        self.window.open_task_picker()
        popup = self.window.task_picker
        self.assertIsInstance(popup, ui.LanguagePicker)
        label = next(label for label, ident in page.options.items() if ident == second["id"])
        popup.on_pick(label)
        self.assertFalse(popup.winfo_exists())
        self.assertEqual(page.task["id"], second["id"])
        self.assertEqual(page.picker_value.get(), label)
        self.assertEqual(self.window.task_store.load(first["id"])["segments"][0]["text"], "切换前修改。")

    def test_task_picker_is_disabled_without_tasks(self):
        self.window.open_tasks()
        self.assertEqual(self.window.task_page.picker.cget("state"), "disabled")
        self.window.open_task_picker()
        self.assertIsNone(getattr(self.window, "task_picker", None))

    def test_new_workbench_generation_binds_task_page_before_busy(self):
        old_task = self.task()
        self.window.open_tasks()
        self.window.show_page("workbench")
        self.window.text.insert("1.0", "新任务的文稿。")
        self.window.worker = Mock()
        self.window.generate()
        self.assertTrue(self.window.busy)
        self.assertNotEqual(self.window.current_task_id, old_task["id"])
        self.assertEqual(self.window.task_page.task["id"], self.window.current_task_id)
        self.assertEqual(self.window.task_page.editor.get("1.0", "end-1c"), "新任务的文稿。")
        self.window.open_tasks()
        self.assertEqual(self.window.task_page.task["id"], self.window.current_task_id)

    def test_saved_task_generation_uses_its_own_dictionary(self):
        task = self.task()
        (Path(self.temp) / "pronunciation.json").write_text("broken json", encoding="utf-8")
        self.window.show_error = Mock()
        self.window.worker = Mock()
        self.window.generate(saved_task=task)
        self.assertTrue(self.window.busy)
        self.window.show_error.assert_not_called()
        self.window.busy = False

    def test_regeneration_autoplays_only_the_selected_segment(self):
        for merged in (False, True):
            with self.subTest(merged=merged):
                task = self.task()
                page = self.window.task_page
                page.refresh(preferred_id=task["id"])
                page.pick(1)
                self.window.worker = Mock()
                self.window.play_audio = Mock()
                self.window.generate(saved_task=page.task, only=1)
                task = page.task
                for index, segment in enumerate(task["segments"]):
                    if merged or index == 1:
                        segment.update(status="done", cues=[(0, .1, segment["text"])])
                        path = self.window.task_store.folder(task["id"]) / (segment["id"] + ".wav")
                        with wave.open(str(path), "wb") as output:
                            output.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                            output.writeframes(bytes(4800))
                task["status"] = "complete" if merged else "draft"
                self.window.task_store.save(task)
                full = self.window.task_store.output(task)
                if merged:
                    full.write_bytes(b"combined audio")
                self.window.events.put(("audio", (full if merged else None, task["name"], False), None))
                self.window.poll()
                self.assertIsNotNone(self.window.latest)
                self.assertNotEqual(self.window.latest, full)
                self.assertEqual(self.window.latest_name, "测试 · 第 2 段")
                self.window.play_audio.assert_called_once()

    def test_full_task_generation_still_autoplays_combined_audio(self):
        task = self.task()
        self.window.worker = Mock()
        self.window.play_audio = Mock()
        self.window.generate(saved_task=task)
        full = self.window.task_store.output(task)
        full.write_bytes(b"combined audio")
        self.window.events.put(("audio", (full, task["name"], False), None))
        self.window.poll()
        self.assertEqual(self.window.latest, full)
        self.window.play_audio.assert_called_once()


class TaskSessionTests(unittest.TestCase):
    def test_restart_clears_tasks_and_preserves_dictionary_and_exports(self):
        from pronunciation import save
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            data = Path(directory)
            stack.enter_context(patch.object(ui, "DATA", data))
            for owner, method in ((ui.App, "refresh_voices"), (ui.App, "warm_up")):
                stack.enter_context(patch.object(owner, method))
            dictionary = data / "pronunciation.json"
            save(dictionary, {"星": "月"})
            exported = data / "export.mp3"
            exported.write_bytes(b"exported audio")
            window = ui.App()
            try:
                session = Path(window.temp.name)
                task = window.task_store.create("本次启动的任务。", "online-test", "测试", 1, 100)
                self.assertTrue((window.task_store.folder(task["id"]) / "task.json").is_file())
            finally:
                window.close()
            self.assertFalse(session.exists())
            self.assertTrue(exported.is_file())
            restarted = ui.App()
            try:
                self.assertEqual(restarted.task_store.list(), [])
                restarted.open_dictionary()
                self.assertEqual(restarted.dictionary_window.path, dictionary)
                self.assertIn("星 = 月", restarted.dictionary_window.editor.get("1.0", "end-1c"))
            finally:
                restarted.close()


if __name__ == "__main__":
    unittest.main()
