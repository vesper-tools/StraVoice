"""Windows TTS client with online Edge voices and local ZipVoice models."""
import asyncio
import hashlib
import json
import math
import os
import queue
import re
import shutil
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, font as tkfont

os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
import customtkinter as ctk
import pygame
import miniaudio
from PIL import Image, ImageDraw, ImageGrab, ImageTk
from customtkinter.windows.widgets.core_rendering import DrawEngine

from engine import fetch_voices, synthesize
from pauses import PAUSE, split_pauses
from offline import (DownloadCancelled, add_clone, clones, install, installed,
                     load_engine, local_voices, remove_clone)

from clone_models import MODEL_INFO, active_model, set_active_model, remove_package
from model_page import ModelPage
from dubbing_tasks import TaskStore, render_task
from pronunciation import load as load_pronunciation
from task_ui import TaskPage, DictionaryWindow, show_editor, dictionary_icon

VERSION = "1.0.0"
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
DATA = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "FreeVoice"
BLUE = "#4F5BEF"
BLUE_DARK = "#3D48D4"
BLUE_SOFT = "#F0EFFF"
BLUE_LINE = "#CDD0FF"
INK = "#151B2E"
MUTED = "#5F6880"
SUBTLE = "#9AA2B4"
PALE = "#F3F4FE"
LINE = "#E3E5FC"
TRACK = "#EDEEF7"
HOVER = "#F7F6FE"
# Native canvas paths avoid missing or mismatched shape-font glyphs in EXEs.
DrawEngine.preferred_drawing_method = "circle_shapes"

NAMES = {
    "Xiaoxiao": "晓晓", "Xiaoyi": "晓伊", "Yunjian": "云健",
    "Yunxi": "云希", "Yunxia": "云夏", "Yunyang": "云扬",
    "Xiaobei": "晓北", "Xiaoni": "晓妮", "HiuGaai": "晓佳",
    "HiuMaan": "晓曼", "WanLung": "云龙", "HsiaoChen": "晓臻",
    "HsiaoYu": "晓雨", "YunJhe": "云哲",
}
LOCALES = {
    "af-ZA": "南非荷兰语 · 南非", "am-ET": "阿姆哈拉语 · 埃塞俄比亚",
    "ar-AE": "阿拉伯语 · 阿联酋", "ar-BH": "阿拉伯语 · 巴林",
    "ar-DZ": "阿拉伯语 · 阿尔及利亚", "ar-EG": "阿拉伯语 · 埃及",
    "ar-IQ": "阿拉伯语 · 伊拉克", "ar-JO": "阿拉伯语 · 约旦",
    "ar-KW": "阿拉伯语 · 科威特", "ar-LB": "阿拉伯语 · 黎巴嫩",
    "ar-LY": "阿拉伯语 · 利比亚", "ar-MA": "阿拉伯语 · 摩洛哥",
    "ar-OM": "阿拉伯语 · 阿曼", "ar-QA": "阿拉伯语 · 卡塔尔",
    "ar-SA": "阿拉伯语 · 沙特阿拉伯", "ar-SY": "阿拉伯语 · 叙利亚",
    "ar-TN": "阿拉伯语 · 突尼斯", "ar-YE": "阿拉伯语 · 也门",
    "az-AZ": "阿塞拜疆语 · 阿塞拜疆", "bg-BG": "保加利亚语 · 保加利亚",
    "bn-BD": "孟加拉语 · 孟加拉国", "bn-IN": "孟加拉语 · 印度",
    "bs-BA": "波斯尼亚语 · 波黑", "ca-ES": "加泰罗尼亚语 · 西班牙",
    "cs-CZ": "捷克语 · 捷克", "cy-GB": "威尔士语 · 英国",
    "da-DK": "丹麦语 · 丹麦", "de-AT": "德语 · 奥地利",
    "de-CH": "德语 · 瑞士", "de-DE": "德语 · 德国", "el-GR": "希腊语 · 希腊",
    "en-AU": "英语 · 澳大利亚", "en-CA": "英语 · 加拿大",
    "en-GB": "英语 · 英国", "en-HK": "英语 · 中国香港",
    "en-IE": "英语 · 爱尔兰", "en-IN": "英语 · 印度",
    "en-KE": "英语 · 肯尼亚", "en-NG": "英语 · 尼日利亚",
    "en-NZ": "英语 · 新西兰", "en-PH": "英语 · 菲律宾",
    "en-SG": "英语 · 新加坡", "en-TZ": "英语 · 坦桑尼亚",
    "en-US": "英语 · 美国", "en-ZA": "英语 · 南非",
    "es-AR": "西班牙语 · 阿根廷", "es-BO": "西班牙语 · 玻利维亚",
    "es-CL": "西班牙语 · 智利", "es-CO": "西班牙语 · 哥伦比亚",
    "es-CR": "西班牙语 · 哥斯达黎加", "es-CU": "西班牙语 · 古巴",
    "es-DO": "西班牙语 · 多米尼加", "es-EC": "西班牙语 · 厄瓜多尔",
    "es-ES": "西班牙语 · 西班牙", "es-GQ": "西班牙语 · 赤道几内亚",
    "es-GT": "西班牙语 · 危地马拉", "es-HN": "西班牙语 · 洪都拉斯",
    "es-MX": "西班牙语 · 墨西哥", "es-NI": "西班牙语 · 尼加拉瓜",
    "es-PA": "西班牙语 · 巴拿马", "es-PE": "西班牙语 · 秘鲁",
    "es-PR": "西班牙语 · 波多黎各", "es-PY": "西班牙语 · 巴拉圭",
    "es-SV": "西班牙语 · 萨尔瓦多", "es-US": "西班牙语 · 美国",
    "es-UY": "西班牙语 · 乌拉圭", "es-VE": "西班牙语 · 委内瑞拉",
    "et-EE": "爱沙尼亚语 · 爱沙尼亚", "fa-IR": "波斯语 · 伊朗",
    "fi-FI": "芬兰语 · 芬兰", "fil-PH": "菲律宾语 · 菲律宾",
    "fr-BE": "法语 · 比利时", "fr-CA": "法语 · 加拿大",
    "fr-CH": "法语 · 瑞士", "fr-FR": "法语 · 法国",
    "ga-IE": "爱尔兰语 · 爱尔兰", "gl-ES": "加利西亚语 · 西班牙",
    "gu-IN": "古吉拉特语 · 印度", "he-IL": "希伯来语 · 以色列",
    "hi-IN": "印地语 · 印度", "hr-HR": "克罗地亚语 · 克罗地亚",
    "hu-HU": "匈牙利语 · 匈牙利", "id-ID": "印度尼西亚语 · 印度尼西亚",
    "is-IS": "冰岛语 · 冰岛", "it-IT": "意大利语 · 意大利",
    "iu-Cans-CA": "因纽特语 · 加拿大音节文字", "iu-Latn-CA": "因纽特语 · 加拿大拉丁字母",
    "ja-JP": "日语 · 日本", "jv-ID": "爪哇语 · 印度尼西亚",
    "ka-GE": "格鲁吉亚语 · 格鲁吉亚", "kk-KZ": "哈萨克语 · 哈萨克斯坦",
    "km-KH": "高棉语 · 柬埔寨", "kn-IN": "卡纳达语 · 印度",
    "ko-KR": "韩语 · 韩国", "lo-LA": "老挝语 · 老挝",
    "lt-LT": "立陶宛语 · 立陶宛", "lv-LV": "拉脱维亚语 · 拉脱维亚",
    "mk-MK": "马其顿语 · 北马其顿", "ml-IN": "马拉雅拉姆语 · 印度",
    "mn-MN": "蒙古语 · 蒙古国", "mr-IN": "马拉地语 · 印度",
    "ms-MY": "马来语 · 马来西亚", "mt-MT": "马耳他语 · 马耳他",
    "my-MM": "缅甸语 · 缅甸", "nb-NO": "挪威语 · 挪威",
    "ne-NP": "尼泊尔语 · 尼泊尔", "nl-BE": "荷兰语 · 比利时",
    "nl-NL": "荷兰语 · 荷兰", "pl-PL": "波兰语 · 波兰",
    "ps-AF": "普什图语 · 阿富汗", "pt-BR": "葡萄牙语 · 巴西",
    "pt-PT": "葡萄牙语 · 葡萄牙", "ro-RO": "罗马尼亚语 · 罗马尼亚",
    "ru-RU": "俄语 · 俄罗斯", "si-LK": "僧伽罗语 · 斯里兰卡",
    "sk-SK": "斯洛伐克语 · 斯洛伐克", "sl-SI": "斯洛文尼亚语 · 斯洛文尼亚",
    "so-SO": "索马里语 · 索马里", "sq-AL": "阿尔巴尼亚语 · 阿尔巴尼亚",
    "sr-RS": "塞尔维亚语 · 塞尔维亚", "su-ID": "巽他语 · 印度尼西亚",
    "sv-SE": "瑞典语 · 瑞典", "sw-KE": "斯瓦希里语 · 肯尼亚",
    "sw-TZ": "斯瓦希里语 · 坦桑尼亚", "ta-IN": "泰米尔语 · 印度",
    "ta-LK": "泰米尔语 · 斯里兰卡", "ta-MY": "泰米尔语 · 马来西亚",
    "ta-SG": "泰米尔语 · 新加坡", "te-IN": "泰卢固语 · 印度",
    "th-TH": "泰语 · 泰国", "tr-TR": "土耳其语 · 土耳其",
    "uk-UA": "乌克兰语 · 乌克兰", "ur-IN": "乌尔都语 · 印度",
    "ur-PK": "乌尔都语 · 巴基斯坦", "uz-UZ": "乌兹别克语 · 乌兹别克斯坦",
    "vi-VN": "越南语 · 越南", "zu-ZA": "祖鲁语 · 南非",
    "zh-CN": "中文 · 普通话", "zh-HK": "中文 · 香港粤语", "zh-TW": "中文 · 台湾国语",
    "zh-CN-liaoning": "中文 · 辽宁方言", "zh-CN-shaanxi": "中文 · 陕西方言",
}
PROVIDER_KEY = {"内置音色": "edge", "克隆语音": "zipvoice", "我的收藏": "favorites"}
PROVIDER_LABEL = {value: key for key, value in PROVIDER_KEY.items()}
CLONE_GENDERS = {"女声": "Female", "男声": "Male"}


def is_personal_voice(short):
    return short.startswith(("local:clone:", "local:qwen3_q8:clone:"))


def clone_preview_folder(short):
    return DATA / "preview-cache" / hashlib.sha256(short.encode("utf-8")).hexdigest()


def trim_clone_previews(data, protected=(), max_entries=200, max_bytes=128 * 1024 * 1024):
    """Evict only generated clone previews, oldest use first; keep active files."""
    protected = {Path(path).resolve() for path in protected if path is not None}
    entries = []
    root = Path(data) / "preview-cache"
    for path in root.glob("*/*.mp3"):
        if path.is_symlink() or path.parent.is_symlink():
            continue
        if not all(re.fullmatch(r"[0-9a-f]{64}", value) for value in (path.parent.name, path.stem)):
            continue
        try:
            if path.resolve() in protected:
                os.utime(path, None)
            subtitle = path.with_suffix(".srt")
            size = path.stat().st_size + (subtitle.stat().st_size if subtitle.is_file() else 0)
            entries.append((path.stat().st_mtime, path, size))
        except OSError:
            continue
    count, size = len(entries), sum(entry[2] for entry in entries)
    for _, path, entry_size in sorted(entries):
        if count <= max_entries and size <= max_bytes:
            break
        if path.resolve() in protected:
            continue
        try:
            path.unlink()
            path.with_suffix(".srt").unlink(missing_ok=True)
        except OSError:
            continue
        count -= 1
        size -= entry_size


def voice_name(voice):
    if voice["ShortName"].startswith("local:") and "Name" in voice:
        return voice["Name"]
    short = voice["ShortName"]
    name = short.split("-")[-1].removesuffix("Neural")
    return NAMES.get(name, name)


class ProviderTabs(ctk.CTkFrame):
    """Source tabs on one continuous track, without per-corner backgrounds."""

    def __init__(self, master, command, values=None, height=28):
        super().__init__(master, fg_color=TRACK, corner_radius=9)
        self.command = command
        self.value = ""
        self.buttons = {}
        for column, value in enumerate(PROVIDER_KEY if values is None else values):
            self.grid_columnconfigure(column, weight=1, uniform="provider")
            button = ctk.CTkButton(
                self, text=value, width=1, height=height, corner_radius=7,
                fg_color=TRACK, hover_color="#E7EAF1", text_color=INK,
                text_color_disabled=SUBTLE,
                font=("Microsoft YaHei UI", 13, "bold"),
                command=lambda value=value: self.select(value))
            button.grid(row=0, column=column, sticky="ew", padx=3, pady=3)
            self.buttons[value] = button

    def set(self, value):
        self.value = value
        for name, button in self.buttons.items():
            button.configure(fg_color=BLUE if name == value else TRACK,
                             hover_color=BLUE_DARK if name == value else "#E7EAF1",
                             text_color="white" if name == value else INK)

    def select(self, value):
        self.set(value)
        self.command(value)

    def get(self):
        return self.value

    def configure(self, **kwargs):
        state = kwargs.pop("state", None)
        if state is not None:
            for button in self.buttons.values():
                button.configure(state=state)
        super().configure(**kwargs)


class StatusLabel(ctk.CTkLabel):
    """Single-line label that ends long messages (e.g. saved paths) with an ellipsis."""

    def __init__(self, *args, **kwargs):
        self._full = kwargs.get("text", "")
        super().__init__(*args, **kwargs)
        self.bind("<Configure>", lambda event: self._fit(), add="+")

    def configure(self, require_redraw=False, **kwargs):
        if "text" in kwargs:
            self._full = kwargs["text"]
            kwargs["text"] = self._clip(self._full)
        super().configure(require_redraw, **kwargs)

    def _clip(self, text):
        width = self.winfo_width() - 8
        if width <= 8:
            return text
        metric = tkfont.Font(root=self, font=self._label.cget("font"))
        if metric.measure(text) <= width:
            return text
        while len(text) > 1 and metric.measure("…" + text) > width:
            text = text[1:]
        return "…" + text

    def _fit(self):
        super().configure(text=self._clip(self._full))


