"""Briques de traitement du signal (numpy / scipy uniquement).

Tout est vectorisé : aucune boucle Python à l'échelle de l'échantillon,
ce qui permet de traiter une réunion d'une heure en quelques dizaines de secondes.
"""
from __future__ import annotations

import warnings

import numpy as np
from scipy import ndimage, signal

EPS = 1e-12

# --------------------------------------------------------------------------- #
#  Filtres biquad (cookbook RBJ) — renvoient des sections SOS
# --------------------------------------------------------------------------- #


def _sos(b0, b1, b2, a0, a1, a2):
    return np.array([[b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]])


def peaking(f0: float, sr: int, gain_db: float, q: float = 1.0):
    A = 10 ** (gain_db / 40)
    w0 = 2 * np.pi * f0 / sr
    alpha = np.sin(w0) / (2 * q)
    cw = np.cos(w0)
    return _sos(1 + alpha * A, -2 * cw, 1 - alpha * A,
                1 + alpha / A, -2 * cw, 1 - alpha / A)


def low_shelf(f0: float, sr: int, gain_db: float, s: float = 0.9):
    A = 10 ** (gain_db / 40)
    w0 = 2 * np.pi * f0 / sr
    cw, sw = np.cos(w0), np.sin(w0)
    alpha = sw / 2 * np.sqrt((A + 1 / A) * (1 / s - 1) + 2)
    tsa = 2 * np.sqrt(A) * alpha
    return _sos(A * ((A + 1) - (A - 1) * cw + tsa),
                2 * A * ((A - 1) - (A + 1) * cw),
                A * ((A + 1) - (A - 1) * cw - tsa),
                (A + 1) + (A - 1) * cw + tsa,
                -2 * ((A - 1) + (A + 1) * cw),
                (A + 1) + (A - 1) * cw - tsa)


def high_shelf(f0: float, sr: int, gain_db: float, s: float = 0.9):
    A = 10 ** (gain_db / 40)
    w0 = 2 * np.pi * f0 / sr
    cw, sw = np.cos(w0), np.sin(w0)
    alpha = sw / 2 * np.sqrt((A + 1 / A) * (1 / s - 1) + 2)
    tsa = 2 * np.sqrt(A) * alpha
    return _sos(A * ((A + 1) + (A - 1) * cw + tsa),
                -2 * A * ((A - 1) + (A + 1) * cw),
                A * ((A + 1) + (A - 1) * cw - tsa),
                (A + 1) - (A - 1) * cw + tsa,
                2 * ((A - 1) - (A + 1) * cw),
                (A + 1) - (A - 1) * cw - tsa)


def highpass_sos(f0: float, sr: int, order: int = 4):
    return signal.butter(order, f0 / (sr / 2), btype="highpass", output="sos")


def bandpass_sos(f_lo: float, f_hi: float, sr: int, order: int = 4):
    hi = min(f_hi, sr / 2 * 0.99)
    return signal.butter(order, [f_lo / (sr / 2), hi / (sr / 2)],
                         btype="bandpass", output="sos")


def notch_sos(f0: float, sr: int, q: float = 30.0):
    b, a = signal.iirnotch(f0 / (sr / 2), q)
    return signal.tf2sos(b, a)


def apply_sos(x: np.ndarray, sos: np.ndarray) -> np.ndarray:
    """Filtrage simple passe (sosfilt).

    On n'utilise PAS filtfilt : le double passage doublerait les gains
    demandés (un shelf de -6 dB en donnerait -12). Le léger déphasage d'un
    IIR doux est inaudible sur de la parole, et le contexte de 1 s ajouté
    autour de chaque bloc absorbe le régime transitoire du filtre.
    """
    if sos is None or len(sos) == 0:
        return x
    return signal.sosfilt(sos, x, axis=0).astype(np.float32)


# --------------------------------------------------------------------------- #
#  Détection d'enveloppe / lissage de gain (vectorisé)
# --------------------------------------------------------------------------- #


