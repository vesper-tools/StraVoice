"""Task and pronunciation editors using the existing desktop controls."""
import customtkinter as ctk
from PIL import Image, ImageDraw

from pronunciation import load, save

BLUE = "#4F5BEF"
MUTED = "#5F6880"
STATUS = dict(draft="待生成", running="生成中／上次中断", stopped="已停止", failed="失败，可继续", complete="已完成")


def dictionary_icon(color):
    image = Image.new("RGBA", (64, 64))
    draw = ImageDraw.Draw(image)
    draw.line([(32, 16), (22, 11), (9, 11), (9, 49), (22, 49), (32, 54),
               (42, 49), (55, 49), (55, 11), (42, 11), (32, 16), (32, 54)], fill=color, width=4)
    for y in (24, 34):
        draw.line([(16, y), (24, y + 2)], fill=color, width=3)
        draw.line([(40, y + 2), (48, y)], fill=color, width=3)
    return ctk.CTkImage(image, size=(16, 16))


class TaskActionButton(ctk.CTkButton):
    COLORS = {
        "plain": ("#FFFFFF", "#F0F2FA", "#E2E6F4", "#D5DAE7", "#35405A"),
        "accent": ("#ECEEFF", "#E0E4FF", "#CCD3FC", "#CCD2FA", "#3D48B8"),
        "primary": (BLUE, "#414CDD", "#333EC4", BLUE, "#FFFFFF"),
        "stop": ("#FFF1F0", "#FFE1DE", "#FFCCC7", "#EAB5B0", "#AC3028"),
    }

    def __init__(self, master, text, command, kind, icon, width):
        self.kind, self.icon = kind, icon
        self._pressed = self._focused = False
        super().__init__(master, text=text, command=command, width=width, height=40,
                         corner_radius=8, border_width=1, border_spacing=8,
                         font=ctk.CTkFont(family="Microsoft YaHei UI", size=13, weight="bold"),
                         hover=False, compound="left")
        self._canvas.configure(takefocus=1)
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<FocusIn>", lambda event: self._focus(True))
        self.bind("<FocusOut>", lambda event: self._focus(False))
        for key in ("space", "Return"):
            self.bind(f"<KeyPress-{key}>", self._press)
            self.bind(f"<KeyRelease-{key}>", self._key_release)
        self._paint_state()

    def _icon_image(self, color):
        image = Image.new("RGBA", (64, 64))
        draw = ImageDraw.Draw(image)
        if self.icon == "regenerate":
            draw.arc((11, 11, 53, 53), 40, 320, fill=color, width=5)
            draw.line([(40, 12), (53, 14), (50, 27)], fill=color, width=5)
        elif self.icon == "dictionary":
            return dictionary_icon(color)
        elif self.icon == "play":
            draw.polygon([(21, 12), (51, 32), (21, 52)], fill=color)
        elif self.icon == "stop":
            draw.rounded_rectangle((15, 15, 49, 49), radius=4, fill=color)
        elif self.icon == "done":
            draw.line([(13, 32), (27, 46), (52, 18)], fill=color, width=5)
        else:
            draw.line([(12, 32), (51, 32), (34, 15)], fill=color, width=5)
            draw.line([(51, 32), (34, 49)], fill=color, width=5)
        return ctk.CTkImage(image, size=(16, 16))

    def _paint_state(self):
        base, hover, pressed, border, text = self.COLORS[self.kind]
        disabled = self.cget("state") == "disabled"
        background = "#E9ECF4" if disabled else pressed if self._pressed else hover if self._mouse_inside else base
        super().configure(fg_color=background, hover_color=hover, text_color=text,
                          text_color_disabled="#8B94A8", border_color="#DDE2ED" if disabled else BLUE if self._focused else border,
                          border_width=2 if self._focused and not disabled else 1,
                          image=self._icon_image("#8B94A8" if disabled else text))

    def configure(self, require_redraw=False, **kwargs):
        super().configure(require_redraw=require_redraw, **kwargs)
        if "state" in kwargs:
            self._pressed = False
            self._canvas.configure(takefocus=kwargs["state"] != "disabled")
            self._paint_state()

    def set_kind(self, kind, icon):
        self.kind, self.icon = kind, icon
        self._paint_state()

    def _on_enter(self, event=None):
        self._mouse_inside = True
        self._paint_state()

    def _on_leave(self, event=None):
        self._mouse_inside = False
        self._paint_state()

    def _focus(self, focused):
        self._focused = focused
        if not focused:
            self._pressed = False
        self._paint_state()

    def _press(self, event=None):
        if self.cget("state") == "normal":
            self._canvas.focus_set()
            self._pressed = True
            self._paint_state()
        return "break"

    def _on_release(self, event=None):
        inside = (self.winfo_rootx() <= event.x_root < self.winfo_rootx() + self.winfo_width()
                  and self.winfo_rooty() <= event.y_root < self.winfo_rooty() + self.winfo_height())
        activate = self._pressed and inside
        self._pressed = False
        self._paint_state()
        if activate:
            self.invoke()

    def _key_release(self, event=None):
        activate = self._pressed
        self._pressed = False
        self._paint_state()
        if activate:
            self.invoke()
        return "break"


