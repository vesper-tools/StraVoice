"""Local synthesis using sherpa-onnx ZipVoice (zero-shot voice cloning)."""
import asyncio
import hashlib
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
import threading
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

DATA = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "FreeVoice"
MODELS = DATA / "models"
CLONES = DATA / "clones"
PACKAGE = "sherpa-onnx-zipvoice-distill-int8-zh-en-emilia"
# ZipVoice ships without a vocoder; the reference one lives in another release.
VOCODER = "vocos_24khz.onnx"
VOCODER_BYTES = 54157409
CATALOG = {
    "zipvoice": ("ZipVoice 中英双语 · 支持 3 秒克隆 · 下载约 164 MB", PACKAGE),
}
_loaded = None
_cwd_lock = threading.Lock()
_engine_lock = threading.Lock()

# Reference voices shipped with the model package. ZipVoice is zero-shot: every
# voice is just a few seconds of audio plus the transcript of that audio, so the
# built-in "voices" are the package's own test recordings (test_wavs/prompt.txt).
BUILTIN_REFS = [
    ("新闻女声", "zh-CN", "Female", "test_wavs/news-female.wav",
     "各位村民, 大家新年好! 近期, 湖北省武汉市等多个地区"),
    ("新闻女声 2", "zh-CN", "Female", "test_wavs/news-female-2.wav",
     "本台消息, 中共中央国务院, 近日印发关于构建数据基础制度, 更好发挥数据要素作用的意见."),
    ("雷军音色", "zh-CN", "Male", "test_wavs/leijun-1.wav",
     "那还是36年前, 1987年. 我呢考上了武汉大学的计算机系."),
]


def registrations():
    try:
        values = json.loads((DATA / "models.json").read_text(encoding="utf-8"))
        return {key: value for key, value in values.items()
                if isinstance(value, str) and value.strip()} if isinstance(values, dict) else {}
    except (OSError, ValueError):
        return {}


def _pick(folder, *patterns, exclude=(".int8.",)):
    """Pick the first ONNX file matching any pattern, preferring float models."""
    hits = []
    for pattern in patterns:
        hits.extend(sorted(Path(folder).glob(pattern)))
    if not hits:
        return None
    hits.sort(key=lambda path: any(mark in path.name for mark in exclude))
    return hits[0]


def bundle_files(folder, kind="zipvoice"):
    """Validate an unpacked ZipVoice bundle and return its file layout."""
    folder = Path(folder).resolve()
    if not folder.is_dir():
        raise ValueError("请选择解压后的 ZipVoice 模型目录。")
    if not (folder / "tokens.txt").is_file():
        raise ValueError("模型目录中缺少 tokens.txt。")
    encoder = _pick(folder, "encoder*.onnx")
    decoder = _pick(folder, "decoder*.onnx")
    vocoder = _pick(folder, "vocos*.onnx", "vocoder*.onnx")
    if vocoder is None and VOCODER and (folder.parent / VOCODER).is_file():
        # The vocoder is shared between bundles; keep a copy beside the model so
        # it can be loaded through a relative path.
        vocoder = folder / VOCODER
        if not vocoder.is_file():
            shutil.copy(folder.parent / VOCODER, vocoder)
    missing = [name for name, path in (("encoder", encoder), ("decoder", decoder)) if path is None]
    if missing:
        raise ValueError("模型缺少 " + "、".join(missing) + " 的 ONNX 文件，"
                         "请使用 sherpa-onnx 的 ZipVoice 完整模型包。")
    if vocoder is None:
        raise ValueError("模型缺少声码器 vocos_24khz.onnx，请重新下载音色包或把该文件放进模型目录。")
    return folder, {"encoder": encoder, "decoder": decoder,
                    "vocoder": vocoder, "tokens": folder / "tokens.txt"}


def register(key, folder):
    bundle_files(folder)
    values = registrations()
    values[key] = str(Path(folder).resolve())
    DATA.mkdir(parents=True, exist_ok=True)
    partial = DATA / "models.json.part"
    partial.write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")
    partial.replace(DATA / "models.json")


def installed(key="zipvoice"):
    if key == "qwen3_q8":
        from clone_models import package_installed
        return package_installed()
    folder = registrations().get("zipvoice")
    if not folder or not Path(folder).is_dir():
        return False
    folder = Path(folder)
    return bool((folder / "tokens.txt").is_file()
                and _pick(folder, "encoder*.onnx")
                and _pick(folder, "decoder*.onnx")
                and _pick(folder, "vocos*.onnx", "vocoder*.onnx"))


class DownloadCancelled(Exception):
    """The user cancelled installation before activation."""


