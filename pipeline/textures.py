"""Draws the face images and set textures used by the Blender scenes.

Faces are cartoon "blocky avatar" style: white eyes with black pupils,
thick brows, simple mouth. Each expression has a closed-mouth and a
talking (open-mouth) version so characters can lip-flap while narrated.
"""
import math
import os
import random

from PIL import Image, ImageDraw, ImageFilter

S = 512  # face texture size

EXPRESSIONS = [
    "neutral", "happy", "smile", "sad", "shocked", "angry", "worried",
    "crying", "smug", "sleepy", "determined", "scared", "blank", "laugh",
]


def _eye(d, cx, cy, w, h, pdx=0, pdy=0, pupil=0.42, lid=0.0, lid_angle=0.0):
    box = [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2]
    d.ellipse(box, fill="white", outline="black", width=9)
    pw, ph = w * pupil, h * pupil * 1.15
    px, py = cx + pdx * w * 0.18, cy + pdy * h * 0.15
    d.ellipse([px - pw / 2, py - ph / 2, px + pw / 2, py + ph / 2], fill="black")
    # small highlight
    d.ellipse([px - pw * 0.1, py - ph * 0.32, px + pw * 0.18, py - ph * 0.08], fill="white")
    if lid > 0:
        # eyelid covering the top part (tired / angry / sad)
        top = cy - h / 2 - 6
        bottom = cy - h / 2 + h * lid
        tilt = lid_angle * w
        d.polygon([(cx - w / 2 - 8, top), (cx + w / 2 + 8, top),
                   (cx + w / 2 + 8, bottom + tilt), (cx - w / 2 - 8, bottom - tilt)],
                  fill=(0, 0, 0, 0))
        d.line([(cx - w / 2 - 2, bottom - tilt), (cx + w / 2 + 2, bottom + tilt)], fill="black", width=10)


def _brow(d, cx, cy, w, angle, thick=16):
    a = math.radians(angle)
    dx, dy = math.cos(a) * w / 2, math.sin(a) * w / 2
    d.line([(cx - dx, cy - dy), (cx + dx, cy + dy)], fill="black", width=thick)
    r = thick / 2
    for x, y in ((cx - dx, cy - dy), (cx + dx, cy + dy)):
        d.ellipse([x - r, y - r, x + r, y + r], fill="black")


def _mouth(d, kind, open_=False):
    cx, cy = S / 2, S * 0.74
    if open_ and kind not in ("sleepy",):
        # talking mouth: dark rounded shape with tongue
        h = {"shocked": 70, "scared": 60, "laugh": 62, "happy": 54}.get(kind, 40)
        w = {"shocked": 64, "scared": 70, "laugh": 120, "happy": 110, "smile": 90}.get(kind, 80)
        if kind in ("sad", "crying", "worried"):
            w = 70
        d.rounded_rectangle([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], radius=min(w, h) / 2.2,
                            fill=(40, 10, 10), outline="black", width=7)
        d.ellipse([cx - w * 0.28, cy + h * 0.05, cx + w * 0.28, cy + h / 2 - 4], fill=(220, 90, 100))
        if kind in ("happy", "laugh", "smile"):
            d.rectangle([cx - w / 2 + 10, cy - h / 2 + 5, cx + w / 2 - 10, cy - h / 2 + 15], fill="white")
        return
    if kind in ("happy", "laugh"):
        d.chord([cx - 70, cy - 55, cx + 70, cy + 45], 0, 180, fill=(40, 10, 10), outline="black", width=7)
        d.rectangle([cx - 58, cy - 6, cx + 58, cy + 6], fill="white")
    elif kind in ("smile", "determined"):
        d.arc([cx - 60, cy - 50, cx + 60, cy + 20], 20, 160, fill="black", width=10)
    elif kind == "smug":
        d.arc([cx - 40, cy - 40, cx + 80, cy + 10], 20, 120, fill="black", width=10)
    elif kind in ("sad", "crying"):
        d.arc([cx - 55, cy - 5, cx + 55, cy + 60], 200, 340, fill="black", width=10)
    elif kind == "worried":
        pts = [(cx - 50 + i * 10, cy + (6 if i % 2 else -6)) for i in range(11)]
        d.line(pts, fill="black", width=8, joint="curve")
    elif kind in ("shocked", "scared"):
        d.ellipse([cx - 28, cy - 34, cx + 28, cy + 34], fill=(40, 10, 10), outline="black", width=7)
    elif kind == "angry":
        d.arc([cx - 50, cy, cx + 50, cy + 50], 200, 340, fill="black", width=11)
    elif kind == "sleepy":
        d.ellipse([cx - 14, cy - 10, cx + 14, cy + 14], outline="black", width=7)
    else:  # neutral, blank
        d.line([(cx - 42, cy), (cx + 42, cy)], fill="black", width=10)


