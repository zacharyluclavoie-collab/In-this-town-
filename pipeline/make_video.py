"""Turns a story JSON into a finished 1080x1920 TikTok video.

Usage:
  python3 pipeline/make_video.py stories/2026-11-08-leo-mute-button.json
  python3 pipeline/make_video.py STORY --preview   # quick low-quality check

Steps: narration (Kokoro TTS) -> per-shot Blender renders -> captions,
music and final encode. Renders are cached in build/<slug>/ so a crashed
run can resume.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPE = os.path.join(ROOT, "pipeline")
sys.path.insert(0, PIPE)
import fx  # noqa: E402
import mastering  # noqa: E402
import music  # noqa: E402
import narration  # noqa: E402
import textures  # noqa: E402

MODEL_DIR = os.environ.get("KOKORO_DIR", os.path.expanduser("~/.cache/inthisworld"))
FONT = "/usr/share/fonts/truetype/roboto/unhinted/RobotoTTF/Roboto-BlackItalic.ttf"
BUBBLE_FONT = "/usr/share/fonts/truetype/roboto/unhinted/RobotoTTF/Roboto-Black.ttf"
FPS = 24
W, H = 1080, 1920
SR = 24000
GAP = 0.18  # silence after each narration line
LEAD = 0.35  # silence before the first line

CAST_FILE = os.path.join(ROOT, "cast.json")


def clean(text):
    return text.replace("*", "")


def tts(lines, voice, speed, out_dir):
    from kokoro_onnx import Kokoro
    k = Kokoro(os.path.join(MODEL_DIR, "kokoro.onnx"), os.path.join(MODEL_DIR, "voices.bin"))
    clips = []
    for i, line in enumerate(lines):
        p = os.path.join(out_dir, f"line_{i:02d}.wav")
        tp = p[:-4] + ".txt"
        same = os.path.exists(tp) and open(tp).read() == clean(line)
        if os.path.exists(p) and (same or not os.path.exists(tp)):
            a, _ = sf.read(p)
        else:
            a, sr = k.create(clean(line), voice=voice, speed=speed, lang="en-us")
            # trim leading/trailing silence
            nz = np.where(np.abs(a) > 0.01)[0]
            if len(nz):
                a = a[max(0, nz[0] - 600): nz[-1] + 1200]
            sf.write(p, a, SR)
            open(tp, "w").write(clean(line))
        clips.append(np.asarray(a, dtype=np.float32))
    return clips


STOP = set("""them they this that with your have been were what when then just from their there every
into about would could should said says will well also even still only some more most like over after
before because while where which who whom whose these those than very much many such each other""".split())


def chunk_caption(line, max_words=4):
    """Split a narration line into 2-4 word caption chunks; one word per chunk in CAPS."""
    words = line.split()
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        end = w.rstrip("*")[-1:] in ".,!?;:" if w.rstrip("*") else False
        if len(cur) >= max_words or (end and len(cur) >= 2):
            chunks.append(cur)
            cur = []
    if cur:
        if chunks and len(cur) == 1:
            chunks[-1] += cur
        else:
            chunks.append(cur)
    out = []
    for c in chunks:
        marked = [i for i, w in enumerate(c) if w.startswith("*")]
        if not marked:
            cand = [i for i, w in enumerate(c) if len(re.sub(r"\W", "", w)) > 3
                    and re.sub(r"\W", "", w).lower() not in STOP]
            marked = [max(cand, key=lambda i: len(c[i]))] if cand else []
        words = []
        for i, w in enumerate(c):
            w = w.replace("*", "")
            w = w.rstrip(",.;:")  # captions drop trailing punctuation except ?!
            words.append(w.upper() if i in marked else w)
        out.append(" ".join(words))
    return out


_font_cache = {}


def font(size):
    if size not in _font_cache:
        _font_cache[size] = ImageFont.truetype(FONT, size)
    return _font_cache[size]


def caption_image(text):
    """White bold-italic caption with a thick black outline, like the reference style."""
    size = 74
    f = font(size)
    while f.getlength(text) > W * 0.86 and size > 44:
        size -= 4
        f = font(size)
    tw = f.getlength(text)
    img = Image.new("RGBA", (W, 220), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x = (W - tw) / 2
    y = 60
    # soft drop shadow
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).text((x + 5, y + 7), text, font=f, fill=(0, 0, 0, 170), stroke_width=9, stroke_fill=(0, 0, 0, 170))
    img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(5)))
    d = ImageDraw.Draw(img)
    d.text((x, y), text, font=f, fill="white", stroke_width=8, stroke_fill="black")
    return img


def render_shot(shot_json, frames_dir, n):
    done = len([f for f in os.listdir(frames_dir) if f.endswith(".png")]) if os.path.isdir(frames_dir) else 0
    if done >= n:
        return
    os.makedirs(frames_dir, exist_ok=True)
    cmd = ["blender", "-b", "--factory-startup", "-P", os.path.join(PIPE, "scene.py"), "--", shot_json]
    r = subprocess.run(cmd, capture_output=True, text=True)
    got = len([f for f in os.listdir(frames_dir) if f.endswith(".png")])
    if got < n:
        sys.stderr.write(r.stdout[-3000:] + r.stderr[-3000:])
        raise SystemExit(f"render failed for {shot_json} ({got}/{n} frames)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("story")
    ap.add_argument("--preview", action="store_true", help="fast low-res render for checking")
    ap.add_argument("--out", help="output mp4 path")
    ap.add_argument("--keep", action="store_true", help="keep rendered frames")
    ap.add_argument("--stills", action="store_true", help="render one frame per shot into a contact sheet")
    a = ap.parse_args()

    story = json.load(open(a.story))
    cast = json.load(open(CAST_FILE))
    for k, v in story.get("cast", {}).items():  # merge, so a story can just recolor a hoodie
        cast[k] = {**cast.get(k, {}), **v}
    slug = story["slug"]
    build = os.path.join(ROOT, "build", slug + ("_preview" if a.preview else ""))
    tex = os.path.join(ROOT, "build", "tex")
    os.makedirs(build, exist_ok=True)
    if not os.path.exists(os.path.join(tex, "face_neutral_open.png")):
        textures.build_all(tex)

    shots = story["shots"]
    lines = [s["line"] for s in shots]
    edge = story.get("tts", "edge") == "edge"  # old stories keep the Kokoro voice they were made with
    if edge:
        nar = narration.build(shots, story, os.path.join(build, "tts"))
    else:
        nar = [{"audio": c, "words": [], "pre": 0.0, "post": GAP, "twist": False}
               for c in tts(lines, story.get("voice", "am_michael"), story.get("speed", 1.08), build)]
    clips = [n["audio"] for n in nar]

    # timeline: a shot's picture starts at t, its narration after an optional pause (before the twist)
    starts, durs = [], []
    t = 0.0
    for i, n in enumerate(nar):
        lead = (LEAD if i == 0 else 0.0) + n["pre"]
        d = lead + len(n["audio"]) / SR + n["post"] + shots[i].get("hold", 0.0)
        starts.append(t + lead)
        durs.append(d)
        t += d
    durs[-1] += 0.6 if not edge else 1.6  # room for the music to fade out
    # round shot boundaries on the cumulative timeline so audio and video never drift
    bounds, acc = [0], 0.0
    for d in durs:
        acc += d
        bounds.append(round(acc * FPS))
    shot_frames = [max(6, bounds[i + 1] - bounds[i]) for i in range(len(durs))]
    # make frame total match audio exactly
    total_frames = sum(shot_frames)
    total = total_frames / FPS

    # narration track
    voice = np.zeros(int(total * SR) + SR, dtype=np.float32)
    for st, c in zip(starts, clips):
        i = int(st * SR)
        voice[i:i + len(c)] += c[: max(0, len(voice) - i)]
    voice = voice[: int(total * SR)]

    # render shots: every narration line is cut into 1-3 camera parts
    res = [360, 640] if a.preview else [720, 1280]
    samples = 3 if a.preview else story.get("samples", 8)
    parts = []  # (shot index, part index, first frame in shot, frames, cam)
    for i, s in enumerate(shots):
        for j, (f0, n, cam) in enumerate(fx.plan_parts(s, shot_frames[i], FPS)):
            parts.append((i, j, f0, n, cam))
    stills = []
    for (i, j, f0, n, cam) in parts:
        s = shots[i]
        fd = os.path.join(build, f"shot_{i:02d}_{j}")
        spec = {
            "tex": tex, "out": fd + "/", "fps": FPS, "frames": shot_frames[i], "res": res,
            "range": [f0 + 1, f0 + n],
            "samples": samples, "set": s.get("set", "bedroom"), "time": s.get("time", "day"),
            "cast": {k: {**v, **s.get("cast", {}).get(k, {})} for k, v in cast.items()},
            "chars": s.get("chars", []), "cam": cam,
            "props": s.get("props", []), "seed": i + 1, "exposure": story.get("exposure", 0.05),
        }
        p = os.path.join(build, f"shot_{i:02d}_{j}.json")
        if a.stills:
            sp = os.path.join(build, f"still_{i:02d}_{j}.png")
            spec.update(still=True, still_frame=f0 + n // 2 + 1, res=[540, 960], samples=6, out=sp)
            json.dump(spec, open(p, "w"))
            subprocess.run(["blender", "-b", "--factory-startup", "-P", os.path.join(PIPE, "scene.py"), "--", p],
                           capture_output=True)
            stills.append((i, j, sp))
            continue
        json.dump(spec, open(p, "w"))
        print(f"[{slug}] shot {i + 1}/{len(shots)} cut {j + 1}: {s['set']} {n} frames", flush=True)
        render_shot(p, fd, n)

    def bubbles_for(i, heads_path):
        """[(image, x, y)] speech bubbles for shot i."""
        out = []
        try:
            heads = json.load(open(heads_path))
        except Exception:
            return out
        for ch in shots[i].get("chars", []):
            if ch.get("say") and ch["who"] in heads:
                probe = fx.bubble_image(ch["say"], BUBBLE_FONT)
                pos = fx.place_bubble(heads[ch["who"]], W, H, probe)
                if pos:
                    img = fx.bubble_image(ch["say"], BUBBLE_FONT, tail_dx=1 if pos[2] else -1)
                    out.append((img, pos[0], pos[1]))
        return out

    def finish(im):
        im = ImageEnhance.Color(im).enhance(1.12)
        return im.filter(ImageFilter.UnsharpMask(radius=2, percent=55, threshold=2))

    if a.stills:
        ims = []
        for (i, j, sp) in stills:
            im = Image.open(sp).convert("RGB") if os.path.exists(sp) else Image.new("RGB", (540, 960), "red")
            im = finish(im.resize((W, H)))
            for (b, bx, by) in bubbles_for(i, sp[:-4] + "_heads.json"):
                im.paste(b, (bx, by), b)
            if j == 0:
                ci = caption_image(chunk_caption(shots[i]["line"])[0])
                im.paste(ci, (0, int(H * 0.6)), ci)
            ims.append(im.resize((216, 384)))
        cols = 8
        rows = (len(ims) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * 216, rows * 384))
        for k, im in enumerate(ims):
            sheet.paste(im, ((k % cols) * 216, (k // cols) * 384))
        sp = os.path.join(build, "stills.png")
        sheet.save(sp)
        print("stills:", sp, f"total {total:.1f}s, {len(parts)} cuts")
        return

    # music + sound effects
    bed = music.make(total, story.get("mood", "emotional"), seed=len(slug))[: len(voice)]
    if len(bed) < len(voice):
        bed = np.pad(bed, (0, len(voice) - len(bed)))
    sfx = np.zeros_like(voice)
    shot_t = [b / FPS for b in bounds]
    soft = 0.35 if edge else 1.0  # new mixes keep effects small
    for k, (i, j, f0, n, cam) in enumerate(parts):
        t0 = shot_t[i] + f0 / FPS
        if k:
            fx.add(sfx, fx.whoosh(SR, seed=k), t0 - 0.16, SR, (0.5 if j == 0 else 0.3) * soft)
        if j == 0:
            chs = shots[i].get("chars", [])
            if any(c.get("say") for c in chs):
                fx.add(sfx, fx.pop(SR), t0 + 0.12, SR, soft)
            if any(c.get("fx") == "sparkle" for c in chs):
                fx.add(sfx, fx.shimmer(SR), t0 + 0.05, SR, 1.6 * soft if edge else 1.0)
            if cam.get("move") == "zoom" or cam.get("shake"):
                fx.add(sfx, fx.boom(SR), t0, SR, soft)
            if any(c.get("beat") for c in chs):  # heartbeat through the whole line
                hb = fx.heartbeat(SR)
                tt = t0 + 0.05
                while tt < shot_t[i + 1] - 0.3:
                    fx.add(sfx, hb, tt, SR, soft)
                    tt += 0.62
            if nar[i]["twist"]:  # two slow heartbeats in the silence before the twist
                for b in range(2):
                    fx.add(sfx, fx.heartbeat(SR), t0 + 0.1 + b * 0.55, SR, 0.6)
    wav = os.path.join(build, "mix.wav")
    report = None
    if edge:
        twist_i = next((i for i, n in enumerate(nar) if n["twist"]), None)
        report = mastering.master(voice, bed, sfx, SR, build, wav,
                                  twist_t=shot_t[twist_i] if twist_i is not None else None,
                                  last_t=shot_t[len(shots) - 1])
    else:
        env = np.abs(voice)
        k = int(0.25 * SR)
        env = np.convolve(env, np.ones(k) / k, mode="same")
        duck = 1 - 0.45 * np.clip(env / 0.05, 0, 1)
        mix = voice * 1.0 + bed * 0.16 * duck + sfx
        mix /= max(1.0, np.max(np.abs(mix)) / 0.95)
        sf.write(wav, mix, SR)

    # captions timeline: word timings from the voice when we have them
    caps = []
    for i, (st, c, s) in enumerate(zip(starts, clips, shots)):
        dur = len(c) / SR
        chunks = chunk_caption(s["line"])
        words = nar[i]["words"]
        end_line = st + dur + (nar[i]["post"] if edge else GAP)
        if words:
            times, wi = [], 0
            for ch in chunks:
                times.append(st + words[min(wi, len(words) - 1)][0])
                wi += len(ch.split())
            for k, ch in enumerate(chunks):
                caps.append((times[k], times[k + 1] if k + 1 < len(chunks) else end_line, ch))
        else:
            weights = [max(4, len(x)) for x in chunks]
            tot = sum(weights)
            tt = st
            for ch, w in zip(chunks, weights):
                cd = dur * w / tot
                caps.append((tt, tt + cd + (GAP if ch == chunks[-1] else 0), ch))
                tt += cd
    cap_imgs = {}

    out = a.out or os.path.join(ROOT, "videos", story.get("date", "undated"), slug + ".mp4")
    if a.preview:
        out = os.path.join(build, slug + "_preview.mp4")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    ff = subprocess.Popen([
        "ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
        "-i", "-", "-i", wav, "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
        "-profile:v", "high"] + ([] if edge else ["-af", "loudnorm=I=-14:TP=-1.5:LRA=11"]) + [
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart",
        "-shortest", out], stdin=subprocess.PIPE)
    fno = 0
    cap_y = int(H * 0.60)
    for (i, j, f0, n, cam) in parts:
        fd = os.path.join(build, f"shot_{i:02d}_{j}")
        files = sorted(f for f in os.listdir(fd) if f.endswith(".png"))[:n]
        bubs = bubbles_for(i, os.path.join(fd, "heads.json"))
        for fi, f in enumerate(files):
            im = finish(Image.open(os.path.join(fd, f)).convert("RGB").resize((W, H), Image.LANCZOS))
            t = fno / FPS
            age_b = (f0 + fi) / FPS - 0.12  # bubbles pop in just after the shot starts
            if age_b > 0:
                for (b, bx, by) in bubs:
                    if age_b < 0.12:
                        sc = 0.6 + 0.4 * age_b / 0.12
                        b2 = b.resize((max(1, int(b.width * sc)), max(1, int(b.height * sc))), Image.LANCZOS)
                        im.paste(b2, (bx + (b.width - b2.width) // 2, by + b.height - b2.height), b2)
                    else:
                        im.paste(b, (bx, by), b)
            cur = next((c for c in caps if c[0] <= t < c[1]), None)
            if cur:
                if cur[2] not in cap_imgs:
                    cap_imgs[cur[2]] = caption_image(cur[2])
                ci = cap_imgs[cur[2]]
                # tiny pop-in on each new caption
                age = t - cur[0]
                if age < 0.08:
                    sc = 0.9 + age / 0.08 * 0.1
                    ci2 = ci.resize((int(W * sc), int(ci.height * sc)), Image.LANCZOS)
                    im.paste(ci2, ((W - ci2.width) // 2, cap_y + (ci.height - ci2.height) // 2), ci2)
                else:
                    im.paste(ci, (0, cap_y), ci)
            ff.stdin.write(im.tobytes())
            fno += 1
    ff.stdin.close()
    ff.wait()
    print("wrote", out, f"{total:.1f}s")
    if report:
        i_lufs, tp = mastering.ebur128(out)
        report.update(final_lufs=i_lufs, true_peak_db=tp, voice=story.get("narrator", narration.VOICE))
        json.dump(report, open(os.path.join(build, "audio_report.json"), "w"), indent=1)
        print("audio:", json.dumps(report))
    if not a.keep and not a.preview:
        for (i, j, *_r) in parts:
            shutil.rmtree(os.path.join(build, f"shot_{i:02d}_{j}"), ignore_errors=True)


if __name__ == "__main__":
    main()
