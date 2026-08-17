"""Fabrique une fausse réunion Zoom bruitée pour tester la chaîne."""
import sys
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audiotool import ffmpeg_io  # noqa: E402
from audiotool import console_utf8  # noqa: E402

console_utf8()

SR = 48000
rng = np.random.default_rng(7)


def voice(n, f0, level_db, syll=4.0, seed=0):
    """Signal vocalique grossier : harmoniques + enveloppe syllabique."""
    r = np.random.default_rng(seed)
    t = np.arange(n) / SR
    jitter = 1 + 0.02 * np.sin(2 * np.pi * 3.1 * t + r.random())
    sig = np.zeros(n)
    for k, amp in enumerate([1.0, .6, .45, .3, .22, .15, .1, .07], start=1):
        sig += amp * np.sin(2 * np.pi * f0 * k * jitter * t + r.random() * 6)
    # bruit de friction (consonnes) filtré vers l'aigu
    fric = r.normal(0, 1, n)
    fric = np.convolve(fric, [1, -0.95], mode="same") * 0.06
    env = 0.5 + 0.5 * np.sin(2 * np.pi * syll * t + r.random() * 6)
    env *= (env > 0.35)
    # pauses de phrase
    ph = (np.sin(2 * np.pi * 0.09 * t + r.random() * 6) > -0.15).astype(float)
    ph = np.convolve(ph, np.hanning(4801) / np.hanning(4801).sum(), mode="same")
    y = (sig + fric) * env * ph
    y /= (np.abs(y).max() + 1e-9)
    return y * 10 ** (level_db / 20)


def main(out="tests/reunion_test.m4a", seconds=90):
    n = SR * seconds
    t = np.arange(n) / SR
    # deux intervenants, l'un bien plus faible (micro éloigné)
    a = voice(n, 118, -14, 4.2, seed=1)
    b = voice(n, 196, -26, 3.6, seed=2)
    b = np.roll(b, SR * 7)
    clean = a + b

    # souffle large bande + ronflement secteur + clics clavier
    hiss = rng.normal(0, 1, n)
    hiss = np.convolve(hiss, np.ones(3) / 3, mode="same") * 10 ** (-42 / 20)
    hum = sum(10 ** ((-38 - 6 * k) / 20) * np.sin(2 * np.pi * 50 * (k + 1) * t)
              for k in range(4))
    clicks = np.zeros(n)
    for pos in rng.integers(SR, n - SR, 40):
        L = 700
        clicks[pos:pos + L] += rng.normal(0, .25, L) * np.exp(-np.arange(L) / 90)

    noisy = clean + hiss + hum + clicks
    noisy = np.stack([noisy, noisy * 0.92 + 0.02 * rng.normal(0, 1, n) * 0.05], axis=1)
    scale = 1.0 / (np.abs(noisy).max() * 1.35)
    noisy = (noisy * scale).astype(np.float32)

    Path(out).parent.mkdir(parents=True, exist_ok=True)
    raw = out + ".f32.wav"
    w = ffmpeg_io.RawWriter(raw, SR, 2)
    w.write(noisy)
    w.close()
    import subprocess
    subprocess.run([ffmpeg_io.ffmpeg(), "-y", "-loglevel", "error", "-i", raw,
                    "-c:a", "aac", "-b:a", "128k", out], check=True)
    Path(raw).unlink()
    # référence propre, pour les mesures
    ref = out.replace(".m4a", "_clean_ref.wav")
    w = ffmpeg_io.RawWriter(ref, SR, 1)
    w.write((clean * scale).astype(np.float32))
    w.close()
    print("écrit :", out, ref)


if __name__ == "__main__":
    main()
