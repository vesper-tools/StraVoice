"""Lossless speech boundaries and conservative Qwen chunk joins."""
import re

TOKEN = re.compile(r"【停顿[0-9.]+秒】|[A-Za-z0-9]+(?:[.'’_+/@:-][A-Za-z0-9]+)*|\s+|.", re.S)


def sentence_segments(text, limit=60):
    pieces, cursor = [], 0
    for token in TOKEN.finditer(text):
        value = token[0]
        boundary = value in "。！？!?；;" or "\n" in value
        if value == "." and (token.end() == len(text) or text[token.end()].isspace()):
            prefix = text[cursor:token.start()].split()
            boundary = not prefix or prefix[-1].casefold() not in ("mr", "mrs", "ms", "dr", "prof", "e.g", "i.e")
        if boundary:
            end = token.end()
            while end < len(text) and text[end] in '”’")） \t\r\n':
                end += 1
            if end > cursor:
                pieces.extend(split_text(text[cursor:end], limit))
                cursor = end
    pieces.extend(split_text(text[cursor:], limit))
    return pieces


def split_text(text, limit=60):
    """Keep words/markers whole, prefer sentences, then clauses, then spaces."""
    chunks = []
    while len(text) > limit:
        tokens = list(TOKEN.finditer(text))
        ends = [m.end() for m in tokens if m.end() <= limit]
        if not ends:
            # An individual identifier longer than the model limit cannot fit.
            cut = limit
        else:
            floor = max(1, limit // 3)
            candidates = [end for end in ends if end >= floor]
            cut = next((end for end in reversed(candidates)
                        if re.search(r'[。！？!?；;\n][”’")）]*\s*$', text[:end])), None)
            if cut is None:
                cut = next((end for end in reversed(candidates)
                            if text[end - 1] in "，,：:、 \t"), ends[-1])
        chunks.append(text[:cut])
        text = text[cut:]
    if text:
        chunks.append(text)
    return chunks


def pause_after(text):
    if re.search(r"\n\s*\n\s*$", text):
        return .32
    if text.endswith("\n"):
        return .24
    last = text.rstrip().rstrip('”’"）)]')
    if last.endswith(tuple("。！？!?；;")):
        return .20
    if last.endswith(tuple("，,：:、")):
        return .10
    return .025


def prepare_join(samples, rate, with_offset=False):
    """Remove only sustained near-silence; keep 80 ms beside audible speech."""
    import numpy as np
    result = np.asarray(samples, dtype=np.float32).copy()
    active = np.flatnonzero(np.abs(result) > .001)  # -60 dBFS
    if not len(active):
        return (result, 0.) if with_offset else result
    keep = round(rate * .08)
    start, end = 0, len(result)
    if active[0] > rate * .25:
        start = max(0, active[0] - keep)
    if len(result) - active[-1] - 1 > rate * .25:
        end = min(len(result), active[-1] + keep + 1)
    result = result[start:end]
    fade = min(round(rate * .003), len(result) // 2)
    if fade:
        result[:fade] *= np.linspace(0, 1, fade)
        result[-fade:] *= np.linspace(1, 0, fade)
    return (result, start / rate) if with_offset else result


def missing_pause(samples, rate, text):
    import numpy as np
    active = np.flatnonzero(np.abs(samples) > .001)
    tail = (len(samples) - active[-1] - 1) / rate if len(active) else len(samples) / rate
    return max(0, round((pause_after(text) - tail) * rate))
