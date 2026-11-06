"""Conservative local duration correction; never synthesize a replacement voice."""
import codecs
from difflib import SequenceMatcher
from pathlib import Path
import re
import subprocess
import sys
import threading
import unicodedata

import numpy as np

ROOT = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
MODEL = ROOT / "models" / "speech-timing"
FFMPEG = ROOT / "bin" / "ffmpeg.exe"
_recognizer = None
_lock = threading.Lock()


def timed_characters(tokens, timestamps):
    # icefall byte_utils.py byte encoding, used by this model's BBPE tokenizer.
    chars = list(range(256, 288)) + list(range(32, 127))
    chars += [c for c in range(288, 512)
              if unicodedata.normalize("NFKC", chr(c)) == chr(c)][:256 - len(chars)]
    byte_map = {chr(c): i for i, c in enumerate(chars)}
    decoder = codecs.getincrementaldecoder("utf8")()
    result, start = [], None
    for token, timestamp in zip(tokens, timestamps):
        for char in token.replace("▁", ""):
            if start is None:
                start = timestamp
            value = decoder.decode(bytes([byte_map[char]]))
            if value:
                result.append((value, start))
                start = None
    decoder.decode(b"", final=True)
    return result


def drawn_intervals(text, aligned):
    """Edit only matched adjacent Chinese characters without punctuation between."""
    reference = [(c, i) for i, c in enumerate(text) if "\u4e00" <= c <= "\u9fff"]
    observed = [(c, t) for c, t in aligned if "\u4e00" <= c <= "\u9fff"]
    match = SequenceMatcher(None, "".join(c for c, _ in reference),
                           "".join(c for c, _ in observed), autojunk=False)
    if len(reference) < 6 or match.ratio() < 0.8:
        return []
    positions = {}
    for block in match.get_matching_blocks():
        for offset in range(block.size):
            positions[block.b + offset] = reference[block.a + offset][1]
    intervals = [(observed[i][1], observed[i + 1][1])
                 for i in range(len(observed) - 1)
                 if i in positions and positions.get(i + 1) == positions[i] + 1
                 and 0.04 <= observed[i + 1][1] - observed[i][1] <= 1.0]
    if len(intervals) < 5:
        return []
    cap = max(0.34, float(np.median([b - a for a, b in intervals])) * 1.8)
    return [(a, b, max(cap, (b - a) * 0.6)) for a, b in intervals if b - a > cap + 0.12]


def _recognize(samples, sample_rate):
    import sherpa_onnx
    global _recognizer
    with _lock:
        if _recognizer is None:
            _recognizer = sherpa_onnx.OnlineRecognizer.from_zipformer2_ctc(
                tokens=str(MODEL / "tokens.txt"), model=str(MODEL / "model.int8.onnx"),
                num_threads=2, sample_rate=16000, feature_dim=80, decoding_method="greedy_search")
        stream = _recognizer.create_stream()
        stream.accept_waveform(sample_rate, samples)
        stream.accept_waveform(sample_rate, np.zeros(sample_rate // 2, dtype="float32"))
        stream.input_finished()
        while _recognizer.is_ready(stream):
            _recognizer.decode_stream(stream)
        result = _recognizer.get_result_all(stream)
        try:
            return timed_characters(result.tokens, result.timestamps)
        except (KeyError, UnicodeError):
            return []  # Uncertain alignment must never change the waveform.


def shorten_drawn_syllables(samples, text, sample_rate):
    if not (MODEL / "model.int8.onnx").is_file() or not FFMPEG.is_file():
        return samples
    if len(re.findall(r"[\u4e00-\u9fff]", text)) < 6 or len(samples) < sample_rate:
        return samples
    edits = drawn_intervals(text, _recognize(samples, sample_rate))
    if not edits:
        return samples
    parts, cursor = [], 0
    for start, end, target in edits:
        a, b = int(start * sample_rate), min(len(samples), int(end * sample_rate))
        if a < cursor or b <= a:
            continue
        # atempo preserves pitch; crossfades suppress splice clicks.
        process = subprocess.run([
            str(FFMPEG), "-v", "error", "-f", "f32le", "-ar", str(sample_rate),
            "-ac", "1", "-i", "pipe:0", "-af", f"atempo={(end-start)/target:.6f}",
            "-f", "f32le", "pipe:1"], input=samples[a:b].astype("<f4").tobytes(),
            capture_output=True, check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        shortened = np.frombuffer(process.stdout, dtype="<f4").copy()
        if len(shortened) < int(sample_rate * target * 0.75):
            continue
        parts.extend((samples[cursor:a], shortened))
        cursor = b
    parts.append(samples[cursor:])
    output = parts[0].copy()
    for part in parts[1:]:
        fade = min(int(sample_rate * 0.006), len(output), len(part))
        if fade:
            ramp = np.linspace(0, 1, fade, dtype="float32")
            output[-fade:] = output[-fade:] * (1 - ramp) + part[:fade] * ramp
        output = np.concatenate((output, part[fade:]))
    return output

