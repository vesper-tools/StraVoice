"""Optional clone model packages and the pinned, verified Qwen runtime."""
import concurrent.futures
import hashlib
import json
import shutil
import threading
import urllib.request
import zipfile
from pathlib import Path

MODEL_INFO = {
    "zipvoice": {"name": "ZipVoice", "label": "ZipVoice · 轻量版", "tag": "轻量版",
                 "description": "模型体积小，克隆效果一般，电脑配置要求低。",
                 "download": "约 164 MB", "storage": "模型约 185 MB",
                 "hardware": "CPU 即可运行", "reference": "需要参考音频和对应文字"},
    "qwen3_q8": {"name": "Qwen3-TTS", "label": "Qwen3-TTS · 音质版", "tag": "音质版",
                "description": "克隆音色效果好，更注重音色还原，推荐使用",
                "download": "约 1.08 GB", "storage": "模型与引擎约 1.15 GB",
                "hardware": "支持显卡加速，也可使用 CPU", "reference": "仅需参考音频，文字可选"},
}
ASSETS = [{'name': 'Qwen3-TTS-12Hz-0.6B-Base.Q8_0.gguf', 'bytes': 646211264, 'sha256': '59b28b4ab6a1c4e24e6701fc871a427c1fb3e8333f0ed5cebec3bb67a699ae8e', 'url': 'https://huggingface.co/mradermacher/Qwen3-TTS-12Hz-0.6B-Base-GGUF/resolve/0762b31e9cd99274d49dca4e895bd81863134f08/Qwen3-TTS-12Hz-0.6B-Base.Q8_0.gguf'}, {'name': 'Qwen3-TTS-12Hz-0.6B-Base.mmproj-Q8_0.gguf', 'bytes': 401129632, 'sha256': '202c1fbf3a0f00b7586ca45b8328d696cc6cd980c3798979eaa4fefe8efd8320', 'url': 'https://huggingface.co/mradermacher/Qwen3-TTS-12Hz-0.6B-Base-GGUF/resolve/0762b31e9cd99274d49dca4e895bd81863134f08/Qwen3-TTS-12Hz-0.6B-Base.mmproj-Q8_0.gguf'}, {'name': 'llama-b11829-bin-win-vulkan-x64.zip', 'bytes': 36876542, 'sha256': '839ff55ce9cbee6a099b403b640ca6b694ee5d74b815e39f77fc5d2b20962f0d', 'url': 'https://github.com/ggml-org/llama.cpp/releases/download/b11829/llama-b11829-bin-win-vulkan-x64.zip'}]
MODEL_MIRROR = "https://modelscope.cn/models/cjf1443/Qwen3-TTS-12Hz-0.6B-Base-GGUF/resolve/d389360c221ca62fa45393b8fffc957d87828727/"
for _asset in ASSETS:
    _asset["fallback_url"] = _asset["url"]
    _asset["url"] = MODEL_MIRROR + _asset["name"]

PACKAGE = "qwen3-tts-q8_0"
_INSTALL_LOCK = threading.Lock()


def package_dir():
    import offline
    return offline.MODELS / PACKAGE


def active_model():
    import offline
    try:
        value = json.loads((offline.DATA / "clone-settings.json").read_text(encoding="utf-8"))
        key = value.get("active", "zipvoice") if isinstance(value, dict) else "zipvoice"
        return key if key in MODEL_INFO else "zipvoice"
    except (OSError, ValueError):
        return "zipvoice"


def set_active_model(key):
    import offline
    if key not in MODEL_INFO or not offline.installed(key):
        raise ValueError("请先下载并安装这个克隆模型。")
    offline.DATA.mkdir(parents=True, exist_ok=True)
    path = offline.DATA / "clone-settings.json"
    partial = path.with_suffix(".tmp")
    partial.write_text(json.dumps({"active": key}), encoding="utf-8")
    partial.replace(path)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_installed():
    folder = package_dir()
    try:
        record = json.loads((folder / "verified.json").read_text(encoding="utf-8"))
        return (record.get("hashes") == [a["sha256"] for a in ASSETS]
                and all((folder / a["name"]).stat().st_size == a["bytes"] for a in ASSETS[:2])
                and all((folder / "runtime" / name).is_file() for name in
                        ("llama-tts.exe", "llama.dll", "ggml.dll", "ggml-base.dll",
                         "ggml-vulkan.dll", "mtmd.dll", "llama-common.dll", "libomp.dll")))
    except (OSError, ValueError, AttributeError):
        return False


def _check_cancel(cancel):
    from offline import DownloadCancelled
    if cancel is not None and cancel.is_set():
        raise DownloadCancelled()


