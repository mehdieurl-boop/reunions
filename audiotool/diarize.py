"""Identification des intervenants (qui parle, quand).

Deux voies :

* **pyannote.audio** si le paquet est installé et qu'un jeton HuggingFace est
  disponible — c'est la référence, nettement plus fiable.
* **repli maison** sinon : MFCC + regroupement hiérarchique, en numpy/scipy
  uniquement. Suffisant pour découper les tours de parole quand les voix sont
  distinctes ; moins fiable sur des voix proches ou qui se chevauchent.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
from scipy import fft as sfft
from scipy.cluster import hierarchy
from scipy.spatial.distance import pdist, squareform

from . import config, ffmpeg_io

SR = 16_000
FRAME, HOP = 400, 160          # 25 ms / 10 ms
N_MEL, N_MFCC = 40, 20
WIN_S, WIN_HOP_S = 1.5, 0.75   # fenêtres d'analyse du locuteur
MIN_TURN_S = 1.0


@dataclass
class Turn:
    start: float
    end: float
    speaker: str


# --------------------------------------------------------------------------- #
#  MFCC (implémentation directe, sans librosa)
# --------------------------------------------------------------------------- #


def _mel_filterbank(sr: int, n_fft: int, n_mel: int, f_lo=20.0, f_hi=7600.0):
    def to_mel(f):
        return 2595 * np.log10(1 + f / 700)

    def to_hz(m):
        return 700 * (10 ** (m / 2595) - 1)

    pts = to_hz(np.linspace(to_mel(f_lo), to_mel(min(f_hi, sr / 2)), n_mel + 2))
    bins = np.floor((n_fft + 1) * pts / sr).astype(int)
    fb = np.zeros((n_mel, n_fft // 2 + 1), dtype=np.float32)
    for i in range(n_mel):
        a, b, c = bins[i], bins[i + 1], bins[i + 2]
        if b == a:
            b = a + 1
        if c == b:
            c = b + 1
        c = min(c, fb.shape[1] - 1)
        b = min(b, c)
        if b > a:
            fb[i, a:b] = np.linspace(0, 1, b - a)
        if c > b:
            fb[i, b:c] = np.linspace(1, 0, c - b)
    return fb


def mfcc(x: np.ndarray, sr: int = SR) -> tuple[np.ndarray, np.ndarray]:
    """Renvoie (mfcc [n_frames, N_MFCC-1], énergie par trame en dB)."""
    x = np.append(x[0], x[1:] - 0.97 * x[:-1])          # pré-accentuation
    n = 1 + max(0, (len(x) - FRAME) // HOP)
    if n < 2:
        return np.zeros((0, N_MFCC - 1), np.float32), np.zeros(0, np.float32)
    idx = np.arange(FRAME)[None, :] + HOP * np.arange(n)[:, None]
    frames = x[idx] * np.hamming(FRAME).astype(np.float32)
    n_fft = 512
    spec = np.abs(sfft.rfft(frames, n=n_fft, axis=1)) ** 2
    energy_db = 10 * np.log10(spec.sum(axis=1) + 1e-12)
    mel = spec @ _mel_filterbank(sr, n_fft, N_MEL).T
    logmel = np.log(mel + 1e-10)
    coef = sfft.dct(logmel, type=2, axis=1, norm="ortho")[:, 1:N_MFCC]  # c0 = volume, écarté
    return coef.astype(np.float32), energy_db.astype(np.float32)


# --------------------------------------------------------------------------- #
#  Repli maison
# --------------------------------------------------------------------------- #


def _silhouette(dist: np.ndarray, labels: np.ndarray) -> float:
    """Silhouette moyenne à partir d'une matrice de distances (sans sklearn)."""
    uniq = np.unique(labels)
    if len(uniq) < 2:
        return -1.0
    scores = []
    for i in range(len(labels)):
        same = labels == labels[i]
        same[i] = False
        if not same.any():
            continue
        a = dist[i, same].mean()
        b = min(dist[i, labels == u].mean() for u in uniq if u != labels[i])
        scores.append((b - a) / max(a, b, 1e-9))
    return float(np.mean(scores)) if scores else -1.0


