"""Clone-package selection in the existing desktop visual system."""
import customtkinter as ctk
from PIL import Image, ImageDraw

from clone_models import MODEL_INFO

# Same tokens as app.py; importing them would re-run app.py when it is __main__.
BLUE, BLUE_DARK, BLUE_SOFT = "#4F5BEF", "#3D48D4", "#EEF0FE"
MUTED, LINE, TRACK = "#5F6880", "#E7EAF0", "#ECEEF3"


class ModelPage(ctk.CTkScrollableFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent", corner_radius=0)
        self._scrollbar.grid_remove()
        self.app = app
        self.grid_columnconfigure((0, 1), weight=1, uniform="model")
        app.label(self, "克隆模型", 24, bold=True).grid(
            row=0, column=0, sticky="w", padx=8, pady=(14, 4))
        app.label(self, "按需下载，安装后可离线使用。",
                  13, MUTED, wraplength=710, justify="left", anchor="w").grid(
            row=1, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 20))
        summary = ctk.CTkFrame(self, fg_color=BLUE_SOFT, corner_radius=12)
        summary.grid(row=0, column=1, sticky="e", padx=8, pady=(14, 4))
        self.current = app.label(summary, "", 13, BLUE_DARK, bold=True, anchor="w")
        self.current.pack(side="left", padx=14, pady=6)
        self.cards = {}
        for index, (key, info) in enumerate(MODEL_INFO.items()):
            card = ctk.CTkFrame(self, fg_color="white", corner_radius=14,
                               border_width=1, border_color=LINE)
            card.grid(row=2 + index // 2, column=index % 2, sticky="nsew", padx=8, pady=(0, 16))
            card.grid_columnconfigure(0, weight=1)
            heading = ctk.CTkFrame(card, fg_color="transparent")
            heading.grid(row=0, column=0, sticky="ew", padx=24, pady=(22, 6))
            app.label(heading, info["name"], 20, bold=True).pack(side="left")
            if key == "qwen3_q8":
                app.label(heading, "推荐使用", 11, BLUE_DARK, bold=True, fg_color=BLUE_SOFT,
                          corner_radius=6, width=66, height=24).pack(side="left", padx=(10, 0))
            badge = app.label(heading, "尚未安装", 12, MUTED, bold=True, fg_color=TRACK,
                              corner_radius=8, width=76, height=28)
            badge.pack(side="right")
            app.label(card, info["description"], 13, MUTED, wraplength=0, height=44,
                      justify="left", anchor="w").grid(row=1, column=0, sticky="ew", padx=24, pady=(0, 12))
            specs = ctk.CTkFrame(card, fg_color="#F5F6FC", corner_radius=12)
            specs.grid(row=2, column=0, sticky="ew", padx=24, pady=(4, 14))
            specs.grid_columnconfigure((0, 1), weight=1, uniform="spec")
            for item, (title, value) in enumerate((("下载大小", info["download"]), ("占用空间", info["storage"]),
                                                   ("运行环境", info["hardware"]), ("参考说明", info["reference"]))):
                cell = ctk.CTkFrame(specs, fg_color="transparent", corner_radius=0)
                cell.grid(row=item // 2, column=item % 2, sticky="nsew", padx=12, pady=10)
                cell.grid_columnconfigure(1, weight=1)
                icon = Image.new("RGBA", (48, 48))
                draw = ImageDraw.Draw(icon)
                if item == 0:
                    draw.line([(24, 7), (24, 30), (15, 22), (24, 31), (33, 22)], fill=BLUE, width=3)
                    draw.line([(9, 30), (9, 40), (39, 40), (39, 30)], fill=BLUE, width=3)
                elif item == 1:
                    draw.rounded_rectangle((10, 11, 38, 38), radius=8, outline=BLUE, width=3)
                    draw.ellipse((10, 7, 38, 20), fill="#F5F6FC", outline=BLUE, width=3)
                    draw.arc((10, 19, 38, 31), 0, 180, fill=BLUE, width=3)
                elif item == 2:
                    draw.rectangle((13, 13, 35, 35), outline=BLUE, width=3)
                    draw.rectangle((19, 19, 29, 29), outline=BLUE, width=2)
                    for tick in (17, 24, 31):
                        for points in (((tick, 6), (tick, 12)), ((tick, 36), (tick, 42)),
                                       ((6, tick), (12, tick)), ((36, tick), (42, tick))):
                            draw.line(points, fill=BLUE, width=3)
                else:
                    draw.line([(30, 7), (12, 7), (12, 41), (36, 41), (36, 15), (30, 7), (30, 17), (36, 17)], fill=BLUE, width=3)
                    for line in (23, 29, 35):
                        draw.line([(18, line), (30, line)], fill=BLUE, width=2)
                ctk.CTkLabel(cell, text="", width=36, height=36, fg_color="transparent", corner_radius=0,
                             image=ctk.CTkImage(icon, size=(23, 23))).grid(row=0, column=0, rowspan=2, padx=(0, 10))
                app.label(cell, title, 12, MUTED, anchor="w").grid(row=0, column=1, sticky="ew")
                detail = app.label(cell, value, 12, bold=item == 0, anchor="w", justify="left", wraplength=170)
                detail.grid(row=1, column=1, sticky="ew", pady=(3, 0))
                cell.bind("<Configure>", lambda e, label=detail: label.configure(wraplength=max(90, e.width - 48)))
            ctk.CTkFrame(card, height=1, corner_radius=0, fg_color="#F0F1F6").grid(
                row=5, column=0, sticky="ew", padx=24, pady=(0, 10))
            status = app.label(card, "尚未安装", 12, MUTED, wraplength=290,
                               justify="left", anchor="w", height=24)
            status.grid(row=6, column=0, sticky="ew", padx=24, pady=(0, 10))
            progress = ctk.CTkProgressBar(card, height=6, corner_radius=3, fg_color=TRACK, progress_color=BLUE)
            progress.set(0)
            progress.grid(row=7, column=0, sticky="ew", padx=24, pady=(0, 14))
            actions = ctk.CTkFrame(card, fg_color="transparent")
            actions.grid(row=8, column=0, sticky="ew", padx=24, pady=(0, 22))
            primary = app.button(actions, "下载模型", lambda k=key: app.model_action(k),
                                 True, height=40, size=13, width=132)
            primary.cget("font").configure(weight="bold")
            primary.pack(side="left")
            remove = app.button(actions, "删除模型", lambda k=key: app.remove_model(k),
                                height=40, size=13, width=92)
            remove.configure(fg_color="white", hover_color="#FFF3F1",
                             border_color=LINE, text_color="#B63A3A",
                             text_color_disabled="#D0B3B1")
            remove.cget("font").configure(weight="bold")
            remove.pack(side="right")
            self.cards[key] = dict(frame=card, status=status, badge=badge, progress=progress,
                                   primary=primary, remove=remove)
        app.label(self, "删除模型只释放模型空间，不会删除你的个人音色与参考录音。",
                  12, MUTED, wraplength=710, justify="left", anchor="w").grid(
            row=20, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 16))

    def refresh(self):
        from offline import installed, registrations
        from clone_models import package_dir
        app = self.app
        self.current.configure(text="当前使用：" + MODEL_INFO[app.clone_model]["label"] +
                               ("" if installed(app.clone_model) else "（尚未安装）"))
        for key, card in self.cards.items():
            ready = installed(key)
            active = key == app.clone_model and ready
            downloading = app.installing and app.download_key == key
            state = app.download_state.get(key, {})
            deleting = getattr(app, "deleting_model", None) == key
            cancelling = downloading and app.download_cancel.is_set()
            badge_text = ("正在删除" if deleting else "正在取消" if cancelling else "正在下载" if downloading else
                          "下载失败" if state.get("error") else "已安装" if ready else "尚未安装")
            card["badge"].configure(text=badge_text,
                fg_color=BLUE_SOFT if downloading else "#EAF5EF" if ready else TRACK,
                text_color="#B3324D" if state.get("error") else BLUE_DARK if downloading else
                           "#22835B" if ready else MUTED)
            if downloading or getattr(app, "deleting_model", None) == key or state.get("error"):
                card["status"].grid()
            else:
                card["status"].grid_remove()
            card["frame"].configure(border_color=BLUE if active else LINE,
                                    border_width=2 if active else 1)
            card["status"].configure(text=state.get("text", "") if downloading or state.get("error") else
                                     "当前使用 · 已安装" if active else
                                     "已安装" if ready else
                                     state.get("text", "尚未安装"),
                                     text_color="#B3324D" if state.get("error") else
                                     "#22835B" if ready else MUTED)
            card["progress"].set(min(state.get("fraction", 0), 0.99) if downloading else 1 if ready else 0)
            text = ("正在取消…" if cancelling else "取消下载") if downloading else (
                "正在使用" if active else "使用此模型" if ready else "重试下载" if state.get("error") else "下载模型")
            card["primary"].configure(text=text, fg_color=BLUE_SOFT if active else BLUE,
                                      text_color_disabled=BLUE_DARK if active else "#9AA2B4",
                                      state="disabled" if (app.busy and not downloading) or active or cancelling or
                                      (app.installing and not downloading) else "normal")
            if getattr(app, "deleting_model", None) == key:
                card["status"].configure(text="正在删除模型文件，请稍候…")
                card["primary"].configure(text="正在删除…", state="disabled")
                card["progress"].configure(mode="indeterminate")
                card["progress"].start()
            else:
                card["progress"].stop()
                card["progress"].configure(mode="determinate")
            if downloading or getattr(app, "deleting_model", None) == key:
                card["progress"].grid()
            else:
                card["progress"].grid_remove()
            has_files = ready or (key == "qwen3_q8" and package_dir().exists()) or (
                key == "zipvoice" and bool(registrations().get(key)))
            card["remove"].configure(state="normal" if has_files and not app.busy and not app.installing else "disabled")
