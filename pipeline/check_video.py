"""Check a finished In This World video against the posting rules.

Usage: python3 pipeline/check_video.py stories/FILE.json
Prints each check and exits non-zero if any fails.
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
import mastering  # noqa: E402


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels",
                          "-show_entries", "format=duration", "-of", "json", path],
                         capture_output=True, text=True).stdout
    return json.loads(out)


def main():
    story = json.load(open(sys.argv[1]))
    slug = story["slug"]
    mp4 = os.path.join(ROOT, "videos", story["date"], slug + ".mp4")
    build = os.path.join(ROOT, "build", slug)
    p = probe(mp4)
    v = next(s for s in p["streams"] if s["codec_type"] == "video")
    a = next(s for s in p["streams"] if s["codec_type"] == "audio")
    dur = float(p["format"]["duration"])
    num, den = map(int, v["r_frame_rate"].split("/"))
    lufs, tp = mastering.ebur128(mp4)
    tl = json.load(open(os.path.join(build, "timeline.json")))
    rep = json.load(open(os.path.join(build, "audio_report.json")))
    cap = story.get("caption", "")
    tags = [w for w in cap.split() if w.startswith("#")]
    checks = [
        ("length 40-55 s", 40 <= dur <= 55, f"{dur:.1f} s"),
        ("1080x1920", (v["width"], v["height"]) == (1080, 1920), f"{v['width']}x{v['height']}"),
        ("30 fps H.264", num / den == 30 and v["codec_name"] == "h264", f"{num / den:g} fps {v['codec_name']}"),
        ("48 kHz stereo AAC", a["codec_name"] == "aac" and a["sample_rate"] == "48000" and a["channels"] == 2,
         f"{a['codec_name']} {a['sample_rate']} Hz {a['channels']} ch"),
        ("loudness -14 LUFS (+-1)", abs(lufs + 14) <= 1.0, f"{lufs:.1f} LUFS"),
        ("true peak <= -1.0 dB", tp <= -1.0, f"{tp:.1f} dB"),
        ("voice clearly over music (>= 6 dB)", rep["voice_over_music_db"] >= 6, f"{rep['voice_over_music_db']} dB"),
        ("narrator pauses present", tl["sentence_pauses"] >= 5, f"{tl['sentence_pauses']} sentence pauses"),
        ("twist at 72-88 %", tl["twist_at"] is not None and 0.72 <= tl["twist_at"] <= 0.88,
         f"{(tl['twist_at'] or 0) * 100:.0f} %"),
        ("hook text <= 6 words", 0 < len(story.get("hook_text", "").split()) <= 6, story.get("hook_text", "")),
        ("caption < 250 chars, 3-5 hashtags, no #fyp", len(cap) < 250 and 3 <= len(tags) <= 5
         and not {"#fyp", "#foryou", "#viral", "#foryoupage"} & {t.lower() for t in tags}, f"{len(cap)} chars {tags}"),
    ]
    bad = 0
    for name, ok, val in checks:
        print(("PASS " if ok else "FAIL ") + f"{name}: {val}")
        bad += not ok
    print(f"voice: {rep.get('voice')}  voice {rep['voice_lufs']} LUFS / music {rep['music_lufs']} LUFS (before final gain)")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
