"""Chaîne complète : analyse du fichier, traitement en flux, exports."""
from __future__ import annotations

import tempfile
from dataclasses import dataclass, asdict, field
from pathlib import Path

import numpy as np
from scipy import ndimage

from . import dsp, ffmpeg_io

SR = 48_000              # fréquence de travail interne
CHUNK = 30 * SR          # blocs de 30 s
PAD = SR                 # 1 s de contexte de part et d'autre (évite les coutures)


# --------------------------------------------------------------------------- #
#  Réglages
# --------------------------------------------------------------------------- #


@dataclass
class Settings:
    denoise: int = 60          # force du débruitage        0-100
    softness: int = 50         # douceur (aigus + désessage) 0-100
    compression: int = 55      # compression                0-100
    presence: int = 45         # intelligibilité (2,8 kHz)  0-100
    highpass: int = 85         # passe-haut (Hz)
    hum: str = "auto"          # "auto" | "50" | "60" | "off"
    gate: bool = True          # expandeur entre les prises de parole
    keep_stereo: bool = False  # une réunion se traite très bien en mono (2x plus rapide)
    target_listen: float = -16.0     # LUFS export écoute
    target_transcribe: float = -20.0  # LUFS export transcription
    exports: list = field(default_factory=lambda: ["listen", "transcribe"])
    listen_format: str = "mp3"       # mp3 | wav | flac
    trim_silence: bool = False       # raccourcir les silences (export transcription)
    segment_minutes: int = 0         # découpage de l'export transcription (0 = non)

    @classmethod
    def from_dict(cls, d: dict) -> "Settings":
        f = {k: v for k, v in (d or {}).items() if k in cls.__annotations__}
        return cls(**f)

    def to_dict(self) -> dict:
        return asdict(self)


PRESETS = {
    "zoom_standard": dict(denoise=60, softness=50, compression=55, presence=45,
                          highpass=85, gate=True),
    "zoom_micro_lointain": dict(denoise=78, softness=40, compression=72, presence=62,
                                highpass=95, gate=True),
    "zoom_bon_micro": dict(denoise=35, softness=55, compression=40, presence=30,
                           highpass=75, gate=False),
    "salle_bruyante": dict(denoise=88, softness=45, compression=78, presence=58,
                           highpass=110, gate=True),
}


# --------------------------------------------------------------------------- #
#  Analyse préalable (un seul passage de décodage, mémoire constante)
# --------------------------------------------------------------------------- #


@dataclass
class Analysis:
    noise_mag: np.ndarray
    noise_floor_db: float
    speech_level_db: float
    peak_db: float
    hum_hz: float | None
    duration: float
    channels: int