def _one_pole(x: np.ndarray, tau_ms: float, sr: int) -> np.ndarray:
    """Lissage exponentiel (release) via lfilter — implémentation C, rapide."""
    n = max(1.0, tau_ms * 1e-3 * sr)
    a = float(np.exp(-1.0 / n))
    return signal.lfilter([1 - a], [1.0, -a], x, axis=0).astype(np.float32)


def envelope_db(x: np.ndarray, sr: int, attack_ms: float, release_ms: float,
                detector: str = "peak", rms_ms: float = 20.0) -> np.ndarray:
    """Enveloppe du signal, en dB.

    detector="peak" : crête (limiteur, désesseur).
    detector="rms"  : valeur efficace sur 20 ms — c'est le bon détecteur pour
                      piloter un compresseur ou un expandeur, et il est calé
                      sur la même échelle que les statistiques d'analyse.

    Dans les deux cas la montée est immédiate (max avec le signal brut) et la
    descente suit la constante de retour : sans cela, le gain arrive en retard
    et les premières crêtes passent au travers.
    """
    if detector == "rms":
        p = (x ** 2).mean(axis=1) if x.ndim > 1 else x ** 2
        w = max(1, int(rms_ms * 1e-3 * sr))
        env = np.sqrt(ndimage.uniform_filter1d(p, size=w, mode="nearest"))
    else:
        rect = np.abs(x)
        if rect.ndim > 1:                   # détecteur lié entre canaux
            rect = rect.max(axis=1)
        w = max(1, int(attack_ms * 1e-3 * sr))
        env = ndimage.maximum_filter1d(rect, size=w, mode="nearest")
    env = np.maximum(env, _one_pole(env, release_ms, sr))
    return 20 * np.log10(env + EPS)


def smooth_gain(gain_db: np.ndarray, sr: int, attack_ms: float, release_ms: float,
                mode: str = "down") -> np.ndarray:
    """Lissage asymétrique du gain, entièrement vectorisé.

    mode="down"  (compresseur / limiteur / désesseur) : le gain descend vite,
                 remonte lentement.
    mode="up"    (expandeur) : le gain remonte vite — pour ne pas hacher les
                 débuts de mots — et redescend lentement.

    Procédé : min/max glissant (anticipation, le gain bouge avant la crête),
    fenêtre de Hann pour arrondir les angles, puis min/max avec un lissage
    exponentiel qui impose la constante de retour.
    """
    w = max(3, int(attack_ms * 1e-3 * sr)) | 1
    fast = (ndimage.minimum_filter1d if mode == "down" else ndimage.maximum_filter1d)
    g = fast(gain_db, size=2 * w + 1, mode="nearest")
    # deux moyennes glissantes = fenêtre triangulaire (O(n), et de support
    # inférieur au min/max glissant : le gain requis reste garanti)
    g = ndimage.uniform_filter1d(g, size=w, mode="nearest")
    g = ndimage.uniform_filter1d(g, size=w, mode="nearest").astype(np.float32)
    slow = _one_pole(g, max(release_ms, attack_ms), sr)
    return np.minimum(g, slow) if mode == "down" else np.maximum(g, slow)


def _apply_gain(x: np.ndarray, gain_db: np.ndarray) -> np.ndarray:
    """Applique un gain (en dB, un par échantillon) en respectant la forme de x.

    x peut être 1-D, (n,1) ou (n,2) : le gain est diffusé sur les canaux.
    """
    g = (10 ** (gain_db / 20)).astype(np.float32)
    if x.ndim > 1:
        g = g[:, None]
    return (x * g).astype(np.float32)


# --------------------------------------------------------------------------- #
#  Dynamique
# --------------------------------------------------------------------------- #