def _download_asset(asset, cache, progress, cancel):
    path = cache / asset["name"]
    if path.is_file() and path.stat().st_size == asset["bytes"] and sha256(path) == asset["sha256"]:
        progress(asset["bytes"])
        return path
    parts = cache / (asset["name"] + ".parts")
    parts.mkdir(exist_ok=True)
    block = 4 * 1024 * 1024
    count = (asset["bytes"] + block - 1) // block
    sizes = [0] * count
    lock = threading.Lock()

    def fetch(index):
        start = index * block
        end = min(asset["bytes"] - 1, start + block - 1)
        piece = parts / str(index)
        expected = end - start + 1
        for attempt in range(3):
            _check_cancel(cancel)
            try:
                if not piece.exists() or piece.stat().st_size != expected:
                    url = asset.get("fallback_url", asset["url"]) if attempt == 2 else asset["url"]
                    request = urllib.request.Request(url + "?part=" + str(index),
                        headers={"Range": f"bytes={start}-{end}", "User-Agent": "FreeVoice/0.6"})
                    with urllib.request.urlopen(request, timeout=20) as response:
                        if response.status != 206 or not response.headers.get("Content-Range", "").startswith(f"bytes {start}-{end}/"):
                            raise OSError("下载源不支持分块下载，请稍后重试。")
                        with piece.open("wb") as output:
                            remaining = expected
                            while remaining:
                                _check_cancel(cancel)
                                chunk = response.read(min(256 * 1024, remaining))
                                if not chunk:
                                    raise OSError("下载中断，请重试。")
                                output.write(chunk)
                                remaining -= len(chunk)
                with lock:
                    sizes[index] = expected
                    progress(sum(sizes))
                return
            except (OSError, ValueError):
                if attempt == 2:
                    raise
                if cancel is not None and cancel.wait(attempt + 1):
                    _check_cancel(cancel)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(fetch, range(count)))
    _check_cancel(cancel)
    with path.open("wb") as output:
        for index in range(count):
            with (parts / str(index)).open("rb") as source:
                shutil.copyfileobj(source, output)
    if sha256(path) != asset["sha256"]:
        path.unlink(missing_ok=True)
        for piece in parts.iterdir():
            piece.unlink()
        parts.rmdir()
        raise ValueError("文件校验失败，已丢弃损坏文件，请重试下载。")
    for piece in parts.iterdir():
        piece.unlink()
    parts.rmdir()
    return path


def install_package(progress=None, cancel=None, stage=None):
    import offline
    import tempfile
    with _INSTALL_LOCK:
        if package_installed():
            return package_dir()
        total = sum(a["bytes"] for a in ASSETS)
        offline.MODELS.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(offline.MODELS).free < total * 2 + 256 * 1024 * 1024:
            raise OSError("磁盘空间不足，请为下载与安装预留至少 2.5 GB。")
        cache = offline.MODELS / ".qwen-download"
        cache.mkdir(exist_ok=True)
        done = 0
        paths = []
        for index, asset in enumerate(ASSETS):
            _check_cancel(cancel)
            if stage:
                stage(f"正在下载配音所需文件（{index + 1}/{len(ASSETS)}）…")
            def advance(size):
                if progress:
                    progress(done + size, total)
            paths.append(_download_asset(asset, cache, advance, cancel))
            done += asset["bytes"]
        if stage:
            stage("正在安装，请稍候…")
        with tempfile.TemporaryDirectory(prefix="qwen-install-", dir=offline.MODELS) as temp:
            staging = Path(temp) / PACKAGE
            staging.mkdir()
            for path in paths[:2]:
                shutil.copy2(path, staging / path.name)
            with zipfile.ZipFile(paths[2]) as archive:
                for member in archive.infolist():
                    _check_cancel(cancel)
                    target = staging / "runtime" / member.filename
                    if not target.resolve().is_relative_to((staging / "runtime").resolve()):
                        raise ValueError("引擎压缩包包含不安全路径。")
                archive.extractall(staging / "runtime")
            (staging / "verified.json").write_text(json.dumps({"hashes": [a["sha256"] for a in ASSETS]}), encoding="utf-8")
            _check_cancel(cancel)
            destination = package_dir()
            if destination.exists():
                raise ValueError("发现未完成的模型目录，请先在模型页删除后重试。")
            staging.rename(destination)
        for path in paths:
            path.unlink(missing_ok=True)
        return destination


def remove_package(key):
    import offline
    if key not in MODEL_INFO:
        raise ValueError("未知克隆模型。")
    folder = package_dir() if key == "qwen3_q8" else Path(offline.registrations().get(key, ""))
    resolved = folder.resolve()
    root = offline.MODELS.resolve()
    if key == "zipvoice":
        with offline._engine_lock:
            offline._loaded = None
    elif key == "qwen3_q8":
        import qwen_backend
        with qwen_backend._LOCK:
            qwen_backend.shutdown()
    managed = resolved.is_relative_to(root) and resolved != root
    if folder.is_dir() and folder.parent.is_dir() and offline.MODELS.is_dir():
        managed = managed or folder.parent.samefile(offline.MODELS)
    if folder.is_dir() and managed:
        for _ in range(3):
            if not folder.exists():
                break
            shutil.rmtree(folder)
        if folder.exists():
            raise OSError("模型目录仍存在，未能完成删除，请关闭占用模型的程序后重试。")
    elif key == "qwen3_q8" and folder.exists():
        raise ValueError("模型目录不在软件管理目录内，未删除文件。")
    elif key == "zipvoice" and offline.installed():
        raise ValueError("该模型位于自定义目录，请保留文件并手动管理。")
    if key == "zipvoice":
        # This download cache belongs only to ZipVoice, not personal voices.
        (offline.MODELS / offline.VOCODER).unlink(missing_ok=True)
    values = offline.registrations()
    values.pop(key, None)
    offline.DATA.mkdir(parents=True, exist_ok=True)
    (offline.DATA / "models.json").write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")