def analyze(path: str, settings: Settings, progress=None) -> Analysis:
    info = ffmpeg_io.probe(path)
    dur = max(info["duration"], 0.001)
    nch = 1                                  # analyse en mono, suffisant et rapide
    mags, rms = [], []
    spec_sum = np.zeros(dsp.N_FFT // 2 + 1)
    nframes = 0
    done = 0.0
    keep_every = max(1, int(dur / 600))      # sous-échantillonnage des trames gardées

    for i, block in enumerate(ffmpeg_io.decode_stream(path, SR, nch)):
        x = block[:, 0]
        done += len(x) / SR
        # RMS courts (50 ms) pour le plancher de bruit et le niveau de parole
        w = int(0.05 * SR)
        n = (len(x) // w) * w
        if n:
            r = np.sqrt(np.mean(x[:n].reshape(-1, w) ** 2, axis=1))
            rms.append(r.astype(np.float32))
        # la STFT n'est calculée que sur les blocs retenus : sur un fichier long
        # cela divise le temps d'analyse par autant, sans changer les statistiques
        if len(x) >= dsp.N_FFT and i % keep_every == 0:
            m = np.abs(dsp._stft(x))
            spec_sum += m.mean(axis=1)
            nframes += 1
            mags.append(m[:, ::8].astype(np.float32))
        if progress:
            progress(min(0.18, 0.18 * done / dur))

    if not mags:
        mags = [np.zeros((dsp.N_FFT // 2 + 1, 1), dtype=np.float32)]
    allmag = np.concatenate(mags, axis=1)
    noise_mag = np.percentile(allmag, 20, axis=1).astype(np.float32)

    r = np.concatenate(rms) if rms else np.array([1e-4], dtype=np.float32)
    rdb = 20 * np.log10(r + dsp.EPS)
    voiced = rdb[rdb > np.percentile(rdb, 50)]
    noise_floor = float(np.percentile(rdb, 12))
    speech = float(np.percentile(voiced if voiced.size else rdb, 75))
    peak = float(np.max(rdb)) if rdb.size else -60.0

    hum = None
    if settings.hum != "off" and nframes:
        spec = spec_sum / max(nframes, 1)
        spec_db = 20 * np.log10(spec + dsp.EPS)
        base = ndimage.median_filter(spec_db, size=21, mode="nearest")
        bin_hz = SR / dsp.N_FFT
        if settings.hum in ("50", "60"):
            hum = float(settings.hum)
        else:
            best, best_score = None, 5.0     # seuil de détection : 5 dB
            for f0 in (50.0, 60.0):
                idx = [int(round(f0 * k / bin_hz)) for k in (1, 2, 3, 4)]
                idx = [i for i in idx if 0 < i < len(spec_db)]
                score = float(np.mean([spec_db[i] - base[i] for i in idx]))
                if score > best_score:
                    best, best_score = f0, score
            hum = best

    return Analysis(noise_mag=noise_mag, noise_floor_db=noise_floor,
                    speech_level_db=speech, peak_db=peak, hum_hz=hum,
                    duration=dur, channels=min(info["channels"], 2))


# --------------------------------------------------------------------------- #
#  Chaîne de traitement appliquée à un segment
# --------------------------------------------------------------------------- #


def _eq_chain(settings: Settings, ana: Analysis) -> np.ndarray:
    soft = settings.softness / 100.0
    pres = settings.presence / 100.0
    sos = [dsp.highpass_sos(max(20, settings.highpass), SR, order=4)]
    if ana.hum_hz:
        for k in (1, 2, 3, 4):
            f = ana.hum_hz * k
            if settings.highpass * 0.9 < f < SR / 2 * 0.9:
                sos.append(dsp.notch_sos(f, SR, q=30))
    sos.append(dsp.low_shelf(140, SR, -1.5 - 1.5 * soft))        # dégraisse le bas
    sos.append(dsp.peaking(330, SR, -2.0 - 1.5 * soft, q=1.1))   # boue / résonance de pièce
    sos.append(dsp.peaking(2800, SR, 3.0 * pres, q=0.9))         # intelligibilité
    sos.append(dsp.high_shelf(7000, SR, -1.0 - 5.0 * soft))      # adoucit / calme le souffle
    return np.vstack(sos)


def process_segment(x: np.ndarray, settings: Settings, ana: Analysis,
                    eq_sos: np.ndarray) -> np.ndarray:
    y = dsp.apply_sos(x, eq_sos)
    y = dsp.denoise(y, ana.noise_mag, settings.denoise / 100.0)
    if settings.gate:
        rng = 5.0 + 9.0 * settings.denoise / 100.0
        y = dsp.expander(y, SR, threshold_db=ana.noise_floor_db + 9.0,
                         ratio=2.0, range_db=rng)
    y = dsp.de_esser(y, SR, amount=settings.softness / 100.0)
    ratio = 1.0 + 4.0 * settings.compression / 100.0
    y = dsp.compressor(y, SR, threshold_db=ana.speech_level_db - 7.0, ratio=ratio)
    return dsp.limiter(y, SR, ceiling_db=-1.5)


# --------------------------------------------------------------------------- #
#  Traitement complet d'un fichier
# --------------------------------------------------------------------------- #


def process_file(path: str, out_dir: str, settings: Settings, progress=None,
                 analysis: Analysis | None = None) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(path).stem
    prog = progress or (lambda f, m=None: None)

    prog(0.02, "Analyse du fichier…")
    ana = analysis or analyze(path, settings, lambda f: prog(f, "Analyse du fichier…"))
    nch = ana.channels if settings.keep_stereo else 1
    eq_sos = _eq_chain(settings, ana)

    tmp = tempfile.NamedTemporaryFile(suffix="_clean.wav", delete=False)
    tmp.close()
    writer = ffmpeg_io.RawWriter(tmp.name, SR, nch)
    meter = dsp.LoudnessMeter(SR, nch)
    meter_mono = dsp.LoudnessMeter(SR, 1) if nch > 1 else meter

    prog(0.2, "Nettoyage…")
    left = np.zeros((0, nch), dtype=np.float32)
    buf = np.zeros((0, nch), dtype=np.float32)
    total = max(ana.duration * SR, 1)
    emitted = 0
    stream = ffmpeg_io.decode_stream(path, SR, nch)
    eof = False

    def flush(core_len: int, right: np.ndarray):
        nonlocal left, emitted
        seg = np.concatenate([left, buf[:core_len], right], axis=0)
        y = process_segment(seg, settings, ana, eq_sos)
        core = y[len(left):len(left) + core_len]
        writer.write(core)
        meter.push(core)
        if nch > 1:
            meter_mono.push(core.mean(axis=1))
        left = np.concatenate([left, buf[:core_len]], axis=0)[-PAD:]
        emitted += core_len
        prog(0.2 + 0.68 * min(1.0, emitted / total), "Nettoyage…")

    while not eof or len(buf):
        while not eof and len(buf) < CHUNK + PAD:
            try:
                buf = np.concatenate([buf, next(stream)], axis=0)
            except StopIteration:
                eof = True
        core_len = min(CHUNK, len(buf)) if eof else CHUNK
        if core_len == 0:
            break
        right = buf[core_len:core_len + PAD]
        flush(core_len, right)
        buf = buf[core_len:]

    writer.close()

    lufs = meter.integrated()
    lufs_mono = meter_mono.integrated() if nch > 1 else lufs
    prog(0.9, "Export…")

    outputs = []
    if "listen" in settings.exports:
        ext = {"mp3": ".mp3", "wav": ".wav", "flac": ".flac"}.get(settings.listen_format, ".mp3")
        dest = out_dir / f"{stem}_ecoute{ext}"
        gain = float(np.clip(settings.target_listen - lufs, -20, 25))
        outputs += [dict(kind="listen", path=p) for p in ffmpeg_io.encode(
            tmp.name, str(dest), gain, bitrate="192k" if nch > 1 else "128k",
            ceiling_db=-1.0)]
    if "transcribe" in settings.exports:
        dest = out_dir / f"{stem}_transcription.wav"
        gain = float(np.clip(settings.target_transcribe - lufs_mono, -20, 25))
        outputs += [dict(kind="transcribe", path=p) for p in ffmpeg_io.encode(
            tmp.name, str(dest), gain, mono=True, sr=16000, codec="pcm_s16le",
            ceiling_db=-1.0, trim_silence=settings.trim_silence,
            segment_minutes=settings.segment_minutes)]

    Path(tmp.name).unlink(missing_ok=True)
    prog(1.0, "Terminé")
    return dict(
        outputs=outputs,
        report=dict(
            duree_s=round(ana.duration, 1),
            canaux=nch,
            canaux_source=ana.channels,
            plancher_bruit_dbfs=round(ana.noise_floor_db, 1),
            niveau_parole_dbfs=round(ana.speech_level_db, 1),
            ronflement_secteur_hz=ana.hum_hz,
            lufs_apres_traitement=round(lufs, 1),
            gain_applique_ecoute_db=round(float(np.clip(settings.target_listen - lufs, -20, 25)), 1),
        ),
    )


# --------------------------------------------------------------------------- #
#  Transcription (à partir de l'export « transcription » déjà nettoyé)
# --------------------------------------------------------------------------- #


def run_transcription(wav_path: str, out_dir: str, ts, duration: float = 0.0,
                      progress=None, titre: str = "") -> dict:
    """Transcrit un WAV mono 16 kHz et écrit les livrables demandés."""
    from . import diarize as diar
    from . import documents, minutes, transcribe as tr

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(wav_path).stem.replace("_transcription", "")
    prog = progress or (lambda f, m=None: None)

    prog(0.02, "Transcription…")
    segs, info = tr.transcribe(wav_path, ts, duration,
                               lambda f: prog(0.02 + 0.80 * f, "Transcription…"))

    methode = None
    if ts.diarize and segs:
        prog(0.84, "Identification des intervenants…")
        turns, methode = diar.diarize(wav_path, ts.max_speakers)
        diar.assign_speakers(segs, turns)
    speaking = diar.speaking_time(segs) if ts.diarize else {}

    prog(0.90, "Relevé de décisions…")
    releve = minutes.extract(segs, duration or (segs[-1].end if segs else 0.0), speaking)

    synthese = None
    if ts.llm:
        prog(0.92, "Synthèse par modèle local…")
        synthese = minutes.synthese_llm(segs, ts.llm_model)

    meta = {
        "titre": titre or stem,
        "durée": documents.hhmmss(duration or (segs[-1].end if segs else 0.0)),
        "modèle": info.get("modele"),
        "langue": info.get("langue"),
        "intervenants": (f"{len(speaking)} (méthode : {methode})" if speaking else "non identifiés"),
    }

    prog(0.95, "Écriture des documents…")
    outputs = []
    if "txt" in ts.formats:
        outputs.append(dict(kind="verbatim_txt", path=documents.write_txt(
            str(out_dir / f"{stem}_verbatim.txt"), segs, meta)))
    if "srt" in ts.formats:
        outputs.append(dict(kind="sous_titres", path=documents.write_srt(
            str(out_dir / f"{stem}.srt"), segs)))
    if "docx" in ts.formats:
        outputs.append(dict(kind="compte_rendu", path=documents.write_docx(
            str(out_dir / f"{stem}_compte-rendu.docx"), segs, meta, releve, synthese)))
    if "json" in ts.formats:
        outputs.append(dict(kind="donnees_json", path=documents.write_json(
            str(out_dir / f"{stem}_transcription.json"), segs, meta, releve)))

    prog(1.0, "Terminé")
    return dict(outputs=outputs, segments=segs, releve=releve, methode_locuteurs=methode,
                report=dict(
                    nb_segments=len(segs),
                    nb_mots=releve["stats"]["nb_mots"],
                    intervenants=len(speaking) or None,
                    methode_locuteurs=methode,
                    decisions_reperees=len(releve["decisions"]),
                    actions_reperees=len(releve["actions"]),
                    modele=info.get("modele"),
                ))


def make_preview(path: str, settings: Settings, out_dir: str, start: float,
                 seconds: float = 20.0, analysis: Analysis | None = None) -> dict:
    """Extrait court avant / après, pour régler les curseurs sans traiter 1 h."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ana = analysis or analyze(path, settings)
    nch = ana.channels if settings.keep_stereo else 1
    blocks = list(ffmpeg_io.decode_stream(path, SR, nch, start=start, duration=seconds))
    x = np.concatenate(blocks, axis=0) if blocks else np.zeros((SR, nch), np.float32)
    y = process_segment(x, settings, ana, _eq_chain(settings, ana))

    # les deux extraits sont calés à la même sonie : on compare la qualité, pas le volume
    before, after = out_dir / "apercu_avant.wav", out_dir / "apercu_apres.wav"
    for arr, dest in ((x, before), (y, after)):
        raw = str(dest) + ".f32.wav"
        w = ffmpeg_io.RawWriter(raw, SR, nch)
        w.write(arr)
        w.close()
        m = dsp.LoudnessMeter(SR, nch)
        m.push(arr)
        g = float(np.clip(settings.target_listen - m.integrated(), -20, 25))
        ffmpeg_io.encode(raw, str(dest), g, codec="pcm_s16le")
        Path(raw).unlink(missing_ok=True)
    return dict(before=str(before), after=str(after), analysis=dict(
        plancher_bruit_dbfs=round(ana.noise_floor_db, 1),
        ronflement_secteur_hz=ana.hum_hz))
