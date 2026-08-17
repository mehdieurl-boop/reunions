"""Mesure objective avant / après sur l'échantillon de test."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audiotool import ffmpeg_io  # noqa: E402
from audiotool import console_utf8  # noqa: E402

console_utf8()

SR = 48000


def load(path, sr=SR, ch=1):
    b = list(ffmpeg_io.decode_stream(path, sr, ch))
    return np.concatenate(b, axis=0)[:, 0] if b else np.zeros(1)


def short_db(x, sr=SR, win=0.05):
    w = int(win * sr)
    n = (len(x) // w) * w
    r = np.sqrt(np.mean(x[:n].reshape(-1, w) ** 2, axis=1))
    return 20 * np.log10(r + 1e-12)


def band_db(x, f_lo, f_hi, sr=SR):
    X = np.fft.rfft(x * np.hanning(len(x)))
    f = np.fft.rfftfreq(len(x), 1 / sr)
    m = (f >= f_lo) & (f <= f_hi)
    return 10 * np.log10(np.mean(np.abs(X[m]) ** 2) + 1e-20)


def align_level(x, ref_db):
    return x * 10 ** ((ref_db - np.percentile(short_db(x), 90)) / 20)


def main():
    src = "tests/reunion_test.m4a"
    if not Path("tests/reunion_test_clean_ref.wav").exists():
        print("Échantillon absent — lancez d'abord : python tests/make_sample.py")
        return
    if not Path("tests/out/reunion_test_ecoute.mp3").exists():
        print("Traitement de l'échantillon…")
        from audiotool.pipeline import Settings, process_file
        process_file(src, "tests/out", Settings())
    ref = load("tests/reunion_test_clean_ref.wav")
    x = load(src)
    y = load("tests/out/reunion_test_ecoute.mp3")
    t = load("tests/out/reunion_test_transcription.wav", sr=16000)

    n = min(len(ref), len(x), len(y))
    ref, x, y = ref[:n], x[:n], y[:n]

    # calage : même niveau de parole (P90) pour comparer à volume égal
    target = -20.0
    x, y = align_level(x, target), align_level(y, target)

    # régions de silence d'après la référence propre
    rdb = short_db(ref)
    sil = rdb <= np.percentile(rdb, 20)
    spk = rdb > np.percentile(rdb, 80)
    w = int(0.05 * SR)

    def region_db(sig, mask):
        s = short_db(sig)
        m = mask[:len(s)]
        return float(np.mean(s[:len(m)][m])) if m.any() else float("nan")

    res = {}
    res["bruit_de_fond_avant_dB"] = region_db(x, sil)
    res["bruit_de_fond_apres_dB"] = region_db(y, sil)
    res["parole_avant_dB"] = region_db(x, spk)
    res["parole_apres_dB"] = region_db(y, spk)
    res["contraste_parole_bruit_avant_dB"] = res["parole_avant_dB"] - res["bruit_de_fond_avant_dB"]
    res["contraste_parole_bruit_apres_dB"] = res["parole_apres_dB"] - res["bruit_de_fond_apres_dB"]

    # ronflement secteur : 50/100/150 Hz mesuré sur une zone silencieuse
    idx = np.flatnonzero(sil)
    seg = slice(idx[len(idx) // 2] * w, idx[len(idx) // 2] * w + SR)
    for f in (50, 100, 150):
        res[f"ronflement_{f}Hz_avant_dB"] = band_db(x[seg], f - 3, f + 3)
        res[f"ronflement_{f}Hz_apres_dB"] = band_db(y[seg], f - 3, f + 3)

    # dynamique pendant la parole (la compression doit la resserrer)
    res["ecart_type_niveau_parole_avant_dB"] = float(np.std(short_db(x)[spk[:len(short_db(x))]]))
    res["ecart_type_niveau_parole_apres_dB"] = float(np.std(short_db(y)[spk[:len(short_db(y))]]))

    # intégrité
    yy = load("tests/out/reunion_test_ecoute.mp3")
    res["NaN_ou_Inf"] = bool(~np.isfinite(yy).all())
    res["crete_dBFS"] = float(20 * np.log10(np.max(np.abs(yy)) + 1e-12))
    res["duree_ecoute_s"] = round(len(yy) / SR, 2)
    res["duree_transcription_s"] = round(len(t) / 16000, 2)
    res["transcription_sr"] = 16000

    # coutures entre blocs de 30 s : un saut anormal se verrait ici
    d = np.abs(np.diff(yy))
    glob = float(np.percentile(d, 99.99))
    seams = [float(np.max(d[k * 30 * SR - 200: k * 30 * SR + 200]))
             for k in (1, 2) if (k * 30 * SR + 200) < len(d)]
    res["saut_max_global_p99.99"] = round(glob, 5)
    res["saut_max_aux_coutures_30s"] = [round(s, 5) for s in seams]

    print(f"{'métrique':46s} valeur")
    for k, v in res.items():
        print(f"{k:46s} {v if isinstance(v, (bool, list, int)) else round(v, 2)}")

    ok = (res["contraste_parole_bruit_apres_dB"] > res["contraste_parole_bruit_avant_dB"] + 6
          and res["ronflement_100Hz_apres_dB"] < res["ronflement_100Hz_avant_dB"] - 10
          and not res["NaN_ou_Inf"] and res["crete_dBFS"] < -0.2
          and all(s <= glob * 3 for s in seams))
    print("\nRÉSULTAT :", "OK" if ok else "À REVOIR")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main() or 0)
