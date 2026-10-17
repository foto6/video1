"""Local storyboard production and the Windows operator entrypoint.

AI images and editorial decisions are supplied by the authoring agent in a
storyboard. Rendering is reproducible offline; no model review is fabricated.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap
import wave


ROOT = Path(__file__).resolve().parents[3]
VERSION = "creator.local_studio.v1"


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(args, *, cwd=None, log=None, timeout=600):
    result = subprocess.run([str(x) for x in args], cwd=cwd, capture_output=True,
                            encoding="utf-8", errors="replace", timeout=timeout,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if log:
        with Path(log).open("a", encoding="utf-8") as f:
            f.write(json.dumps([str(x) for x in args], ensure_ascii=False) + "\n")
            f.write(result.stdout + result.stderr + "\n")
    if result.returncode:
        raise RuntimeError(f"{Path(str(args[0])).name} failed ({result.returncode}): {result.stderr[-2500:]}")
    return result.stdout


def probe(path):
    return json.loads(run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path]))


def checked_manifest(path):
    path = Path(path).resolve()
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    if manifest.get("version") != 1 or not 1 <= len(manifest.get("scenes", [])) <= 8:
        raise ValueError("Storyboard must have version 1 and one to eight scenes")
    for scene in manifest["scenes"]:
        image = (path.parent / scene["image"]).resolve()
        if not image.is_relative_to(path.parent) or not image.is_file():
            raise ValueError("Every image must exist inside the storyboard folder")
        if image.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise ValueError("Unsupported image format")
        if sha(image) != scene.get("sha256"):
            raise ValueError(f"Image changed: {image.name}; update its storyboard digest intentionally")
        for name, limit in (("title", 70), ("caption", 180), ("narration", 250)):
            if not isinstance(scene.get(name), str) or not scene[name].strip() or len(scene[name]) > limit:
                raise ValueError(f"Scene {name} must be nonempty, at most {limit} characters")
    return manifest


def new_output(kind):
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    out = ROOT / "output" / f"{kind}-{stamp}"
    out.mkdir(parents=True, exist_ok=False)
    return out


def font_filter(name="arial.ttf"):
    font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
    if not font.is_file():
        raise ValueError(f"Missing font: {font}")
    return font.as_posix().replace(":", r"\:")


def narration(scene, folder, log):
    (folder / "narration.txt").write_text(scene["narration"], encoding="utf-8-sig")
    script = Path(__file__).resolve().parents[2] / "tools" / "studio-speech.ps1"
    run([str(Path(os.environ.get("WINDIR", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"),
         "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script,
         "-TextFile", folder / "narration.txt", "-OutputFile", folder / "voice.wav"], log=log, timeout=60)
    return float(probe(folder / "voice.wav")["format"]["duration"])


def make_score(path, duration):
    """Original ambient chord progression; no downloaded or licensed music."""
    import numpy as np
    rate = 48000
    t = np.arange(round(duration * rate), dtype=np.float64) / rate
    left = np.zeros(len(t)); right = np.zeros(len(t))
    chords = [(130.8128, 164.8138, 195.9977, 246.9417),
              (110.0, 130.8128, 164.8138, 195.9977),
              (87.3071, 110.0, 130.8128, 164.8138)]
    length = duration / len(chords)
    for i, chord in enumerate(chords):
        local = t - i * length
        env = np.clip(local / 1.8, 0, 1) * np.clip((length + 1.8 - local) / 2.8, 0, 1)
        for j, freq in enumerate(chord):
            amp = .042 * env * (1 + .11 * np.sin(2 * np.pi * .13 * t + j))
            left += amp * (np.sin(2 * np.pi * freq * t) + .16 * np.sin(2 * np.pi * freq * 2 * t))
            right += amp * (np.sin(2 * np.pi * freq * 1.001 * t) + .16 * np.sin(2 * np.pi * freq * 2.001 * t))
    # Sparse bell notes with soft attacks and long decays.
    for i, start in enumerate(np.arange(1.8, duration - 1, 2.4)):
        u = np.maximum(t - start, 0)
        env = np.where(t >= start, np.minimum(u / .05, 1) * np.exp(-u / 1.25), 0)
        freq = [523.251, 659.255, 783.991, 987.767, 659.255][i % 5]
        note = .045 * env * np.sin(2 * np.pi * freq * u)
        left += note * .85; right += note
    fade = np.clip(t / 1.5, 0, 1) * np.clip((duration - t) / 2, 0, 1)
    audio = np.stack([left * fade, right * fade], axis=1)
    audio = np.clip(audio, -.8, .8)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(2); f.setsampwidth(2); f.setframerate(rate)
        f.writeframes((audio * 32767).astype("<i2").tobytes())


def validate_final(path, expected_duration, log=None):
    data = probe(path)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
    duration = float(data.get("format", {}).get("duration", 0))
    checks = {
        "video_h264": video.get("codec_name") == "h264",
        "vertical_1080p": (video.get("width"), video.get("height")) == (1080, 1920),
        "pixel_format": video.get("pix_fmt") == "yuv420p",
        "audio_aac": audio.get("codec_name") == "aac",
        "duration": abs(duration - expected_duration) <= .2,
    }
    if not all(checks.values()):
        raise RuntimeError(f"Final video failed QA: {checks}")
    # Decode every frame and audio packet, so a successful probe is insufficient.
    run(["ffmpeg", "-v", "error", "-xerror", "-i", path, "-f", "null", "-"], log=log)
    checks["full_decode"] = True
    return {"passed": True, "checks": checks, "duration_seconds": duration,
            "sha256": sha(path), "size": Path(path).stat().st_size,
            "creative_review": "not_performed_by_this_renderer"}


def render_storyboard(manifest_path, progress=print):
    manifest_path = Path(manifest_path).resolve()
    manifest = checked_manifest(manifest_path)
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool): raise ValueError(f"{tool} is not installed")
    out = new_output("demo")
    log = out / "render.log"
    save(out / "storyboard.json", manifest)
    save(out / "status.json", {"state": "running", "version": VERSION})
    try:
        duration = 0.0; scenes = []
        for index, scene in enumerate(manifest["scenes"]):
            progress(f"Сцена {index + 1}/{len(manifest['scenes'])}: озвучка и анимация")
            folder = out / f"scene-{index + 1}"; folder.mkdir()
            voice_duration = narration(scene, folder, log)
            seconds = math.ceil(max(6.5, voice_duration + 2.2) * 30) / 30
            if seconds > 20: raise ValueError("Narration is too long for a scene")
            source = manifest_path.parent / scene["image"]
            shutil.copy2(source, folder / "image.png")
            (folder / "title.txt").write_text(scene["title"], encoding="utf-8", newline="\n")
            (folder / "caption.txt").write_text(textwrap.fill(scene["caption"], 29), encoding="utf-8", newline="\n")
            (folder / "chapter.txt").write_text(f"0{index+1}  /  0{len(manifest['scenes'])}     {manifest['title'].upper()}", encoding="utf-8", newline="\n")
            frames = round(seconds * 30)
            zoom = "1.03+0.08*on/" + str(frames) if index % 2 == 0 else "1.11-0.08*on/" + str(frames)
            alpha = f"min(1,max(0,(t-0.3)/0.6))*min(1,max(0,({seconds}-.2-t)/.6))"
            filters = (
                "scale=2160:3840:force_original_aspect_ratio=increase,crop=2160:3840,"
                f"zoompan=z='{zoom}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d={frames}:s=1080x1920:fps=30,"
                "setsar=1,vignette=angle=PI/5,"
                f"drawtext=fontfile='{font_filter()}':textfile=chapter.txt:expansion=none:fontsize=24:fontcolor=0xB9D4E7:x=90:y=185,"
                f"drawtext=fontfile='{font_filter('arialbd.ttf')}':textfile=title.txt:expansion=none:fontsize=82:line_spacing=10:fontcolor=white:x=86:y=285:shadowcolor=black@0.5:shadowx=1:shadowy=3:alpha='{alpha}',"
                f"drawtext=fontfile='{font_filter()}':textfile=caption.txt:expansion=none:fontsize=46:line_spacing=14:fontcolor=white:x=(w-text_w)/2:y=1500:box=1:boxcolor=black@0.35:boxborderw=18:alpha='{alpha}',"
                f"fade=t=in:st=0:d=0.25,fade=t=out:st={seconds-.35}:d=0.35,format=yuv420p"
            )
            run(["ffmpeg", "-hide_banner", "-v", "warning", "-nostdin", "-i", "image.png", "-i", "voice.wav",
                 "-vf", filters, "-af", "adelay=850|850,apad", "-t", str(seconds),
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-threads", "2",
                 "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "192k", "-movflags", "+faststart", "clip.mp4"], cwd=folder, log=log)
            scenes.append({"path": f"scene-{index+1}/clip.mp4", "duration": seconds, "start": duration,
                           "voice_duration": voice_duration, "image_sha256": scene["sha256"]})
            duration += seconds
        progress("Сборка, музыка и проверка готового видео")
        (out / "clips.txt").write_text("".join(f"file '{s['path']}'\n" for s in scenes), encoding="utf-8")
        run(["ffmpeg", "-v", "warning", "-nostdin", "-f", "concat", "-safe", "1", "-i", "clips.txt", "-c", "copy", "assembly.mp4"], cwd=out, log=log)
        make_score(out / "score.wav", duration)
        mix = ("[0:a]aresample=48000,loudnorm=I=-18:TP=-2:LRA=9,asplit=2[voice][side];"
               "[1:a]volume=0.65[bed];[bed][side]sidechaincompress=threshold=0.03:ratio=5:attack=30:release=500[duck];"
               "[voice][duck]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=9[a]")
        run(["ffmpeg", "-v", "warning", "-nostdin", "-i", "assembly.mp4", "-i", "score.wav", "-filter_complex", mix,
             "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
             "-t", str(duration), "-movflags", "+faststart", "final.mp4"], cwd=out, log=log)
        qa = validate_final(out / "final.mp4", duration, log)
        save(out / "qa.json", qa)
        run(["ffmpeg", "-v", "error", "-nostdin", "-ss", "2", "-i", "final.mp4", "-frames:v", "1", "poster.jpg"], cwd=out, log=log)
        run(["ffmpeg", "-v", "error", "-nostdin", "-i", "final.mp4", "-vf", "scale=360:640", "-c:v", "libx264",
             "-preset", "veryfast", "-crf", "26", "-c:a", "aac", "-movflags", "+faststart", "preview.mp4"], cwd=out, log=log)
        srt = []
        for i, (scene, timing) in enumerate(zip(manifest["scenes"], scenes), 1):
            def ts(s):
                ms = round(s * 1000); return f"{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}"
            srt.append(f"{i}\n{ts(timing['start']+.85)} --> {ts(timing['start']+.85+timing['voice_duration'])}\n{scene['narration']}\n")
        (out / "subtitles.srt").write_text("\n".join(srt), encoding="utf-8-sig")
        save(out / "receipt.json", {"version": VERSION, "state": "LOCAL_VIDEO_READY", "manifest_sha256": sha(manifest_path),
             "final": str(out / "final.mp4"), "qa": qa, "scenes": scenes, "asset_provenance": manifest.get("provenance"),
             "motion": "animated_AI_stills", "voice": "Microsoft Irina Desktop", "music": "original_procedural_score",
             "live_model_review": False, "published": False})
        save(out / "status.json", {"state": "complete", "final": str(out / "final.mp4")})
        save(ROOT / "latest.json", {"folder": str(out), "final": str(out / "final.mp4")})
        progress(f"Готово: {out / 'final.mp4'}")
        return out
    except Exception as exc:
        save(out / "status.json", {"state": "failed", "error": str(exc)})
        raise


def edit_input(source, brief, progress=print):
    from .mvp import run_pipeline
    out = new_output("edit")
    progress("Монтаж исходника: вертикальный формат, титры и проверка")
    result = run_pipeline(input_path=source, brief_arg=brief, out_dir=out, style="auto",
                          media_repo=str(ROOT / "media-mvp"), semantic_provider="local")
    save(ROOT / "latest.json", {"folder": str(out), "final": str(out / "final.mp4")})
    progress(f"Готово: {out / 'final.mp4'}")
    return out


def doctor():
    tools = {t: shutil.which(t) for t in ("ffmpeg", "ffprobe", "node", "git")}
    pins = {}
    for folder in ("creator", "media", "media-mvp", "growth"):
        try: pins[folder] = run(["git", "rev-parse", "HEAD"], cwd=ROOT / folder).strip()
        except Exception: pins[folder] = None
    return {"version": VERSION, "root": str(ROOT), "tools": tools, "repositories": pins,
            "ready": all(tools.values()) and all(pins.values()),
            "new_topic": "Agent supplies a storyboard and AI assets; local rendering then runs offline.",
            "automatic_model_review": False, "publishing_enabled": False}


def gui():
    import queue
    import threading
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    app = tk.Tk(); app.title("AI Video Studio"); app.geometry("760x560"); app.minsize(680, 500)
    app.configure(bg="#101722")
    style = ttk.Style(); style.theme_use("clam")
    style.configure("TButton", font=("Segoe UI", 12), padding=12)
    panel = tk.Frame(app, bg="#101722"); panel.pack(fill="both", expand=True, padx=30, pady=25)
    tk.Label(panel, text="AI Video Studio", font=("Segoe UI", 26, "bold"), fg="white", bg="#101722").pack(anchor="w")
    tk.Label(panel, text="Сценарий → кадры → голос → монтаж → MP4", font=("Segoe UI", 12), fg="#B6C4D6", bg="#101722").pack(anchor="w", pady=(6, 16))
    events = queue.Queue(); busy = [False]
    log = tk.Text(panel, height=9, bg="#182333", fg="#DCE7F4", font=("Segoe UI", 11), wrap="word", state="disabled")
    buttons = []
    def append(text):
        log.config(state="normal"); log.insert("end", text + "\n"); log.see("end"); log.config(state="disabled")
    def start(fn):
        if busy[0]: return
        busy[0] = True
        for b in buttons: b.config(state="disabled")
        def worker():
            try: events.put(("done", fn(lambda x: events.put(("log", x)))))
            except Exception as exc: events.put(("error", str(exc)))
        threading.Thread(target=worker, daemon=True).start()
    def own_video():
        source = filedialog.askopenfilename(title="Выбери исходное видео", filetypes=[("Видео", "*.mp4 *.mov *.mkv *.webm"), ("Все файлы", "*.*")])
        selected_brief = brief.get().strip() or "Смотри, как это работает"
        if source: start(lambda cb: edit_input(source, selected_brief, cb))
    def last_video():
        latest = ROOT / "latest.json"
        if latest.exists(): os.startfile(json.loads(latest.read_text(encoding="utf-8"))["final"])
        else: messagebox.showinfo("Ролики", "Сначала собери демонстрацию или выбери исходник.")
    for label, fn in [("Собрать демонстрацию «Выше горизонта»", lambda: start(lambda cb: render_storyboard(ROOT / "assets/demo/storyboard.json", cb))),
                      ("Смонтировать своё видео", own_video), ("Открыть последний ролик", last_video)]:
        button = ttk.Button(panel, text=label, command=fn); button.pack(fill="x", pady=4); buttons.append(button)
    tk.Label(panel, text="Краткая задача для своего видео (первые 30 секунд):", fg="#B6C4D6", bg="#101722").pack(anchor="w", pady=(12, 3))
    brief = ttk.Entry(panel, font=("Segoe UI", 11)); brief.insert(0, "Покажи главное коротко и понятно"); brief.pack(fill="x")
    log.pack(fill="both", expand=True, pady=(15, 0))
    append("Демо: ИИ-изображения, движение камеры, русский голос и музыка.\nДля новой темы попроси Codex подготовить новый ролик. Результаты сохраняются в папку output.")
    def poll():
        while not events.empty():
            kind, value = events.get()
            if kind == "log": append(value)
            else:
                busy[0] = False
                for b in buttons: b.config(state="normal")
                if kind == "error": append("Ошибка: " + value); messagebox.showerror("Рендер", value)
                else: append("Можно открыть готовый ролик кнопкой выше.")
        app.after(150, poll)
    def close():
        if busy[0]: messagebox.showinfo("Идёт рендер", "Дождись окончания рендера перед закрытием окна.")
        else: app.destroy()
    app.protocol("WM_DELETE_WINDOW", close); poll(); app.mainloop()


def main(argv=None):
    parser = argparse.ArgumentParser(description="AI Video Studio")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("gui"); sub.add_parser("doctor")
    render = sub.add_parser("render"); render.add_argument("--storyboard", default=str(ROOT / "assets/demo/storyboard.json"))
    edit = sub.add_parser("edit"); edit.add_argument("--input", required=True); edit.add_argument("--brief", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command in {None, "gui"}: gui()
        elif args.command == "doctor": print(json.dumps(doctor(), ensure_ascii=False, indent=2))
        elif args.command == "render": render_storyboard(args.storyboard)
        else: edit_input(args.input, args.brief)
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr); return 1


if __name__ == "__main__":
    raise SystemExit(main())
