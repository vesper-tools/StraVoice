"""Explicit pauses shared by online and local synthesis."""
import asyncio
import re
import tempfile
from pathlib import Path

from subtitles import write_srt

PAUSE = re.compile(r"【停顿([0-9]+(?:\.[0-9]+)?)秒】")


def split_pauses(text):
    pieces = []
    cursor = 0
    matches = list(PAUSE.finditer(text))
    if text.count("【停顿") != len(matches):
        raise ValueError("停顿格式应为【停顿0.5秒】，时长为 0.1 至 10 秒。")
    if len(matches) > 100:
        raise ValueError("每次最多插入 100 处停顿。")
    for match in matches:
        seconds = float(match[1])
        if not 0.1 <= seconds <= 10:
            raise ValueError("停顿时长须为 0.1 至 10 秒。")
        if text[cursor:match.start()].strip():
            pieces.append(text[cursor:match.start()].strip())
        pieces.append(seconds)
        cursor = match.end()
    if text[cursor:].strip():
        pieces.append(text[cursor:].strip())
    if not any(isinstance(piece, str) for piece in pieces):
        raise ValueError("请输入要配音的文字，不能只有停顿。")
    return pieces


def read_cues(path):
    path = Path(path).with_suffix(".srt")
    if not path.exists():
        return []
    cues = []
    for block in path.read_text(encoding="utf-8-sig").strip().split("\n\n"):
        lines = block.splitlines()
        if len(lines) < 3:
            continue
        times = []
        for stamp in lines[1].split(" --> "):
            h, m, s, ms = map(int, re.split("[:,]", stamp))
            times.append(h * 3600 + m * 60 + s + ms / 1000)
        cues.append((*times, " ".join(lines[2:])))
    return cues


async def synthesize_pauses(pieces, target, render, on_stage=None, on_progress=None, cancel=None, lossless=False):
    import lameenc
    import miniaudio

    target = Path(target)
    partial = target.with_suffix(".part")
    rate = 24000
    encoder = lameenc.Encoder()
    encoder.set_bit_rate(128)
    encoder.set_in_sample_rate(rate)
    encoder.set_channels(1)
    encoder.set_quality(2)
    encoder.silence()
    elapsed, cues = 0.0, []
    try:
        with tempfile.TemporaryDirectory(prefix="freevoice-pauses-") as folder, partial.open("wb") as output:
            for index, piece in enumerate(pieces):
                if cancel is not None and cancel.is_set():
                    raise asyncio.CancelledError()
                if isinstance(piece, str):
                    path = Path(folder) / f"{index}{'.wav' if lossless else '.mp3'}"
                    await render(piece, path)
                    decoded = miniaudio.decode(path.read_bytes(),
                        output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1, sample_rate=rate)
                    pcm = decoded.samples.tobytes()
                    cues.extend((start + elapsed, end + elapsed, caption)
                                for start, end, caption in read_cues(path))
                else:
                    if on_stage:
                        on_stage(f"正在插入 {piece:g} 秒停顿")
                    pcm = bytes(round(piece * rate) * 2)
                output.write(encoder.encode(pcm))
                elapsed += len(pcm) / (rate * 2)
                if on_progress:
                    on_progress((index + 1) / len(pieces) * 0.99)
            if cancel is not None and cancel.is_set():
                raise asyncio.CancelledError()
            output.write(encoder.flush())
        partial.replace(target)
        write_srt(target, cues)
        return target
    finally:
        partial.unlink(missing_ok=True)