def _speech_regions(voiced: np.ndarray, bridge_s=0.25, min_s=0.5) -> list[tuple[int, int]]:
    """Plages de parole continues (indices de trames), petits trous comblés."""
    if not voiced.any():
        return []
    d = np.diff(voiced.astype(np.int8))
    starts = list(np.flatnonzero(d == 1) + 1)
    ends = list(np.flatnonzero(d == -1) + 1)
    if voiced[0]:
        starts.insert(0, 0)
    if voiced[-1]:
        ends.append(len(voiced))
    regions = list(zip(starts, ends))
    bridge = int(bridge_s * SR / HOP)
    merged = []
    for a, b in regions:
        if merged and a - merged[-1][1] <= bridge:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    keep = int(min_s * SR / HOP)
    return [r for r in merged if r[1] - r[0] >= keep]


# Distance de coupure du dendrogramme. Les fenêtres d'un même locuteur
# fusionnent en dessous ; changer de locuteur coûte nettement plus cher.
# Calibré sur des dialogues de référence à 1, 2 et 3 intervenants
# (fusion la plus haute : 0,22 pour un seul locuteur, 0,52 pour deux).
CUT_DISTANCE = 0.32
MAX_AUTO_SPEAKERS = 8


def _auto_labels(link: np.ndarray) -> np.ndarray:
    """Regroupement à seuil absolu : décide aussi du nombre d'intervenants.

    À ne pas remplacer par une silhouette : celle-ci continue de monter en
    découpant un même locuteur en sous-groupes phonétiques, et surestime donc
    systématiquement le nombre d'intervenants.
    """
    lab = hierarchy.fcluster(link, CUT_DISTANCE, criterion="distance")
    if lab.max() > MAX_AUTO_SPEAKERS:
        lab = hierarchy.fcluster(link, MAX_AUTO_SPEAKERS, criterion="maxclust")
    return lab


def _light_diarize(wav_path: str, max_speakers: int = 0) -> list[Turn]:
    blocks = list(ffmpeg_io.decode_stream(wav_path, SR, 1))
    if not blocks:
        return []
    x = np.concatenate(blocks, axis=0)[:, 0]
    coef, energy = mfcc(x)
    if len(coef) < 50:
        return []

    # activité vocale : seuil entre le plancher de bruit et le niveau de parole
    thr = np.percentile(energy, 25) + 0.35 * (np.percentile(energy, 90) - np.percentile(energy, 25))
    voiced = energy > thr
    regions = _speech_regions(voiced)
    if not regions:
        return []

    # normalisation par fichier (compense le micro et le canal)
    m, s = coef[voiced].mean(axis=0), coef[voiced].std(axis=0) + 1e-6
    coef = (coef - m) / s

    # Les changements de locuteur ont presque toujours lieu sur une pause :
    # on découpe d'abord en plages de parole, puis en fenêtres à l'intérieur.
    win = int(WIN_S * SR / HOP)
    hop = int(WIN_HOP_S * SR / HOP)
    embs, meta = [], []                          # meta = (indice de plage, début, fin) en s
    for ri, (a, b) in enumerate(regions):
        positions = list(range(a, max(a + 1, b - win + 1), hop)) or [a]
        for p in positions:
            q = min(p + win, b)
            blk = coef[p:q][voiced[p:q]]
            if len(blk) < 20:
                continue
            embs.append(np.concatenate([blk.mean(axis=0), blk.std(axis=0)]))
            meta.append((ri, p * HOP / SR, q * HOP / SR))
    if len(embs) < 2:
        a, b = regions[0]
        return [Turn(a * HOP / SR, b * HOP / SR, "Intervenant 1")]

    # Pas de normalisation par dimension ici : elle ramènerait toutes les
    # distances à la même échelle et rendrait impossible de distinguer
    # « un seul locuteur » de « plusieurs ». La normalisation MFCC par fichier
    # (plus haut) suffit à compenser le micro.
    E = np.asarray(embs, dtype=np.float64)
    link = hierarchy.linkage(pdist(E, metric="cosine"), method="average")
    if max_speakers:
        k = max(1, min(max_speakers, len(E)))
        labels = (hierarchy.fcluster(link, k, criterion="maxclust") if k > 1
                  else np.ones(len(E), dtype=int))
    else:
        labels = _auto_labels(link)

    # étiquette par fenêtre → tours de parole, avec coupure à l'intérieur d'une
    # plage si le locuteur change en cours de route
    turns: list[Turn] = []
    for ri, (a, b) in enumerate(regions):
        idx = [i for i, mt in enumerate(meta) if mt[0] == ri]
        if not idx:
            continue
        r_start, r_end = a * HOP / SR, b * HOP / SR
        cuts, cur = [], labels[idx[0]]
        for j in range(1, len(idx)):
            if labels[idx[j]] != cur:
                cuts.append((meta[idx[j]][1] + meta[idx[j - 1]][2]) / 2)
                cur = labels[idx[j]]
        bounds = [r_start] + cuts + [r_end]
        seen = [labels[idx[0]]]
        for j in range(1, len(idx)):
            if labels[idx[j]] != seen[-1]:
                seen.append(labels[idx[j]])
        for j, lab in enumerate(seen):
            turns.append(Turn(round(bounds[j], 2), round(bounds[j + 1], 2), str(lab)))

    # fusion des tours voisins du même locuteur, puis nommage par ordre d'entrée
    merged: list[Turn] = []
    for t in turns:
        if merged and merged[-1].speaker == t.speaker and t.start - merged[-1].end < 0.8:
            merged[-1].end = t.end
        else:
            merged.append(t)
    order: dict[str, str] = {}
    for t in merged:
        if t.speaker not in order:
            order[t.speaker] = f"Intervenant {len(order) + 1}"
        t.speaker = order[t.speaker]
    return merged


