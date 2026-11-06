"""Exercise the actual packaged UI, online synthesis, decoder and export."""
import json
import time
import traceback


def run(app_type, output):
    output.mkdir(parents=True, exist_ok=True)
    app = None
    report = {}
    try:
        app = app_type()
        import sys
        ui = sys.modules[app_type.__module__]
        def fail_dialog(title, text, **kwargs):
            raise RuntimeError(f"{title}: {text}")
        app.show_error = fail_dialog
        app.show_notice = fail_dialog
        app.withdraw()
        app.update()
        report["voices"] = len(app.voices)
        assert len(app.voice_rows) == len(app.voices)
        app.locale_value.set("中文 · 普通话")
        app.change_locale(None)
        assert len(app.voice_rows) == 6
        app.filter_buttons["女声"].invoke()
        assert len(app.voice_rows) == 2
        app.filter_buttons["男声"].invoke()
        assert len(app.voice_rows) == 4
        app.filter_buttons["全部"].invoke()
        app.select_voice("zh-CN-XiaoxiaoNeural")
        report["filters"] = "passed"
        for preview in (True, False):
            if not preview:
                app.text.insert("1.0", "你好，这是免费配音 Windows 客户端的实际生成测试。音频通过微软在线服务生成，直接保存在你的电脑。")
                app.count_text()
                app.speed.set(1.1)
                app.volume.set(85)
            app.generate(preview)
            deadline = time.monotonic() + 200
            while app.busy and time.monotonic() < deadline:
                app.update()
                time.sleep(0.05)
            assert not app.busy, "Synthesis timed out"
            assert app.latest and app.latest.stat().st_size > 1000
            assert app.audio_ready, "Audio playback could not initialize"
            import pygame
            length = pygame.mixer.Sound(str(app.latest)).get_length()
            assert length > 1
            target = output / ("preview.mp3" if preview else "generated.mp3")
            original = ui.filedialog.asksaveasfilename
            ui.filedialog.asksaveasfilename = lambda **kwargs: str(target)
            try:
                app.save_audio()
            finally:
                ui.filedialog.asksaveasfilename = original
            assert target.read_bytes() == app.latest.read_bytes()
            report[target.name] = {"bytes": target.stat().st_size, "seconds": round(length, 2)}
            app.stop_audio()
        app.clear_text()
        assert app.text.get("1.0", "end-1c") == ""
        report["result"] = "passed"
    except Exception:
        report["result"] = "failed"
        report["error"] = traceback.format_exc()
    finally:
        if app is not None:
            app.close()
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def run_offline(app_type, output):
    """Exercise an installed clone model through the UI and MP3 exporter."""
    import os
    import sys
    from unittest.mock import patch
    import pygame
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {}
    with patch.object(app_type, "refresh_voices"):
        app = app_type()
    ui = sys.modules[app_type.__module__]
    errors = []
    def fail_dialog(title, text, **kwargs):
        errors.append(f"{title}: {text}")
        raise RuntimeError(f"{title}: {text}")
    app.show_error = fail_dialog
    app.show_notice = fail_dialog
    try:
        app.withdraw()
        app.update()
        model = os.environ.get("FREEVOICE_SMOKE_MODEL", "zipvoice")
        from clone_models import MODEL_INFO
        if model != app.clone_model:
            with patch.object(ui, "set_active_model"):
                app.change_clone_model(MODEL_INFO[model]["label"])
        assert app.clone_model == model
        for provider in ("克隆语音",):
            app.provider_menu.set(provider)
            app.change_provider(provider)
            assert app.voice_rows, f"No {provider} models installed"
            assert app.voices
            app.filter_voices("男声")
            assert len(app.voice_rows) == sum(v["Gender"] == "Male" for v in app.voices)
            app.filter_voices("女声")
            assert len(app.voice_rows) == sum(v["Gender"] == "Female" for v in app.voices)
            app.filter_voices("全部")
            app.text.delete("1.0", "end")
            app.text.insert("1.0", "你好，这是本地离线配音。今天是2026年10月20日，欢迎试听。")
            app.speed.set(1.1)
            app.volume.set(85)
            # Any accidental network access during synthesis fails this check.
            with patch("urllib.request.urlopen", side_effect=AssertionError("Unexpected network access")):
                app.generate(False)
                deadline = time.monotonic() + 180
                while app.busy and time.monotonic() < deadline:
                    app.update()
                    time.sleep(0.03)
            assert not app.busy and app.latest, "; ".join(errors) or "Synthesis did not finish"
            if model == "qwen3_q8":
                import qwen_backend
                assert qwen_backend._WORKER is not None, "Qwen worker fell back to the CLI"
                assert qwen_backend._WORKER.process.poll() is None, "Qwen worker exited after synthesis"
                report["resident_worker"] = "passed"
            seconds = pygame.mixer.Sound(str(app.latest)).get_length()
            assert seconds > 1
            destination = output / (model + ".mp3")
            with patch.object(ui.filedialog, "asksaveasfilename", return_value=str(destination)):
                app.save_audio()
            assert destination.read_bytes() == app.latest.read_bytes()
            from offline import read_audio
            samples, sample_rate = read_audio(destination, max_seconds=20)
            assert len(samples) / sample_rate > 1
            if model == "qwen3_q8":
                import numpy as np
                active = np.flatnonzero(np.abs(samples) > .001)
                assert len(active), "Qwen generated silent audio"
                leading = active[0] / sample_rate
                assert leading < .35, f"Qwen leading silence: {leading:.2f}s"
                report["leading_silence_seconds"] = round(leading, 3)
            import subprocess
            from pathlib import Path
            root = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
            ffmpeg = root / "bin" / "ffmpeg.exe"
            formats = []
            with patch.dict(os.environ, {"PATH": ""}):
                for suffix, codec in (("m4a", "aac"), ("wma", "wmav2")):
                    reference = output / (model + "." + suffix)
                    subprocess.run([str(ffmpeg), "-v", "error", "-y", "-i", str(destination),
                                    "-c:a", codec, str(reference)], check=True, capture_output=True,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    decoded, rate = read_audio(reference, max_seconds=20)
                    assert len(decoded) / rate > 1
                    formats.append(suffix)
            report["bundled_ffmpeg_imports_without_path"] = formats
            import asyncio
            import offline
            from engine import synthesize
            from pauses import read_cues
            reading_text = "2026年，这是MD5和MD56的文字说明，共56个。"
            reading_output = output / "numbers.mp3"
            spoken = []
            normalize = offline._normalize_chinese_numbers
            def capture_normalize(text):
                value = normalize(text)
                spoken.append(value)
                return value
            with patch.object(offline, "_normalize_chinese_numbers", side_effect=capture_normalize):
                asyncio.run(synthesize(reading_text, app.selected, 1, 100, reading_output, lexicon={}))
            assert any("MD五六" in value for value in spoken)
            assert any("五十六个" in value for value in spoken)
            assert any("二零二六年" in value for value in spoken)
            assert "".join(cue[2] for cue in read_cues(reading_output)) == reading_text
            report["md5_default_reading_input"] = "MD五"
            report["year_default_reading_input"] = "二零二六年"
            report["identifier_default_reading_input"] = "MD五六"
            report["quantity_default_reading_input"] = "五十六个"
            if model == "qwen3_q8":
                short_output = output / "short-qwen.mp3"
                asyncio.run(synthesize("没", app.selected, 1, 100, short_output, lexicon={}))
                short_samples, short_rate = read_audio(short_output, max_seconds=5)
                assert np.any(np.abs(short_samples) > .001), "Short Qwen output is silent"
                assert "".join(cue[2] for cue in read_cues(short_output)) == "没"
                report["short_chunk_end_of_speech"] = "passed"
            report[provider] = {"voices": len(app.voices), "bytes": destination.stat().st_size,
                                "seconds": round(seconds, 2), "mp3_reference_decode": "passed"}
            app.stop_audio()
            started = time.monotonic()
            app.preview_voice(app.selected)
            deadline = time.monotonic() + 180
            while app.busy and time.monotonic() < deadline:
                app.update()
                time.sleep(0.03)
            assert not app.busy and app.latest
            report[provider]["quick_preview_seconds"] = round(time.monotonic() - started, 2)
            cached = app.latest
            if model == "qwen3_q8":
                samples, sample_rate = read_audio(cached, max_seconds=20)
                active = np.flatnonzero(np.abs(samples) > .001)
                assert len(active), "Qwen preview is silent"
                leading = active[0] / sample_rate
                assert leading < .35, f"Qwen preview leading silence: {leading:.2f}s"
                report["preview_leading_silence_seconds"] = round(leading, 3)
            app.preview_voice(app.selected)
            assert not app.busy and app.latest == cached
            report[provider]["preview_cache"] = "passed"
            app.stop_audio()
        report["result"] = "passed"
    except Exception:
        report["result"] = "failed"
        report["error"] = traceback.format_exc()
    finally:
        app.close()
        if errors:
            report["dialogs"] = errors
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