def draw_face(kind, open_=False):
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ey = S * 0.47
    lx, rx = S * 0.33, S * 0.67
    ew, eh = 100, 112
    pdx = pdy = 0
    lid = 0
    lid_angle = 0
    brow_y = S * 0.27
    bl, br = -6, 6  # brow angles (left brow, right brow)
    if kind in ("happy", "laugh"):
        if kind == "laugh":
            # closed happy eyes ^ ^
            for x in (lx, rx):
                d.arc([x - 50, ey - 30, x + 50, ey + 50], 200, 340, fill="black", width=12)
        else:
            _eye(d, lx, ey, ew, eh)
            _eye(d, rx, ey, ew, eh)
        bl, br = -10, 10
        brow_y -= 10
    elif kind == "sad" or kind == "crying":
        _eye(d, lx, ey, ew, eh, pdy=0.6)
        _eye(d, rx, ey, ew, eh, pdy=0.6)
        bl, br = -20, 20
        if kind == "crying":
            for x in (lx, rx):
                d.rounded_rectangle([x - 16, ey + 40, x + 16, ey + 190], radius=14, fill=(110, 190, 255, 230))
    elif kind in ("shocked", "scared"):
        _eye(d, lx, ey, ew + 16, eh + 22, pupil=0.25)
        _eye(d, rx, ey, ew + 16, eh + 22, pupil=0.25)
        bl, br = -8, 8
        brow_y -= 26
        if kind == "scared":
            d.ellipse([S * 0.8, S * 0.18, S * 0.86, S * 0.3], fill=(130, 200, 255, 230))
    elif kind == "angry":
        _eye(d, lx, ey, ew, eh - 10, pupil=0.48)
        _eye(d, rx, ey, ew, eh - 10, pupil=0.48)
        bl, br = 24, -24
        brow_y += 14
    elif kind == "worried":
        _eye(d, lx, ey, ew, eh, pdx=0.3)
        _eye(d, rx, ey, ew, eh, pdx=0.3)
        bl, br = -16, 16
    elif kind == "smug":
        _eye(d, lx, ey + 6, ew, eh - 30, pdx=0.6)
        _eye(d, rx, ey + 6, ew, eh - 30, pdx=0.6)
        bl, br = 0, 14
    elif kind == "sleepy":
        for x in (lx, rx):
            d.arc([x - 45, ey - 20, x + 45, ey + 30], 20, 160, fill="black", width=11)
        bl, br = 0, 0
    elif kind == "determined":
        _eye(d, lx, ey, ew, eh - 8, pupil=0.5)
        _eye(d, rx, ey, ew, eh - 8, pupil=0.5)
        bl, br = 14, -14
        brow_y += 6
    elif kind == "blank":
        _eye(d, lx, ey, ew - 20, eh - 20, pupil=0.3)
        _eye(d, rx, ey, ew - 20, eh - 20, pupil=0.3)
        bl, br = 0, 0
    else:  # neutral, smile
        _eye(d, lx, ey, ew, eh)
        _eye(d, rx, ey, ew, eh)
    _brow(d, lx, brow_y, 96, bl)
    _brow(d, rx, brow_y, 96, br)
    _mouth(d, kind, open_)
    return img


def wood(path, base=(176, 120, 72), plank=(160, 104, 60)):
    img = Image.new("RGB", (1024, 1024), base)
    d = ImageDraw.Draw(img)
    rnd = random.Random(3)
    for i in range(8):
        y = i * 128
        c = tuple(max(0, min(255, v + rnd.randint(-16, 16))) for v in plank)
        d.rectangle([0, y, 1024, y + 124], fill=c)
        for _ in range(14):
            yy = y + rnd.randint(4, 120)
            d.line([(0, yy), (1024, yy + rnd.randint(-6, 6))], fill=tuple(v - 14 for v in c), width=2)
        off = rnd.randint(0, 900)
        d.line([(off, y), (off, y + 124)], fill=tuple(v - 40 for v in c), width=4)
        d.line([(0, y + 124), (1024, y + 124)], fill=tuple(v - 50 for v in c), width=4)
    img.filter(ImageFilter.GaussianBlur(0.8)).save(path)