class VoiceList(ctk.CTkFrame):
    """Canvas-drawn voice list.

    Rows are canvas items rather than nested CTk widgets: scrolling becomes a
    canvas blit, no native child window is moved or repainted, so cost stays flat
    for any number of voices.
    """

    ROW_HEIGHT = 52   # logical px, excludes the gap
    ROW_GAP = 8
    OVERSCAN = 3      # extra rows kept above/below the viewport
    RADIUS = 10
    BADGE = 34
    BUTTON_W = 56
    BUTTON_H = 30

    def __init__(self, master, on_select, on_preview, on_favorite=None, on_delete=None):
        super().__init__(master, fg_color="transparent")
        self.on_select = on_select
        self.on_preview = on_preview
        self.on_favorite = on_favorite
        self.on_delete = on_delete
        self.favorites = set()
        self.voices = []
        self.selected = None
        self.empty_frame = None
        self.empty_status = None
        try:
            self._s = self._get_widget_scaling() or 1.0
        except Exception:
            self._s = 1.0
        s = self._s
        self._step = round((self.ROW_HEIGHT + self.ROW_GAP) * s)
        self._pad = round(self.ROW_GAP / 2 * s)
        self._row_px = round(self.ROW_HEIGHT * s)
        # Negative sizes mean pixels in Tk; CTkFont does the same, so canvas text
        # matches the widget text exactly instead of being scaled twice.
        self._fonts = {
            "name": ("Microsoft YaHei UI", -round(14 * s), "bold"),
            "small": ("Microsoft YaHei UI", -round(12 * s)),
            "button": ("Microsoft YaHei UI", -round(12 * s), "bold"),
        }
        self._metrics = {key: tkfont.Font(root=self, font=value) for key, value in self._fonts.items()}
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, bg="white", highlightthickness=0, bd=0, takefocus=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar = ctk.CTkScrollbar(self, command=self._yview, width=10,
            button_color="#D5DAE4", button_hover_color="#B7C0D0")
        self.scrollbar.grid(row=0, column=1, sticky="ns", padx=(2, 0))
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.slots = []
        self._hover = None
        self._hover_action = None
        self.tooltip = tk.Label(self.canvas, bg=INK, fg="white", padx=6, pady=3,
                                font=self._fonts["small"])
        self._grow(10)
        self.canvas.bind("<Configure>", self._resize)
        self.canvas.bind("<Motion>", self._motion)
        self.canvas.bind("<Leave>", self._leave)
        self.canvas.bind_all("<MouseWheel>", self._wheel, add="+")

    # ---------- primitives ----------

    @staticmethod
    def _round_points(x1, y1, x2, y2, r, steps=10):
        """Exact rounded-rectangle outline. Tk's smooth=True runs a B-spline that
        never touches the vertices, which bows the straight edges and inflates
        the corners, so the arc is sampled explicitly instead."""
        r = max(0.0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
        points = []
        for cx, cy, start in ((x2 - r, y1 + r, -90), (x2 - r, y2 - r, 0),
                              (x1 + r, y2 - r, 90), (x1 + r, y1 + r, 180)):
            for step in range(steps + 1):
                angle = math.radians(start + 90 * step / steps)
                points.append(cx + r * math.cos(angle))
                points.append(cy + r * math.sin(angle))
        return points

    def _grow(self, count):
        while len(self.slots) < count:
            self.slots.append(self._make_slot())

    def _make_slot(self):
        tag = f"row{len(self.slots)}"
        button_tag = tag + "b"
        canvas = self.canvas
        slot = {
            "tag": tag, "button_tag": button_tag, "index": None, "short": None,
            "box": canvas.create_polygon(0, 0, 0, 0, 0, 0,
                fill="white", outline="white", width=max(1, self._s * 0.75), tags=(tag,)),
            "badge": canvas.create_oval(0, 0, 0, 0, fill=BLUE_SOFT, outline="",
                tags=(tag,)),
            "badge_text": canvas.create_text(0, 0, text="", fill=BLUE,
                font=self._fonts["small"], tags=(tag,)),
            "name": canvas.create_text(0, 0, text="", anchor="w", fill=INK,
                font=self._fonts["name"], tags=(tag,)),
            "detail": canvas.create_text(0, 0, text="", anchor="w", fill=MUTED,
                font=self._fonts["small"], tags=(tag,)),
            "button": canvas.create_polygon(0, 0, 0, 0, 0, 0,
                fill="white", outline=BLUE_LINE, width=self._s, tags=(tag, button_tag)),
            "play_icon": canvas.create_polygon(0, 0, 0, 0, 0, 0,
                fill=BLUE_DARK, outline="", tags=(tag, button_tag)),
            "button_text": canvas.create_text(0, 0, text="试听", fill=BLUE_DARK,
                font=self._fonts["button"], tags=(tag, button_tag)),
            "favorite": canvas.create_polygon(0, 0, 0, 0, 0, 0,
                fill=PALE, outline="", tags=(tag,)),
            "favorite_icon": canvas.create_polygon(0, 0, 0, 0, 0, 0, fill="",
                outline=BLUE, width=1.6 * self._s, joinstyle="round", tags=(tag,)),
            "delete": canvas.create_polygon(0, 0, 0, 0, 0, 0,
                fill="#FFF1F0", outline="", tags=(tag,)),
            "delete_body": canvas.create_line(0, 0, 0, 0, fill="#B63A3A", width=1.6 * self._s,
                capstyle="round", joinstyle="round", tags=(tag,)),
            "delete_lid": canvas.create_line(0, 0, 0, 0, fill="#B63A3A", width=1.6 * self._s,
                capstyle="round", tags=(tag,)),
            "delete_handle": canvas.create_line(0, 0, 0, 0, fill="#B63A3A", width=1.6 * self._s,
                capstyle="round", joinstyle="round", tags=(tag,)),
        }
        canvas.tag_bind(tag, "<Button-1>", lambda event, s=slot: self._click(s, event))
        canvas.itemconfigure(tag, state="hidden")
        return slot

    def _click(self, slot, event):
        self.tooltip.place_forget()
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        for key, callback in (("favorite", self.on_favorite), ("delete", self.on_delete),
                              ("button", self.on_preview)):
            box = slot.get(key + "_box")
            if box and box[0] <= x <= box[2] and box[1] <= y <= box[3]:
                if callback and slot["short"]:
                    callback(slot["short"])
                return
        self._select(slot)

    def _select(self, slot):
        if slot["short"]:
            self.on_select(slot["short"])

    def _preview(self, slot):
        if slot["short"]:
            self.on_preview(slot["short"])

    # ---------- row rendering ----------

    def _place(self, slot, index):
        s, canvas = self._s, self.canvas
        width = max(canvas.winfo_width(), 60)
        y1 = index * self._step + self._pad
        y2 = y1 + self._row_px
        canvas.coords(slot["box"],
            *self._round_points(1, y1, width - 2, y2, self.RADIUS * s))
        size = self.BADGE * s
        top = y1 + (self._row_px - size) / 2
        left = 10 * s
        canvas.coords(slot["badge"], left, top, left + size, top + size)
        canvas.coords(slot["badge_text"], left + size / 2, top + size / 2)
        canvas.coords(slot["name"], 56 * s, (y1 + y2) / 2)
        bw, bh = self.BUTTON_W * s, self.BUTTON_H * s
        bx2 = width - 10 * s
        by1 = y1 + (self._row_px - bh) / 2
        canvas.coords(slot["button"],
            *self._round_points(bx2 - bw, by1, bx2, by1 + bh, self.RADIUS * s))
        canvas.coords(slot["play_icon"], bx2-bw+10*s, by1+bh/2-4*s,
                      bx2-bw+10*s, by1+bh/2+4*s, bx2-bw+16*s, by1+bh/2)
        canvas.coords(slot["button_text"], bx2 - bw / 2 + 7*s, by1 + bh / 2)
        slot["button_box"] = (bx2 - bw, by1, bx2, by1 + bh)
        is_clone = is_personal_voice(slot["short"])
        delete_right = bx2 - bw - 6 * s
        favorite_right = delete_right - 30 * s if is_clone else delete_right
        favorite_left = favorite_right - 26 * s
        icon_top = by1 + (bh - 26 * s) / 2
        for key, box in (("favorite", (favorite_left, icon_top, favorite_right, icon_top + 26 * s)),
                         ("delete", (delete_right - 26 * s, icon_top, delete_right, icon_top + 26 * s))):
            canvas.coords(slot[key], *self._round_points(*box, 6 * s))
            cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
            if key == "favorite":
                points = []
                for i in range(10):
                    angle = math.radians(-90 + i * 36)
                    radius = (6.5 if i % 2 == 0 else 3.1) * s
                    points.extend((cx + math.cos(angle) * radius, cy + math.sin(angle) * radius))
                canvas.coords(slot["favorite_icon"], *points)
            else:
                canvas.coords(slot["delete_body"], cx-4*s, cy-2.5*s, cx-3.5*s, cy+6*s,
                              cx+3.5*s, cy+6*s, cx+4*s, cy-2.5*s)
                canvas.coords(slot["delete_lid"], cx-6*s, cy-4*s, cx+6*s, cy-4*s)
                canvas.coords(slot["delete_handle"], cx-2.5*s, cy-4*s, cx-2.5*s, cy-6.5*s,
                              cx+2.5*s, cy-6.5*s, cx+2.5*s, cy-4*s)
            slot[key + "_box"] = box if key != "delete" or is_clone else None
        # Keep both text styles on one line and clear of the action buttons.
        text_left = 56 * s
        text_right = favorite_left - 8 * s
        available = max(0, text_right - text_left - 8 * s)
        detail_width = min(self._metrics["small"].measure(slot["detail_full"]), available * 0.65)
        for key, budget in (("name", available - detail_width), ("detail", detail_width)):
            text = slot[key + "_full"]
            metric = self._metrics["name" if key == "name" else "small"]
            if metric.measure(text) > budget:
                while text and metric.measure(text + "…") > budget:
                    text = text[:-1]
                text = text + "…" if text else ""
            canvas.itemconfigure(slot[key], text=text)
            if key == "name":
                canvas.coords(slot["detail"], text_left + metric.measure(text) + 8 * s, (y1 + y2) / 2)

    def _action_visibility(self, slot):
        for key, visible in (("favorite", self.on_favorite is not None),
                             ("delete", self.on_delete is not None and is_personal_voice(slot["short"]))):
            for item in (("favorite", "favorite_icon") if key == "favorite" else
                         ("delete", "delete_body", "delete_lid", "delete_handle")):
                self.canvas.itemconfigure(slot[item], state="normal" if visible else "hidden")

    def _fill(self, slot, voice):
        short = voice["ShortName"]
        female = voice["Gender"] == "Female"
        gender = "女" if female else "男" if voice["Gender"] == "Male" else "声"
        canvas = self.canvas
        canvas.itemconfigure(slot["badge"],
            fill="#F3EEFE" if female else "#E9F3FE" if gender == "男" else TRACK)
        canvas.itemconfigure(slot["badge_text"], text=gender,
            fill="#7A4FE0" if female else "#2F78D6" if gender == "男" else MUTED)
        slot["name_full"] = voice_name(voice)
        if short.startswith("local:qwen3_q8:"):
            slot["name_full"] = slot["name_full"].removesuffix(" · 音质版")
        canvas.itemconfigure(slot["name"], text=slot["name_full"])
        if short.startswith("local:"):
            model = "qwen3_q8" if short.startswith("local:qwen3_q8:") else "zipvoice"
            slot["detail_full"] = MODEL_INFO[model]["tag"]
        else:
            slot["detail_full"] = LOCALES.get(voice["Locale"], voice["Locale"])
        canvas.itemconfigure(slot["detail"], text=slot["detail_full"])
        canvas.itemconfigure(slot["favorite_icon"], fill=BLUE if short in self.favorites else "")
        slot["short"] = short
        self._paint(slot)

    def _paint(self, slot, hover=False):
        chosen = slot["short"] is not None and slot["short"] == self.selected
        self.canvas.itemconfigure(slot["box"],
            fill=BLUE_SOFT if chosen else "#F8F9FC" if hover else "white",
            outline=BLUE_LINE if chosen else "#F8F9FC" if hover else "white")
        self.canvas.itemconfigure(slot["button"],
            fill=BLUE_SOFT if hover and self._hover_action == "button" else "white")
        self.canvas.itemconfigure(slot["favorite"],
            fill="#E3E6FD" if hover and self._hover_action == "favorite" else
                 "white" if chosen else PALE)
        self.canvas.itemconfigure(slot["delete"],
            fill="#FFE5E2" if hover and self._hover_action == "delete" else "#FFF3F1")
        for key in ("delete_body", "delete_lid", "delete_handle"):
            self.canvas.itemconfigure(slot[key], fill="#982E2E" if hover and self._hover_action == "delete" else "#B63A3A")

    # ---------- scrolling ----------

    def _content_height(self):
        """The scroll region must never be shorter than the viewport. With a
        short list Tk otherwise lets yview_scroll push the content down into
        negative offsets, which shows up as a blank strip above the first row."""
        return max(len(self.voices) * self._step, self.canvas.winfo_height(), 1)

    def _scrollable(self):
        return len(self.voices) * self._step > self.canvas.winfo_height()

    def _yview(self, *args):
        if not self.voices:
            return
        if not self._scrollable():
            self.canvas.yview_moveto(0)
            self._apply()
            return
        self.canvas.yview(*args)
        self._apply()

    def _wheel(self, event):
        widget = event.widget
        while isinstance(widget, tk.Misc):
            if widget is self.canvas:
                if self._scrollable():
                    self.canvas.yview_scroll(int(-event.delta / 120), "units")
                    self._apply()
                return
            if widget is self:
                return
            widget = getattr(widget, "master", None)

    def _motion(self, event):
        # Button boxes are in content coordinates; event.x/y are viewport coordinates.
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        hit = None
        action = None
        for slot in self.slots:
            if slot["index"] is None:
                continue
            for key in ("button", "favorite", "delete"):
                box = slot.get(key + "_box")
                if box and box[0] <= cx <= box[2] and box[1] <= cy <= box[3]:
                    hit = slot
                    action = key
                    break
            if hit is not None:
                break
        if hit is None:
            # Anywhere else on a row selects it, so the whole row reacts.
            index = int(cy // self._step)
            if self._pad <= cy - index * self._step <= self._pad + self._row_px:
                hit = next((slot for slot in self.slots if slot["index"] == index), None)
                action = "row" if hit is not None else None
        if hit is self._hover and action == self._hover_action:
            return
        if self._hover is not None:
            self._paint(self._hover)
        self._hover = hit
        self._hover_action = action
        self.tooltip.place_forget()
        if hit is not None:
            self._paint(hit, hover=True)
            if action in ("favorite", "delete"):
                self.tooltip.configure(text=("取消收藏" if hit["short"] in self.favorites else "收藏音色")
                                       if action == "favorite" else "删除克隆音色")
                box = hit[action + "_box"]
                self.tooltip.place(x=box[2], y=box[3] - self.canvas.canvasy(0) + 4 * self._s,
                                   anchor="ne")
        self.canvas.configure(cursor="hand2" if hit else "")

    def _leave(self, event=None):
        self.tooltip.place_forget()
        self._hover_action = None
        if self._hover is not None:
            self._paint(self._hover)
            self._hover = None
        self.canvas.configure(cursor="")

    def _resize(self, event=None):
        width = max(event.width if event else self.canvas.winfo_width(), 60)
        self.canvas.configure(scrollregion=(0, 0, width, self._content_height()))
        row_count = max(self.canvas.winfo_height() // self._step + 1, 1)
        self._grow(row_count + 2 * self.OVERSCAN + 1)
        if not self._scrollable():
            self.canvas.yview_moveto(0)
        # The first layout runs before Tk knows the canvas width; re-flow every
        # visible row whenever the geometry actually changes.
        for slot in self.slots:
            if slot["index"] is not None:
                self._place(slot, slot["index"])
        self._apply()

    def _apply(self):
        total = len(self.voices)
        if not total:
            for slot in self.slots:
                if slot["index"] is not None:
                    slot["index"] = None
                    self.canvas.itemconfigure(slot["tag"], state="hidden")
            return
        top = max(0.0, self.canvas.canvasy(0))
        first = max(0, int(top // self._step) - self.OVERSCAN)
        if first >= total:
            first = max(0, total - 1)
        needed = list(range(first, min(total, first + len(self.slots))))
        current = {slot["index"]: slot for slot in self.slots if slot["index"] is not None}
        keep = {index: current[index] for index in needed if index in current}
        released = [slot for index, slot in current.items() if index not in keep]
        released += [slot for slot in self.slots if slot["index"] is None]
        for index, slot in zip([i for i in needed if i not in keep], released):
            slot["index"] = index
            self._fill(slot, self.voices[index])
            self._place(slot, index)
            self.canvas.itemconfigure(slot["tag"], state="normal")
            self._action_visibility(slot)
        active = set(needed)
        for slot in self.slots:
            index = slot["index"]
            if index is not None and index not in active:
                slot["index"] = None
                self.canvas.itemconfigure(slot["tag"], state="hidden")

    # ---------- public ----------

    def set_voices(self, voices, selected):
        self.tooltip.place_forget()
        self.voices = voices
        self.selected = selected
        self._hover = None
        for slot in self.slots:
            slot["index"] = None
            self.canvas.itemconfigure(slot["tag"], state="hidden")
        width = max(self.canvas.winfo_width(), 60)
        self.canvas.configure(scrollregion=(0, 0, width, self._content_height()))
        self.canvas.yview_moveto(0)
        if self._scrollable():
            self.scrollbar.grid()
        else:
            self.scrollbar.grid_remove()
        self._apply()

    def set_selected(self, short):
        self.selected = short
        for slot in self.slots:
            if slot["index"] is not None:
                self._paint(slot, hover=slot is self._hover)

    def show_empty(self, title, subtitle, primary_text=None, primary_command=None):
        self.hide_empty()
        self.scrollbar.grid_remove()
        self.canvas.itemconfigure("all", state="hidden")
        frame = self.empty_frame = ctk.CTkFrame(self, fg_color="white")
        frame.place(x=0, y=0, relwidth=1, relheight=1)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)
        body = ctk.CTkFrame(frame, fg_color="transparent")
        body.grid(row=0, column=0)
        ctk.CTkLabel(body, text=title, text_color=INK,
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=14, weight="bold")).pack(pady=(0, 6))
        self.empty_status = ctk.CTkLabel(body, text=subtitle, text_color=MUTED, wraplength=270,
            justify="center", font=ctk.CTkFont(family="Microsoft YaHei UI", size=12))
        if subtitle:
            self.empty_status.pack(pady=(0, 0 if primary_command else 4))
        button = None
        if primary_command is not None:
            button = ctk.CTkButton(body, text=primary_text or "", command=primary_command, height=42,
                corner_radius=10, fg_color=BLUE, hover_color=BLUE_DARK, text_color="white",
                text_color_disabled="#C9CEFA",
                font=ctk.CTkFont(family="Microsoft YaHei UI", size=13, weight="bold"), width=200)
            button.pack(pady=(16, 0))
        return button

    def hide_empty(self):
        if self.empty_frame is not None and self.empty_frame.winfo_exists():
            self.empty_frame.destroy()
        self.empty_frame = None
        self.empty_status = None


class LanguagePicker(ctk.CTkToplevel):
    """Canvas-drawn dropdown menu.

    One CTkButton per language meant 438 widgets and a ~225 ms stall before the
    popup showed up, because the online catalog exposes 143 locales. Canvas items
    cost a fraction of that and keep the same look: a rounded highlight behind
    the selected row, a lighter one under the pointer.
    """

    ROW_HEIGHT = 32
    ROW_STEP = 36     # 32 + 2px breathing room above and below, as before
    PAD = 6
    RADIUS = 6

    def __init__(self, master, labels, current, on_pick):
        super().__init__(master, fg_color="white")
        self.labels = list(labels)
        self.current = current
        self.on_pick = on_pick
        self._hover = None
        self._s = self._get_window_scaling() or 1.0
        s = self._s
        self._step = round(self.ROW_STEP * s)
        self._row_h = round(self.ROW_HEIGHT * s)
        self._pad = round(self.PAD * s)
        self.withdraw()
        self.overrideredirect(True)
        self.transient(master)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        frame = ctk.CTkFrame(self, fg_color="white", border_width=1,
                             border_color=LINE, corner_radius=10)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(frame, bg="white", highlightthickness=0, bd=0, takefocus=0)
        self.canvas.grid(row=0, column=0, sticky="nsew",
                         padx=(self.PAD * s, 0), pady=self.PAD * s)
        self.scrollbar = ctk.CTkScrollbar(frame, command=self._yview, width=12,
            button_color="#D5DAE4", button_hover_color="#B7C0D0")
        self.scrollbar.grid(row=0, column=1, sticky="ns",
                            padx=(2 * s, self.PAD * s), pady=self.PAD * s)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        font = ("Microsoft YaHei UI", -round(12 * s))
        self._texts = [self.canvas.create_text(round(12 * s), 0, text=label, anchor="w",
                                               fill=INK, font=font) for label in self.labels]
        self._hover_pill = self.canvas.create_polygon(0, 0, 0, 0, 0, 0, fill=HOVER,
                                                      outline="", state="hidden")
        self._select_pill = self.canvas.create_polygon(0, 0, 0, 0, 0, 0, fill=BLUE_SOFT,
                                                       outline="", state="hidden")
        self.canvas.tag_lower(self._hover_pill)
        self.canvas.tag_lower(self._select_pill)
        self.canvas.bind("<Configure>", self._draw)
        self.canvas.bind("<Motion>", self._motion)
        self.canvas.bind("<Leave>", self._leave)
        self.canvas.bind("<Button-1>", self._click)
        for widget in (self.canvas, frame, self):
            widget.bind("<MouseWheel>", self._wheel)
        self.bind("<Escape>", lambda event: self.destroy())

    # ---------- drawing ----------

    def _index_of(self, label):
        try:
            return self.labels.index(label)
        except ValueError:
            return None

    def _content_height(self):
        return self._pad * 2 + self._row_h + max(len(self.labels) - 1, 0) * self._step

    def _draw(self, event=None):
        s = self._s
        width = max(self.canvas.winfo_width(), 60)
        for index, item in enumerate(self._texts):
            self.canvas.coords(item, round(12 * s),
                               self._pad + index * self._step + self._row_h / 2)
        self._paint()
        self.canvas.configure(scrollregion=(
            0, 0, width, max(self._content_height(), self.canvas.winfo_height(), 1)))
        if not getattr(self, "_revealed", False) and self.canvas.winfo_height() > 1:
            self._revealed = True
            self._reveal_current()

    def _reveal_current(self):
        """Reopening the menu should show the current pick, not always the top."""
        index = self._index_of(self.current)
        if index is None:
            return
        viewport, content = self.canvas.winfo_height(), self._content_height()
        if content <= viewport:
            return
        top = self._pad + index * self._step
        if top + self._row_h <= viewport:
            return
        offset = min(max(top - (viewport - self._row_h) / 2, 0), content - viewport)
        self.canvas.yview_moveto(offset / content)


    def _paint(self):
        width = max(self.canvas.winfo_width(), 60)
        for item, index in ((self._select_pill, self._index_of(self.current)),
                            (self._hover_pill, self._hover)):
            if index is None:
                self.canvas.itemconfigure(item, state="hidden")
                continue
            y1 = self._pad + index * self._step
            self.canvas.coords(item, *VoiceList._round_points(
                1, y1, width - 1, y1 + self._row_h, self.RADIUS * self._s))
            self.canvas.itemconfigure(item, state="normal")

    # ---------- interaction ----------

    def _index_at(self, event):
        y = self.canvas.canvasy(event.y) - self._pad
        if y < 0:
            return None
        index = int(y // self._step)
        return index if 0 <= index < len(self.labels) else None

    def _motion(self, event):
        index = self._index_at(event)
        if index == self._hover:
            return
        self._hover = index
        self._paint()
        self.canvas.configure(cursor="hand2" if index is not None else "")

    def _leave(self, event=None):
        if self._hover is not None:
            self._hover = None
            self._paint()
        self.canvas.configure(cursor="")

    def _click(self, event):
        index = self._index_at(event)
        if index is not None:
            self.on_pick(self.labels[index])

    def _wheel(self, event):
        if self._content_height() > self.canvas.winfo_height():
            self.canvas.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    def _yview(self, *args):
        if self._content_height() > self.canvas.winfo_height():
            self.canvas.yview(*args)
        else:
            self.canvas.yview_moveto(0)


class PlaybackSlider(ctk.CTkSlider):
    def _draw(self, no_color_updates=False):
        super()._draw(no_color_updates)
        # Keep a small circular thumb within the full-height clickable canvas.
        points = self._canvas.coords("slider_line_1")
        if points:
            x, y = points[0], self._apply_widget_scaling(self._current_height) / 2
            self._canvas.coords("slider_line_1", *([x, y] * 4))


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        # CTk handles monitor DPI. Keep type/control sizes fixed on resize.
        left, top, right, bottom = self.screen_work_area()
        scaling = self._get_window_scaling()
        width = min(1120, int((right - left - 64) / scaling))
        height = min(700, int((bottom - top - 64) / scaling))
        x = left + (right - left - round(width * scaling)) // 2
        y = top + (bottom - top - round(height * scaling)) // 2
        self.title(f"星悦配音 · v{VERSION}")
        self.geometry(f"{width}x{height}{x:+d}{y:+d}")
        self.minsize(min(860, width), min(560, height))
        self.configure(fg_color=PALE)
        if (ROOT / "app.ico").exists():
            self.iconbitmap(str(ROOT / "app.ico"))
        self._native_icons = []
        self.after(250, self.set_window_icons)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.events = queue.Queue()
        self.closing = threading.Event()
        self.generation_cancel = threading.Event()
        self.audio_worker = None
        self.worker_lock = threading.Lock()
        self.worker_threads = []
        self.worker_tasks = {}
        self.busy = False
        self.refreshing = False
        self.temp = tempfile.TemporaryDirectory(prefix="freevoice-")
        self.latest = None
        self.latest_name = "配音"
        self.preview_cache = {}
        self.task_store = TaskStore(Path(self.temp.name) / "tasks")
        self.pronunciation_path = DATA / "pronunciation.json"
        self.current_task_id = None
        self.workbench_task_id = None
        self.audio_ready = False
        self.audio_paused = False
        self.audio_duration = 0.0
        self.audio_offset = 0.0
        self.voice_filter = "全部"
        self.selected = "zh-CN-XiaoxiaoNeural"
        self.provider = "edge"
        self.clone_model = active_model()
        self.installing = False
        self.download_key = None
        self.download_state = {}
        self.download_cancel = threading.Event()
        self.voices = self.load_voices()
        self.online_voices = self.voices
        self.favorites = self.load_favorites()
        self.build()
        self.update_locales()
        self.render_voices()
        self.trim_audio_cache()
        self.bind("<Control-s>", lambda event: self.save_audio())
        self.after(100, self.poll)
        self.after(200, self.refresh_voices)

    def set_window_icons(self):
        if sys.platform != "win32" or not (ROOT / "app.ico").exists():
            return
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        user32.GetParent.argtypes = [wintypes.HWND]
        user32.GetParent.restype = wintypes.HWND
        user32.GetDpiForWindow.argtypes = [wintypes.HWND]
        user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                                      ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        hwnd = user32.GetParent(self.winfo_id())
        dpi = user32.GetDpiForWindow(hwnd) or 96
        # The Windows taskbar uses a 24-DIP icon; the title bar uses 16 DIP.
        for kind, logical_size in ((1, 24), (0, 16)):
            size = round(logical_size * dpi / 96)
            icon = user32.LoadImageW(None, str(ROOT / "app.ico"), 1, size, size, 0x10)
            if icon:
                user32.SendMessageW(hwnd, 0x80, kind, icon)
                self._native_icons.append(icon)

    def screen_work_area(self):
        if sys.platform != "win32":
            return 0, 0, self.winfo_screenwidth(), self.winfo_screenheight()
        # Tk can report DPI-virtualized screen sizes; use Windows monitor pixels.
        import ctypes
        from ctypes import wintypes
        class MonitorInfo(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                        ("work", wintypes.RECT), ("flags", wintypes.DWORD)]
        user32 = ctypes.windll.user32
        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.MonitorFromWindow.restype = wintypes.HANDLE
        user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
        info = MonitorInfo()
        info.size = ctypes.sizeof(info)
        monitor = user32.MonitorFromWindow(self.winfo_id(), 2)
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            raise ctypes.WinError()
        return info.work.left, info.work.top, info.work.right, info.work.bottom

    def load_voices(self):
        for path in (DATA / "voices.json", ROOT / "voices.json"):
            try:
                voices = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(voices, list) and voices and all(
                    isinstance(v, dict) and all(isinstance(v.get(k), str) and v[k].strip()
                                               for k in ("ShortName", "Locale", "Gender"))
                    for v in voices
                ):
                    return voices
            except (OSError, ValueError):
                pass
        return [{"ShortName": "zh-CN-XiaoxiaoNeural", "Locale": "zh-CN", "Gender": "Female"}]

    def label(self, parent, text, size=15, color=INK, bold=False, **kwargs):
        return ctk.CTkLabel(parent, text=text, text_color=color,
                            font=ctk.CTkFont(family="Microsoft YaHei UI", size=size,
                                            weight="bold" if bold else "normal"), **kwargs)

    def button(self, parent, text, command, primary=False, height=42, size=16, **kwargs):
        return ctk.CTkButton(parent, text=text, command=command, height=height,
                            corner_radius=10, fg_color=BLUE if primary else PALE,
                            hover_color=BLUE_DARK if primary else "#E9EBF2",
                            text_color="white" if primary else INK,
                            text_color_disabled=SUBTLE, border_width=0 if primary else 1,
                            border_color=LINE,
                            font=ctk.CTkFont(family="Microsoft YaHei UI", size=size, weight="bold"), **kwargs)

    def build(self):
        # Layout follows the dubbing flow: pick a voice and write on the
        # workbench, generate from the editor, then listen and export in the
        # player dock along the bottom edge.
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        topbar = ctk.CTkFrame(self, fg_color="#F8F8FE", corner_radius=0, height=60)
        topbar.grid(row=0, column=0, sticky="ew")
        topbar.grid_propagate(False)
        topbar.grid_columnconfigure(2, weight=1)
        topbar.grid_rowconfigure(0, weight=1)
        ctk.CTkFrame(topbar, height=1, fg_color=LINE, corner_radius=0).place(
            relx=0, rely=1, relwidth=1, anchor="sw")
        brand = ctk.CTkFrame(topbar, fg_color="transparent")
        brand.grid(row=0, column=0, padx=(24, 32))
        with Image.open(ROOT / "app.ico") as icon:
            logo = ctk.CTkImage(icon.copy(), size=(26, 26))
        ctk.CTkLabel(brand, text="", image=logo, width=26).pack(side="left", padx=(0, 10))
        self.label(brand, "星悦配音", 17, bold=True).pack(side="left")
        nav = ctk.CTkFrame(topbar, fg_color="transparent")
        nav.grid(row=0, column=1)
        self.page_buttons = {}
        for key, title in (("workbench", "配音工作台"), ("tasks", "配音任务"), ("models", "克隆模型配置")):
            button = ctk.CTkButton(nav, text=title, command=lambda k=key: self.show_page(k),
                height=34, width=96, corner_radius=17, border_width=0,
                font=ctk.CTkFont(family="Microsoft YaHei UI", size=14, weight="bold"))
            button.pack(side="left", padx=(0, 6))
            self.page_buttons[key] = button
        self.status = StatusLabel(topbar, text="", text_color=MUTED, anchor="e", width=1,
                                  font=ctk.CTkFont(family="Microsoft YaHei UI", size=12))
        self.status.grid(row=0, column=2, sticky="ew", padx=(16, 24))

        body = ctk.CTkFrame(self, fg_color="transparent")
        # A decorative background layer leaves the existing grid untouched.
        wash = Image.new("RGB", (320, 180))
        # Colors sampled from the approved mockup's exposed background.
        wash_colors = (
            ((246, 240, 253), (231, 235, 254), (238, 242, 253), (239, 242, 254)),
            ((237, 238, 253), (241, 242, 253), (241, 246, 253), (229, 239, 253)),
            ((239, 242, 253), (239, 243, 253), (234, 238, 253), (230, 232, 253)),
        )
        pixels = []
        for y in range(180):
            for x in range(320):
                gx, gy = x / 319 * 3, y / 179 * 2
                col, row = min(int(gx), 2), min(int(gy), 1)
                u, v = gx - col, gy - row
                u, v = u * u * (3 - 2 * u), v * v * (3 - 2 * v)
                pixels.append(tuple(round(255 - 1.15 * (255 - (
                    (1 - v) * ((1 - u) * wash_colors[row][col][c] + u * wash_colors[row][col + 1][c])
                    + v * ((1 - u) * wash_colors[row + 1][col][c] + u * wash_colors[row + 1][col + 1][c]))))
                    for c in range(3)))
        wash.putdata(pixels)
        self.ambient_background = tk.Label(body, bd=0, highlightthickness=0)
        self.ambient_background.place(x=0, y=0, relwidth=1, relheight=1)
        self.ambient_background.lift()

        def paint_background(event):
            size = (max(1, event.width), max(1, event.height))
            if size == getattr(self, "ambient_size", None):
                return
            self.ambient_size = size
            self.ambient_image = ImageTk.PhotoImage(wash.resize(size, Image.Resampling.BILINEAR))
            self.ambient_background.configure(image=self.ambient_image)

        body.bind("<Configure>", paint_background, add="+")
        self.workbench = body
        body.grid(row=1, column=0, sticky="nsew", padx=20, pady=(18, 16))
        body.grid_columnconfigure(0, weight=1, minsize=round(self._apply_window_scaling(300)))
        body.grid_columnconfigure(1, weight=0, minsize=round(self._apply_window_scaling(360)))
        body.grid_rowconfigure(0, weight=1)

        # ---------- editor ----------
        self.editor_panel = left = self.card(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(1, weight=1)
        bar = ctk.CTkFrame(left, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=24, pady=(18, 6))
        self.label(bar, "配音文稿", 16, bold=True).pack(side="left")
        self.clear_btn = self.button(bar, "清空", self.clear_text, width=48, height=28, size=12)
        self.clear_btn.configure(fg_color="transparent", hover_color=PALE, border_width=0, text_color=MUTED)
        self.clear_btn.pack(side="right")
        self.counter = self.label(bar, "0 / 5000 字", 12, SUBTLE)
        self.counter.pack(side="right", padx=(0, 8))
        self.editor_focused = False
        self.text = ctk.CTkTextbox(left, fg_color="#FAFBFE", border_width=1,
            border_color="#CBD2DF", corner_radius=10, cursor="xterm", insertwidth=2,
            insertofftime=0,
            text_color="#555E6D", font=("Microsoft YaHei UI", 15), wrap="word", spacing3=8,
            scrollbar_button_color="#D5DAE4", scrollbar_button_hover_color="#B7C0D0")
        self.text.grid(row=1, column=0, sticky="nsew", padx=24, pady=(6, 0))
        self.placeholder = self.label(self.text, "在这里输入或粘贴文稿…", 15, SUBTLE, anchor="w")
        self.placeholder.configure(fg_color="#FAFBFE", cursor="xterm")
        self.placeholder.place(x=12, y=10, anchor="nw")
        self.placeholder.bind("<Button-1>", self.focus_editor)
        self.text.bind("<FocusIn>", lambda event: self.editor_focus(True))
        self.text.bind("<FocusOut>", lambda event: self.editor_focus(False))
        self.text.bind("<KeyRelease>", self.count_text)
        self.text.bind("<<Paste>>", lambda event: self.after(50, self.count_text), add="+")
        self.text.bind("<Control-Return>", lambda event: (self.generate(), "break")[1])

        pause_bar = ctk.CTkFrame(left, fg_color="transparent")
        pause_bar.grid(row=2, column=0, sticky="ew", padx=24, pady=(8, 0))
        dictionary = self.button(pause_bar, "发音词典", self.open_dictionary, width=100, height=28, size=12,
                                 image=dictionary_icon(BLUE_DARK), compound="left")
        dictionary.configure(fg_color=BLUE_SOFT, hover_color="#E0E3FF", text_color=BLUE_DARK,
                             border_color="#A8AEF7", border_width=1)
        dictionary.cget("font").configure(weight="bold")
        dictionary.pack(side="right", padx=(12, 0))
        pause_label = self.label(pause_bar, "插入停顿", 12, MUTED)
        pause_label.pack(side="left", padx=(0, 8))
        pause_buttons = []
        for seconds in (0.5, 1, 2):
            button = self.button(pause_bar, f"{seconds:g}秒",
                                 lambda value=seconds: self.insert_pause(value),
                                 width=40, height=28, size=12)
            button.configure(border_width=0, fg_color=PALE, hover_color=TRACK, text_color=MUTED)
            button.cget("font").configure(weight="normal")
            button.pack(side="left", padx=(0, 4))
            pause_buttons.append(button)
        self.pause_duration = ctk.CTkEntry(pause_bar, width=70, height=28,
            placeholder_text="自定义秒", font=("Microsoft YaHei UI", 12),
            border_width=1, border_color=LINE, fg_color="white")
        self.pause_duration.pack(side="left", padx=(4, 4))
        self.pause_duration.bind("<Return>", lambda event: self.insert_pause())
        pause_insert = self.button(pause_bar, "插入", self.insert_pause, width=40, height=28, size=12)
        pause_insert.configure(fg_color=BLUE_SOFT, hover_color="#E0E3FF", text_color=BLUE_DARK,
                               border_color="#A8AEF7", border_width=1)
        pause_insert.pack(side="left")
        tools_layout = None
        def layout_tools(event):
            nonlocal tools_layout
            compact = event.width < pause_bar._apply_widget_scaling(500)
            if tools_layout == compact:
                return
            tools_layout = compact
            size = 11 if compact else 12
            dictionary.configure(width=84 if compact else 100)
            dictionary.pack_configure(padx=(6 if compact else 12, 0))
            pause_label.pack_configure(padx=(0, 4 if compact else 8))
            for index, button in enumerate(pause_buttons):
                button.configure(width=(32 if index == 0 else 26) if compact else 40)
                button.pack_configure(padx=(0, 2 if compact else 4))
            for widget in (dictionary, pause_label, *pause_buttons, pause_insert):
                widget.cget("font").configure(size=size)
            self.pause_duration.configure(width=52 if compact else 70, font=("Microsoft YaHei UI", size))
            self.pause_duration.pack_configure(padx=(2, 2) if compact else (4, 4))
            pause_insert.configure(width=32 if compact else 40)
        pause_bar.bind("<Configure>", layout_tools)
        settings = ctk.CTkFrame(left, fg_color="transparent")
        settings.grid(row=4, column=0, sticky="ew", padx=24, pady=(14, 0))
        for column, title, start, end, default, callback in [
            (0, "语速", 0.5, 2.0, 1.0, self.speed_changed),
            (1, "音调", -50, 50, 0, self.pitch_changed),
            (2, "音量", 0, 200, 100, self.volume_changed),
        ]:
            settings.grid_columnconfigure(column, weight=1, uniform="settings")
            frame = ctk.CTkFrame(settings, fg_color="transparent")
            frame.grid(row=0, column=column, sticky="ew", padx=(0, 20) if column < 2 else 0)
            frame.grid_columnconfigure(0, weight=1)
            self.label(frame, title, 12, MUTED).grid(row=0, column=0, sticky="w")
            value = self.label(frame, ("1.0×", "+0 Hz", "100%")[column], 12, INK, bold=True)
            value.grid(row=0, column=1, sticky="e")
            slider = ctk.CTkSlider(frame, from_=start, to=end, width=96, height=16,
                border_width=5, corner_radius=3, button_corner_radius=7, button_length=0,
                fg_color=TRACK, progress_color=BLUE, button_color=BLUE,
                button_hover_color=BLUE_DARK, command=callback)
            slider.set(default)
            slider.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
            if column == 0:
                self.speed, self.speed_value = slider, value
            elif column == 2:
                self.volume, self.volume_value = slider, value
            else:
                slider.configure(number_of_steps=100)
                self.pitch, self.pitch_value = slider, value

        action_bar = ctk.CTkFrame(left, fg_color="transparent")
        action_bar.grid(row=5, column=0, sticky="ew", padx=24, pady=(18, 20))
        action_bar.grid_columnconfigure(0, weight=1)
        generation = ctk.CTkFrame(action_bar, fg_color="transparent")
        generation.grid(row=0, column=0, sticky="ew")
        generation.grid_columnconfigure(1, weight=1)
        wave = ctk.CTkFrame(generation, width=28, height=24, fg_color="transparent")
        wave.grid(row=0, column=0, rowspan=2, padx=(0, 10), pady=2)
        self.generation_bars = []
        for index, height in enumerate((6, 12, 18, 12, 6)):
            bar = ctk.CTkFrame(wave, width=4, height=height, corner_radius=2, fg_color=SUBTLE)
            bar.place(x=1 + index * 5, rely=0.5, anchor="w")
            self.generation_bars.append(bar)
        self.generation_title = self.label(generation, "准备就绪", 13, INK, bold=True, anchor="w", width=1, height=18)
        self.generation_title.grid(row=0, column=1, sticky="ew")
        self.generation_detail = self.label(generation, "选择音色后点击生成", 11, MUTED, anchor="w", width=1, height=18)
        self.generation_detail.grid(row=1, column=1, sticky="ew")
        self.generation_percent = self.label(generation, "", 13, BLUE, bold=True, width=40, anchor="e")
        self.generation_percent.grid(row=0, column=2, rowspan=2, padx=(4, 12))
        self.preview_btn = self.button(action_bar, "试听前100字", lambda: self.generate(True),
                                      width=112, height=42, size=13)
        self.preview_btn.configure(fg_color="white", hover_color=BLUE_SOFT, text_color=BLUE_DARK,
                                   border_color=BLUE_LINE)
        self.preview_btn.grid(row=0, column=1, padx=(0, 10))
        self.generate_btn = self.button(action_bar, "生成配音", self.generate, True,
                                       width=132, height=42, size=14)
        self.generate_btn.configure(font=ctk.CTkFont(family="Microsoft YaHei UI", size=14, weight="bold"))
        self.generate_btn.grid(row=0, column=2)
        self.generation_spinner = []
        for angle in range(0, 360, 15):
            image = Image.new("RGBA", (64, 64))
            draw = ImageDraw.Draw(image)
            draw.ellipse((8, 8, 56, 56), outline=BLUE_LINE, width=7)
            draw.arc((8, 8, 56, 56), angle, angle + 100, fill=BLUE_DARK, width=7)
            image = image.resize((32, 32), Image.Resampling.LANCZOS)
            self.generation_spinner.append(ctk.CTkImage(light_image=image, dark_image=image, size=(16, 16)))

        def reflow_feedback(event):
            width = action_bar._reverse_widget_scaling(event.width)
            narrow = width < 440
            generation.grid_configure(columnspan=3 if narrow else 1)
            self.preview_btn.grid_configure(row=1 if narrow else 0, pady=(12, 0) if narrow else 0)
            self.generate_btn.grid_configure(row=1 if narrow else 0, pady=(12, 0) if narrow else 0)
            self.generation_detail.configure(wraplength=max(100, width - (60 if narrow else 320)), justify="left")
        action_bar.bind("<Configure>", reflow_feedback)

        # ---------- voices ----------
        self.voice_panel = right = self.card(body, width=360)
        right.grid_propagate(False)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(5, weight=1)
        top = ctk.CTkFrame(right, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 12))
        top.grid_columnconfigure(1, weight=1)
        self.label(top, "选择音色", 16, bold=True).grid(row=0, column=0, sticky="w")
        self.voice_count = self.label(top, "", 12, SUBTLE, anchor="e", width=1)
        self.voice_count.grid(row=0, column=1, sticky="ew", padx=(12, 0))
        self.provider_menu = ProviderTabs(right, command=self.change_provider, height=32)
        self.provider_menu.set("内置音色")
        self.provider_menu.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 12))

        self.model_bar = ctk.CTkFrame(right, fg_color="transparent")
        self.model_bar.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 10))
        self.model_bar.grid_columnconfigure(0, weight=1)
        self.clone_model_value = ctk.StringVar(value=MODEL_INFO[self.clone_model]["label"])
        self.clone_selector = self.button(self.model_bar, self.clone_model_value.get(), self.open_clone_model_picker,
            height=34, size=12, textvariable=self.clone_model_value, anchor="w")
        self.clone_selector.configure(fg_color="white", hover_color=PALE)
        self.clone_selector.cget("font").configure(weight="normal")
        self.clone_selector.grid(row=0, column=0, sticky="ew")
        self.clone_btn = self.button(self.model_bar, "＋ 新增克隆", self.open_clone_dialog, True,
                                     width=96, height=34, size=12)
        self.clone_btn.configure(font=ctk.CTkFont(family="Microsoft YaHei UI", size=12, weight="bold"))
        self.clone_btn.grid(row=0, column=1, padx=(8, 0))
        self.model_bar.grid_remove()

        filters = ctk.CTkFrame(right, fg_color="transparent")
        filters.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 8))
        filters.grid_columnconfigure(0, weight=1)
        self.locale_value = ctk.StringVar(value="全部语言")
        self.locale = self.button(filters, "全部语言", self.open_language_picker, height=32, size=12,
                                  textvariable=self.locale_value, anchor="w")
        self.locale.configure(fg_color="white", hover_color=PALE)
        self.locale.cget("font").configure(weight="normal")
        self.locale.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        chevron = Image.new("RGBA", (48, 48))
        ImageDraw.Draw(chevron).line([(12, 18), (24, 30), (36, 18)], fill=MUTED, width=5)
        self.locale_arrow = ctk.CTkLabel(self.locale, text="", width=16, height=16,
                                       image=ctk.CTkImage(chevron, size=(12, 12)))
        self.locale_arrow.place(relx=1, rely=0.5, x=-10, anchor="e")
        self.locale_arrow.bind("<Button-1>", lambda event: self.locale.invoke())
        self.clone_arrow = ctk.CTkLabel(self.clone_selector, text="", width=16, height=16,
                                       image=ctk.CTkImage(chevron, size=(12, 12)))
        self.clone_arrow.place(relx=1, rely=0.5, x=-10, anchor="e")
        self.clone_arrow.bind("<Button-1>", lambda event: self.clone_selector.invoke())
        self.gender_tabs = tabs = ctk.CTkFrame(filters, fg_color="transparent")
        tabs.grid(row=0, column=1, sticky="e")
        self.filter_buttons = {}
        for i, value in enumerate(("全部", "女声", "男声")):
            button = self.button(tabs, value, lambda v=value: self.filter_voices(v),
                width=48, height=32, size=12)
            button.configure(border_width=0, corner_radius=16)
            button.pack(side="left", padx=(0 if i == 0 else 4, 0))
            self.filter_buttons[value] = button
        self.paint_filters("全部")
        ctk.CTkFrame(right, height=1, fg_color=LINE, corner_radius=0).grid(
            row=4, column=0, sticky="ew", padx=20, pady=(4, 0))
        self.voice_list = VoiceList(right, self.select_voice, self.preview_voice,
                                    self.toggle_favorite, self.delete_voice)
        self.voice_list.grid(row=5, column=0, sticky="nsew", padx=(12, 8), pady=(8, 12))

        # ---------- player dock ----------
        self.dock = dock = ctk.CTkFrame(self, fg_color="#F8F9FE", corner_radius=0, height=76)
        dock.grid(row=2, column=0, sticky="ew")
        dock.grid_propagate(False)
        dock.grid_rowconfigure(0, weight=1)
        dock.grid_columnconfigure(2, weight=1)
        ctk.CTkFrame(dock, height=1, fg_color=LINE, corner_radius=0).place(
            relx=0, rely=0, relwidth=1, anchor="nw")
        self.play_icons = {}
        for action in ("播放", "暂停"):
            icon = Image.new("RGBA", (72, 72))
            draw = ImageDraw.Draw(icon)
            if action == "播放":
                draw.polygon([(28, 16), (28, 56), (58, 36)], fill="white")
            else:
                draw.rounded_rectangle((22, 17, 31, 55), radius=2, fill="white")
                draw.rounded_rectangle((42, 17, 51, 55), radius=2, fill="white")
            self.play_icons[action] = ctk.CTkImage(icon, icon, size=(14, 14))
        self.play_btn = ctk.CTkButton(dock, text="", command=self.toggle_play,
            image=self.play_icons["播放"], width=28, height=28, corner_radius=14, border_spacing=0,
            fg_color="#D5DAE4", hover_color=BLUE_DARK, state="disabled")
        self.play_btn.grid_propagate(False)
        # Circular buttons need the icon centered without radius-sized side gutters.
        self.play_btn.grid_columnconfigure((0, 4), minsize=0)
        self.play_btn.grid(row=0, column=1, padx=(0, 8))
        self.playback_action = "播放"
        identity = ctk.CTkFrame(dock, fg_color="transparent", height=40)
        identity.grid(row=0, column=0, sticky="w", padx=(24, 24))
        identity.grid_columnconfigure(0, weight=1)
        self.selected_caption = self.label(identity, "当前音色", 11, SUBTLE, anchor="w", height=16)
        self.selected_caption.grid(row=0, column=0, sticky="ew")
        self.selected_label = self.label(identity, "", 14, INK, bold=True, anchor="w", height=22)
        self.selected_label.grid(row=1, column=0, sticky="ew")
        self.seek_slider = PlaybackSlider(dock, from_=0, to=1, height=16,
            border_width=6.5, corner_radius=8, button_length=0, button_corner_radius=4,
            fg_color=TRACK, progress_color=BLUE, button_color=BLUE, button_hover_color=BLUE_DARK,
            command=self.seek_audio, state="disabled")
        self.seek_slider.set(0)
        self.seek_slider.grid(row=0, column=2, sticky="ew")
        self.time_label = self.label(dock, "00:00 / 00:00", 12, MUTED)
        self.time_label.grid(row=0, column=3, padx=(14, 24))
        self.subtitle_btn = self.button(dock, "下载SRT字幕", self.save_subtitles,
            width=96, height=38, size=13, state="disabled")
        self.subtitle_btn.configure(fg_color="white", hover_color=BLUE_SOFT, border_color=BLUE_LINE,
                                    text_color=BLUE_DARK, text_color_disabled=SUBTLE)
        self.subtitle_btn.grid(row=0, column=4, padx=(0, 10))
        self.save_btn = self.button(dock, "下载音频", self.save_audio,
            width=112, height=38, size=13, state="disabled")
        self.save_btn.configure(fg_color=TRACK, hover_color=BLUE_DARK, border_width=0,
                                text_color="white", text_color_disabled=SUBTLE,
                                font=ctk.CTkFont(family="Microsoft YaHei UI", size=13, weight="bold"))
        self.save_btn.grid(row=0, column=5, padx=(0, 24))

        self.model_page = ModelPage(self, self)
        self.model_page.grid(row=1, column=0, rowspan=2, sticky="nsew", padx=20, pady=(8, 16))
        self.model_page.grid_remove()
        self.task_page = TaskPage(self)
        self.task_page.grid(row=1, column=0, sticky="nsew", padx=20, pady=(8, 12))
        self.task_page.grid_remove()
        self.show_page("workbench")
        # Loading the ONNX bundle costs two to three seconds. Doing it here, after
        # the window is already on screen, means the first 试听 renders straight
        # away instead of stopping to load the model.
        self.after(1500, self.warm_up)

    def card(self, parent, **kwargs):
        return ctk.CTkFrame(parent, fg_color="white", corner_radius=14,
                            border_width=1, border_color=LINE, **kwargs)

    def paint_filters(self, value):
        for key, button in self.filter_buttons.items():
            active = key == value
            button.configure(fg_color=BLUE if active else "transparent",
                             text_color="white" if active else MUTED,
                             hover_color=BLUE_DARK if active else PALE)

    def warm_up(self):
        if self.clone_model != "zipvoice" or not installed():
            return
        async def operation():
            await asyncio.to_thread(self._load_model)
        self.worker("warmup", operation)

    def _load_model(self):
        try:
            load_engine("zipvoice")
        except Exception:
            # A broken bundle is reported when the user actually asks for audio.
            pass

    def change_provider(self, value):
        if self.busy:
            self.provider_menu.set(PROVIDER_LABEL[self.provider])
            return
        self.locale_value.set("全部语言")
        popup = getattr(self, "clone_model_picker", None)
        if popup is not None and popup.winfo_exists():
            popup.destroy()
        if getattr(self, "language_picker", None) and self.language_picker.winfo_exists():
            self.language_picker.destroy()
        self.provider = PROVIDER_KEY[value]
        if self.provider == "edge":
            self.locale.grid()
            self.gender_tabs.grid_configure(column=1, sticky="e")
        else:
            self.locale.grid_remove()
            self.gender_tabs.grid_configure(column=0, sticky="w")
        self.reload_voice_catalog()
        if self.provider != "zipvoice":
            self.model_bar.grid_remove()
        else:
            self.model_bar.grid()
        self.update_locales()
        self.filter_voices("全部")
        self.update_model_ui()
        self.status.configure(text="", text_color=MUTED)

    def load_favorites(self):
        try:
            items = json.loads((DATA / "favorites.json").read_text(encoding="utf-8"))
            return set(items) if isinstance(items, list) and all(isinstance(item, str) for item in items) else set()
        except (OSError, ValueError):
            return set()

    def save_favorites(self, favorites):
        DATA.mkdir(parents=True, exist_ok=True)
        path = DATA / "favorites.json"
        partial = path.with_suffix(".tmp")
        partial.write_text(json.dumps(sorted(favorites), ensure_ascii=False), encoding="utf-8")
        partial.replace(path)
        self.favorites = favorites

    def reload_voice_catalog(self):
        if self.provider == "edge":
            self.voices = self.online_voices
        elif self.provider == "favorites":
            self.voices = [v for v in self.online_voices + local_voices() + local_voices("qwen3_q8")
                           if v["ShortName"] in self.favorites]
        else:
            self.voices = local_voices() if self.clone_model == "zipvoice" else local_voices(self.clone_model)

    def toggle_favorite(self, short):
        if self.busy:
            return
        favorites = self.favorites ^ {short}
        try:
            self.save_favorites(favorites)
        except OSError as error:
            self.show_error("收藏保存失败", str(error), parent=self)
            return
        position = self.voice_list.canvas.yview()[0]
        self.reload_voice_catalog()
        self.update_locales()
        self.render_voices()
        self.voice_list._yview("moveto", position)
        self.status.configure(text="已收藏 · 在“收藏”中查看" if short in favorites else "已取消收藏", text_color=BLUE)

    def delete_voice(self, short):
        if self.busy or not is_personal_voice(short):
            return
        self.delete_clone(short.rsplit(":", 1)[-1])

    def update_model_ui(self):
        self.update_empty_install()
        self.clone_model_value.set(MODEL_INFO[self.clone_model]["label"])
        self.clone_selector.configure(state="disabled" if self.busy else "normal")
        self.model_page.refresh()

    def show_page(self, key):
        if (getattr(self, "current_page", None) == "tasks" and key != "tasks"
                and not self.busy and not self.task_page.save_edit()):
            return
        popup = getattr(self, "clone_model_picker", None)
        if popup is not None and popup.winfo_exists():
            popup.destroy()
        if key == "models":
            self.task_page.grid_remove()
            self.workbench.grid_remove()
            self.dock.grid_remove()
            self.model_page.grid()
            self.model_page.refresh()
        elif key == "tasks":
            self.workbench.grid_remove()
            self.model_page.grid_remove()
            self.task_page.grid()
            self.dock.grid()
            self.task_page.refresh()
        else:
            self.task_page.grid_remove()
            self.model_page.grid_remove()
            self.workbench.grid()
            self.dock.grid()
        self.current_page = key
        for name, button in self.page_buttons.items():
            button.configure(fg_color=BLUE if name == key else "white",
                             hover_color=BLUE_DARK if name == key else PALE,
                             text_color="white" if name == key else MUTED)

    def change_clone_model(self, label):
        if self.busy:
            return
        key = next(key for key, info in MODEL_INFO.items() if info["label"] == label)
        if not installed(key):
            self.clone_model_value.set(MODEL_INFO[self.clone_model]["label"])
            self.show_page("models")
            return
        try:
            set_active_model(key)
        except (OSError, ValueError) as error:
            self.show_error("无法切换模型", str(error), parent=self)
            return
        self.clone_model = key
        self.provider_menu.set("克隆语音")
        self.change_provider("克隆语音")
        self.status.configure(text="当前克隆模型：" + label, text_color=BLUE)

    def model_action(self, key):
        if self.installing:
            if key == self.download_key:
                self.download_cancel.set()
                self.update_model_ui()
            return
        if self.busy:
            return
        if installed(key):
            self.change_clone_model(MODEL_INFO[key]["label"])
            self.show_page("workbench")
        else:
            self.download_model(key)

    def preview_model(self, key):
        self.change_clone_model(MODEL_INFO[key]["label"])
        self.show_page("workbench")
        if self.voice_rows:
            self.preview_voice(next(iter(self.voice_rows)))
        else:
            self.open_clone_dialog()

    def open_model_folder(self, key):
        from clone_models import package_dir
        from offline import registrations, MODELS
        folder = package_dir() if key == "qwen3_q8" else Path(registrations().get(key) or MODELS)
        while not folder.is_dir() and folder != folder.parent:
            folder = folder.parent
        try:
            os.startfile(str(folder.resolve()))
        except OSError as error:
            self.show_error("无法打开模型文件夹", str(error), parent=self)

    def remove_model(self, key):
        if self.busy or self.installing:
            return
        self.show_delete_confirmation(self, "删除模型",
            "确认删除【" + MODEL_INFO[key]["label"] + "】的模型文件？",
            "删除后需要重新安装才能使用。\n个人音色和参考录音会保留。",
            "删除模型", lambda: self.remove_confirmed_model(key))

    def remove_confirmed_model(self, key):
        if self.busy or self.installing:
            return
        self.deleting_model = key
        self.installing = True
        self.download_key = None
        self.update_model_ui()

        def operation():
            try:
                remove_package(key)
            except Exception as error:
                self.events.put(("model_removed", key, error))
            else:
                self.events.put(("model_removed", key, None))

        threading.Thread(target=operation, daemon=True).start()

    def download_model(self, key):
        if self.installing or self.busy:
            return
        self.installing = True
        self.download_key = key
        cancel = self.download_cancel = threading.Event()
        self.download_state[key] = {"text": "正在连接下载源…", "fraction": 0}
        self.update_model_ui()
        def progress(done, total):
            if not cancel.is_set() and cancel is self.download_cancel:
                self.events.put(("download_progress", (done, total), None))
        def stage(text):
            if not cancel.is_set() and cancel is self.download_cancel:
                self.events.put(("download_stage", text, None))
        async def operation():
            await asyncio.to_thread(install, key, progress, cancel, stage)
            return key
        self.worker("model", operation)

    def update_locales(self):
        codes = sorted({v["Locale"] for v in self.voices}, key=lambda c: (not c.startswith("zh"), c))
        if not codes:
            codes = ["zh-CN"]
        if "zh-CN" in codes:
            codes.remove("zh-CN")
            codes.insert(0, "zh-CN")
        self.locale_map = {"全部语言": None, **{LOCALES.get(c, c): c for c in codes}}
        current = self.locale_value.get()
        self.locale_value.set(current if current in self.locale_map else "全部语言")

    def open_clone_model_picker(self):
        if self.busy:
            return
        popup = getattr(self, "clone_model_picker", None)
        if popup is not None and popup.winfo_exists():
            popup.destroy()
            return
        labels = [info["label"] for info in MODEL_INFO.values()]
        def choose(label):
            popup.destroy()
            self.change_clone_model(label)
        self.clone_model_picker = popup = LanguagePicker(
            self, labels, self.clone_model_value.get(), choose)
        popup.scrollbar.grid_remove()
        popup.canvas.grid_configure(padx=popup.PAD * popup._s)
        scale = self._get_window_scaling()
        width = round(self.clone_selector.winfo_width() / scale)
        height = len(labels) * popup.ROW_STEP + 2 * popup.PAD
        x = self.clone_selector.winfo_rootx()
        y = self.clone_selector.winfo_rooty() + self.clone_selector.winfo_height() + 6
        bottom = self.winfo_rooty() + self.winfo_height() - 12
        if y + height * scale > bottom:
            y = self.clone_selector.winfo_rooty() - round(height * scale) - 6
        popup.geometry(f"{width}x{height}+{x}+{y}")
        popup.deiconify()
        popup.geometry(f"{width}x{height}+{x}+{y}")
        def dismiss():
            if popup.winfo_exists():
                focused = popup.focus_get()
                if focused is None or focused.winfo_toplevel() is not popup:
                    popup.destroy()
        popup.bind("<FocusOut>", lambda event: popup.after(100, dismiss))
        popup.after(50, popup.focus_set)

    def open_task_picker(self):
        page = self.task_page
        if self.busy or not page.options:
            return
        popup = getattr(self, "task_picker", None)
        if popup is not None and popup.winfo_exists():
            popup.destroy()
            return
        def choose(label):
            popup.destroy()
            page.choose(label)
            if page.task:
                selected = next((text for text, ident in page.options.items()
                                 if ident == page.task["id"]), page.picker_value.get())
                page.picker_value.set(selected)
        self.task_picker = popup = LanguagePicker(
            self, list(page.options), page.picker_value.get(), choose)
        scale = popup._s
        width = round(page.picker.winfo_width() / scale)
        height = min(280, len(page.options) * popup.ROW_STEP + 2 * popup.PAD)
        if len(page.options) * popup.ROW_STEP + 2 * popup.PAD <= height:
            popup.scrollbar.grid_remove()
            popup.canvas.grid_configure(padx=popup.PAD * scale)
        left, top, right, bottom = self.screen_work_area()
        x = max(left, min(page.picker.winfo_rootx(), right - round(width * scale)))
        below = page.picker.winfo_rooty() + page.picker.winfo_height() + 6
        y = below if below + height * scale <= bottom else max(top, page.picker.winfo_rooty() - round(height * scale) - 6)
        popup.geometry(f"{width}x{height}{x:+d}{y:+d}")
        popup.deiconify()
        popup.geometry(f"{width}x{height}{x:+d}{y:+d}")
        def dismiss():
            if popup.winfo_exists():
                focused = popup.focus_get()
                if focused is None or focused.winfo_toplevel() is not popup:
                    popup.destroy()
        popup.bind("<FocusOut>", lambda event: popup.after(100, dismiss))
        popup.after(50, popup.focus_set)

    def open_language_picker(self):
        if self.busy:
            return
        if getattr(self, "language_picker", None) and self.language_picker.winfo_exists():
            self.language_picker.destroy()
            return
        scale = self._get_window_scaling()
        self.language_picker = popup = LanguagePicker(
            self, list(self.locale_map), self.locale_value.get(), self.choose_locale)
        label_font = tkfont.Font(family="Microsoft YaHei UI", size=-round(12 * scale))
        content_width = max(label_font.measure(label) for label in self.locale_map) / scale
        width = min(round(self.winfo_width() / scale) - 24,
                    max(math.ceil(content_width + 56), round(self.locale.winfo_width() / scale)))
        height = 280
        x = max(self.winfo_rootx(), min(self.locale.winfo_rootx(), self.winfo_rootx() + self.winfo_width() - round(width * scale)))
        below = self.locale.winfo_rooty() + self.locale.winfo_height() + 6
        bottom = self.winfo_rooty() + self.winfo_height() - 12
        y = below if below + height * scale <= bottom else max(self.winfo_rooty(), bottom - round(height * scale))
        popup.geometry(f"{width}x{height}+{x}+{y}")
        popup.deiconify()
        popup.geometry(f"{width}x{height}+{x}+{y}")
        popup.bind("<FocusOut>", lambda event: popup.after(100, self.dismiss_language_picker))
        popup.after(50, popup.focus_set)

    def dismiss_language_picker(self):
        popup = getattr(self, "language_picker", None)
        if popup is None or not popup.winfo_exists():
            return
        focused = popup.focus_get()
        if focused is None or focused.winfo_toplevel() is not popup:
            popup.destroy()

    def choose_locale(self, label):
        self.locale_value.set(label)
        popup = getattr(self, "language_picker", None)
        if popup is not None and popup.winfo_exists():
            popup.destroy()
        self.change_locale(label)

    def change_locale(self, _):
        self.render_voices()

    def filter_voices(self, value):
        self.voice_filter = value
        self.paint_filters(value)
        self.render_voices()

    def render_voices(self):
        self.empty_install_btn = None
        self.voice_list.hide_empty()
        locale = self.locale_map[self.locale_value.get()]
        voices = [v for v in self.voices if (locale is None or v["Locale"] == locale) and
                  (self.voice_filter == "全部" or v["Gender"] == ("Female" if self.voice_filter == "女声" else "Male"))]
        voices.sort(key=lambda v: (
            0 if v["Locale"] == "zh-CN" else
            1 if v["Locale"] == "zh-TW" else
            2 if v["Locale"].startswith("zh") else
            4 if v["Locale"].startswith("en") else 3))
        if voices and self.selected not in {v["ShortName"] for v in voices}:
            self.selected = voices[0]["ShortName"]
        self.voice_count.configure(text=f"{self.voice_filter} {len(voices)} 个" if self.voice_filter in ("男声", "女声")
                                   else f"共 {len(self.voices)} 个音色" if len(voices) == len(self.voices)
                                   else f"找到 {len(voices)} 个 · 共 {len(self.voices)} 个")
        self.voice_rows = {v["ShortName"]: None for v in voices}
        self.voice_list.favorites = self.favorites
        self.voice_list.set_voices(voices, self.selected)
        self.update_selected_label()
        if voices:
            return
        if self.provider == "favorites":
            self.voice_list.show_empty("还没有收藏音色" if not self.voices else "这个分类暂无收藏",
                                       "在在线或克隆语音的音色卡上点击“收藏”" if not self.voices else "试试其他语言或性别分类")
        elif self.provider == "zipvoice" and installed(self.clone_model):
            self.voice_list.show_empty("还没有可用的个人音色", "",
                                       "新增克隆音色", self.open_clone_dialog)
        elif self.provider == "zipvoice" and not self.voices:
            self.empty_install_btn = self.voice_list.show_empty(
                "尚未安装克隆音色包",
                "下载 " + MODEL_INFO[self.clone_model]["download"] + " · 安装后可离线克隆",
                "", self.install_empty_provider)
            self.update_empty_install()
        else:
            self.voice_list.show_empty("这个分类暂时没有音色", "")

    def update_empty_install(self):
        if not getattr(self, "empty_install_btn", None):
            return
        relevant = self.provider != "edge" and self.download_key == self.clone_model
        state = self.download_state.get(self.download_key, {}) if relevant else {}
        self.empty_install_btn.configure(text="查看下载进度" if self.installing else "下载安装克隆包",
                                         state="disabled" if self.busy else "normal")
        if state:
            self.voice_list.empty_status.configure(text=state["text"].split("\n", 1)[0],
                                                  text_color="#B3324D" if state.get("error") else MUTED)

    def install_empty_provider(self):
        if self.busy:
            return
        self.show_page("models")

    # ---------- voice cloning ----------

    def open_clone_dialog(self):
        if not installed(self.clone_model):
            self.show_page("models")
            self.show_notice("请先下载克隆包",
                                "使用克隆音色前，请先点击“下载安装克隆包”，安装完成后再添加克隆音色。",
                                parent=self)
            return
        if getattr(self, "clone_dialog", None) and self.clone_dialog.winfo_exists():
            self.clone_dialog.lift()
            return
        self.clone_audio = None
        self.clone_decoded = None
        self.clone_dialog = dialog = ctk.CTkToplevel(self)
        dialog.withdraw()
        dialog.title("克隆音色")
        dialog.geometry("560x580")
        dialog.minsize(520, 580)
        dialog.configure(fg_color="white")
        dialog.transient(self)
        dialog.bind("<Escape>", lambda event: dialog.destroy())
        heading = ctk.CTkFrame(dialog, fg_color="transparent")
        heading.pack(fill="x", padx=28, pady=(24, 8))
        self.label(heading, "克隆自己的音色", 20, bold=True).pack(side="left")
        self.label(heading, MODEL_INFO[self.clone_model]["label"], 11, MUTED).pack(side="right")
        self.label(dialog, "上传 3 至 10 秒的清晰人声。音质版无需填写参考文字。" if self.clone_model == "qwen3_q8" else
                          "上传 3 至 10 秒的清晰人声，再填写录音里说的文字。参考录音可在模型间共用。", 12, MUTED,
                   wraplength=440, justify="left").pack(anchor="w", padx=28, pady=(0, 16))

        fields = ctk.CTkFrame(dialog, fg_color="transparent")
        fields.pack(fill="x", padx=28, pady=(0, 20))
        fields.grid_columnconfigure(0, weight=1)
        fields.grid_columnconfigure(1, minsize=136)
        self.label(fields, "音色名称", 12, INK, bold=True).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.label(fields, "音色性别", 12, INK, bold=True).grid(row=0, column=1, sticky="w", padx=(16, 0), pady=(0, 8))
        self.clone_name = ctk.CTkEntry(fields, height=40, corner_radius=8, border_width=1,
            border_color="#DDE2EA", fg_color="white", text_color=INK, placeholder_text_color=MUTED,
            placeholder_text="例如：我的声音",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=13))
        self.clone_name.grid(row=1, column=0, sticky="ew")
        self.clone_gender = ctk.StringVar(master=dialog, value="请选择")
        def open_gender_menu():
            previous = getattr(dialog, "gender_popup", None)
            if previous is not None and previous.winfo_exists():
                previous.destroy()
                return
            def choose(value):
                self.clone_gender.set(value)
                gender_field.configure(text_color=INK)
                popup.destroy()
            dialog.gender_popup = popup = LanguagePicker(
                dialog, list(CLONE_GENDERS), self.clone_gender.get(), choose)
            popup.scrollbar.grid_remove()
            popup.canvas.grid_configure(padx=popup.PAD * popup._s)
            scale = dialog._get_window_scaling()
            width = round(gender_field.winfo_width() / scale)
            height = len(CLONE_GENDERS) * popup.ROW_STEP + 2 * popup.PAD
            x = gender_field.winfo_rootx()
            y = gender_field.winfo_rooty() + gender_field.winfo_height() + 6
            popup.geometry(f"{width}x{height}{x:+d}{y:+d}")
            popup.deiconify()
            def dismiss():
                if popup.winfo_exists():
                    focused = popup.focus_get()
                    if focused is None or focused.winfo_toplevel() is not popup:
                        popup.destroy()
            popup.bind("<FocusOut>", lambda event: popup.after(100, dismiss))
            popup.after(50, popup.focus_set)
        gender_field = self.button(fields, "请选择", open_gender_menu,
            height=40, size=13, width=120, textvariable=self.clone_gender, anchor="w")
        gender_field.configure(fg_color="white", hover_color="#F7F8FC",
                               border_color="#DDE2EA", corner_radius=8, text_color=MUTED)
        gender_field.cget("font").configure(weight="normal")
        gender_field.grid(row=1, column=1, sticky="ew", padx=(16, 0))
        gender_arrow = ctk.CTkLabel(gender_field, text="", width=16, height=16,
                                   image=self.locale_arrow.cget("image"))
        gender_arrow.place(relx=1, rely=0.5, x=-12, anchor="e")
        gender_arrow.bind("<Button-1>", lambda event: gender_field.invoke())

        self.label(dialog, "参考音频", 12, INK, bold=True).pack(anchor="w", padx=28)
        self.clone_pick = self.button(dialog, "＋  选择音频文件", self.choose_clone_audio,
                                      height=64, size=14)
        self.clone_pick.configure(fg_color="#F7F8FC", hover_color="#EEF0F8", text_color=BLUE_DARK,
                                  border_color="#DDE2EA", corner_radius=8)
        self.clone_pick.cget("font").configure(weight="bold")
        self.clone_pick.pack(fill="x", padx=28, pady=(8, 8))
        self.label(dialog, "建议 3–10 秒 · 支持 MP3 / WAV / M4A · 避免背景音乐和多人说话",
                   11, MUTED).pack(anchor="w", padx=28, pady=(0, 16))

        self.label(dialog, "参考文字 · 可选" if self.clone_model == "qwen3_q8" else "参考文字 · 必填，与录音内容一致",
                   12, INK, bold=True).pack(anchor="w", padx=28)
        self.clone_text = ctk.CTkTextbox(dialog, height=72, corner_radius=8, border_width=1,
            border_color="#DDE2EA", fg_color="white", text_color=INK, wrap="word",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=13))
        self.clone_text.pack(fill="both", expand=True, padx=28, pady=(8, 16))

        footer = ctk.CTkFrame(dialog, fg_color="#F8F9FC", corner_radius=0)
        footer.pack(side="bottom", fill="x")
        ctk.CTkFrame(footer, height=1, fg_color="#E8EBF1", corner_radius=0).pack(fill="x")
        actions = ctk.CTkFrame(footer, fg_color="transparent")
        actions.pack(fill="x", padx=28, pady=14)
        self.clone_save = self.button(actions, "保存", self.save_clone, True,
                                      height=40, size=14, width=112)
        self.clone_save.configure(corner_radius=8)
        self.clone_save.cget("font").configure(weight="bold")
        self.clone_save.pack(side="right")
        cancel = self.button(actions, "取消", dialog.destroy, height=40, size=13, width=80)
        cancel.configure(fg_color="white", border_color="#DDE2EA", corner_radius=8)
        cancel.pack(side="right", padx=(0, 8))

        self.update_idletasks()
        scale = dialog._get_window_scaling()
        width, height = 560, 580
        left, top, right, bottom = self.screen_work_area()
        x = max(left, min(self.winfo_rootx() + (self.winfo_width() - round(width * scale)) // 2,
                          right - round(width * scale)))
        y = max(top, min(self.winfo_rooty() + (self.winfo_height() - round(height * scale)) // 2,
                        bottom - round(height * scale)))
        dialog.geometry(f"{width}x{height}{x:+d}{y:+d}")
        dialog.deiconify()
        dialog.after(50, lambda: self.clone_name.focus_set())

    def choose_clone_audio(self):
        path = filedialog.askopenfilename(
            parent=self.clone_dialog, title="选择参考音频",
            filetypes=[("音频文件", "*.wav *.mp3 *.m4a *.flac *.ogg *.opus *.aac *.wma *.aif *.aiff"),
                       ("所有文件", "*.*")])
        if not path:
            return
        dialog = self.clone_dialog
        self.clone_audio = self.clone_decoded = None
        self.clone_pick.configure(text="正在读取音频…", state="disabled")
        self.clone_save.configure(state="disabled")
        async def operation():
            from offline import read_audio
            try:
                audio = await asyncio.to_thread(read_audio, path, max_seconds=20)
                return dialog, path, audio, None
            except Exception as error:
                return dialog, path, None, error
        self.worker("clone_read", operation)

    def save_clone(self):
        gender = CLONE_GENDERS.get(self.clone_gender.get())
        if not gender:
            self.show_notice("选择音色性别", "请选择女声或男声，方便在音色列表中筛选。", parent=self.clone_dialog)
            return
        if not self.clone_audio:
            self.show_notice("选择音频", "请先选择一个参考音频。", parent=self.clone_dialog)
            return
        dialog = self.clone_dialog
        name = self.clone_name.get()
        text = self.clone_text.get("1.0", "end-1c")
        path, audio = self.clone_audio, self.clone_decoded
        require_text = self.clone_model != "qwen3_q8"
        self.clone_save.configure(state="disabled", text="正在保存…")
        self.clone_pick.configure(state="disabled")
        async def operation():
            try:
                clone_id = await asyncio.to_thread(add_clone, name, text, path, gender=gender, audio=audio, require_text=require_text)
                return dialog, clone_id, None
            except Exception as error:
                return dialog, None, error
        self.worker("clone_save", operation)

    def finish_clone_event(self, task, result):
        dialog = result[0]
        if dialog is not getattr(self, "clone_dialog", None) or not dialog.winfo_exists():
            # Saving may finish after the dialog closes; keep the catalog current.
            if task == "clone_save" and result[2] is None:
                self.reload_voice_catalog()
                self.render_voices()
            return
        self.clone_pick.configure(state="normal")
        self.clone_save.configure(state="normal", text="保存")
        if task == "clone_read":
            _, path, audio, error = result
            if error:
                self.clone_pick.configure(text="＋  选择音频文件")
                self.show_error("无法读取音频", str(error), parent=dialog)
            else:
                self.clone_audio, self.clone_decoded = path, audio
                seconds = len(audio[0]) / max(audio[1], 1)
                self.clone_pick.configure(text=f"{self.short_text(Path(path).name, 28)} · {seconds:.1f} 秒")
            return
        _, clone_id, error = result
        if error:
            self.show_error("克隆失败", str(error), parent=dialog)
            return
        self.clone_audio = None
        self.clone_decoded = None
        self.clone_name.delete(0, "end")
        self.clone_gender.set("请选择")
        self.clone_text.delete("1.0", "end")
        self.clone_pick.configure(text="＋  选择音频文件")
        if self.provider != "zipvoice":
            self.provider_menu.set("克隆语音")
            self.change_provider("克隆语音")
        self.reload_voice_catalog()
        self.filter_voices("全部")
        short = f"local:qwen3_q8:clone:{clone_id}" if self.clone_model == "qwen3_q8" else f"local:clone:{clone_id}"
        dialog.destroy()
        self.select_voice(short)
        self.status.configure(text="音色已保存 · 点击试听可听效果", text_color=BLUE)

    def delete_clone(self, clone_id):
        if self.busy:
            return
        parent = self.clone_dialog if (getattr(self, "clone_dialog", None)
                                      and self.clone_dialog.winfo_exists()) else self
        item = next((item for item in clones() if item["id"] == clone_id), None)
        if item is None:
            return
        name = item["name"] if len(item["name"]) <= 36 else item["name"][:35] + "…"
        confirmation = (f"确认删除【{name}】这个克隆音色？" if len(name) <= 10 else
                        f"确认删除【{name}】\n这个克隆音色？")
        self.show_delete_confirmation(parent, "删除克隆音色", confirmation,
            "需要时，可重新上传录音克隆。", "删除音色",
            lambda: self.remove_confirmed_clone(clone_id))

    def show_notice(self, title, message, parent=None, error=False):
        parent = parent or self
        current = getattr(self, "delete_dialog", None)
        if current is not None and current.winfo_exists():
            parent.wait_window(current)
        if not parent.winfo_exists():
            return
        dialog = self.show_delete_confirmation(
            parent, title, message, "", "确定", lambda: None,
            success=True, notice="error" if error else "info")
        if dialog is not None:
            parent.wait_window(dialog)

    def show_error(self, title, message, parent=None):
        self.show_notice(title, message, parent=parent, error=True)

    def show_delete_confirmation(self, parent, title, confirmation, description, action, on_confirm,
                                 success=False, notice=None):
        if getattr(self, "delete_dialog", None) and self.delete_dialog.winfo_exists():
            self.delete_dialog.lift()
            return
        scale = self._get_window_scaling()
        parent.update_idletasks()
        x, y = parent.winfo_rootx(), parent.winfo_rooty()
        backdrop = ImageGrab.grab((x, y, x + parent.winfo_width(), y + parent.winfo_height()),
                                 all_screens=True).convert("RGB")
        backdrop = Image.blend(backdrop, Image.new("RGB", backdrop.size, "#172344"), 0.25)
        # Native image label avoids CTk's intermediate dark canvas redraws.
        overlay = tk.Frame(parent, bg="#F2F5FC", borderwidth=0, highlightthickness=0)
        background_image = ImageTk.PhotoImage(backdrop, master=overlay)
        background = tk.Label(overlay, image=background_image, borderwidth=0,
                              highlightthickness=0, bg="#F2F5FC")
        background.image = background_image
        background.place(x=0, y=0, relwidth=1, relheight=1)
        self.delete_dialog = dialog = ctk.CTkFrame(overlay, fg_color="#BEC4D0")
        dialog.place(relx=0.5, rely=0.5, anchor="center")
        surface = ctk.CTkFrame(dialog, fg_color="white", corner_radius=16,
                               border_width=1, border_color=LINE)
        surface.pack(fill="both", expand=True)
        scale = self._get_window_scaling()
        previous_grab = self.grab_current()
        previous_focus = parent.focus_get()

        def dismiss():
            dialog.grab_release()
            parent.unbind("<Escape>", escape_binding)
            overlay.destroy()
            if previous_grab and previous_grab.winfo_exists():
                previous_grab.grab_set()
            if previous_focus and previous_focus.winfo_exists():
                previous_focus.focus_set()
            else:
                parent.focus_set()

        def confirm():
            dismiss()
            # Paint the dismissed dialog before filesystem work can block Tk.
            parent.update_idletasks()
            parent.after(50, on_confirm)

        dialog.bind("<Escape>", lambda event: dismiss())
        escape_binding = parent.bind("<Escape>", lambda event: dismiss(), add="+")
        header = ctk.CTkFrame(surface, fg_color="transparent")
        header.pack(fill="x", padx=24, pady=(24, 0))
        header.grid_columnconfigure(1, weight=1)
        icon = Image.new("RGBA", (72, 72))
        draw = ImageDraw.Draw(icon)
        if notice:
            color = "#B63A3A" if notice == "error" else BLUE
            draw.rounded_rectangle((1, 1, 71, 71), radius=20,
                                   fill="#FFF0EE" if notice == "error" else BLUE_SOFT)
            draw.ellipse((19, 19, 53, 53), outline=color, width=3)
            draw.line([(36, 32), (36, 46)], fill=color, width=4)
            draw.ellipse((34, 25, 38, 29), fill=color)
        elif success:
            draw.rounded_rectangle((1, 1, 71, 71), radius=20, fill="#EEF0FF")
            draw.line([(21, 36), (32, 47), (52, 26)], fill=BLUE, width=5)
        else:
            draw.rounded_rectangle((1, 1, 71, 71), radius=20, fill="#FFF0EE")
            draw.line([(25, 31), (27, 53), (45, 53), (47, 31)], fill="#B63A3A", width=3)
            draw.line([(21, 25), (51, 25)], fill="#B63A3A", width=3)
            draw.line([(30, 25), (30, 19), (42, 19), (42, 25)], fill="#B63A3A", width=3)
        ctk.CTkLabel(header, text="", width=36, height=36,
                     image=ctk.CTkImage(icon, size=(36, 36))).grid(row=0, column=0, sticky="n", padx=(0, 12))
        self.label(header, title, 17, bold=True,
                   anchor="w", wraplength=276, justify="left").grid(row=0, column=1, sticky="ew", padx=(0, 12))
        close_icon = Image.new("RGBA", (32, 32))
        close_draw = ImageDraw.Draw(close_icon)
        close_draw.line([(9, 9), (23, 23)], fill=MUTED, width=3)
        close_draw.line([(23, 9), (9, 23)], fill=MUTED, width=3)
        self.delete_close_btn = ctk.CTkButton(header, text="", command=dismiss,
            width=24, height=24, corner_radius=6, fg_color="transparent", hover_color=PALE,
            image=ctk.CTkImage(close_icon, size=(16, 16)))
        self.delete_close_btn.grid(row=0, column=2, sticky="n")
        if notice and (len(confirmation) > 240 or confirmation.count("\n") > 5):
            body = ctk.CTkTextbox(surface, width=324, height=180, corner_radius=10,
                fg_color=HOVER, text_color=INK, wrap="word",
                font=ctk.CTkFont(family="Microsoft YaHei UI", size=13))
            body.pack(fill="x", padx=(72, 24), pady=(12, 0))
            body.insert("1.0", confirmation)
            body.configure(state="disabled")
        else:
            self.label(surface, confirmation, 14, wraplength=324, justify="left", anchor="w").pack(
                fill="x", padx=(72, 24), pady=(12, 0))
        if description:
            self.label(surface, description, 12, MUTED, wraplength=324,
                       justify="left", anchor="w").pack(fill="x", padx=(72, 24), pady=(8, 0))
        actions = ctk.CTkFrame(surface, fg_color="transparent")
        actions.pack(fill="x", padx=24, pady=(28, 24))
        self.delete_confirm_btn = self.button(actions, action, confirm, width=104, height=36, size=13)
        self.delete_confirm_btn.configure(fg_color=BLUE if success else "#B63A3A",
                                          hover_color=BLUE_DARK if success else "#982E2E", text_color="white")
        self.delete_confirm_btn.pack(side="right")
        self.delete_cancel_btn = self.button(actions, "取消", dismiss, width=80, height=36, size=13)
        self.delete_cancel_btn.configure(text_color=INK, fg_color=PALE)
        if not success:
            self.delete_cancel_btn.pack(side="right", padx=(0, 8))
        self.delete_cancel_btn.bind("<Return>", lambda event: dismiss())
        self.delete_confirm_btn.bind("<Return>", lambda event: confirm())
        for control in (self.delete_cancel_btn, self.delete_confirm_btn, self.delete_close_btn):
            control.bind("<Escape>", lambda event: dismiss())
        dialog.update_idletasks()
        width = 420
        height = max(208, round(surface.winfo_reqheight() / scale))
        dialog.configure(width=width, height=height)
        dialog.pack_propagate(False)
        overlay.place(x=0, y=0, relwidth=1, relheight=1)
        overlay.lift()
        dialog.lift()
        dialog.grab_set()
        (self.delete_confirm_btn if success else self.delete_cancel_btn).focus_set()
        return dialog

    def remove_confirmed_clone(self, clone_id):
        if self.busy:
            return
        item = next((item for item in clones() if item["id"] == clone_id), None)
        if item is None:
            return
        parent = self.clone_dialog if (getattr(self, "clone_dialog", None)
                                      and self.clone_dialog.winfo_exists()) else self
        short = f"local:clone:{clone_id}"
        matching = {short, f"local:qwen3_q8:clone:{clone_id}"}
        try:
            if self.latest and any(Path(self.latest).parent == clone_preview_folder(key) for key in matching):
                preserved = Path(self.temp.name) / (uuid.uuid4().hex + ".mp3")
                shutil.copyfile(self.latest, preserved)
                captions = Path(self.latest).with_suffix(".srt")
                if captions.is_file():
                    shutil.copyfile(captions, preserved.with_suffix(".srt"))
                self.stop_audio()
                self.latest = preserved
            remove_clone(clone_id)
        except OSError as error:
            self.show_error("删除失败", str(error), parent=parent)
            return
        if matching & self.favorites:
            try:
                self.save_favorites(self.favorites - matching)
            except OSError as error:
                self.favorites.difference_update(matching)
                self.show_error("收藏保存失败", str(error), parent=parent)
        self.preview_cache = {key: path for key, path in self.preview_cache.items() if key[0] not in matching}
        for voice_key in matching:
            shutil.rmtree(clone_preview_folder(voice_key), ignore_errors=True)
        if self.selected in matching:
            self.selected = ""
        self.reload_voice_catalog()
        self.update_locales()
        self.render_voices()
        self.status.configure(text=f"已删除克隆音色 · {item['name']}", text_color=BLUE)

    def update_selected_label(self):
        available = self.selected in self.voice_rows
        local = self.provider == "zipvoice" or (available and self.selected.startswith("local:"))
        self.pitch.configure(state="disabled" if local else "normal",
                             progress_color=TRACK if local else BLUE,
                             button_color="#C7CDDC" if local else BLUE)
        self.pitch_value.configure(text="仅在线" if local else f"{round(self.pitch.get()):+d} Hz",
                                   text_color=MUTED if local else INK)
        self.preview_btn.configure(state="normal" if available and not self.busy else "disabled")
        if not self.busy:
            self.generate_btn.configure(state="normal" if available else "disabled",
                                         fg_color=BLUE if available else "#E4E7F0")
        if self.latest:
            self.selected_caption.configure(text="音频音色")
            self.selected_label.configure(text=self.short_text(self.latest_name, 10), text_color=INK)
            return
        voice = next((v for v in self.voices if v["ShortName"] == self.selected), None)
        self.selected_caption.configure(text="当前音色")
        self.selected_label.configure(text=self.short_text(voice_name(voice), 10) if voice else
                                      "请选择收藏音色" if self.provider == "favorites" else "尚未选择音色",
                                      text_color=INK if voice else SUBTLE)

    @staticmethod
    def short_text(text, limit):
        return text if len(text) <= limit else text[:limit - 1] + "…"

    def select_voice(self, short):
        if self.busy:
            return
        self.selected = short
        self.update_selected_label()
        self.voice_list.set_selected(short)

    def preview_voice(self, short):
        if not self.busy:
            self.select_voice(short)
            self.generate(True, voice_sample=True)

    def focus_editor(self, event=None):
        self.placeholder.place_forget()
        self.after_idle(self.text.focus_set)

    def editor_focus(self, focused):
        self.editor_focused = focused
        self.text.configure(border_color=BLUE if focused else "#CBD2DF")
        self.count_text()

    def count_text(self, event=None):
        content = self.text.get("1.0", "end-1c")
        count = len(content)
        self.text._textbox.tag_configure("pause", foreground=BLUE, background=BLUE_SOFT)
        self.text._textbox.tag_remove("pause", "1.0", "end")
        for match in PAUSE.finditer(content):
            self.text._textbox.tag_add("pause", f"1.0+{match.start()}c", f"1.0+{match.end()}c")
        self.counter.configure(text=f"{count} / 5000 字", text_color="#D14A64" if count > 5000 else MUTED)
        if count or self.editor_focused:
            self.placeholder.place_forget()
        else:
            self.placeholder.place(x=12, y=10, anchor="nw")

    def clear_text(self):
        self.text.delete("1.0", "end")
        self.count_text()

    def insert_pause(self, seconds=None):
        if seconds is None:
            try:
                seconds = float(self.pause_duration.get())
                if not 0.1 <= seconds <= 10:
                    raise ValueError()
            except ValueError:
                self.show_notice("停顿时长", "请输入 0.1 至 10 秒，例如 0.8。", parent=self)
                return
        marker = f"【停顿{seconds:g}秒】"
        if len(self.text.get("1.0", "end-1c")) + len(marker) > 5000:
            self.show_notice("文稿过长", "插入后超过 5000 个字符，请先缩短文稿。", parent=self)
            return
        self.text.insert("insert", marker)
        self.text.see("insert")
        self.text.focus_set()
        self.count_text()
        self.status.configure(text=f"已插入 {seconds:g} 秒停顿 · 可删除标记取消", text_color=MUTED)

    def speed_changed(self, value):
        self.speed_value.configure(text=f"{value:.1f}×")

    def volume_changed(self, value):
        self.volume_value.configure(text=f"{value:.0f}%")

    def pitch_changed(self, value):
        self.pitch_value.configure(text=f"{round(value):+d} Hz")

    def worker(self, task, operation):
        async def execute():
            loop = asyncio.get_running_loop()
            with self.worker_lock:
                self.worker_tasks[loop] = asyncio.current_task()
                if task == "audio":
                    self.audio_worker = (loop, asyncio.current_task())
            try:
                if self.closing.is_set():
                    return
                result = await operation()
                if not self.closing.is_set():
                    self.events.put((task, result, None))
            finally:
                with self.worker_lock:
                    self.worker_tasks.pop(loop, None)
                    if task == "audio":
                        self.audio_worker = None
        def run():
            try:
                asyncio.run(execute())
            except asyncio.CancelledError:
                if task == "audio" and not self.closing.is_set():
                    self.events.put((task, None, asyncio.CancelledError()))
            except Exception as error:
                if not self.closing.is_set():
                    self.events.put((task, None, error))
        thread = threading.Thread(target=run, daemon=True)
        with self.worker_lock:
            self.worker_threads = [item for item in self.worker_threads if item.is_alive()]
            self.worker_threads.append(thread)
        thread.start()

    def refresh_voices(self):
        if self.refreshing:
            return
        self.refreshing = True
        if not self.busy:
            self.status.configure(text="正在获取在线音色列表…", text_color=MUTED)
        self.worker("voices", fetch_voices)

    def open_tasks(self):
        self.show_page("tasks")

    def open_dictionary(self):
        try:
            window = getattr(self, "dictionary_window", None)
            if window is not None and window.winfo_exists():
                show_editor(window, self)
                return
            self.dictionary_window = DictionaryWindow(self)
        except (OSError, ValueError) as error:
            self.show_error("词典无法打开", str(error), parent=self)

    def use_task_audio(self, path, name):
        self.stop_audio()
        self.latest, self.latest_name = path, name
        self.update_selected_label()
        self.save_btn.configure(state="normal", fg_color=BLUE)
        self.play_btn.configure(state="normal", fg_color=BLUE)
        self.update_subtitle_button()
        self.play_audio()

    def run_saved_task(self, task, only=None):
        if self.busy:
            return False
        self.generate(saved_task=task, only=only)
        return self.busy

    def generate(self, preview=False, voice_sample=False, saved_task=None, only=None):
        if self.busy:
            return
        task_page = getattr(self, "task_page", None)
        if task_page is not None and not task_page.save_edit():
            return
        if saved_task is None and self.selected not in self.voice_rows:
            self.show_notice("选择音色", "请先选择一个有音色的分类。", parent=self)
            return
        text = ("".join(s["text"] for s in saved_task["segments"]) if saved_task
                else self.text.get("1.0", "end-1c").strip())
        voice = next((v for v in self.voices if v["ShortName"] == self.selected), None)
        name = saved_task["name"] if saved_task else voice_name(voice)
        if preview:
            # A two-word sample cannot show pauses or speaking rate, so audition
            # with a full sentence: that is what people actually judge a voice by.
            sample = ("这是一段试听文本，你可以听一下是否合适"
                      if voice["Locale"].startswith("zh")
                      else "Hello, this is a short sample so you can hear how the voice sounds.")
            if voice_sample or not text:
                text = sample
            else:
                end = next((match.end() for match in PAUSE.finditer(text)
                            if match.start() < 100 < match.end()), 100)
                text = text[:end]
        if not text or len(text) > 5000:
            self.show_notice("输入文本", "请输入 1 至 5000 个字符。", parent=self)
            return
        if "【停顿" in text:
            try:
                split_pauses(text)
            except ValueError as error:
                self.show_notice("检查停顿标记", str(error), parent=self)
                return
        self.stop_audio()
        speed, volume, short = ((saved_task["speed"], saved_task["volume"], saved_task["voice"])
                                if saved_task else (self.speed.get(), self.volume.get(), self.selected))
        pitch = saved_task["pitch"] if saved_task else (0 if short.startswith("local:") else round(self.pitch.get()))
        try:
            lexicon = saved_task["lexicon"] if saved_task else ({} if voice_sample else load_pronunciation(self.pronunciation_path))
            if not preview and saved_task is None:
                task = self.task_store.load(self.workbench_task_id) if self.workbench_task_id else None
                if task and (task["voice"], task["speed"], task["volume"], task["pitch"], task["lexicon"]) == (short, speed, volume, pitch, lexicon):
                    self.task_store.set_script(task, text)
                else:
                    task = self.task_store.create(text, short, name, speed, volume, pitch, lexicon)
                saved_task = task
                self.workbench_task_id = task["id"]
            if saved_task:
                self.current_task_id = saved_task["id"]
                if task_page is not None and task_page.task is not saved_task:
                    task_page.refresh(preferred_id=saved_task["id"])
        except (OSError, ValueError) as error:
            self.show_error("任务未保存", str(error), parent=self)
            return
        cache_key = (short, text, speed, volume, pitch)
        if lexicon:
            cache_key += (json.dumps(lexicon, sort_keys=True, ensure_ascii=False),)
        if short.startswith("local:qwen3_q8:"):
            cache_key += ("trim-reference-v1",)
        persistent = None
        if preview and voice_sample and short.startswith("local:"):
            digest = hashlib.sha256(json.dumps(cache_key, ensure_ascii=False).encode("utf-8")).hexdigest()
            persistent = clone_preview_folder(short) / f"{digest}.mp3"
            if persistent.is_file():
                self.preview_cache[cache_key] = persistent
        if preview and voice_sample and (speed, volume, pitch) == (1, 100, 0):
            bundled = ROOT / "voice_samples" / f"{short}.mp3"
            if voice["Locale"].startswith("zh") and bundled.is_file():
                self.preview_cache[cache_key] = bundled
        if preview and cache_key in self.preview_cache and self.preview_cache[cache_key].is_file():
            self.latest, self.latest_name = self.preview_cache[cache_key], name
            self.update_selected_label()
            self.save_btn.configure(state="normal", fg_color=BLUE)
            self.play_btn.configure(state="normal", fg_color=BLUE)
            self.status.configure(text="", text_color=MUTED)
            self.set_generation_state("配音已生成", f"{name} · 可以试听或下载")
            self.update_subtitle_button()
            self.trim_audio_cache()
            self.play_audio()
            return
        self.busy = True
        if task_page is not None:
            task_page.set_busy(preview=preview)
        self.generation_cancel = threading.Event()
        self.update_model_ui()
        for button in (self.preview_btn, self.provider_menu, self.locale,
                       *self.filter_buttons.values()):
            button.configure(state="disabled")
        self.generate_btn.configure(text="停止生成", command=self.stop_generation,
                                    state="normal", fg_color=BLUE_SOFT, text_color=BLUE_DARK,
                                    hover_color=PALE,
                                    text_color_disabled=BLUE_DARK,
                                    border_width=1, border_color=BLUE_LINE,
                                    image=self.generation_spinner[0])
        self.generate_started = time.time()
        self.generate_animation_started = time.monotonic()
        self.generate_name = name
        self.generate_segment = only
        self.generate_kind = "试听" if preview else "完整配音"
        self.progress_percent = -1
        self.set_generation_state("正在生成配音", f"{name} · 正在准备语音合成")
        self.status.configure(text="", text_color=MUTED)
        target = Path(self.temp.name) / (uuid.uuid4().hex + ".mp3")
        if persistent is not None:
            try:
                persistent.parent.mkdir(parents=True, exist_ok=True)
                target = persistent
            except OSError:
                pass  # A read-only cache must not prevent auditioning.
        def on_stage(message):
            self.events.put(("audio_stage", f"{message} · {name}", None))
        def on_progress(fraction):
            self.events.put(("audio_progress", fraction, None))
        async def operation():
            if self.generation_cancel.is_set():
                raise asyncio.CancelledError()
            if saved_task:
                path = await render_task(self.task_store, saved_task, on_stage, on_progress,
                                         self.generation_cancel, only=only)
            else:
                path = await synthesize(text, short, speed, volume, target,
                                        on_stage=on_stage, on_progress=on_progress, cancel=self.generation_cancel,
                                        pitch=pitch, lexicon=lexicon)
            if preview:
                self.preview_cache[cache_key] = path
            return path, name, preview
        self.worker("audio", operation)

    def stop_generation(self):
        if not self.busy or self.generation_cancel.is_set():
            return
        self.generation_cancel.set()
        self.generate_btn.configure(text="正在停止…", state="disabled")
        self.set_generation_state("正在停止生成", "正在结束当前任务，请稍候")
        with self.worker_lock:
            if self.audio_worker is not None:
                loop, task = self.audio_worker
                if not loop.is_closed():
                    loop.call_soon_threadsafe(task.cancel)

    def set_generation_state(self, title, detail, percent=""):
        self.generation_title.configure(text=title)
        self.generation_detail.configure(text=detail)
        self.generation_percent.configure(text=percent)
        if not self.busy:
            for bar, height in zip(self.generation_bars, (6, 12, 18, 12, 6)):
                bar.configure(height=height, fg_color="#22835B" if title == "配音已生成" else "#8492AB")

    def animate_generation(self):
        if not self.busy or not self.winfo_viewable():
            return
        # A small state indicator, independent of the real completion percentage.
        phase = (time.monotonic() - self.generate_animation_started) * 5
        frame = int((time.monotonic() - self.generate_animation_started) * 18) % len(self.generation_spinner)
        self.generate_btn.configure(image=self.generation_spinner[frame])
        for index, bar in enumerate(self.generation_bars):
            height = 6 + 18 * (0.5 + 0.5 * math.sin(phase - index * 0.8))
            bar.configure(height=height, fg_color=BLUE)

    def show_progress(self, fraction):
        """Only synthesis callbacks may update the completion percentage."""
        percent = int(min(max(fraction, 0), 0.99) * 100)
        if percent == self.progress_percent:
            return
        self.progress_percent = percent
        self.generation_percent.configure(text=f"{percent}%")

    def poll(self):
        if self.closing.is_set():
            return
        try:
            while True:
                task, result, error = self.events.get_nowait()
                if task == "warmup":
                    continue
                elif task in ("clone_read", "clone_save"):
                    if error:
                        self.show_error("克隆失败", str(error), parent=self)
                    else:
                        self.finish_clone_event(task, result)
                elif task == "audio_stage":
                    if self.busy and not self.generation_cancel.is_set():
                        self.generation_detail.configure(text=result)
                        task_page = getattr(self, "task_page", None)
                        if task_page is not None and self.generate_kind != "试听":
                            task_page.info.configure(text=result)
                elif task == "audio_progress":
                    if self.busy and not self.generation_cancel.is_set():
                        self.show_progress(result)
                elif task == "download_progress":
                    done, total = result
                    fraction = min(done / total, 1) if total else 0
                    text = (f"下载中 {fraction:.0%} · " if total else "下载中 · ") + f"{done / 1000000:.1f} MB" + (f" / {total / 1000000:.1f} MB" if total else "")
                    self.download_state[self.download_key] = {"text": text, "fraction": fraction}
                    self.update_model_ui()
                elif task == "download_stage":
                    previous = self.download_state.get(self.download_key, {})
                    self.download_state[self.download_key] = {
                        "text": result, "fraction": previous.get("fraction", 0)}
                    self.update_model_ui()
                elif task == "model_removed":
                    self.installing = False
                    self.deleting_model = None
                    self.model_page.cards[result]["progress"].stop()
                    if error:
                        self.update_model_ui()
                        self.show_error("删除失败", str(error), parent=self)
                    else:
                        self.download_state.pop(result, None)
                        self.reload_voice_catalog()
                        self.update_locales()
                        self.render_voices()
                        self.update_model_ui()
                        self.model_page.cards[result]["status"].configure(text="模型已删除 · 已释放模型磁盘空间")
                        self.show_delete_confirmation(self, "删除成功", "模型已删除，已释放磁盘空间。",
                            "个人音色和参考录音已保留。", "知道了", lambda: None, success=True)
                elif task == "model":
                    self.installing = False
                    if isinstance(error, DownloadCancelled):
                        self.download_state[self.download_key] = {"text": "下载已取消，可重新下载"}
                    elif error:
                        self.download_state[self.download_key] = {"text": "下载失败，请检查网络后重试。\n" + str(error)[:160], "error": True}
                    else:
                        self.preview_cache.clear()
                        self.download_state[result] = {"text": "安装完成，可离线使用", "fraction": 1}
                        if self.provider != "edge":
                            self.reload_voice_catalog()
                            self.update_locales()
                            self.render_voices()
                        self.status.configure(text="音色包装好了 · 选择音色即可离线合成", text_color=BLUE)
                    self.update_model_ui()
                elif task == "voices":
                    self.refreshing = False
                    if error:
                        if not self.busy:
                            self.status.configure(text="音色刷新失败，保留已有列表。下次启动时自动重试。", text_color="#D14A64")
                    else:
                        self.online_voices = result
                        self.reload_voice_catalog()
                        try:
                            DATA.mkdir(parents=True, exist_ok=True)
                            (DATA / "voices.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
                        except OSError:
                            pass
                        self.update_locales()
                        self.render_voices()
                        if not self.busy:
                            self.status.configure(text=f"音色已更新 · 共 {len(result)} 个", text_color=BLUE)
                else:
                    self.busy = False
                    self.progress_percent = -1

                    self.preview_btn.configure(state="normal")
                    self.generate_btn.configure(state="normal", text="生成配音",
                                                command=self.generate, text_color="white",
                                                fg_color=BLUE, hover_color=BLUE_DARK, border_width=0,
                                                text_color_disabled=SUBTLE, image=None)
                    for control in (self.provider_menu, self.locale, *self.filter_buttons.values()):
                        control.configure(state="normal")
                    self.update_selected_label()
                    self.update_model_ui()
                    task_page = getattr(self, "task_page", None)
                    if task_page is not None:
                        task_page.finished()
                    if isinstance(error, asyncio.CancelledError) or self.generation_cancel.is_set():
                        self.set_generation_state("已停止生成", "可以修改文稿或重新生成")
                    elif error:
                        self.set_generation_state("生成失败", "请检查错误说明后重试")
                        self.show_error("配音未完成", ("离线配音未完成。\n\n" if self.selected.startswith("local:") else "请检查网络后重试。\n\n")
                            + (str(error)[:350] or type(error).__name__), parent=self)
                    else:
                        segment = getattr(self, "generate_segment", None)
                        if segment is not None and task_page is not None:
                            self.set_generation_state("分段已生成", f"第 {segment + 1} 段 · 正在试听")
                            task_page.listen_segment()
                            continue
                        if result[0] is None:
                            self.set_generation_state("分段已更新", "其他分段待生成，可在任务中继续")
                            continue
                        self.latest, self.latest_name, preview = result
                        self.update_selected_label()
                        self.set_generation_state("配音已生成", f"{self.latest_name} · 可以试听或下载")
                        self.trim_audio_cache()
                        self.save_btn.configure(state="normal", fg_color=BLUE)
                        self.play_btn.configure(state="normal", fg_color=BLUE)
                        self.update_subtitle_button()
                        self.play_audio()
        except queue.Empty:
            pass
        self.animate_generation()
        self.update_playback()
        self.after(100, self.poll)

    def stop_audio(self):
        if self.audio_ready:
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()
        self.audio_paused = False
        self.audio_offset = 0.0
        self.audio_duration = 0.0
        self.seek_slider.set(0)
        self.seek_slider.configure(state="disabled")
        self.time_label.configure(text="00:00 / 00:00")
        self.set_play_action("播放")

    def play_audio(self):
        try:
            if not self.audio_ready:
                try:
                    # Every file we play comes out of edge-tts or ZipVoice at
                    # 24 kHz mono, so opening the device at that rate skips a
                    # resampling stage that only ever loses detail.
                    pygame.mixer.init(frequency=24000, size=-16, channels=2, buffer=1024)
                except pygame.error:
                    pygame.mixer.init()
                self.audio_ready = True
            pygame.mixer.music.load(str(self.latest))
            self.audio_duration = miniaudio.get_file_info(str(self.latest)).duration
            self.audio_offset = 0.0
            self.audio_paused = False
            self.seek_slider.configure(state="normal", to=max(self.audio_duration, 0.001))
            self.seek_slider.set(0)
            pygame.mixer.music.play()
            self.set_play_action("暂停")
            self.update_playback()
        except (pygame.error, miniaudio.MiniaudioError, OSError):
            self.stop_audio()
            self.status.configure(text="无法播放音频，请检查音频文件或播放设备；仍可保存 MP3。", text_color="#D14A64")

    def set_play_action(self, action):
        self.playback_action = action
        self.play_btn.configure(image=self.play_icons[action])

    @staticmethod
    def audio_time(seconds):
        minutes, seconds = divmod(max(0, int(seconds)), 60)
        return f"{minutes:02d}:{seconds:02d}"

    def update_playback(self):
        if not self.audio_ready or not self.audio_duration:
            return
        if self.audio_paused:
            position = self.audio_offset
        elif pygame.mixer.music.get_busy():
            position = self.audio_offset + max(0, pygame.mixer.music.get_pos()) / 1000
        else:
            position = self.audio_duration
            self.set_play_action("播放")
        position = min(position, self.audio_duration)
        self.seek_slider.set(position)
        self.time_label.configure(text=f"{self.audio_time(position)} / {self.audio_time(self.audio_duration)}")

    def seek_audio(self, seconds):
        if not self.audio_ready or not self.latest:
            return
        # Restarting at an absolute offset also works after playback has ended.
        position = min(float(seconds), max(0, self.audio_duration - 0.01))
        try:
            pygame.mixer.music.play(start=position)
            self.audio_offset = position
            if self.audio_paused:
                pygame.mixer.music.pause()
            self.set_play_action("播放" if self.audio_paused else "暂停")
            self.update_playback()
        except pygame.error:
            self.status.configure(text="无法跳转到该位置，请重新播放。", text_color="#D14A64")

    def toggle_play(self):
        if self.audio_ready and self.audio_paused:
            pygame.mixer.music.play(start=self.audio_offset)
            self.audio_paused = False
            self.set_play_action("暂停")
        elif self.audio_ready and pygame.mixer.music.get_busy():
            self.audio_offset += max(0, pygame.mixer.music.get_pos()) / 1000
            pygame.mixer.music.pause()
            self.audio_paused = True
            self.set_play_action("播放")
        elif self.latest:
            self.play_audio()

    def update_subtitle_button(self):
        available = self.latest and Path(self.latest).with_suffix(".srt").is_file()
        self.subtitle_btn.configure(state="normal" if available else "disabled")

    def save_subtitles(self):
        if not self.latest:
            return
        source = Path(self.latest).with_suffix(".srt")
        if not source.is_file():
            return
        destination = filedialog.asksaveasfilename(parent=self, title="下载 SRT 字幕", defaultextension=".srt",
            initialfile=f"{self.latest_name}_{datetime.now():%Y%m%d_%H%M%S}.srt",
            filetypes=[("SRT 字幕", "*.srt")])
        if destination:
            try:
                shutil.copyfile(source, destination)
                self.status.configure(text=f"字幕已保存：{destination}", text_color=BLUE)
            except OSError as error:
                self.show_error("字幕保存失败", str(error), parent=self)

    def save_audio(self):
        if not self.latest or self.closing.is_set():
            return
        source, name = Path(self.latest), self.latest_name
        self.status.configure(text="请选择音频保存位置", text_color=MUTED)
        destination = filedialog.asksaveasfilename(parent=self, title="保存配音", defaultextension=".mp3",
            initialfile=f"{name}_{datetime.now():%Y%m%d_%H%M%S}.mp3",
            filetypes=[("MP3 音频", "*.mp3")])
        if destination:
            try:
                shutil.copyfile(source, destination)
                self.status.configure(text=f"已保存：{destination}", text_color=BLUE)
            except OSError as error:
                self.status.configure(text="音频保存失败 · 请重试", text_color=MUTED)
                self.show_error("保存失败", str(error), parent=self)
        else:
            self.status.configure(text="已取消下载 · 音频已保留", text_color=MUTED)

    def trim_audio_cache(self):
        # Keep at most 20 auditions / 64 MB, plus the current playable result.
        while self.preview_cache and (len(self.preview_cache) > 20 or
                sum(path.stat().st_size for path in self.preview_cache.values() if path.is_file()) > 64 * 1024 * 1024):
            self.preview_cache.pop(next(iter(self.preview_cache)))
        retained = set(self.preview_cache.values()) | {self.latest}
        for path in Path(self.temp.name).glob("*.mp3"):
            if path not in retained:
                try:
                    path.unlink(missing_ok=True)
                    path.with_suffix(".srt").unlink(missing_ok=True)
                except OSError:
                    pass
        trim_clone_previews(DATA, (self.latest,))
        if getattr(self, "current_task_id", None) and not self.busy:
            try:
                self.task_store.prune(self.task_store.load(self.current_task_id),
                    (self.latest,))
            except OSError:
                pass

    def close(self):
        task_page = getattr(self, "task_page", None)
        if task_page is not None and not self.busy and not task_page.save_edit():
            return
        self.closing.set()
        self.generation_cancel.set()
        self.download_cancel.set()
        with self.worker_lock:
            threads = list(self.worker_threads)
            for loop, task in self.worker_tasks.items():
                if not loop.is_closed():
                    loop.call_soon_threadsafe(task.cancel)
        self.stop_audio()
        if self.audio_ready:
            pygame.mixer.quit()
        def cleanup():
            for thread in threads:
                thread.join()
            self.temp.cleanup()
        if any(thread.is_alive() for thread in threads):
            # Native inference finishes its current chunk before files can be removed.
            threading.Thread(target=cleanup, daemon=False).start()
        else:
            cleanup()
        for callback in self.tk.call("after", "info"):
            # Each widget owns its registered Tcl command and deletes it on
            # destruction; cancel the timer without deleting another widget's command.
            self.tk.call("after", "cancel", callback)
        self.destroy()
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.DestroyIcon.argtypes = [ctypes.c_void_p]
            for icon in self._native_icons:
                ctypes.windll.user32.DestroyIcon(icon)


if __name__ == "__main__":
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(ctypes.c_wchar_p("FreeVoice.Desktop"))
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")
    if len(sys.argv) == 3 and sys.argv[1] == "--smoke-test":
        from smoke_test import run
        run(App, Path(sys.argv[2]))
    elif len(sys.argv) == 3 and sys.argv[1] == "--offline-smoke-test":
        from smoke_test import run_offline
        run_offline(App, Path(sys.argv[2]))
    else:
        window = App()
        window.mainloop()