def _download(url, destination, progress=None, cancel=None):
    """Cancel promptly even while urllib is blocked connecting or reading."""
    def check_cancel():
        if abandoned.is_set() or (cancel is not None and cancel.is_set()):
            raise DownloadCancelled()

    abandoned, finished = threading.Event(), threading.Event()
    check_cancel()
    request = urllib.request.Request(url, headers={"User-Agent": "FreeVoice/0.4"})
    # The reader owns a unique directory outside the installer's staging tree.
    # Cancelling can release that tree immediately, including on Windows.
    staging = tempfile.TemporaryDirectory(prefix="freevoice-download-")
    partial = Path(staging.name) / "payload.part"
    error = []

    def read():
        try:
            check_cancel()
            with urllib.request.urlopen(request, timeout=45) as response, partial.open("wb") as output:
                check_cancel()
                total = int(response.headers.get("Content-Length", 0))
                done = 0
                while True:
                    check_cancel()
                    chunk = response.read(256 * 1024)
                    check_cancel()
                    if not chunk:
                        break
                    output.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
                if total and done != total:
                    raise OSError(f"下载不完整（{done}/{total} 字节），请重试下载。")
        except Exception as exc:
            error.append(exc)
        finally:
            finished.set()
            if abandoned.is_set():
                staging.cleanup()

    threading.Thread(target=read, daemon=True).start()
    try:
        while not finished.wait(0.05):
            check_cancel()
        check_cancel()
        if error:
            raise error[0]
        shutil.move(str(partial), str(destination))
        return destination
    finally:
        abandoned.set()
        if finished.is_set():
            staging.cleanup()


ZIPVOICE_MIRROR = "https://modelscope.cn/models/cjf1443/ZipVoice-distill-int8-zh-en/resolve/0ec26835d974629fe97939062366d9eea20cb7ba/"
ZIPVOICE_HASHES = {
    PACKAGE + ".tar.bz2": "42e228d6d36e258c8d5c6b3a88113f3d6267c7aef8dc9388cc394ed6cf3524c8",
    VOCODER: "bcb3b970e384161c4d634f0bb9e999ff1c471b34c9bc0b1049a5014065ed3cc0",
}


def _download_zipvoice(name, destination, progress, cancel):
    try:
        _download(ZIPVOICE_MIRROR + name, destination, progress, cancel)
        digest = hashlib.sha256()
        with Path(destination).open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                if cancel is not None and cancel.is_set():
                    raise DownloadCancelled()
                digest.update(chunk)
        if digest.hexdigest() != ZIPVOICE_HASHES[name]:
            raise ValueError("模型文件校验失败，请重试下载。")
        return destination
    except (DownloadCancelled, OSError, ValueError):
        Path(destination).unlink(missing_ok=True)
        raise


def install(key, progress=None, cancel=None, stage=None):
    """Extract only regular files/directories into a fresh staging folder."""
    if key == "qwen3_q8":
        from clone_models import install_package
        return install_package(progress, cancel, stage)
    def check_cancel():
        if cancel is not None and cancel.is_set():
            raise DownloadCancelled()

    check_cancel()
    name = CATALOG[key][1]
    MODELS.mkdir(parents=True, exist_ok=True)
    destination = MODELS / name
    vocoder = MODELS / VOCODER
    bundled_vocoder = destination / VOCODER
    if destination.exists():
        try:
            bundle_files(destination)
        except ValueError:
            raise ValueError("模型文件不完整，请先在模型页删除模型，再重新下载。") from None
    if bundled_vocoder.is_file() and bundled_vocoder.stat().st_size == VOCODER_BYTES:
        register(key, destination)
        return destination
    if not vocoder.is_file() or vocoder.stat().st_size != VOCODER_BYTES:
        if stage:
            stage("正在下载配音所需文件…")
        _download_zipvoice(VOCODER, vocoder, progress, cancel)
    if destination.exists():
        # A previous run finished the tarball but not the vocoder.
        shutil.copy(vocoder, destination / VOCODER)
        register(key, destination)
        return destination
    with tempfile.TemporaryDirectory(prefix="download-", dir=MODELS) as temp:
        archive = Path(temp) / "model.tar.bz2"
        if stage:
            stage("正在下载音色包…")
        _download_zipvoice(name + ".tar.bz2", archive, progress, cancel)
        check_cancel()
        if stage:
            stage("正在解压音色包…")
        staging = Path(temp) / "unpacked"
        staging.mkdir()
        with tarfile.open(archive, "r:bz2") as package:
            members = package.getmembers()
            for member in members:
                target = (staging / member.name).resolve()
                if not target.is_relative_to(staging.resolve()) or not (member.isfile() or member.isdir()):
                    raise ValueError("模型压缩包包含不安全的路径或链接。")
            for member in members:
                check_cancel()
                package.extractall(staging, members=[member], filter="data")
        source = staging / name
        shutil.copy(vocoder, source / VOCODER)
        bundle_files(source)
        check_cancel()
        source.rename(destination)
    register(key, destination)
    return destination


# ---------- reference voices (built-in + cloned) ----------

class ReferenceTooLong(ValueError):
    """A reference exceeds the bounded decoding duration."""


