"""Durable local dubbing tasks with independently replaceable audio segments."""
import asyncio
from collections import defaultdict, deque
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import tempfile
import uuid
import wave

from pauses import PAUSE, read_cues, split_pauses
from pronunciation import apply, validate
from segmentation import sentence_segments, missing_pause, prepare_join
from subtitles import write_srt

PIPELINE = 1


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


class TaskStore:
    def __init__(self, root):
        self.root = Path(root)

    def folder(self, ident):
        if not re.fullmatch(r"[0-9a-f]{32}", ident):
            raise ValueError("无效的任务编号。")
        return self.root / ident

    def save(self, task):
        folder = self.folder(task["id"])
        folder.mkdir(parents=True, exist_ok=True)
        task["updated"] = datetime.now().isoformat(timespec="seconds")
        partial = folder / "task.tmp"
        partial.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
        partial.replace(folder / "task.json")

    def load(self, ident):
        task = json.loads((self.folder(ident) / "task.json").read_text(encoding="utf-8"))
        if not isinstance(task, dict) or task.get("id") != ident or task.get("version") != 1:
            raise ValueError("任务文件版本或编号不正确。")
        if not all(isinstance(task.get(key), str) for key in ("name", "voice", "updated", "status")):
            raise ValueError("任务基本信息不完整。")
        if not all(type(task.get(key)) in (int, float) for key in ("speed", "volume", "pitch")):
            raise ValueError("任务配音参数不正确。")
        validate(task.get("lexicon"))
        if task["status"] not in ("draft", "running", "stopped", "failed", "complete"):
            raise ValueError("任务状态不正确。")
        if not isinstance(task.get("segments"), list) or not task["segments"]:
            raise ValueError("任务缺少有效分段。")
        for segment in task["segments"]:
            if not isinstance(segment, dict) or not isinstance(segment.get("id"), str) or not re.fullmatch(r"[0-9a-f]{32}", segment["id"]):
                raise ValueError("任务分段编号不正确。")
            if not isinstance(segment.get("text"), str) or segment.get("status") not in ("pending", "running", "done"):
                raise ValueError("任务分段内容或状态不正确。")
        self.output(task)
        return task

    def list(self):
        items = []
        for path in self.root.glob("*/task.json"):
            try:
                items.append(self.load(path.parent.name))
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return sorted(items, key=lambda task: task["updated"], reverse=True)

    def create(self, text, voice, name, speed, volume, pitch=0, lexicon=None):
        task = dict(version=1, id=uuid.uuid4().hex, name=name, voice=voice,
                    speed=speed, volume=volume, pitch=pitch, lexicon=validate(lexicon or {}),
                    segments=[], status="draft", error="")
        self.set_script(task, text)
        return task

    def set_script(self, task, text):
        if not text.strip() or len(text) > 5000:
            raise ValueError("文稿须为 1–5000 个字符。")
        split_pauses(text)
        pieces, cursor = [], 0
        limit = 60 if task["voice"].startswith("local:qwen3_q8:") else 240
        for match in PAUSE.finditer(text):
            pieces.extend(sentence_segments(text[cursor:match.start()], limit))
            pieces.append(match[0])
            cursor = match.end()
        pieces.extend(sentence_segments(text[cursor:], limit))
        previous = defaultdict(deque)
        for item in task["segments"]:
            previous[item["text"]].append(item)
        task["segments"] = [previous[piece].popleft() if previous[piece] else
                            dict(id=uuid.uuid4().hex, text=piece, signature="", status="pending")
                            for piece in pieces]
        task.update(status="draft", error="")
        self.save(task)

    def edit(self, task, index, text):
        if not text.strip():
            raise ValueError("分段不能为空。")
        script = "".join(text if i == index else s["text"] for i, s in enumerate(task["segments"]))
        if len(script) > 5000:
            raise ValueError("任务文稿最多 5000 个字符。")
        split_pauses(script)
        segment = task["segments"][index]
        if segment["text"] != text:
            updated = dict(task, segments=list(task["segments"]), status="draft", error="")
            updated["segments"][index] = dict(segment, text=text, signature="", status="pending")
            self.save(updated)
            task.update(updated)

    def output(self, task):
        name = task.get("output", "result.mp3")
        if not re.fullmatch(r"result(?:-[0-9a-f]{32})?\.mp3", name):
            raise ValueError("任务音频文件名不正确。")
        return self.folder(task["id"]) / name

    def prune(self, task, protected=()):
        """Only remove this task's obsolete generated files; keep its plan/audio."""
        folder = self.folder(task["id"])
        keep = {Path(path) for path in protected if path is not None}
        keep.add(self.output(task))
        active = {s["id"] + ".wav" for s in task["segments"]}
        for path in folder.iterdir():
            obsolete = (re.fullmatch(r"[0-9a-f]{32}\.wav", path.name) and path.name not in active) or \
                       (re.fullmatch(r"result-[0-9a-f]{32}\.mp3", path.name) and path not in keep)
            if obsolete and path.is_file():
                path.unlink(missing_ok=True)
                path.with_suffix(".srt").unlink(missing_ok=True)


def voice_identity(voice):
    if not voice.startswith("local:"):
        return voice
    if voice.startswith("local:qwen3_q8:clone:"):
        from offline import clones
        item = next((item for item in clones() if item["id"] == voice.rsplit(":", 1)[-1]), None)
        if item is None:
            raise ValueError("任务使用的克隆音色已删除，请重新添加音色后创建任务。")
        return [voice, hashlib.sha256(Path(item["wav"]).read_bytes()).hexdigest()]
    from offline import reference_for
    transcript, samples, rate = reference_for(voice)
    return [voice, transcript, rate, hashlib.sha256(samples.tobytes()).hexdigest()]