def show_editor(window, app, center=False):
    """Keep modeless editors owned by the app, including restored windows."""
    window.transient(app)
    if center:
        window.update_idletasks()
        left, top, right, bottom = app.screen_work_area()
        x = app.winfo_rootx() + (app.winfo_width() - window.winfo_width()) // 2
        y = app.winfo_rooty() + (app.winfo_height() - window.winfo_height()) // 2
        x = max(left, min(x, right - window.winfo_width()))
        y = max(top, min(y, bottom - window.winfo_height()))
        window.geometry(f"{x:+d}{y:+d}")
    if window.state() in ("withdrawn", "iconic"):
        window.deiconify()
    window.lift()
    window.focus_force()


class TaskPage(ctk.CTkFrame):
    def __init__(self, app):
        super().__init__(app, fg_color="#F3F4FE", corner_radius=0)
        self.app, self.task, self.index = app, None, None
        self.options = {}
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        top = ctk.CTkFrame(self, fg_color="white", corner_radius=0)
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(0, weight=1)
        app.label(top, "本次启动的配音任务", 17, bold=True).grid(row=0, column=0, sticky="w", padx=20, pady=(16, 8))
        actions = ctk.CTkFrame(top, fg_color="transparent")
        actions.grid(row=0, column=1, sticky="e", padx=(12, 20), pady=(16, 8))
        refresh = TaskActionButton(actions, "刷新", self.refresh, "plain", "regenerate", 84)
        dictionary = TaskActionButton(actions, "应用当前词典", self.apply_dictionary, "accent", "dictionary", 144)
        for button in (refresh, dictionary):
            button.configure(height=32, border_spacing=6)
            button.cget("font").configure(size=12)
        refresh.pack(side="left", padx=(0, 8))
        dictionary.pack(side="left")
        self.picker_value = ctk.StringVar(value="暂无任务")
        self.picker = app.button(top, "暂无任务", app.open_task_picker, height=36, size=13,
                                 textvariable=self.picker_value, anchor="w")
        self.picker.configure(fg_color="white", hover_color="#F3F4FE", border_width=1,
                              border_color="#CBD2DF", text_color="#151B2E", corner_radius=8)
        self.picker.cget("font").configure(weight="normal")
        self.picker.grid(row=1, column=0, columnspan=2, sticky="ew", padx=20, pady=(0, 16))
        arrow = ctk.CTkLabel(self.picker, text="", width=16, height=16,
                             image=app.locale_arrow.cget("image"))
        arrow.place(relx=1, rely=0.5, x=-12, anchor="e")
        arrow.bind("<Button-1>", lambda event: self.picker.invoke())
        self.info = app.label(self, "任务仅本次启动可用，关闭前请下载需要的音频。", 12, MUTED, anchor="w")
        self.info.grid(row=1, column=0, sticky="ew", padx=20, pady=10)
        body = ctk.CTkFrame(self, fg_color="white", corner_radius=14)
        body.grid(row=2, column=0, sticky="nsew", padx=20)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(1, weight=1)
        app.label(body, "分段", 14, bold=True).grid(row=0, column=0, sticky="w", padx=16, pady=12)
        self.segment_title = app.label(body, "选择分段后修改", 14, bold=True, anchor="w")
        self.segment_title.grid(row=0, column=1, sticky="ew", padx=16, pady=12)
        self.rows = ctk.CTkScrollableFrame(body, width=210, fg_color="#FAFBFE", corner_radius=0)
        self.rows.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=(0, 12))
        self.editor = ctk.CTkTextbox(body, wrap="word", font=("Microsoft YaHei UI", 15),
                                   fg_color="#FAFBFE", border_width=1, border_color="#CBD2DF")
        self.editor.grid(row=1, column=1, sticky="nsew", padx=(8, 16), pady=(0, 12))
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=3, column=0, sticky="ew", padx=20, pady=16)
        bottom.grid_columnconfigure(3, weight=1)
        self.buttons = []
        for column, (title, command, kind, icon, width) in enumerate((
                ("重生成此段", self.regenerate, "accent", "regenerate", 124),
                ("试听此段", self.listen_segment, "plain", "play", 112),
                ("试听完整音频", self.listen, "plain", "play", 140),
                ("继续生成任务", self.resume, "primary", "next", 144))):
            button = TaskActionButton(bottom, title, command, kind, icon, width)
            button.grid(row=0, column=4 if column == 3 else column, padx=(0, 16 if column == 0 else 8 if column < 3 else 0))
            self.buttons.append(button)
        self.editor.edit_modified(False)
        self.editor.bind("<<Modified>>", self.editor_changed)
        self.after(100, self.initial_refresh)

    def initial_refresh(self):
        if self.task is None:
            self.refresh()

    def refresh(self, preferred_id=None):
        if self.app.busy:
            return
        ident = preferred_id or (self.task["id"] if self.task else getattr(self.app, "current_task_id", None))
        tasks = self.app.task_store.list()
        self.options = {f"{t['updated'].replace('T', ' ')} · {t['name']} · {''.join(s['text'] for s in t['segments'])[:18]} · {t['id'][:6]}": t["id"] for t in tasks}
        self.picker.configure(state="normal" if self.options else "disabled")
        selected = next((label for label, key in self.options.items() if key == ident), next(iter(self.options), None))
        if selected:
            self.picker_value.set(selected)
            self.choose(selected)
        else:
            self.picker_value.set("暂无任务")
            self.editor.configure(state="disabled")
            for button in self.buttons:
                button.configure(state="disabled")

    def choose(self, label):
        if self.app.busy or not self.save_edit():
            return
        try:
            self.task = self.app.task_store.load(self.options[label])
        except (OSError, ValueError, KeyError) as error:
            self.app.show_error("任务无法打开", str(error), parent=self)
            return
        self.index = None
        self.draw_rows()
        self.pick(0)

    def draw_rows(self):
        for widget in self.rows.winfo_children():
            widget.destroy()
        for index, segment in enumerate(self.task["segments"]):
            mark = "已生成" if segment["status"] == "done" else "待生成"
            button = self.app.button(self.rows, f"第 {index + 1} 段 · {mark}\n{segment['text'][:16]}",
                                     lambda i=index: self.pick(i), width=190, height=56, size=12)
            button.configure(anchor="w", fg_color="white", border_width=0)
            button.cget("font").configure(weight="normal")
            button.pack(fill="x", pady=3)
        self.info.configure(text=f"{self.task['name']} · 语速 {self.task['speed']:g}× · {STATUS[self.task['status']]} · 共 {len(self.task['segments'])} 段")
        self.update_continue()

    def pick(self, index):
        if self.app.busy or not self.save_edit():
            return
        self.index = index
        self.editor.configure(state="normal")
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", self.task["segments"][index]["text"])
        self.segment_title.configure(text=f"第 {index + 1} 段 · 切换时自动保存，字幕保留原文")
        for i, row in enumerate(self.rows.winfo_children()):
            row.configure(fg_color="#EEF0FE" if i == index else "white")
        for button in self.buttons:
            button.configure(state="normal")
        self.update_continue()

    def editor_changed(self, event=None):
        if self.editor.edit_modified():
            self.editor.edit_modified(False)
            self.update_continue()

    def update_continue(self):
        if self.app.busy:
            return
        changed = (self.task is not None and self.index is not None
                   and self.editor.get("1.0", "end-1c") != self.task["segments"][self.index]["text"])
        complete = (self.task is not None and self.task["status"] == "complete" and not changed
                    and all(segment["status"] == "done" for segment in self.task["segments"])
                    and self.app.task_store.output(self.task).is_file())
        button = self.buttons[-1]
        button.set_kind("primary", "done" if complete else "next")
        button.configure(text="已全部生成" if complete else "继续生成任务",
                         state="disabled" if complete or self.task is None else "normal")

    def save_edit(self):
        if self.app.busy:
            return False
        if self.task is None or self.index is None:
            return True
        try:
            changed = self.task["segments"][self.index]["text"] != self.editor.get("1.0", "end-1c")
            self.app.task_store.edit(self.task, self.index, self.editor.get("1.0", "end-1c"))
            if changed:
                self.draw_rows()
            return True
        except (OSError, ValueError) as error:
            self.app.show_error("修改未保存", str(error), parent=self)
            return False

    def apply_dictionary(self):
        if not self.task or not self.save_edit():
            return
        from pronunciation import apply
        try:
            entries = load(self.app.pronunciation_path)
            changed = False
            for segment in self.task["segments"]:
                if apply(segment["text"], self.task["lexicon"]) != apply(segment["text"], entries):
                    segment.update(status="pending", signature="")
                    changed = True
            self.task["lexicon"] = entries
            if changed:
                self.task["status"] = "draft"
            self.app.task_store.save(self.task)
            self.draw_rows()
        except (OSError, ValueError) as error:
            self.app.show_error("词典未应用", str(error), parent=self)

    def regenerate(self):
        self.run(self.index)

    def resume(self):
        self.run(None)

    def run(self, only):
        if not self.task or not self.save_edit():
            return
        if not self.app.run_saved_task(self.task, only):
            return

    def set_busy(self, preview=False):
        self.info.configure(text="正在试听音色 · 任务内容已保留" if preview else "正在生成 · 已完成分段会保留，可停止后继续")
        self.editor.configure(state="disabled")
        self.picker.configure(state="disabled")
        for button in self.buttons:
            button.configure(state="disabled")
        self.buttons[-1].set_kind("stop", "stop")
        self.buttons[-1].configure(text="停止生成", command=self.stop, state="normal")

    def stop(self):
        self.app.stop_generation()
        self.buttons[-1].configure(text="正在停止…", state="disabled")

    def finished(self):
        self.picker.configure(state="normal" if self.options else "disabled")
        self.buttons[-1].set_kind("primary", "next")
        self.buttons[-1].configure(text="继续生成任务", command=self.resume)
        if self.task:
            self.task = self.app.task_store.load(self.task["id"])
            index = self.index or 0
            self.index = None
            self.draw_rows()
            self.pick(index)
        else:
            self.refresh()

    def listen(self):
        if not self.task or not self.save_edit():
            return
        if self.task["status"] != "complete":
            self.app.show_notice("音频需要更新", "请先继续生成任务，合并最新分段后再试听。", parent=self)
            return
        path = self.app.task_store.output(self.task)
        if not path.is_file():
            self.app.show_notice("音频文件缺失", "请点击“继续生成任务”重新合并音频。", parent=self)
            return
        self.app.use_task_audio(path, self.task["name"])

    def listen_segment(self):
        if not self.task or not self.save_edit():
            return
        segment = self.task["segments"][self.index]
        path = self.app.task_store.folder(self.task["id"]) / (segment["id"] + ".wav")
        if segment["status"] != "done" or not path.is_file():
            self.app.show_notice("这段尚未生成", "请先点击“重生成此段”。", parent=self)
            return
        import uuid
        import wave
        from pathlib import Path
        from audio_output import audio_output
        from subtitles import write_srt
        try:
            target = Path(self.app.temp.name) / (uuid.uuid4().hex + ".mp3")
            with wave.open(str(path), "rb") as source, audio_output(target, source.getframerate()) as write:
                write(source.readframes(source.getnframes()))
            write_srt(target, segment.get("cues", []))
            self.app.use_task_audio(target, f"{self.task['name']} · 第 {self.index + 1} 段")
            self.app.trim_audio_cache()
        except (OSError, wave.Error) as error:
            self.app.show_error("这段无法试听", str(error), parent=self)

