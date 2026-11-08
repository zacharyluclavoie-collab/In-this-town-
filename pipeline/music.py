"""Procedural background music: soft piano arpeggios over a warm pad.

Moods:
  emotional - slow minor progression (default for heartfelt twists)
  hopeful   - major progression, a bit brighter
  tense     - low minor drone with sparse notes
"""
import numpy as np

SR = 24000

PROGRESSIONS = {
    "emotional": [[57, 60, 64], [53, 57, 60], [48, 52, 55], [55, 59, 62]],   # Am F C G
    "hopeful": [[48, 52, 55], [55, 59, 62], [57, 60, 64], [53, 57, 60]],     # C G Am F
    "tense": [[50, 53, 57], [50, 53, 58], [46, 50, 53], [49, 52, 57]],       # Dm Dm(b6) Bb A
    "mystery": [[52, 55, 59], [48, 52, 55], [50, 54, 57], [47, 50, 54]],     # Em C D Bm
}


def midi_hz(n):
    return 440.0 * 2 ** ((n - 69) / 12)


def piano(freq, dur, vel=0.5):
    t = np.arange(int(dur * SR)) / SR
    env = np.exp(-t * 3.2) * (1 - np.exp(-t * 400))
    sig = np.zeros_like(t)
    for h, a in [(1, 1.0), (2, 0.45), (3, 0.22), (4, 0.12), (5, 0.06)]:
        sig += a * np.sin(2 * np.pi * freq * h * t * (1 + 0.0004 * h)) * np.exp(-t * h * 0.6)
    return vel * sig * env


def pad(freqs, dur):
    t = np.arange(int(dur * SR)) / SR
    env = np.minimum(1, t / 0.8) * np.minimum(1, (dur - t) / 0.8)
    sig = np.zeros_like(t)
    for f in freqs:
        for det in (-0.6, 0.6):
            sig += np.sin(2 * np.pi * (f + det) * t) * 0.5
            sig += 0.15 * np.sin(2 * np.pi * (f * 2 + det) * t)
    return sig * env / len(freqs)


def reverb(x, secs=2.2, wet=0.28, seed=1):
    rng = np.random.default_rng(seed)
    n = int(secs * SR)
    ir = rng.standard_normal(n) * np.exp(-np.arange(n) / SR * 3.0)
    ir /= np.abs(ir).sum() ** 0.5 * 6
    L = len(x) + n
    nfft = 1 << (L - 1).bit_length()
    y = np.fft.irfft(np.fft.rfft(x, nfft) * np.fft.rfft(ir, nfft), nfft)[:len(x)]
    return x * (1 - wet) + y * wet


def make(total_secs, mood="emotional", seed=0):
    rng = np.random.default_rng(seed)
    prog = PROGRESSIONS.get(mood, PROGRESSIONS["emotional"])
    bpm = {"emotional": 72, "hopeful": 92, "tense": 64, "mystery": 70}.get(mood, 72)
    beat = 60 / bpm
    bar = beat * 4
    out = np.zeros(int((total_secs + 4) * SR))
    nbars = int(total_secs / bar) + 2
    pattern = [0, 1, 2, 1, 0 + 12, 2, 1, 2] if mood != "tense" else [0, -1, -1, 2, -1, -1, 1, -1]
    for b in range(nbars):
        chord = prog[b % len(prog)]
        t0 = b * bar
        # pad
        p = pad([midi_hz(n - 12) for n in chord], bar + 0.6) * 0.18
        i0 = int(t0 * SR)
        out[i0:i0 + len(p)] += p[:max(0, len(out) - i0)]
        # bass note
        bn = piano(midi_hz(chord[0] - 24), bar, 0.35)
        out[i0:i0 + len(bn)] += bn[:max(0, len(out) - i0)]
        # arpeggio in eighths
        for k, idx in enumerate(pattern):
            if idx < 0:
                continue
            note = chord[idx % 3] + (12 if idx >= 12 else 0) + 12
            tt = t0 + k * beat / 2
            v = 0.22 + 0.06 * rng.random()
            s = piano(midi_hz(note), 1.6, v)
            j = int(tt * SR)
            out[j:j + len(s)] += s[:max(0, len(out) - j)]
        # occasional melody note on top
        if mood in ("emotional", "hopeful", "mystery") and b % 2 == 1:
            note = chord[rng.integers(0, 3)] + 24
            s = piano(midi_hz(note), 2.0, 0.18)
            j = int((t0 + beat * 2) * SR)
            out[j:j + len(s)] += s[:max(0, len(out) - j)]
    out = reverb(out)
    out = out[: int(total_secs * SR)]
    fade = int(1.5 * SR)
    out[-fade:] *= np.linspace(1, 0, fade)
    out[: int(0.5 * SR)] *= np.linspace(0, 1, int(0.5 * SR))
    out /= np.max(np.abs(out)) + 1e-9
    return out.astype(np.float32)