def expander(x: np.ndarray, sr: int, threshold_db: float, ratio: float = 2.0,
             range_db: float = 12.0, attack_ms: float = 5.0,
             release_ms: float = 180.0) -> np.ndarray:
    """Expandeur descendant : atténue les creux (respiration de fond) sans couper net."""
    if range_db <= 0:
        return x
    env = envelope_db(x, sr, attack_ms, release_ms, detector="rms")
    knee = 6.0
    below = np.clip(threshold_db - env, 0, None)
    below = np.where(below < knee, below ** 2 / (2 * knee), below - knee / 2)
    gain_db = np.clip(-(ratio - 1.0) * below, -range_db, 0.0)
    gain_db = smooth_gain(gain_db, sr, attack_ms, release_ms, mode="up")
    return _apply_gain(x, gain_db)


def compressor(x: np.ndarray, sr: int, threshold_db: float, ratio: float = 3.0,
               attack_ms: float = 12.0, release_ms: float = 220.0,
               knee_db: float = 8.0, makeup_db: float | None = None) -> np.ndarray:
    """Compresseur à genou progressif, détecteur lié (préserve l'image stéréo)."""
    if ratio <= 1.0:
        return x
    env = envelope_db(x, sr, attack_ms, release_ms, detector="rms")
    over = env - threshold_db
    # genou progressif
    soft = np.where(
        over < -knee_db / 2, 0.0,
        np.where(over > knee_db / 2, over, (over + knee_db / 2) ** 2 / (2 * knee_db)),
    )
    gain_db = -(1.0 - 1.0 / ratio) * soft
    gain_db = smooth_gain(gain_db, sr, attack_ms, release_ms)
    if makeup_db is None:
        makeup_db = -np.percentile(gain_db, 10) * 0.9   # compense la réduction typique
    return _apply_gain(x, gain_db + makeup_db)


def de_esser(x: np.ndarray, sr: int, amount: float, f_lo: float = 5200.0,
             f_hi: float = 9500.0, max_db: float = 8.0) -> np.ndarray:
    """Atténue dynamiquement les sifflantes sans ternir l'ensemble du spectre."""
    if amount <= 0.01 or sr / 2 <= f_lo * 1.05:
        return x
    sos = bandpass_sos(f_lo, f_hi, sr)
    band = signal.sosfilt(sos, x, axis=0).astype(np.float32)
    env = envelope_db(band, sr, 1.0, 45.0)
    thr = np.percentile(env, 97) - 9.0
    gain_db = np.clip(-(env - thr) * 0.7, -max_db * amount, 0.0)
    gain_db = smooth_gain(gain_db, sr, 1.5, 45.0)
    return (x - band + _apply_gain(band, gain_db)).astype(np.float32)


def limiter(x: np.ndarray, sr: int, ceiling_db: float = -1.0,
            attack_ms: float = 3.0, release_ms: float = 60.0) -> np.ndarray:
    env = envelope_db(x, sr, attack_ms, release_ms)
    gain_db = np.minimum(0.0, ceiling_db - env)
    gain_db = smooth_gain(gain_db, sr, attack_ms, release_ms)
    return np.clip(_apply_gain(x, gain_db), -1.0, 1.0).astype(np.float32)


# --------------------------------------------------------------------------- #
#  Débruitage spectral (porte spectrale douce, type soustraction de Wiener)
# --------------------------------------------------------------------------- #

N_FFT, HOP = 2048, 512


def _stft(x1d: np.ndarray):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return signal.stft(x1d, nperseg=N_FFT, noverlap=N_FFT - HOP,
                           window="hann", boundary="zeros", padded=True)[2]


def _istft(Z, n: int):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        y = signal.istft(Z, nperseg=N_FFT, noverlap=N_FFT - HOP, window="hann")[1]
    if len(y) < n:
        y = np.pad(y, (0, n - len(y)))
    return y[:n].astype(np.float32)


