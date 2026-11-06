"""Synthesis routing shared by the desktop UI and smoke tests."""
import asyncio
import re
from pathlib import Path

import edge_tts

from subtitles import online_cues, write_srt

# Characters the service actually pronounces. Punctuation and spaces never reach
# the audio, so counting them would leave the progress bar stuck below 100%.
SPEAKABLE = re.compile(r"[0-9A-Za-z\u3400-\u9fff\uf900-\ufaff]+")


def speakable_length(text):
    return sum(len(match.group()) for match in SPEAKABLE.finditer(text)) or len(text.strip())


async def synthesize(text, voice, speed, volume, target, on_stage=None, on_progress=None, cancel=None, pitch=0, lexicon=None):
    if not text.strip() or len(text) > 5000:
        raise ValueError("请输入 1 至 5000 个字符。")
    from pronunciation import apply, load
    if lexicon is None:
        from offline import DATA
        lexicon = load(DATA / "pronunciation.json")
    spoken = apply(text, lexicon)
    result = await _synthesize(spoken, voice, speed, volume, target, on_stage, on_progress, cancel, pitch)
    if spoken != text:
        from pauses import PAUSE, read_cues
        cues = read_cues(result)
        if cues:
            write_srt(result, [(cues[0][0], cues[-1][1], PAUSE.sub(" ", text))])
    return result


async def _synthesize(text, voice, speed, volume, target, on_stage=None, on_progress=None, cancel=None, pitch=0):
    if not text.strip():
        raise ValueError("请输入要配音的文字")
    if len(text) > 5000:
        raise ValueError("每次最多输入 5000 个字符，请分段生成")
    if "【停顿" in text:
        from pauses import split_pauses, synthesize_pauses
        pieces = split_pauses(text)

        async def render(piece, path):
            return await _synthesize(piece, voice, speed, volume, path,
                                    on_stage=on_stage, cancel=cancel, pitch=pitch)

        return await synthesize_pauses(pieces, target, render, on_stage, on_progress, cancel,
                                       lossless=voice.startswith("local:"))
    if voice.startswith("local:"):
        from offline import synthesize_local
        return await synthesize_local(text, voice, speed, volume, target,
                                      on_stage=on_stage, on_progress=on_progress, cancel=cancel)
    target = Path(target)
    partial = target.with_suffix(".part")
    total = speakable_length(text)
    state = {"spoken": 0, "reported": -1}
    boundaries = []

    def advance(piece):
        state["spoken"] += len(piece)
        if on_progress is None or not total:
            return
        # Word boundaries arrive many times per second; repaint only when the
        # visible percentage changes, and never reach 100% before the audio does.
        step = int(min(state["spoken"] / total, 0.99) * 100)
        if step > state["reported"]:
            state["reported"] = step
            on_progress(step / 100)

    try:
        rate = f"{round((speed - 1) * 100):+d}%"
        gain = f"{round(volume - 100):+d}%"
        if on_stage:
            on_stage("正在连接语音服务")
        # Word boundaries rather than sentence boundaries: the same audio, but a
        # progress signal that moves instead of jumping in five big steps.
        communicate = edge_tts.Communicate(text, voice, rate=rate, volume=gain,
                                           pitch=f"{round(pitch):+d}Hz", boundary="WordBoundary")

        async def download():
            with partial.open("wb") as output:
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        output.write(chunk["data"])
                    elif chunk.get("text"):
                        advance(chunk["text"])
                        if chunk["type"] == "WordBoundary" and "offset" in chunk and "duration" in chunk:
                            start = chunk["offset"] / 10000000
                            boundaries.append((start, start + chunk["duration"] / 10000000, chunk["text"]))

        await asyncio.wait_for(download(), timeout=180)
        if not partial.exists() or partial.stat().st_size == 0:
            raise RuntimeError("服务未返回音频，请稍后重试")
        partial.replace(target)
        write_srt(target, online_cues(text, boundaries))
        return target
    finally:
        partial.unlink(missing_ok=True)


async def fetch_voices():
    return await asyncio.wait_for(edge_tts.list_voices(), timeout=25)