# --------------------------------------------------------------------------- #
#  pyannote
# --------------------------------------------------------------------------- #


def _hf_token() -> str:
    """Jeton lu dans les réglages de l'outil, ou dans l'environnement."""
    return (config.get("hf_token") or os.environ.get("HF_TOKEN")
            or os.environ.get("HUGGINGFACE_TOKEN") or "")


def pyannote_available() -> bool:
    try:
        import pyannote.audio  # noqa: F401
        return bool(_hf_token())
    except Exception:
        return False


def _pyannote_diarize(wav_path: str, max_speakers: int = 0) -> list[Turn]:
    from pyannote.audio import Pipeline

    token = _hf_token()
    pipe = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=token)
    kw = dict(num_speakers=max_speakers) if max_speakers else {}
    result = pipe(wav_path, **kw)
    names, turns = {}, []
    for seg, _, label in result.itertracks(yield_label=True):
        if label not in names:
            names[label] = f"Intervenant {len(names) + 1}"
        turns.append(Turn(round(seg.start, 2), round(seg.end, 2), names[label]))
    return turns


# --------------------------------------------------------------------------- #


def diarize(wav_path: str, max_speakers: int = 0) -> tuple[list[Turn], str]:
    """Renvoie (tours de parole, méthode employée)."""
    if pyannote_available():
        try:
            return _pyannote_diarize(wav_path, max_speakers), "pyannote"
        except Exception:
            pass                                # jeton refusé, modèle absent : on retombe
    return _light_diarize(wav_path, max_speakers), "repli intégré"


def assign_speakers(segments, turns: list[Turn]) -> None:
    """Attribue un intervenant à chaque segment transcrit (recouvrement maximal)."""
    if not turns:
        return
    ts = np.array([[t.start, t.end] for t in turns])
    for s in segments:
        ov = np.minimum(ts[:, 1], s.end) - np.maximum(ts[:, 0], s.start)
        i = int(np.argmax(ov))
        if ov[i] > 0:
            s.speaker = turns[i].speaker
        else:                                   # aucun recouvrement : tour le plus proche
            mid = (s.start + s.end) / 2
            j = int(np.argmin(np.minimum(np.abs(ts[:, 0] - mid), np.abs(ts[:, 1] - mid))))
            s.speaker = turns[j].speaker


def speaking_time(segments) -> dict[str, float]:
    """Temps de parole par intervenant, mesuré sur les segments transcrits."""
    out: dict[str, float] = {}
    for s in segments:
        k = s.speaker or "Non attribué"
        out[k] = out.get(k, 0.0) + max(0.0, s.end - s.start)
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))
