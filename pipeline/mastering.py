"""Clean, mix and master the soundtrack of an In This World video with ffmpeg.

voice  -> highpass 80 Hz, light denoise, de-esser, gentle compression, +3 dB presence at 3 kHz
music  -> about 8 dB under the voice, ducked further by the voice (sidechain), swells at the twist,
          fades in at the start and out over the last 2 s
sfx    -> quiet accents (whoosh, chime, heartbeat)
master -> two-pass loudnorm to -14 LUFS, true peak -1.5 dB, 48 kHz stereo
"""
import json
import os
import re
import subprocess

import numpy as np
import soundfile as sf

VOICE_CHAIN = ("highpass=f=80,afftdn=nf=-30:nr=8,deesser=i=0.35:m=0.5:f=0.5,"
               "acompressor=threshold=-20dB:ratio=2.5:attack=8:release=120:makeup=1.5,"
               "equalizer=f=3000:t=o:w=1.2:g=3")
TARGET_I, TARGET_TP, TARGET_LRA = -14.0, -1.5, 11.0
MUSIC_UNDER_VOICE_DB = 8.0   # music bed sits ~-22 LUFS when the voice is ~-14 LUFS


def _ff(args):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-y"] + args, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[-2000:])
    return r.stderr


def loudness(path, extra_filter=""):
    """Integrated loudness / true peak / LRA as measured by loudnorm (first pass)."""
    flt = (extra_filter + "," if extra_filter else "") + \
        f"loudnorm=I={TARGET_I}:TP={TARGET_TP}:LRA={TARGET_LRA}:print_format=json"
    err = _ff(["-i", path, "-af", flt, "-f", "null", "-"])
    js = json.loads(re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", err, re.S).group(0))
    return js


def ebur128(path):
    """Integrated loudness (LUFS) and true peak (dBTP) of a finished file."""
    err = _ff(["-i", path, "-af", "ebur128=peak=true", "-f", "null", "-"])
    i = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", err)[-1])
    tp = float(re.findall(r"Peak:\s+(-?[\d.]+) dBFS", err)[-1])
    return i, tp


def music_envelope(n, sr, twist_t=None, end_t=None):
    """Gain curve for the music: fade in 1.5 s, swell +4 dB from the twist, fade out over the last 2 s."""
    t = np.arange(n) / sr
    g = np.ones(n)
    g *= np.clip(t / 1.5, 0, 1)
    if twist_t is not None:
        up = 10 ** (4 / 20)
        ramp = np.clip((t - twist_t) / 2.0, 0, 1)
        if end_t:
            ramp *= 1 - 0.4 * np.clip((t - end_t) / 2.0, 0, 1)  # settle a little for the last line
        g *= 1 + (up - 1) * ramp
    tail = n / sr - 2.0
    g *= np.clip(1 - (t - tail) / 2.0, 0, 1)
    return g


def master(voice, music, sfx, sr, build, out_wav, twist_t=None, last_t=None):
    """Write the finished 48 kHz stereo soundtrack to out_wav. Returns a small report dict."""
    vraw = os.path.join(build, "stem_voice_raw.wav")
    vcl = os.path.join(build, "stem_voice.wav")
    mus = os.path.join(build, "stem_music.wav")
    fxp = os.path.join(build, "stem_sfx.wav")
    sf.write(vraw, voice / max(1e-6, np.max(np.abs(voice))) * 0.8, sr)
    _ff(["-i", vraw, "-af", VOICE_CHAIN + ",aresample=48000", "-ac", "1", vcl])

    # music level relative to the cleaned voice (both measured on their own)
    vi = loudness(vcl)["input_i"]
    m = music * music_envelope(len(music), sr, twist_t, last_t)
    sf.write(mus, m / max(1e-6, np.max(np.abs(m))) * 0.5, sr)
    mi = loudness(mus)["input_i"]
    mg = float(vi) - MUSIC_UNDER_VOICE_DB - float(mi)
    sf.write(fxp, sfx, sr)

    graph = (f"[1:a]aresample=48000,volume={mg:.2f}dB[m];"
             "[0:a]asplit=2[v][vk];"
             "[m][vk]sidechaincompress=threshold=0.02:ratio=4:attack=30:release=450:makeup=1[md];"
             "[2:a]aresample=48000,volume=-6dB[s];"
             "[v][md][s]amix=inputs=3:normalize=0,aformat=channel_layouts=stereo[mix]")
    pre = os.path.join(build, "mix_pre.wav")
    _ff(["-i", vcl, "-i", mus, "-i", fxp, "-filter_complex", graph, "-map", "[mix]", "-ar", "48000", pre])

    # two-pass loudness normalisation
    ms = loudness(pre)
    ln = (f"loudnorm=I={TARGET_I}:TP={TARGET_TP}:LRA={TARGET_LRA}:measured_I={ms['input_i']}:"
          f"measured_TP={ms['input_tp']}:measured_LRA={ms['input_lra']}:measured_thresh={ms['input_thresh']}:"
          f"offset={ms['target_offset']}:linear=true")
    _ff(["-i", pre, "-af", ln + ",aresample=48000", "-ac", "2", "-c:a", "pcm_s16le", out_wav])

    # report: how far the (ducked) music sits under the voice in the final mix
    gain = TARGET_I - float(ms["input_i"])
    vf = os.path.join(build, "chk_voice.wav")
    mf = os.path.join(build, "chk_music.wav")
    _ff(["-i", vcl, "-af", f"volume={gain:.2f}dB", vf])
    _ff(["-i", vcl, "-i", mus, "-filter_complex",
         f"[1:a]aresample=48000,volume={mg:.2f}dB[m];[m][0:a]sidechaincompress=threshold=0.02:ratio=4:"
         f"attack=30:release=450:makeup=1,volume={gain:.2f}dB[o]", "-map", "[o]", mf])
    rep = {"voice_lufs": float(loudness(vf)["input_i"]), "music_lufs": float(loudness(mf)["input_i"])}
    rep["voice_over_music_db"] = round(rep["voice_lufs"] - rep["music_lufs"], 1)
    return rep
