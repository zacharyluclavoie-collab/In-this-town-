"""Small helpers for the final video: auto camera cuts, comic speech bubbles, sound effects."""
import copy
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont

CLOSER = {"wide": "full", "full": "medium", "medium": "close", "close": "close", "extreme": "close"}
EMO = {"shocked", "scared", "angry", "crying", "worried"}


def plan_parts(shot, n_frames, fps):
    """Split one narration shot into 1-3 camera cuts so the video changes picture every ~1.5-2.5 s."""
    if shot.get("cams"):
        cams = shot["cams"]
    else:
        base = shot.get("cam", {})
        secs = n_frames / fps
        hug = any("hug" in (ch.get("act") if isinstance(ch.get("act"), list) else [ch.get("act")]) for ch in shot.get("chars", []))
        n = 1 if secs < 2.9 or shot.get("nocut") or hug or len(shot.get("chars", [])) >= 4 else (2 if secs < 5.6 else 3)
        cams = [base]
        chars = shot.get("chars", [])
        on = base.get("on")
        names = on if isinstance(on, list) else ([on] if on else [c["who"] for c in chars[:1]])
        for k in range(1, n):
            c = copy.deepcopy(base)
            if len(names) > 1:
                # cut to a single character: the talker, or the next one in the list
                talker = next((ch["who"] for ch in chars if ch.get("talk") and ch["who"] in names), None)
                who = talker or names[k % len(names)]
                c.update(on=who, shot="medium", front=None)
                c.pop("front", None)
                c["angle"] = (-1) ** k * 18
            else:
                c["shot"] = CLOSER.get(base.get("shot", "medium"), "close")
                if any(ch.get("fx") for ch in chars) and c["shot"] in ("close", "extreme"):
                    c["shot"] = "medium"  # sparkles too near the lens cover the face
                c["angle"] = base.get("angle", 0) + (-1) ** k * 22
                if base.get("shot") in ("close", "extreme"):
                    c["height"] = "low" if base.get("height") != "low" else "eye"
            c["move"] = "push"
            c.pop("follow", None)
            who = c.get("on") if isinstance(c.get("on"), str) else names[0] if names else None
            face = next((ch.get("face") for ch in chars if ch["who"] == who), None)
            if face in EMO:
                c["tilt"] = 7 * (-1) ** k
            cams.append(c)
    n = len(cams)
    cuts = [round(n_frames * i / n) for i in range(n + 1)]
    return [(cuts[i], cuts[i + 1] - cuts[i], cams[i]) for i in range(n)]


_fonts = {}


def _font(path, size):
    if (path, size) not in _fonts:
        _fonts[(path, size)] = ImageFont.truetype(path, size)
    return _fonts[(path, size)]


def bubble_image(text, font_path, tail_dx=-1):
    """White comic speech bubble with a black outline and a tail pointing down-left (or right)."""
    f = _font(font_path, 92)
    tw = f.getlength(text)
    bw, bh = int(tw + 100), 160
    img = Image.new("RGBA", (bw + 40, bh + 90), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x0, y0 = 20, 10
    tx = x0 + (bw * 0.28 if tail_dx < 0 else bw * 0.72)
    tail = [(tx - 26, y0 + bh - 12), (tx + 26, y0 + bh - 12), (tx + tail_dx * 40, y0 + bh + 66)]
    d.polygon(tail, fill="black")
    d.rounded_rectangle((x0, y0, x0 + bw, y0 + bh), radius=60, fill="black")
    inner = [(tx - 17, y0 + bh - 16), (tx + 17, y0 + bh - 16), (tx + tail_dx * 32, y0 + bh + 52)]
    d.rounded_rectangle((x0 + 8, y0 + 8, x0 + bw - 8, y0 + bh - 8), radius=52, fill="white")
    d.polygon(inner, fill="white")
    d.text((x0 + bw / 2, y0 + bh / 2 + 2), text, font=f, fill="black", anchor="mm")
    return img


def place_bubble(head, W, H, img):
    """Top-left corner for a bubble above a head at normalised screen position, or None if off screen."""
    x, y, z = head
    if z <= 0 or not (-0.1 < x < 1.1) or y > 0.95:
        return None
    left = x > 0.5  # put the bubble on the side with more room
    bx = int(x * W + (-img.width + 60 if left else -60))
    by = int(y * H - img.height - 10)
    bx = max(20, min(W - img.width - 20, bx))
    by = max(80, min(int(H * 0.5) - img.height, by))
    return bx, by, left


# ------------------------------------------------------------------ sound effects

def _env(n, a, r):
    e = np.ones(n)
    ai = max(1, int(n * a))
    e[:ai] = np.linspace(0, 1, ai)
    e[ai:] = np.exp(-np.linspace(0, r, n - ai))
    return e


def whoosh(sr, dur=0.32, seed=0):
    rng = np.random.default_rng(seed)
    n = int(dur * sr)
    x = rng.standard_normal(n)
    out, lp = np.zeros(n), 0.0
    for i in range(n):  # sweeping one-pole low-pass
        k = 0.05 + 0.35 * math.sin(math.pi * i / n)
        lp += k * (x[i] - lp)
        out[i] = lp
    return out * np.sin(np.linspace(0, math.pi, n)) ** 2 * 0.5


def pop(sr):
    n = int(0.09 * sr)
    t = np.arange(n) / sr
    f = np.linspace(900, 260, n)
    return np.sin(2 * np.pi * np.cumsum(f) / sr) * _env(n, 0.05, 6) * 0.35


def shimmer(sr):
    n = int(1.0 * sr)
    t = np.arange(n) / sr
    s = sum(np.sin(2 * np.pi * f * t) * a for f, a in ((1568, 1), (2093, 0.7), (2637, 0.5), (3136, 0.3)))
    trem = 0.6 + 0.4 * np.sin(2 * np.pi * 9 * t)
    return s * trem * _env(n, 0.04, 4) * 0.06


def boom(sr):
    n = int(0.5 * sr)
    t = np.arange(n) / sr
    f = np.linspace(110, 42, n)
    return np.sin(2 * np.pi * np.cumsum(f) / sr) * _env(n, 0.01, 5) * 0.5


def add(track, clip, at_sec, sr, gain=1.0):
    i = int(at_sec * sr)
    if i >= len(track):
        return
    j = min(len(track), i + len(clip))
    track[i:j] += clip[: j - i] * gain