def noise_profile(x: np.ndarray, percentile: float = 20.0) -> np.ndarray:
    """Profil de bruit = percentile bas de l'énergie par bande (les silences de réunion)."""
    mono = x.mean(axis=1) if x.ndim > 1 else x
    mag = np.abs(_stft(mono))
    return np.percentile(mag, percentile, axis=1).astype(np.float32)


def denoise(x: np.ndarray, noise_mag: np.ndarray, strength: float) -> np.ndarray:
    """strength ∈ [0,1] : 0 = inactif, 1 = agressif."""
    if strength <= 0.01:
        return x
    beta = 1.0 + 1.6 * strength                    # sur-soustraction
    floor = 10 ** ((-5.0 - 24.0 * strength) / 20)  # plancher : on garde un fond naturel
    mono_in = x.ndim == 1
    xx = x[:, None] if mono_in else x
    out = np.empty_like(xx)
    for c in range(xx.shape[1]):
        Z = _stft(xx[:, c])
        mag = np.abs(Z)
        gain = (mag - beta * noise_mag[:, None]) / (mag + EPS)
        gain = np.clip(gain, floor, 1.0)
        # lissage temps/fréquence : évite le "bruit musical"
        gain = ndimage.uniform_filter(gain, size=(3, 5), mode="nearest")
        out[:, c] = _istft(Z * gain, xx.shape[0])
    return out[:, 0] if mono_in else out


# --------------------------------------------------------------------------- #
#  Mesure de sonie ITU-R BS.1770-4 (LUFS)
# --------------------------------------------------------------------------- #


def _k_weight_sos(sr: int):
    """Pré-filtre tête + RLB, dérivés analytiquement pour un sr quelconque."""
    # étage 1 : high-shelf +4 dB @ ~1681 Hz ; étage 2 : high-pass @ ~38 Hz
    return np.vstack([high_shelf(1681.97, sr, 3.999, s=1.0),
                      highpass_sos(38.13, sr, order=2)])


class LoudnessMeter:
    """Mesure LUFS intégrée en flux (blocs de 400 ms, recouvrement 75 %, gating)."""

    def __init__(self, sr: int, nch: int):
        self.sr, self.nch = sr, nch
        self.sos = _k_weight_sos(sr)
        self.zi = np.zeros((self.sos.shape[0], 2, nch), dtype=np.float64)
        self.block = int(0.4 * sr)
        self.step = self.block // 4
        self.buf = np.zeros(0, dtype=np.float64)
        self.powers: list[float] = []
        # pondération des canaux (G = 1 pour L/R)
        self.g = np.ones(nch, dtype=np.float32)

    def push(self, chunk: np.ndarray):
        c = chunk[:, None] if chunk.ndim == 1 else chunk
        y, self.zi = signal.sosfilt(self.sos, c, axis=0, zi=self.zi)
        # puissance pondérée par échantillon, puis moyennes de blocs par
        # sommes cumulées : pas de boucle Python, coût négligeable
        q = (y.astype(np.float64) ** 2 * self.g).sum(axis=1)
        self.buf = np.concatenate([self.buf, q])
        n = len(self.buf)
        if n >= self.block:
            starts = np.arange(0, n - self.block + 1, self.step)
            c_sum = np.concatenate([[0.0], np.cumsum(self.buf)])
            vals = (c_sum[starts + self.block] - c_sum[starts]) / self.block
            self.powers.extend(vals.tolist())
            self.buf = self.buf[starts[-1] + self.step:]

    def integrated(self) -> float:
        p = np.asarray(self.powers)
        if p.size == 0:
            return -70.0
        l = -0.691 + 10 * np.log10(p + EPS)
        p = p[l > -70.0]                       # gate absolu
        if p.size == 0:
            return -70.0
        rel = -0.691 + 10 * np.log10(p.mean()) - 10.0
        keep = p[(-0.691 + 10 * np.log10(p + EPS)) > rel]   # gate relatif
        if keep.size == 0:
            keep = p
        return float(-0.691 + 10 * np.log10(keep.mean() + EPS))
