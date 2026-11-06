"""SRT captions from service boundaries or final local synthesis segments."""
import html
import re
from pathlib import Path


def timestamp(seconds):
    value = max(0, round(seconds * 1000))
    hours, value = divmod(value, 3600000)
    minutes, value = divmod(value, 60000)
    seconds, millis = divmod(value, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def write_srt(audio, cues):
    blocks = []
    for start, end, text in cues:
        text = " ".join(text.split())
        if not text or end <= start:
            continue
        blocks.append(f"{len(blocks) + 1}\n{timestamp(start)} --> {timestamp(end)}\n{text}\n")
    target = Path(audio).with_suffix(".srt")
    if blocks:
        target.write_text("\n".join(blocks), encoding="utf-8-sig")
    else:
        target.unlink(missing_ok=True)


def online_cues(text, boundaries):
    """Keep source punctuation when the service returns the original words."""
    units = []
    cursor = 0
    for start, end, word in boundaries:
        word = html.unescape(word)
        index = text.casefold().find(word.casefold(), cursor)
        if index >= 0:
            last = index + len(word)
            while last < len(text) and not text[last].isalnum():
                last += 1
            caption = text[cursor:last] if not text[cursor:index].strip() else text[index:last]
            cursor = last
        else:
            caption = word
        units.append((start, end, caption))
    cues = []
    for start, end, caption in units:
        if cues and start - cues[-1][1] < 0.65 and len(cues[-1][2]) + len(caption) <= 36 and not re.search(r"[。！？!?；;]\s*$", cues[-1][2]):
            previous = cues[-1]
            separator = " " if previous[2][-1:].isascii() and previous[2][-1:].isalnum() and caption[:1].isascii() and caption[:1].isalnum() else ""
            cues[-1] = (previous[0], end, previous[2] + separator + caption)
        else:
            cues.append((start, end, caption))
    return cues
