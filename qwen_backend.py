"""Qwen3-TTS Q8_0 through an isolated, cancellable native process."""
import re
import atexit
import hashlib
from collections import OrderedDict
from collections import deque
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

from clone_models import ASSETS, package_dir, package_installed

_LOCK = threading.Lock()
_DLL_LOCK = threading.Lock()
_WORKER = None
_IDLE_SECONDS = 600
_REFERENCE_CACHE = OrderedDict()


def _failure_detail(code, log):
    status = code & 0xFFFFFFFF
    if status == 0xC0000135:
        reason = "引擎缺少运行库或 DLL，请重新运行最新版安装包修复微软 C++ x64 运行库。"
    elif status in (0xC000007B, 0xC0000139):
        reason = "引擎运行库版本或架构不兼容，请使用最新版 x64 安装包修复安装。"
    elif status == 0xC000001D:
        reason = "引擎执行了当前处理器不支持的指令，请暂用 ZipVoice，并向开发者提供 CPU 型号。"
    elif status in (0xC0000017, 0xC000012D):
        reason = "系统可用内存或虚拟内存不足，请关闭其他程序、检查系统虚拟内存，或切换 ZipVoice。"
    else:
        reason = "引擎异常退出，请向开发者提供此错误信息及电脑配置。"
    detail = f"{reason}\n退出码：0x{status:08X}（{code}）"
    if log.strip():
        detail += "\n引擎日志：\n" + log.strip()[-700:]
    return detail


def reference_audio(path):
    """Bound decoded reference memory; content identity also invalidates native cache."""
    import offline
    path = Path(path)
    key = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    if key is not None and key in _REFERENCE_CACHE:
        _REFERENCE_CACHE.move_to_end(key)
        return _REFERENCE_CACHE[key]
    samples, rate = offline._decode_audio(path, max_seconds=20)
    from segmentation import prepare_join
    samples = prepare_join(samples, rate)
    pcm = (samples.clip(-1, 1) * 32767).astype("<i2").tobytes()
    result = (pcm, rate, key or hashlib.sha256(pcm).hexdigest())
    if key is not None:
        _REFERENCE_CACHE[key] = result
        while len(_REFERENCE_CACHE) > 8:
            _REFERENCE_CACHE.popitem(last=False)
    return result


def _native_popen(*args, **kwargs):
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return subprocess.Popen(*args, **kwargs)
    import ctypes
    # External llama libraries need the system C++ runtime, not PyInstaller's copy.
    kernel = ctypes.windll.kernel32
    kernel.GetDllDirectoryW.argtypes = [ctypes.c_uint, ctypes.c_wchar_p]
    kernel.SetDllDirectoryW.argtypes = [ctypes.c_wchar_p]
    env = kwargs.get("env", os.environ).copy()
    bundle = str(Path(sys._MEIPASS).resolve()).casefold()
    env["PATH"] = os.pathsep.join(path for path in env.get("PATH", "").split(os.pathsep)
        if path.casefold() != bundle and not path.casefold().startswith(bundle + os.sep))
    kwargs["env"] = env
    with _DLL_LOCK:
        original = ctypes.create_unicode_buffer(32768)
        kernel.GetDllDirectoryW(len(original), original)
        kernel.SetDllDirectoryW(None)
        try:
            return subprocess.Popen(*args, **kwargs)
        finally:
            kernel.SetDllDirectoryW(original.value or None)