def read_wave(path, max_seconds=None):
    """Load a PCM wav as mono float32 samples."""
    import wave
    import numpy as np
    with wave.open(str(path), "rb") as source:
        frames, channels = source.getnframes(), source.getnchannels()
        width, rate = source.getsampwidth(), source.getframerate()
        if max_seconds is not None and frames > rate * max_seconds:
            raise ReferenceTooLong("参考音频超过 20 秒，请裁剪到 3 至 10 秒。")
        raw = source.readframes(frames)
    if width == 2:
        samples = np.frombuffer(raw, "<i2").astype("float32") / 32768.0
    elif width == 1:
        samples = (np.frombuffer(raw, "u1").astype("float32") - 128.0) / 128.0
    elif width == 4:
        samples = np.frombuffer(raw, "<i4").astype("float32") / 2147483648.0
    else:
        raise ValueError("只支持 8/16/32 位 PCM 的 WAV 参考音频。")
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return np.ascontiguousarray(samples), int(rate)


def _decode_audio(path, rate=24000, max_seconds=None):
    """Decode any container miniaudio understands into mono float32 samples.

    Python supplies bounded reads and seeks to miniaudio: its own file opener
    uses the ANSI API on Windows, so a path under a
    CJK user folder ("C:\\Users\\常佳峰\\…") fails with DOES_NOT_EXIST.
    """
    import miniaudio
    import numpy as np
    if not Path(path).stat().st_size:
        raise ValueError("音频文件是空的。")
    class FileSource(miniaudio.StreamableSource):
        def read(self, num_bytes):
            return source.read(min(num_bytes, 65536))

        def seek(self, offset, origin):
            source.seek(offset, origin.value)
            return True

    with Path(path).open("rb") as source:
        input_stream = FileSource()
        stream = miniaudio.stream_any(input_stream, output_format=miniaudio.SampleFormat.SIGNED16,
                                     nchannels=1, sample_rate=rate, frames_to_read=4096)
        pieces, count = [], 0
        try:
            for piece in stream:
                count += len(piece)
                if max_seconds is not None and count > rate * max_seconds:
                    raise ReferenceTooLong("参考音频超过 20 秒，请裁剪到 3 至 10 秒。")
                pieces.append(np.asarray(piece, dtype="float32") / 32768.0)
        finally:
            stream.close()
        samples = np.concatenate(pieces) if pieces else np.empty(0, dtype="float32")
    if not samples.size:
        raise ValueError("音频里没有可读取的声音。")
    return np.ascontiguousarray(samples), int(rate)


