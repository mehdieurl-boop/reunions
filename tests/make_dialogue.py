"""Fabrique un faux dialogue à deux intervenants, avec la vérité terrain.

Sert à mesurer l'identification des intervenants : on connaît exactement qui
parle et quand.
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audiotool import dsp, ffmpeg_io  # noqa: E402

SR = 48000


def speaker(n, f0, formants, seed, level_db=-16):
    """Voix synthétique : harmoniques + résonances (formants) propres au locuteur."""
    r = np.random.default_rng(seed)
    t = np.arange(n) / SR
    jitter = 1 + 0.015 * np.sin(2 * np.pi * 3.7 * t + r.random())
    sig = np.zeros(n)
    for k in range(1, 26):
        sig += (1.0 / k) * np.sin(2 * np.pi * f0 * k * jitter * t + r.random() * 6)
    sig += 0.05 * r.normal(0, 1, n)                     # souffle glottique
    y = sig.astype(np.float32)
    for f, q, g in formants:                            # empreinte spectrale du locuteur
        y = dsp.apply_sos(y, dsp.peaking(f, SR, g, q=q))
    # enveloppe syllabique
    env = 0.5 + 0.5 * np.sin(2 * np.pi * 4.3 * t + r.random() * 6)
    env = np.clip(env - 0.25, 0, None) / 0.75
    y = y * env
    y /= (np.abs(y).max() + 1e-9)
    return (y * 10 ** (level_db / 20)).astype(np.float32)


def main(out="tests/dialogue_test.m4a", n_speakers=2, n_turns=16):
    rng = np.random.default_rng(3)
    voices = [
        dict(f0=112, formants=[(650, 4, 12), (1150, 5, 9), (2600, 6, 6)], seed=11),
        dict(f0=187, formants=[(480, 4, 11), (1850, 5, 10), (3100, 6, 7)], seed=22),
        dict(f0=145, formants=[(560, 4, 10), (1500, 5, 11), (2200, 6, 8)], seed=33),
        dict(f0=210, formants=[(720, 4, 9), (1650, 5, 8), (3400, 6, 9)], seed=44),
    ][:n_speakers]
    turns, audio, t = [], [], 0.0
    for i in range(n_turns):                             # tours de parole alternés
        who = i % n_speakers
        d = float(rng.uniform(4.0, 9.0))
        n = int(d * SR)
        audio.append(speaker(n, voices[who]["f0"], voices[who]["formants"],
                             voices[who]["seed"] + i))
        turns.append(dict(start=round(t, 2), end=round(t + d, 2),
                          speaker=f"Intervenant {who + 1}"))
        t += d
        pause = int(rng.uniform(0.3, 0.9) * SR)          # respiration entre les tours
        audio.append(np.zeros(pause, np.float32))
        t += pause / SR
    x = np.concatenate(audio)

    # bruit de fond réaliste
    x = x + (rng.normal(0, 1, len(x)) * 10 ** (-46 / 20)).astype(np.float32)
    x = (x / (np.abs(x).max() * 1.3)).astype(np.float32)

    Path(out).parent.mkdir(parents=True, exist_ok=True)
    raw = out + ".f32.wav"
    w = ffmpeg_io.RawWriter(raw, SR, 1)
    w.write(x)
    w.close()
    subprocess.run([ffmpeg_io.ffmpeg(), "-y", "-loglevel", "error", "-i", raw,
                    "-c:a", "aac", "-b:a", "128k", out], check=True)
    Path(raw).unlink()
    ref = out.replace(".m4a", "_verite.json")
    Path(ref).write_text(json.dumps(turns, indent=1, ensure_ascii=False))
    print(f"écrit : {out} ({t:.0f} s, {len(turns)} tours) et {ref}")


if __name__ == "__main__":
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    out = sys.argv[2] if len(sys.argv) > 2 else "tests/dialogue_test.m4a"
    main(out, n_speakers=n)