def checker(path, a=(235, 235, 240), b=(60, 70, 160), n=8):
    img = Image.new("RGB", (1024, 1024), a)
    d = ImageDraw.Draw(img)
    s = 1024 // n
    for i in range(n):
        for j in range(n):
            if (i + j) % 2:
                d.rectangle([i * s, j * s, i * s + s, j * s + s], fill=b)
    d2 = ImageDraw.Draw(img)
    for i in range(n + 1):
        d2.line([(i * s, 0), (i * s, 1024)], fill=(200, 200, 205), width=3)
        d2.line([(0, i * s), (1024, i * s)], fill=(200, 200, 205), width=3)
    img.save(path)


def rug(path):
    """Persian-style rug, like the cosy bedrooms in the reference style."""
    W, H = 1024, 1536
    img = Image.new("RGB", (W, H), (150, 30, 35))
    d = ImageDraw.Draw(img)
    for k, col in enumerate([(30, 30, 70), (220, 180, 120), (150, 30, 35), (30, 30, 70)]):
        m = 40 + k * 45
        d.rectangle([m, m, W - m, H - m], outline=col, width=30)
    rnd = random.Random(7)
    for _ in range(260):
        x, y = rnd.randint(230, W - 230), rnd.randint(230, H - 230)
        r = rnd.randint(8, 26)
        col = rnd.choice([(230, 190, 130), (40, 40, 90), (200, 80, 60), (240, 230, 210)])
        d.regular_polygon((x, y, r), 4, rotation=45, fill=col)
    cx, cy = W / 2, H / 2
    for r, col in [(260, (40, 40, 90)), (200, (230, 190, 130)), (140, (150, 30, 35)), (70, (240, 230, 210))]:
        d.regular_polygon((cx, cy, r), 8, fill=col)
    img.save(path)


def bricks(path, base=(165, 70, 55)):
    img = Image.new("RGB", (1024, 1024), (200, 195, 185))
    d = ImageDraw.Draw(img)
    rnd = random.Random(5)
    bh, bw = 48, 128
    for row in range(1024 // bh + 1):
        off = (row % 2) * bw // 2
        for col in range(-1, 1024 // bw + 1):
            x = col * bw + off
            y = row * bh
            c = tuple(max(0, min(255, v + rnd.randint(-18, 18))) for v in base)
            d.rectangle([x + 4, y + 4, x + bw - 4, y + bh - 4], fill=c)
    img.save(path)


def chalkboard(path, text_lines=("2 + 2 = 4", "Superpowers 101")):
    img = Image.new("RGB", (1536, 768), (38, 78, 58))
    d = ImageDraw.Draw(img)
    rnd = random.Random(2)
    for _ in range(40):
        x, y = rnd.randint(0, 1536), rnd.randint(0, 768)
        d.line([(x, y), (x + rnd.randint(40, 200), y + rnd.randint(-10, 10))], fill=(70, 110, 90), width=6)
    try:
        from PIL import ImageFont
        f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 90)
    except Exception:
        f = None
    for i, t in enumerate(text_lines):
        d.text((120, 160 + i * 200), t, fill=(235, 235, 225), font=f)
    img.save(path)


def poster(path, seed=1):
    rnd = random.Random(seed)
    img = Image.new("RGB", (512, 768), tuple(rnd.randint(40, 230) for _ in range(3)))
    d = ImageDraw.Draw(img)
    for _ in range(6):
        c = tuple(rnd.randint(40, 255) for _ in range(3))
        x, y, r = rnd.randint(0, 512), rnd.randint(0, 768), rnd.randint(40, 200)
        d.ellipse([x - r, y - r, x + r, y + r], fill=c)
    d.rectangle([0, 0, 511, 767], outline="white", width=18)
    img.save(path)


def build_all(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    for e in EXPRESSIONS:
        for open_ in (False, True):
            p = os.path.join(out_dir, f"face_{e}{'_open' if open_ else ''}.png")
            draw_face(e, open_).save(p)
    wood(os.path.join(out_dir, "wood.png"))
    wood(os.path.join(out_dir, "wood_light.png"), base=(214, 178, 128), plank=(200, 160, 110))
    checker(os.path.join(out_dir, "tiles_blue.png"))
    checker(os.path.join(out_dir, "tiles_gray.png"), a=(230, 230, 230), b=(150, 150, 160))
    rug(os.path.join(out_dir, "rug.png"))
    bricks(os.path.join(out_dir, "bricks.png"))
    chalkboard(os.path.join(out_dir, "chalkboard.png"))
    for i in range(4):
        poster(os.path.join(out_dir, f"poster{i}.png"), seed=i + 11)


if __name__ == "__main__":
    import sys
    build_all(sys.argv[1] if len(sys.argv) > 1 else "build/tex")