def segment_signature(task, segment, reference):
    return digest([PIPELINE, task["voice"], reference, task["speed"], task["volume"],
                   task["pitch"], apply(segment["text"], task["lexicon"])])


def playable(path):
    try:
        with wave.open(str(path), "rb") as source:
            frames = source.getnframes()
            return (source.getnchannels() == 1 and source.getsampwidth() == 2
                    and source.getframerate() == 24000 and frames > 0
                    and len(source.readframes(frames)) == frames * 2)
    except (OSError, EOFError, wave.Error):
        return False


async def render_task(store, task, on_stage=None, on_progress=None, cancel=None, only=None, render=None):
    import miniaudio
    import numpy as np
    from audio_output import audio_output
    from engine import synthesize
    from offline import _check_cancel
    render = render or synthesize
    folder = store.folder(task["id"])
    task.update(status="running", error="")
    store.save(task)
    try:
        reference = await asyncio.to_thread(voice_identity, task["voice"])
        for index, segment in enumerate(task["segments"]):
            _check_cancel(cancel)
            signature = segment_signature(task, segment, reference)
            path = folder / (segment["id"] + ".wav")
            valid = signature == segment.get("signature") and playable(path)
            if (only is None or only == index) and (not valid or only == index):
                segment["status"] = "running"
                store.save(task)
                if on_stage:
                    on_stage(f"正在生成第 {index + 1} 段，共 {len(task['segments'])} 段")
                with tempfile.TemporaryDirectory(prefix="render-", dir=folder) as temp:
                    work = Path(temp) / ("piece.wav" if task["voice"].startswith("local:") else "piece.mp3")
                    spoken = apply(segment["text"], task["lexicon"])
                    pause = PAUSE.fullmatch(spoken)
                    if pause:
                        pcm = bytes(round(float(pause[1]) * 24000) * 2)
                        cues = []
                    elif not spoken.strip():
                        pcm, cues = bytes(240), []
                    else:
                        await render(spoken, task["voice"], task["speed"], task["volume"], work,
                                     cancel=cancel, pitch=task["pitch"], lexicon={})
                        decoded = miniaudio.decode(work.read_bytes(), output_format=miniaudio.SampleFormat.SIGNED16,
                                                   nchannels=1, sample_rate=24000)
                        pcm, cues = decoded.samples.tobytes(), read_cues(work)
                        if task["voice"].startswith("local:qwen3_q8:") and len(task["segments"]) > 1 and "【停顿" not in spoken:
                            samples, offset = prepare_join(np.frombuffer(pcm, dtype="<i2") / 32768, 24000, with_offset=True)
                            pcm = np.clip(samples * 32768, -32768, 32767).astype("<i2").tobytes()
                            duration = len(pcm) / 48000
                            cues = [(max(0, start - offset), min(duration, end - offset), caption)
                                    for start, end, caption in cues if min(duration, end - offset) > max(0, start - offset)]
                        if spoken != segment["text"]:
                            # Source captions stay unchanged; substitutions make word timings approximate.
                            source = [part for part in split_pauses(segment["text"]) if isinstance(part, str)]
                            source = " ".join(source)
                            cues = [(0, len(pcm) / 48000, source)]
                    _check_cancel(cancel)
                    ready = Path(temp) / "ready.wav"
                    with audio_output(ready, 24000, pcm=True) as write:
                        write(pcm)
                    if not playable(ready):
                        raise RuntimeError("这段未返回有效音频，请重试。")
                    ready.replace(path)
                segment.update(signature=signature, status="done", cues=cues)
                store.save(task)
            if on_progress:
                on_progress((index + 1) / len(task["segments"]) * .98)
        _check_cancel(cancel)
        complete = all(s.get("signature") == segment_signature(task, s, reference)
                       and playable(folder / (s["id"] + ".wav")) for s in task["segments"])
        if not complete:
            task["status"] = "draft"
            store.save(task)
            return None
        target = folder / ("result-" + uuid.uuid4().hex + ".mp3")
        with tempfile.TemporaryDirectory(prefix="assemble-", dir=folder) as temp:
            ready = Path(temp) / "result.mp3"
            cues, elapsed = [], 0.
            with audio_output(ready, 24000) as write:
                for index, segment in enumerate(task["segments"]):
                    _check_cancel(cancel)
                    with wave.open(str(folder / (segment["id"] + ".wav")), "rb") as source:
                        pcm = source.readframes(source.getnframes())
                    write(pcm)
                    cues.extend((start + elapsed, end + elapsed, caption)
                                for start, end, caption in segment.get("cues", []))
                    elapsed += len(pcm) / 48000
                    if index + 1 < len(task["segments"]) and not PAUSE.fullmatch(segment["text"]) \
                            and not PAUSE.fullmatch(task["segments"][index + 1]["text"]):
                        gap = missing_pause(np.frombuffer(pcm, dtype="<i2") / 32768, 24000, segment["text"])
                        write(bytes(gap * 2))
                        elapsed += gap / 24000
            _check_cancel(cancel)
            write_srt(ready, cues)
            ready.replace(target)
            if ready.with_suffix(".srt").exists():
                ready.with_suffix(".srt").replace(target.with_suffix(".srt"))
            else:
                target.with_suffix(".srt").unlink(missing_ok=True)
        task.update(status="complete", error="", output=target.name)
        store.save(task)
        return target
    except BaseException as error:
        task.update(status="stopped" if isinstance(error, asyncio.CancelledError) else "failed",
                    error="" if isinstance(error, asyncio.CancelledError) else str(error)[:500])
        for segment in task["segments"]:
            if segment["status"] == "running":
                segment["status"] = "pending"
        store.save(task)
        raise