def _decode_with_ffmpeg(path, rate=24000, max_seconds=None):
    """Last resort for containers miniaudio cannot open (m4a/aac/wma)."""
    import subprocess
    import tempfile
    import numpy as np
    root = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    bundled = root / "bin" / "ffmpeg.exe"
    ffmpeg = str(bundled) if bundled.is_file() else shutil.which("ffmpeg")
    if not ffmpeg:
        raise ValueError("找不到音频转换组件，请使用完整安装包修复安装，或先将录音另存为 MP3 / WAV。")
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "decoded.wav"
        command = [ffmpeg, "-v", "error", "-y", "-i", str(path)]
        if max_seconds is not None:
            command += ["-t", str(max_seconds + 1)]
        command += ["-ac", "1", "-ar", str(rate), "-f", "wav", str(target)]
        result = subprocess.run(command, capture_output=True, timeout=45,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode != 0 or not target.is_file():
            raise ValueError("无法解码这个音频，请换一段 MP3 / WAV 录音。")
        return read_wave(target, max_seconds=max_seconds)


def read_audio(path, max_seconds=None):
    """Load any common recording as mono float32 samples for cloning.

    WAV keeps its native rate (lossless, nothing to resample); every other
    container is decoded straight to ZipVoice's own 24 kHz.
    """
    path = Path(path)
    if not path.is_file():
        raise ValueError("找不到这个音频文件。")
    if max_seconds is not None and path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("参考音频文件过大，请裁剪到 3 至 10 秒。")
    try:
        return read_wave(path, max_seconds=max_seconds)
    except ReferenceTooLong:
        raise
    except Exception:
        pass
    try:
        return _decode_audio(path, max_seconds=max_seconds)
    except ReferenceTooLong:
        raise
    except Exception as error:
        try:
            return _decode_with_ffmpeg(path, max_seconds=max_seconds)
        except ReferenceTooLong:
            raise
        except Exception:
            raise ValueError("无法读取这段音频，请换一段 MP3 / WAV 录音。") from error


def _read_reference(path):
    """Load a reference recording as mono float samples."""
    return read_audio(path, max_seconds=20)


def _clone_meta(folder):
    try:
        meta = json.loads((Path(folder) / "meta.json").read_text(encoding="utf-8"))
        if not isinstance(meta, dict):
            return {}
        for key in ("name", "text", "locale", "gender"):
            if key in meta and not isinstance(meta[key], str):
                return {}
        if not isinstance(meta.get("added", 0), (int, float)):
            return {}
        return meta
    except (OSError, ValueError):
        return {}


def clones():
    """Registered cloned voices, newest first."""
    if not CLONES.is_dir():
        return []
    items = []
    for folder in CLONES.iterdir():
        meta = _clone_meta(folder)
        wav = folder / "prompt.wav"
        if meta.get("name") and wav.is_file():
            items.append({"id": folder.name, "name": meta["name"],
                          "text": meta.get("text", ""), "wav": wav,
                          "locale": meta.get("locale", "zh-CN"),
                          "gender": meta.get("gender", "Unknown"),
                          "added": meta.get("added", 0)})
    return sorted(items, key=lambda item: item["added"])


def add_clone(name, prompt_text, wav_path, locale="zh-CN", gender="Unknown", audio=None, require_text=True):
    """Store a reference recording as a reusable voice; returns its folder id."""
    name = (name or "").strip()
    prompt_text = (prompt_text or "").strip()
    if not name:
        raise ValueError("请给克隆音色起个名字。")
    if require_text and not prompt_text:
        raise ValueError("请填写参考音频里说的文字，ZipVoice 需要它来对齐音色。")
    if gender not in ("Male", "Female", "Unknown"):
        raise ValueError("请选择男声或女声。")
    samples, rate = audio if audio is not None else _read_reference(wav_path)
    seconds = len(samples) / max(rate, 1)
    if seconds < 2:
        raise ValueError(f"参考音频只有 {seconds:.1f} 秒，请提供 3 至 10 秒的清晰人声。")
    if seconds > 20:
        raise ValueError(f"参考音频有 {seconds:.0f} 秒，太长会拖慢合成，请裁剪到 10 秒以内。")
    CLONES.mkdir(parents=True, exist_ok=True)
    folder = CLONES / uuid.uuid4().hex[:12]
    folder.mkdir()
    import wave
    with wave.open(str(folder / "prompt.wav"), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        pcm = (samples.clip(-1, 1) * 32767).astype("<i2")
        output.writeframes(pcm.tobytes())
    (folder / "meta.json").write_text(json.dumps(
        {"name": name, "text": prompt_text, "locale": locale, "gender": gender,
         "added": int(__import__("time").time())}, ensure_ascii=False), encoding="utf-8")
    return folder.name


def set_clone_gender(clone_id, gender):
    if gender not in ("Male", "Female"):
        raise ValueError("请选择男声或女声。")
    if not any(item["id"] == clone_id for item in clones()):
        raise ValueError("克隆音色不存在。")
    folder = CLONES / clone_id
    meta = _clone_meta(folder)
    meta["gender"] = gender
    (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def remove_clone(clone_id):
    folder = CLONES / str(clone_id)
    if folder.is_dir() and folder.parent == CLONES:
        shutil.rmtree(folder)


def local_voices(provider="zipvoice"):
    """List selectable local voices: cloned voices first, then the built-ins."""
    if provider == "qwen3_q8":
        if not installed(provider):
            return []
        return [{"ShortName": f"local:qwen3_q8:clone:{item['id']}", "Name": item["name"] + " · 音质版",
                 "Locale": item["locale"], "Gender": item["gender"], "Kind": "克隆音色"}
                for item in clones()]
    if provider != "zipvoice" or not installed():
        return []
    folder = Path(registrations()["zipvoice"])
    voices = []
    for item in clones():
        if not item["text"]:
            continue
        voices.append({"ShortName": f"local:clone:{item['id']}", "Name": item["name"],
                       "Locale": item["locale"], "Gender": item["gender"], "Kind": "克隆音色"})
    for index, (label, locale, gender, relative, _) in enumerate(BUILTIN_REFS):
        if (folder / relative).is_file():
            voices.append({"ShortName": f"local:ref:{index}", "Name": label,
                           "Locale": locale, "Gender": gender, "Kind": "内置音色"})
    return voices


def reference_for(voice):
    """Return (prompt_text, samples, sample_rate) for a voice key."""
    _, kind, ident = voice.split(":")
    folder = Path(registrations()["zipvoice"])
    if kind == "ref":
        index = int(ident)
        entry = BUILTIN_REFS[index]
        wav = folder / entry[3]
        text = entry[4] or (wav.with_suffix(".txt").read_text(encoding="utf-8").strip()
                            if wav.with_suffix(".txt").is_file() else "")
        if not text:
            raise RuntimeError("内置参考音色缺少对应文字，请重新安装 ZipVoice 音色包。")
        samples, rate = _read_reference(wav)
        return text, samples, rate
    item = next((c for c in clones() if c["id"] == ident), None)
    if item is None:
        raise RuntimeError("克隆音色已被删除，请重新选择。")
    samples, rate = _read_reference(item["wav"])
    return item["text"], samples, rate


# ---------- engine ----------

def espeak_data_dir(folder):
    """Return the espeak-ng data directory for a model bundle.

    espeak-ng opens its data files through ANSI APIs on Windows, so a model
    stored under a non-ASCII folder (a CJK user name, for example) makes voice
    initialisation fail with "Failed to set eSpeak-ng voice" and synthesis then
    returns no audio at all. Mirror the data into an ASCII cache directory and
    hand espeak that path instead.
    """
    data = Path(folder) / "espeak-ng-data"
    if not data.is_dir():
        return ""
    source = str(data.resolve())
    if source.isascii():
        return source
    digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:12]
    cache = Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "FreeVoice" / "espeak" / digest
    try:
        if not (cache / "phontab").is_file():
            cache.mkdir(parents=True, exist_ok=True)
            shutil.copytree(data, cache, dirs_exist_ok=True)
        return str(cache)
    except OSError:
        # Fall back to the original path; the caller surfaces the failure.
        return source


def load_engine(key="zipvoice"):
    # Preloading and synthesis must share both the cache check and construction.
    with _engine_lock:
        return _load_engine(key)


def _load_engine(key):
    global _loaded
    import sherpa_onnx
    registered = registrations().get(key)
    if not registered:
        raise ValueError("离线模型尚未登记或配置已损坏，请重新下载音色包。")
    folder, files = bundle_files(registered)
    identity = (key, str(folder))
    if _loaded and _loaded[0] == identity:
        return _loaded[1]
    # Release the previous model before loading another, keeping memory bounded.
    _loaded = None
    # Native FST readers on Windows cannot open UTF-8 absolute paths. Load all
    # resources relative to their directory; restore the process cwd immediately.
    config = sherpa_onnx.OfflineTtsModelConfig(zipvoice=sherpa_onnx.OfflineTtsZipvoiceModelConfig(
        encoder=files["encoder"].name, decoder=files["decoder"].name,
        vocoder=files["vocoder"].name, tokens="tokens.txt",
        data_dir=espeak_data_dir(folder),
        lexicon="lexicon.txt" if (folder / "lexicon.txt").is_file() else "",
        # Classifier-free guidance at 2.0 keeps every syllable pinned to the
        # text: several clones slurred characters at the default 1.0 (one voice
        # read 把文字 as 爸爸文字), and the ASR character error rate drops from
        # 0.13 to 0.09 on average. It costs no extra generation time.
        guidance_scale=2.0),
        num_threads=max(2, min(8, (os.cpu_count() or 4) - 2)))
    rules = ",".join(n for n in ("phone.fst", "date.fst", "number.fst",
        "phone-zh.fst", "date-zh.fst", "number-zh.fst") if (folder / n).exists())
    tts_config = sherpa_onnx.OfflineTtsConfig(model=config, rule_fsts=rules, max_num_sentences=1)
    with _cwd_lock:
        previous = Path.cwd()
        try:
            os.chdir(folder)
            if not tts_config.validate():
                raise ValueError("离线模型配置无效，请重新导入完整模型包。")
            tts = sherpa_onnx.OfflineTts(tts_config)
        finally:
            os.chdir(previous)
    _loaded = (identity, tts)
    return tts


def _chinese_number(value):
    digits = "零一二三四五六七八九"
    integer, dot, fraction = value.partition(".")
    if (len(integer) > 1 and integer.startswith("0")) or len(integer) > 12:
        spoken = "".join(digits[int(d)] for d in integer)
    else:
        def cardinal(number):
            if number >= 10000:
                base, unit = (100000000, "亿") if number >= 100000000 else (10000, "万")
                head, tail = divmod(number, base)
                return cardinal(head) + unit + (("零" if tail < base // 10 else "") + cardinal(tail) if tail else "")
            if number == 0:
                return "零"
            result, pending_zero = "", False
            for divisor, unit in ((1000, "千"), (100, "百"), (10, "十"), (1, "")):
                digit, number = divmod(number, divisor)
                if digit:
                    result += ("零" if pending_zero else "") + digits[digit] + unit
                    pending_zero = False
                elif result and number:
                    pending_zero = True
            return result
        spoken = cardinal(int(integer))
        if spoken.startswith("一十"):
            spoken = spoken[1:]
    return spoken + ("点" + "".join(digits[int(d)] for d in fraction) if dot else "")


def _normalize_chinese_numbers(text):
    """Keep Chinese numbers out of the bilingual frontend's English reading path."""
    def normalize(match):
        value = match.group()
        return "百分之" + _chinese_number(value[:-1]) if value.endswith("%") else _chinese_number(value)

    parts = re.split(r"([。！？!?；;\n])", text)
    for index, part in enumerate(parts):
        if re.search(r"[\u3400-\u9fff]", part) or (re.search(r"\d", part) and not re.search(r"[A-Za-z]", part)):
            part = re.sub(r"(?<![A-Za-z0-9_.])\d{4}(?=\s*年)",
                          lambda match: "".join(_chinese_number(digit) for digit in match.group()), part)
            part = re.sub(r"(?<![A-Za-z0-9_.])[A-Za-z0-9]*[A-Za-z][A-Za-z0-9]*(?![A-Za-z0-9_]|\.[A-Za-z0-9])",
                          lambda match: re.sub(r"\d", lambda digit: _chinese_number(digit.group()),
                                               match.group()), part, flags=re.IGNORECASE)
            parts[index] = re.sub(r"(?<![A-Za-z0-9_.])\d+(?:\.\d+)?%?(?![A-Za-z0-9_.%])", normalize, part)
    return "".join(parts)


def _speech_chunks(text, limit=60):
    """Keep sentences and acronym lists together; split long sentences at clauses."""
    sentences = [part for part in re.findall(
        r'''[^。！？!?；;\n]+[。！？!?；;]*[”’")）]*(?:[ \t\r]*\n+)?|[。！？!?；;\n]+''',
        text) if part.strip()]
    chunks = []
    for sentence in sentences:
        if len(sentence) <= limit:
            chunks.append(sentence)
            continue
        buffer = ""
        for clause in re.findall(r"[^，,：:、]+[，,：:、]*|[，,：:、]+", sentence):
            if buffer and len(buffer) + len(clause) > limit:
                chunks.append(buffer)
                buffer = ""
            buffer += clause
        if buffer:
            chunks.append(buffer)
    return chunks or [text]


def _time_stretch(samples, ratio, sample_rate):
    """WSOLA time scaling: `ratio` is the output length divided by the input.

    ZipVoice's own `speed` argument squashes the duration tokens themselves, so
    past about 1.25 it stops producing pauses and starts slurring syllables (a
    93-character paragraph at 1.5 came back at 8.9 characters per second with
    only three pauses left). Generating at the model's stable rate and then
    stretching the waveform keeps the articulation and the rhythm intact.

    The frames must line up over the *whole* overlap before they are mixed: a
    partial match leaves the harmonics out of phase, and the resulting comb
    filter is heard as a second, hollow voice riding along with the speaker.
    So each frame is placed on a fixed output step, the search measures the
    entire overlap, and the join is a linear crossfade whose weights sum to one
    (no window normalisation, which used to amplify the edges of the frame).
    """
    import numpy as np
    if abs(ratio - 1.0) < 0.02 or len(samples) < 4096:
        return samples
    frame = 2048
    hop = frame // 4
    step = int(round(hop * ratio))
    step = max(hop // 4, min(frame - hop, step))
    match = frame - step
    tolerance = hop // 2
    count = (len(samples) - frame) // hop
    if count < 2:
        return samples
    output = np.zeros(count * step + frame, dtype="float32")
    previous = 0
    for index in range(count):
        nominal = index * hop
        if index == 0:
            start = nominal
        else:
            reference = samples[previous + step:previous + frame]
            low = max(0, nominal - tolerance)
            high = min(len(samples) - frame, nominal + tolerance)
            if high <= low:
                start = min(max(nominal, 0), len(samples) - frame)
            else:
                window = samples[low:high + match]
                candidates = np.lib.stride_tricks.sliding_window_view(window, match)
                start = low + int(np.argmax(candidates @ reference))
        take = samples[start:start + frame]
        position = index * step
        if index == 0:
            output[position:position + frame] = take
        else:
            ramp = np.linspace(0.0, 1.0, match, dtype="float32")
            output[position:position + match] = (
                output[position:position + match] * (1.0 - ramp) + take[:match] * ramp)
            output[position + match:position + frame] = take[match:]
        previous = start
    # Slowing down needs one extra frame of tail; pad with silence rather than
    # dropping the last syllable's decay.
    target = max(1, int(len(samples) * ratio))
    if output.shape[0] < target:
        output = np.pad(output, (0, target - output.shape[0]))
    return output[:target]


# Silence inserted after a chunk, before time scaling. Chunks are cut on
# sentence punctuation, so without this the paragraphs run into each other.
PAUSE_AFTER = {"。": 0.35, "！": 0.35, "？": 0.35, "…": 0.35, "；": 0.30, ";": 0.30,
               "，": 0.12, ",": 0.12, "、": 0.35, "：": 0.22, ":": 0.22,
               ".": 0.35, "!": 0.35, "?": 0.35}


def _pause_after(chunk):
    if re.search(r"\n[ \t\r]*\n[ \t\r\n]*$", chunk):
        return 1.20
    if chunk.rstrip(" \t\r").endswith("\n"):
        return 1.00
    stripped = chunk.rstrip().rstrip('”’"）)]')
    return PAUSE_AFTER.get(stripped[-1:], 0.24) if stripped else 0.0


def _soften_speech_tail(samples, text, sample_rate):
    """Fade quiet trailing breath after Chinese speech, preserving voiced words."""
    if not re.search(r'''[\u3400-\u9fff][。！？.!?；;…][”’")）]*\s*$''', text):
        return samples
    import numpy as np
    frame, hop = int(sample_rate * 0.06), max(1, int(sample_rate * 0.01))
    if len(samples) < frame * 3:
        return samples
    peak = float(np.max(np.abs(samples)))
    if peak < 0.001:
        return samples
    voiced = []
    window = np.hanning(frame)
    for start in range(max(0, len(samples) - int(sample_rate * 1.5)), len(samples) - frame + 1, hop):
        block = samples[start:start + frame]
        if float(np.sqrt(np.mean(block ** 2))) < max(peak * 0.04, 0.003):
            continue
        weighted = block * window
        corr = np.correlate(weighted, weighted, "full")[frame - 1:]
        periodicity = corr[int(sample_rate / 450):int(sample_rate / 70)].max() / (corr[0] + 1e-10)
        if periodicity > 0.65:
            voiced.append(start + frame)
    if len(voiced) < 3:
        return samples
    end_voice = voiced[-1]
    active = np.flatnonzero(np.abs(samples) > peak * 0.01)
    tail = (active[-1] + 1 - end_voice) / sample_rate
    if not 0.12 <= tail <= 1.0:
        return samples
    vowel = samples[max(0, end_voice - int(sample_rate * 0.12)):end_voice]
    breath = samples[end_voice:active[-1] + 1]
    if np.sqrt(np.mean(breath ** 2)) > np.sqrt(np.mean(vowel ** 2)) * 0.6:
        return samples
    # The analysis frame already includes the vowel's decay. Fade only the
    # boundary, leaving the spoken syllable intact.
    start = max(0, end_voice - int(sample_rate * 0.02))
    end = min(len(samples), end_voice + int(sample_rate * 0.02))
    output = samples.copy()
    output[start:end] *= np.cos(np.linspace(0, np.pi / 2, end - start)) ** 2
    output[end:] = 0
    return output


def _render_chunk(tts, chunk, prompt, ratio, volume):
    """Render one chunk to 16-bit PCM; safe to run from several threads."""
    import numpy as np
    prompt_text, prompt_samples, prompt_rate = prompt
    # Expressive punctuation can make cloned voices add a drawn-out question
    # tail. Use a neutral cadence; keep the original chunk for pause timing.
    spoken = re.sub(r"[！？!?]+", "。", chunk)
    # Give unterminated Chinese text an explicit sentence boundary.
    if re.search(r"[\u3400-\u9fff]\s*$", spoken):
        spoken = spoken.rstrip() + "。"
    acronym = r"[A-Z]{2,5}(?:[0-9零一二三四五六七八九]+)?"
    list_pattern = rf"(?<![A-Za-z0-9]){acronym}(?:\s*[、，,]\s*{acronym})+(?![A-Za-z0-9])"
    acronym_list = re.search(list_pattern, spoken) is not None
    if acronym_list:
        import sherpa_onnx
        spoken = re.sub(list_pattern, lambda match: re.sub(
            acronym, lambda item: " ".join(item.group()), match.group()), spoken)
        config = sherpa_onnx.GenerationConfig()
        config.reference_text, config.reference_audio = prompt_text, prompt_samples
        config.reference_sample_rate = prompt_rate
        config.speed, config.num_steps, config.silence_scale = 1.0, 16, 0.2
        config.extra = {"min_char_in_sentence": "200", "max_char_in_sentence": "200"}
        audio = tts.generate(spoken, config)
    else:
        audio = tts.generate(spoken, prompt_text, prompt_samples, prompt_rate, 1.0, 4)
    samples = np.asarray(audio.samples, dtype="float32")
    if not samples.size:
        raise RuntimeError("离线模型未返回音频。")
    if not acronym_list:
        from speech_timing import shorten_drawn_syllables
        samples = shorten_drawn_syllables(samples, chunk, tts.sample_rate)
        samples = _soften_speech_tail(samples, spoken, tts.sample_rate)
    samples = _time_stretch(samples, ratio, tts.sample_rate)
    # A few milliseconds of fade keeps chunk joins from clicking.
    edge = min(len(samples) // 2, int(tts.sample_rate * 0.008))
    if edge > 1:
        ramp = np.linspace(0.0, 1.0, edge, dtype="float32")
        samples[:edge] *= ramp
        samples[-edge:] *= ramp[::-1]
    return (np.clip(samples * (volume / 100), -1, 1) * 32767).astype("<i2")


def render_workers(chunk_count, cpu=None):
    """How many chunks to render at once.

    One generate() call only keeps about six cores busy (process CPU time over
    wall time measures 5.9 on a 16-core box), and asking for more threads inside
    a single call changes nothing, so the idle cores are only reachable by
    running chunks side by side. Three at a time turns a 274-character paragraph
    from 29.5 s into 21.6 s; wider than that gains nothing because the work is
    memory-bound.
    """
    if chunk_count < 2:
        return 1
    cores = cpu or os.cpu_count() or 4
    return max(1, min(3, chunk_count, cores // 4))


def _steady_tempo(chunks, audio, sample_rate, ratio):
    """Align Chinese sentence tempos to this passage, then apply the user's speed once."""
    import numpy as np
    rates = []
    for text, pcm in zip(chunks, audio):
        chinese = len(re.findall(r"[\u3400-\u9fff]", text))
        if chinese < 8 or re.search(r"[A-Za-z]", text) or not pcm.size:
            rates.append(None)
            continue
        values = np.abs(pcm.astype("float32"))
        active = np.flatnonzero(values > max(32, float(values.max()) * 0.015))
        if not active.size:
            rates.append(None)
            continue
        seconds = (active[-1] - active[0] + 1) / sample_rate
        # Acronyms are normally spelled out; ordinary words span fewer syllables.
        units = chinese + sum(len(word) if word.isupper() else max(1, len(word) / 3)
                              for word in re.findall(r"[A-Za-z]+", text))
        rates.append(units / max(seconds, 0.1))
    usable = [rate for rate in rates if rate is not None]
    target = float(np.median(usable)) if len(usable) >= 2 else None
    for pcm, rate in zip(audio, rates):
        correction = 1.0
        if target and rate:
            # Keep a small natural variation and cap any correction at 25%.
            bounded = min(max(rate, target * 0.97), target * 1.03)
            correction = min(max(rate / bounded, 0.8), 1.25)
        adjusted = _time_stretch(pcm.astype("float32"), ratio * correction, sample_rate)
        yield np.clip(adjusted, -32768, 32767).astype("<i2")


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise asyncio.CancelledError()


def _encode_chunks(partial, chunks, tts, prompt, ratio, volume, workers, total, on_progress, cancel=None, pcm=False):
    """Render chunks to MP3 or lossless WAV; workers above one run side by side."""
    from audio_output import audio_output
    import numpy as np
    done = 0
    cues = []
    elapsed = 0.0
    pool = None
    def render(chunk):
        _check_cancel(cancel)
        return _render_chunk(tts, chunk, prompt, 1.0, volume)
    if workers > 1:
        # map() keeps the chunk order, so the file is written in reading order
        # even though several chunks render at the same time.
        pool = ThreadPoolExecutor(max_workers=workers)
        rendered = pool.map(render, chunks)
    else:
        rendered = map(render, chunks)
    with audio_output(partial, tts.sample_rate, pcm=pcm) as write:
        try:
            audio = []
            for chunk, pcm in zip(chunks, rendered):
                _check_cancel(cancel)
                audio.append(pcm)
                done += len(chunk)
                if on_progress:
                    on_progress(min(done / total * 0.9, 0.9))
            paced = _steady_tempo(chunks, audio, tts.sample_rate, ratio)
            done = 0
            for index, (chunk, pcm) in enumerate(zip(chunks, paced)):
                _check_cancel(cancel)
                write(pcm.tobytes())
                end = elapsed + len(pcm) / tts.sample_rate
                cues.append((elapsed, end, chunk))
                elapsed = end
                if index < len(chunks) - 1:
                    gap = int(tts.sample_rate * _pause_after(chunk) * ratio)
                    if gap > 0:
                        write(np.zeros(gap, dtype="<i2").tobytes())
                        elapsed += gap / tts.sample_rate
                done += len(chunk)
                if on_progress:
                    on_progress(min(0.9 + done / total * 0.09, 0.99))
        finally:
            if workers > 1:
                pool.shutdown(wait=True, cancel_futures=True)
        # The model cuts the decay of the final syllable, which listeners hear as
        # a swallowed last character; a little silence restores it.
        write(np.zeros(int(tts.sample_rate * 0.18), dtype="<i2").tobytes())
    return cues


def generate_local(text, voice, speed, volume, target, on_stage=None, on_progress=None, cancel=None):
    if voice.startswith("local:qwen3_q8:clone:"):
        from qwen_backend import generate
        return generate(text, voice, speed, volume, target, on_stage, on_progress, cancel)
    _check_cancel(cancel)
    if on_stage:
        on_stage("正在准备音色，首次使用请稍候")
    tts = load_engine("zipvoice")
    _check_cancel(cancel)
    if on_stage:
        on_stage("正在准备你的音色")
    prompt = reference_for(voice)
    prompt = (_normalize_chinese_numbers(prompt[0]), prompt[1], prompt[2])
    if on_stage:
        on_stage("正在生成配音，请稍候")
    partial = Path(target).with_suffix(".part")
    # Sentence boundaries are kept so pauses and passage tempo can be controlled.
    chunks = _speech_chunks(_normalize_chinese_numbers(text))
    total = sum(len(part) for part in chunks) or 1
    # The model runs at its stable rate and the waveform is scaled afterwards,
    # so the whole 0.5x-2.0x range keeps its pauses and its consonants.
    ratio = 1.0 / min(max(float(speed), 0.5), 2.0)
    workers = min(render_workers(len(chunks)), getattr(tts, "max_workers", 3))
    try:
        try:
            cues = _encode_chunks(partial, chunks, tts, prompt, ratio, volume,
                           workers, total, on_progress, cancel, pcm=Path(target).suffix == ".wav")
        except Exception:
            if workers <= 1:
                raise
            # Sharing one engine between threads is not documented as safe. If it
            # ever objects, fall back to one chunk at a time instead of failing
            # the whole job.
            if on_stage:
                on_stage("正在分段生成配音")
            cues = _encode_chunks(partial, chunks, tts, prompt, ratio, volume,
                           1, total, on_progress, cancel, pcm=Path(target).suffix == ".wav")
        _check_cancel(cancel)
        partial.replace(target)
        from subtitles import write_srt
        source_chunks = _speech_chunks(text)
        if [_normalize_chinese_numbers(chunk) for chunk in source_chunks] == chunks:
            cues = [(start, end, source) for (start, end, _), source in zip(cues, source_chunks)]
        write_srt(target, cues)
        return Path(target)
    finally:
        partial.unlink(missing_ok=True)


async def synthesize_local(text, voice, speed, volume, target, on_stage=None, on_progress=None, cancel=None):
    cancel = cancel if cancel is not None else threading.Event()
    pending = asyncio.create_task(asyncio.to_thread(generate_local, text, voice, speed, volume, target,
                                    on_stage=on_stage, on_progress=on_progress, cancel=cancel))
    try:
        return await asyncio.shield(pending)
    except asyncio.CancelledError:
        cancel.set()
        # A task's temporary folder must outlive the native worker using it.
        try:
            await pending
        except (Exception, asyncio.CancelledError):
            pass
        raise
