"""Storyteller narration with Microsoft Edge neural voices (edge-tts).

Each narration line is split into sentences. Every sentence is spoken on its own
(slightly slower than normal), trimmed, and stitched back together with controlled
pauses, so the voice breathes like a storyteller instead of reading one long block.
Word timings from the voice are kept so captions land exactly on the spoken words.
"""
import asyncio
import hashlib
import json
import os
import re
import subprocess

import numpy as np
import soundfile as sf

SR = 24000
VOICE = "en-US-AndrewMultilingualNeural"
RATE = "-8%"          # about 0.92x
LAST_RATE = "-18%"    # softer, slower final line
LAST_VOLUME = "-12%"
PITCH = "-2Hz"        # a touch warmer
SENTENCE_PAUSE = 0.45
LINE_PAUSE = 0.55
TWIST_PAUSE = 1.1     # extra silence before the twist line


def sentences(line):
    """Split a narration line into sentences; '...' inside a sentence stays as a breath."""
    text = line.replace("*", "").strip()
    parts = [p.strip() for p in re.split(r'(?<=[.!?])\s+(?=[A-Z"\'])', text) if p.strip()]
    # the voice service returns nothing for one-word sentences: keep them with the one before
    out = []
    for p in parts:
        if out and len(re.findall(r"[A-Za-z0-9']+", p)) < 2:
            out[-1] = out[-1] + " " + p
        else:
            out.append(p)
    return out


async def _speak(text, voice, rate, volume, pitch, mp3, proxy):
    import edge_tts
    com = edge_tts.Communicate(text, voice, rate=rate, volume=volume, pitch=pitch,
                               boundary="WordBoundary", proxy=proxy)
    words = []
    with open(mp3, "wb") as f:
        async for chunk in com.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                words.append([chunk["offset"] / 1e7, (chunk["offset"] + chunk["duration"]) / 1e7, chunk["text"]])
    return words


def speak(text, out_dir, voice=VOICE, rate=RATE, volume="+0%", pitch=PITCH):
    """Return (mono float32 audio at SR, word timings) for one sentence, cached on disk."""
    key = hashlib.sha1(f"{voice}|{rate}|{volume}|{pitch}|{text}".encode()).hexdigest()[:16]
    mp3 = os.path.join(out_dir, f"tts_{key}.mp3")
    wav = mp3[:-4] + ".wav"
    meta = mp3[:-4] + ".json"
    if not (os.path.exists(wav) and os.path.exists(meta)):
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        last = None
        for attempt in range(5):
            try:
                words = asyncio.run(_speak(text, voice, rate, volume, pitch, mp3, proxy))
                if os.path.getsize(mp3) > 1000:
                    break
            except Exception as e:  # network hiccup: try again
                last = e
            import time
            time.sleep(3 * (attempt + 1))
        else:
            raise RuntimeError(f"edge-tts failed for {text!r}: {last}")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", mp3, "-ac", "1", "-ar", str(SR), wav], check=True)
        json.dump(words, open(meta, "w"))
    a, _ = sf.read(wav, dtype="float32")
    words = json.load(open(meta))
    # trim the voice's own silence at both ends, keep a few ms so consonants aren't clipped
    nz = np.where(np.abs(a) > 0.008)[0]
    if len(nz):
        s0 = max(0, nz[0] - int(0.03 * SR))
        s1 = min(len(a), nz[-1] + int(0.08 * SR))
        a = a[s0:s1]
        words = [[w0 - s0 / SR, w1 - s0 / SR, t] for w0, w1, t in words]
    return a, words


def build(shots, story, out_dir):
    """Narrate every shot. Returns a list of dicts: audio, words [(t0, t1, word)], pre, post."""
    os.makedirs(out_dir, exist_ok=True)
    voice = story.get("narrator", VOICE)
    n = len(shots)
    twist = next((i for i, s in enumerate(shots) if s.get("twist")), None)
    out = []
    for i, shot in enumerate(shots):
        last = i == n - 1
        rate = LAST_RATE if last else story.get("rate", RATE)
        vol = LAST_VOLUME if last else "+0%"
        pieces, words, t = [], [], 0.0
        sents = sentences(shot["line"])
        for k, s in enumerate(sents):
            try:
                a, w = speak(s, out_dir, voice=voice, rate=rate, volume=vol)
            except RuntimeError:
                if len(s.split()) > 2:
                    raise
                a, w = speak(s.rstrip(".!") + "...", out_dir, voice=voice, rate=rate, volume=vol)
            pieces.append(a)
            words += [[w0 + t, w1 + t, txt] for w0, w1, txt in w]
            t += len(a) / SR
            if k < len(sents) - 1:
                gap = np.zeros(int(SENTENCE_PAUSE * SR), dtype=np.float32)
                pieces.append(gap)
                t += SENTENCE_PAUSE
        audio = np.concatenate(pieces) if pieces else np.zeros(1, dtype=np.float32)
        out.append({
            "audio": audio,
            "words": words,
            "pre": TWIST_PAUSE if i == twist else (0.5 if last else 0.0),
            "post": LINE_PAUSE,
            "twist": i == twist,
        })
    return out