class _ResidentWorker:
    def __init__(self, executable, command, folder):
        env = os.environ.copy()
        env["PATH"] = str(folder / "runtime") + os.pathsep + env.get("PATH", "")
        self.process = _native_popen([str(executable), *command[1:]], cwd=folder,
            env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.messages = queue.Queue()
        self.logs = deque(maxlen=40)
        self.last_used = time.monotonic()
        self.closed = threading.Event()
        self.readers = [threading.Thread(target=self._read, daemon=True),
                        threading.Thread(target=self._read_logs, daemon=True)]
        for reader in self.readers:
            reader.start()
        threading.Thread(target=self._idle, daemon=True).start()

    def _read(self):
        for raw in self.process.stdout:
            self.messages.put(raw.decode("utf-8", "replace").strip())
        self.messages.put("EXIT")

    def _read_logs(self):
        for raw in self.process.stderr:
            self.logs.append(raw.decode("utf-8", "replace"))

    def _idle(self):
        while not self.closed.wait(5):
            if time.monotonic() - self.last_used > _IDLE_SECONDS and _LOCK.acquire(blocking=False):
                try:
                    if time.monotonic() - self.last_used > _IDLE_SECONDS:
                        self.stop()
                finally:
                    _LOCK.release()

    def wait(self, expected, cancel, on_stage):
        import offline
        start = time.monotonic()
        while True:
            offline._check_cancel(cancel)
            if time.monotonic() - start > 300:
                raise RuntimeError("这段配音耗时过长，请缩短文案后重试。")
            try:
                message = self.messages.get(timeout=0.1)
            except queue.Empty:
                continue
            if message.startswith(expected):
                return message
            if message.startswith("PROGRESS ") and on_stage:
                on_stage("正在生成配音，请稍候")
            if message == "EXIT":
                code = self.process.wait()
                self.readers[1].join()
                raise RuntimeError("Qwen3-TTS 后台进程退出：" + _failure_detail(code, "".join(self.logs)))

    def stop(self):
        self.closed.set()
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait()
        for reader in self.readers:
            reader.join()
        for pipe in (self.process.stdin, self.process.stdout, self.process.stderr):
            pipe.close()


def shutdown(clear_reference=True):
    global _WORKER
    if _WORKER is not None:
        _WORKER.stop()
        _WORKER = None
    if clear_reference:
        _REFERENCE_CACHE.clear()


atexit.register(shutdown)


def _device(executable, folder):
    # A live worker already proved this device works; avoid starting another
    # Vulkan process (and initializing every adapter) for each preview/export.
    if (_WORKER is not None and _WORKER.process.poll() is None
            and not _WORKER.closed.is_set() and _WORKER.key[0] == str(folder)):
        return _WORKER.key[1][1]
    try:
        with _native_popen([str(executable), "--list-devices"], cwd=folder,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) as process:
            try:
                stdout, stderr = process.communicate(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                return "none"
        devices = re.findall(r"(Vulkan\d+): ([^\r\n]+)", stdout.decode("utf-8", "replace"))
        if not devices:
            devices = re.findall(r"(Vulkan\d+): ([^\r\n]+)", stderr.decode("utf-8", "replace"))
        nvidia = next((key for key, label in devices if "NVIDIA" in label), None)
        return nvidia or (devices[0][0] if devices else "none")
    except (OSError, subprocess.TimeoutExpired):
        return "none"


def _run(command, folder, cancel, on_stage):
    global _WORKER
    executable = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "bin/qwen-worker.exe"
    if not executable.is_file():
        return _run_once(command, folder, cancel, on_stage)
    language = command[command.index("--tts-lang") + 1] if "--tts-lang" in command else "zh"
    key = (str(folder), tuple(command[command.index("--device"):]), language)
    try:
        if (_WORKER is None or _WORKER.process.poll() is not None
                or _WORKER.closed.is_set() or _WORKER.key != key):
            shutdown(clear_reference=False)
            if on_stage:
                on_stage("正在加载模型")
            _WORKER = _ResidentWorker(executable, command, folder)
            _WORKER.key = key
            _WORKER.wait("READY", cancel, on_stage)
        job = Path(command[command.index("-f") + 1]).parent.name
        _WORKER.process.stdin.write((job + "\n").encode("ascii"))
        _WORKER.process.stdin.flush()
        message = _WORKER.wait("DONE ", cancel, on_stage)
        _WORKER.last_used = time.monotonic()
        fields = message.split()
        log = f"generated {int(fields[1])} frames"
        if len(fields) > 2:
            log += "; stop=" + fields[2]
        return 0, log
    except BaseException as error:
        shutdown()
        if not isinstance(error, Exception):
            raise
        # Keep the shipped CLI as a recovery path for worker/driver failures.
        if on_stage:
            on_stage("刚才未能完成，正在重新尝试")
        code, log = _run_once(command, folder, cancel, on_stage)
        if code:
            log += "\n常驻引擎错误：" + str(error)
        return code, log


def _run_once(command, folder, cancel, on_stage):
    from offline import _check_cancel
    lines = []
    process = _native_popen(command, cwd=folder, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def read():
        for raw in iter(process.stdout.readline, b""):
            line = raw.decode("utf-8", "replace")
            lines.append(line)
            if "frames generated:" in line and on_stage:
                on_stage("正在生成配音，请稍候")
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    start = time.monotonic()
    try:
        while process.poll() is None:
            _check_cancel(cancel)
            if time.monotonic() - start > 300:
                raise RuntimeError("这段配音耗时过长，请缩短文案后重试。")
            time.sleep(0.1)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        reader.join()
        process.stdout.close()
    return process.returncode, "".join(lines)


def generate(text, voice, speed, volume, target, on_stage=None, on_progress=None, cancel=None):
    from audio_output import audio_output
    import numpy as np
    import offline
    if not package_installed():
        raise ValueError("请先在“克隆模型”页面下载 Qwen3-TTS 音质版。")
    ident = voice.removeprefix("local:qwen3_q8:clone:")
    item = next((item for item in offline.clones() if item["id"] == ident), None)
    if item is None:
        raise ValueError("找不到这个参考音色，请重新添加参考音频。")
    folder = package_dir()
    executable = folder / "runtime" / "llama-tts.exe"
    partial = Path(target).with_suffix(".part")
    from segmentation import split_text, prepare_join, missing_pause
    chunks = split_text(text)
    language = "en" if re.search(r"[A-Za-z]", text) and not re.search(r"[\u3400-\u9fff\uf900-\ufaff]", text) else "zh"
    while not _LOCK.acquire(timeout=0.1):
        offline._check_cancel(cancel)
    try:
        offline._check_cancel(cancel)
        if on_stage:
            on_stage("正在准备音色")
        device = _device(executable, folder)
        # Relative ASCII names work even under a Chinese Windows account/folder.
        with tempfile.TemporaryDirectory(prefix="job-", dir=folder) as temp:
            work = Path(temp)
            prefix = work.name + "/"
            reference, rate, reference_key = reference_audio(item["wav"])
            with wave.open(str(work / "reference.wav"), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(rate)
                output.writeframes(reference)
            (work / "reference.key").write_text(reference_key, encoding="ascii")
            cues, elapsed = [], 0.0
            with audio_output(partial, 24000, pcm=Path(target).suffix == ".wav") as write:
                index = 0
                while index < len(chunks):
                    chunk = chunks[index]
                    offline._check_cancel(cancel)
                    (work / "text.txt").write_text(offline._normalize_chinese_numbers(chunk), encoding="utf-8")
                    if on_stage:
                        on_stage(f"正在生成第 {index + 1} 段，共 {len(chunks)} 段")
                    def command(selected, seed):
                        # Qwen does not use llama.cpp's default min-p filter.
                        args = [str(executable), "-m", ASSETS[0]["name"], "-mm", ASSETS[1]["name"],
                            "-f", prefix + "text.txt", "--tts-lang", language,
                            "--tts-speaker-file", prefix + "reference.wav", "-o", prefix + "result.wav",
                            "-c", "2048", "-b", "128", "-ub", "128", "-n", "512", "-t", "6",
                            "--device", selected, "--mmproj-device", selected,
                            "-ngl", "0" if selected == "none" else "99", "--seed", str(seed),
                            "--temp", "0.9", "--top-k", "50", "--top-p", "1.0", "--min-p", "0.0",
                            "--repeat-penalty", "1.05", "--verbosity", "3"]
                        if selected == "none":
                            args.append("--no-mmproj-offload")
                        return args
                    for seed in (42, 43):
                        offline._check_cancel(cancel)
                        code, log = _run(command(device, seed), folder, cancel, on_stage)
                        if code and device != "none":
                            device = "none"
                            if on_stage:
                                on_stage("刚才未能完成，正在换一种方式生成")
                            code, log = _run(command(device, seed), folder, cancel, on_stage)
                        if code:
                            raise RuntimeError("Qwen3-TTS 合成失败：" + _failure_detail(code, log))
                        limited = "stop=limit" in log or ("stop=eos" not in log and "generated 512 frames" in log)
                        if not limited:
                            break
                        if seed == 42 and on_stage:
                            on_stage("这段未正常结束，正在重新生成")
                    if limited:
                        if len(chunk) <= 12:
                            raise RuntimeError(f"模型未能正常结束这段配音，重新生成后仍达到输出上限。\n问题文字：{chunk!r}\n请调整这段文字后重试。")
                        chunks[index:index + 1] = split_text(chunk, max(6, len(chunk) // 2))
                        if on_stage:
                            on_stage("这段文字较长，正在分成短句生成")
                        continue
                    pcm, rate = offline.read_wave(work / "result.wav")
                    pcm = offline._time_stretch(pcm, 1.0 / max(0.5, min(float(speed), 2)), rate)
                    pcm = prepare_join(pcm, rate)
                    gap = missing_pause(pcm, rate, chunk) if index < len(chunks) - 1 else 0
                    pcm = np.clip(pcm * float(volume) / 100 * 32767, -32768, 32767).astype("<i2")
                    write(pcm.tobytes())
                    end = elapsed + len(pcm) / rate
                    cues.append((elapsed, end, chunk))
                    elapsed = end
                    if index < len(chunks) - 1:
                        silence = np.zeros(gap, dtype="<i2")
                        write(silence.tobytes())
                        elapsed += gap / rate
                    if on_progress:
                        on_progress(min(sum(len(cue[2]) for cue in cues) / sum(map(len, chunks)), 0.99))
                    index += 1
            offline._check_cancel(cancel)
            partial.replace(target)
            from subtitles import write_srt
            write_srt(target, cues)
            return Path(target)
    finally:
        _LOCK.release()
        partial.unlink(missing_ok=True)
