"""Tests unitaires des briques DSP (exécutables sans fichier audio)."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audiotool import dsp  # noqa: E402
from audiotool import console_utf8  # noqa: E402

console_utf8()

SR = 48000
FAILS = []


def check(name, cond, detail=""):
    print(f"{'✓' if cond else '✗'} {name} {detail}")
    if not cond:
        FAILS.append(name)


def db(x):
    return 20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-12)


def tone(f, n, amp=0.1):
    return (amp * np.sin(2 * np.pi * f * np.arange(n) / SR)).astype(np.float32)


# --- compresseur : un palier de +15 dB doit ressortir réduit ---------------- #
n = SR * 3
sig = np.concatenate([tone(200, n, 0.06), tone(200, n, 0.06 * 10 ** (15 / 20))])
for ratio in (2.0, 4.0):
    out = dsp.compressor(sig, SR, threshold_db=-32.0, ratio=ratio, makeup_db=0.0)
    step_in = db(sig[n + SR:2 * n - SR]) - db(sig[SR:n - SR])
    step_out = db(out[n + SR:2 * n - SR]) - db(out[SR:n - SR])
    expected = step_in / ratio          # les deux paliers sont au-dessus du seuil
    check(f"compresseur ratio {ratio}", abs(step_out - expected) < 2.0,
          f"(entrée {step_in:.1f} dB → sortie {step_out:.1f} dB, attendu ~{expected:.1f})")

# --- limiteur : plafond respecté ------------------------------------------- #
loud = tone(300, SR, 0.95) + tone(1700, SR, 0.5)
lim = dsp.limiter(loud, SR, ceiling_db=-1.0)
peak = 20 * np.log10(np.max(np.abs(lim)))
check("limiteur : crête ≤ -1 dBFS", peak <= -0.9, f"(crête {peak:.2f} dBFS)")

# --- EQ : le passe-haut coupe le grave, le high-shelf calme l'aigu ---------- #
low, high = tone(45, SR), tone(12000, SR)
hp = dsp.apply_sos(low, dsp.highpass_sos(85, SR))
check("passe-haut 85 Hz sur 45 Hz", db(hp) - db(low) < -12, f"({db(hp) - db(low):.1f} dB)")
hs = dsp.apply_sos(high, dsp.high_shelf(7000, SR, -6.0))
check("high-shelf -6 dB à 12 kHz", -8 < db(hs) - db(high) < -4, f"({db(hs) - db(high):.1f} dB)")
mid = tone(2800, SR)
pk = dsp.apply_sos(mid, dsp.peaking(2800, SR, 3.0, q=0.9))
check("cloche +3 dB à 2,8 kHz", 2.0 < db(pk) - db(mid) < 4.0, f"({db(pk) - db(mid):.1f} dB)")

# --- notch secteur --------------------------------------------------------- #
h = tone(100, SR)
nt = dsp.apply_sos(h, dsp.notch_sos(100, SR, q=20))[SR // 2:]  # hors régime transitoire
check("réjecteur 100 Hz", db(nt) - db(h) < -25, f"({db(nt) - db(h):.1f} dB)")

# --- expandeur : atténue le fond, laisse la parole intacte ----------------- #
quiet = (np.random.default_rng(0).normal(0, 1, SR) * 10 ** (-50 / 20)).astype(np.float32)
loud2 = tone(220, SR, 0.2)
mix = np.concatenate([quiet, loud2, quiet])
ex = dsp.expander(mix, SR, threshold_db=-40.0, ratio=2.0, range_db=12.0)
d_quiet = db(ex[SR // 2:SR - 2000]) - db(mix[SR // 2:SR - 2000])  # après engagement
d_loud = db(ex[SR + 4000:2 * SR - 4000]) - db(mix[SR + 4000:2 * SR - 4000])
# valeur théorique : (ratio-1) x (10 dB sous le seuil - genou/2) = -7 dB
check("expandeur : fond atténué ~-7 dB", -9.0 < d_quiet < -5.0, f"({d_quiet:.1f} dB)")
check("expandeur : parole préservée", abs(d_loud) < 0.5, f"({d_loud:.1f} dB)")

# --- débruitage : souffle retiré, ton conservé ----------------------------- #
rng = np.random.default_rng(1)
hiss = (rng.normal(0, 1, SR * 4) * 10 ** (-40 / 20)).astype(np.float32)
voice = np.concatenate([np.zeros(SR, np.float32), tone(500, SR * 2, 0.15),
                        np.zeros(SR, np.float32)])
noisy = voice + hiss
prof = dsp.noise_profile(hiss[:SR])
den = dsp.denoise(noisy, prof, 0.6)
d_sil = db(den[:SR - 3000]) - db(noisy[:SR - 3000])
d_voice = db(den[SR + 6000:3 * SR - 6000]) - db(noisy[SR + 6000:3 * SR - 6000])
check("débruitage : souffle réduit", d_sil < -12, f"({d_sil:.1f} dB)")
check("débruitage : voix conservée", abs(d_voice) < 1.5, f"({d_voice:.1f} dB)")

# --- débruitage : les débuts de mots ne doivent pas être rabotés ----------- #
# Le masque spectral était lissé de façon symétrique dans le temps : au démarrage
# d'un mot il restait fermé par le silence précédent, ce qui coûtait 5,4 dB sur
# les 50 premières ms mesurées sur la chaîne complète. Ce test compare la tête
# d'une salve à son corps : avec un lissage centré il retombe sous 0 dB.
r2 = np.random.default_rng(5)
sal = (r2.normal(0, 1, SR * 6) * 10 ** (-42 / 20)).astype(np.float32)
_t = np.arange(int(0.15 * SR)) / SR
_burst = (0.2 * np.sin(2 * np.pi * 220 * _t) + 0.1 * np.sin(2 * np.pi * 660 * _t)).astype(np.float32)
_deb = [int(x * SR) for x in (0.8, 1.35, 1.9, 2.45, 3.0, 3.55, 4.1, 4.65)]
for _d in _deb:
    sal[_d:_d + len(_burst)] += _burst
_den = dsp.denoise(sal, dsp.noise_profile(sal), 0.6)
_tete = np.mean([db(_den[d:d + int(.03 * SR)]) - db(sal[d:d + int(.03 * SR)]) for d in _deb])
_corps = np.mean([db(_den[d + int(.05 * SR):d + int(.14 * SR)])
                  - db(sal[d + int(.05 * SR):d + int(.14 * SR)]) for d in _deb])
check("débruitage : attaques préservées", _tete - _corps > 0.7,
      f"({_tete - _corps:+.2f} dB tête/corps ; lissage centré = {-0.32:+.2f})")

# --- sonie : un signal calibré doit être mesuré correctement --------------- #
# une sinusoïde 1 kHz à -20 dBFS mesure ≈ -23 LUFS (mono)
m = dsp.LoudnessMeter(SR, 1)
m.push(tone(1000, SR * 5, 10 ** (-20 / 20)))
val = m.integrated()
check("mesure LUFS (référence -23 LUFS)", abs(val + 23.0) < 1.0, f"({val:.2f} LUFS)")

# --- stabilité numérique --------------------------------------------------- #
for name, arr in (("silence", np.zeros((SR, 2), np.float32)),
                  ("saturation", np.ones((SR, 2), np.float32))):
    y = dsp.limiter(dsp.compressor(arr, SR, -30, 3.0), SR)
    check(f"stabilité : {name}", np.isfinite(y).all())

print("\nRÉSULTAT :", "OK" if not FAILS else f"ÉCHECS → {FAILS}")
sys.exit(1 if FAILS else 0)