class DictionaryWindow(ctk.CTkToplevel):
    def __init__(self, app):
        super().__init__(app)
        self.withdraw()
        self.transient(app)
        self.app = app
        self.title("发音词典")
        self.geometry("660x500")
        self.minsize(560, 420)
        self.configure(fg_color="white")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        app.label(self, "发音词典", 18, bold=True).grid(row=0, column=0, sticky="w", padx=24, pady=(20, 8))
        app.label(self, "每行填写一个替换词：要替换的文字 = 配音时读出的文字。\n例如“星 = 月”，配音遇到“星”时就会读成“月”。\n只替换朗读内容，文稿和字幕不变；区分大小写，长词优先。", 13, MUTED,
                  justify="left", anchor="w").grid(row=1, column=0, sticky="ew", padx=24, pady=(0, 12))
        self.editor = ctk.CTkTextbox(self, font=("Microsoft YaHei UI", 14), wrap="word",
                                    fg_color="#FAFBFE", border_width=1, border_color="#CBD2DF")
        self.editor.grid(row=2, column=0, sticky="nsew", padx=24)
        self.path = app.pronunciation_path
        self.editor.insert("1.0", "\n".join(f"{key} = {value}" for key, value in load(self.path).items()))
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew", padx=24, pady=20)
        app.label(footer, "旧任务可在配音任务页点击“应用当前词典”。", 12, MUTED).pack(side="left")
        app.button(footer, "保存", self.commit, primary=True, width=80, height=36, size=13).pack(side="right")
        self.bind("<Escape>", lambda event: self.destroy())
        self.after(0, lambda: show_editor(self, app, center=True))

    def commit(self):
        if self.app.busy:
            self.app.show_notice("正在生成", "请在当前配音结束后保存词典。", parent=self)
            return
        entries = {}
        try:
            for number, line in enumerate(self.editor.get("1.0", "end-1c").splitlines(), 1):
                if not line.strip():
                    continue
                if "=" not in line:
                    raise ValueError(f"第 {number} 行缺少等号，请填写“要替换的文字 = 配音时读出的文字”。")
                key, value = (part.strip() for part in line.split("=", 1))
                if key in entries:
                    raise ValueError(f"第 {number} 行的原文重复：{key}")
                entries[key] = value
            save(self.path, entries)
        except (OSError, ValueError) as error:
            self.app.show_error("词典未保存", str(error), parent=self)
            return
        self.app.preview_cache.clear()
        self.destroy()
