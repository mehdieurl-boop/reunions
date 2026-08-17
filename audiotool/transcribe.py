"""Transcription locale par faster-whisper.

Le moteur tourne entièrement sur la machine : rien n'est envoyé sur Internet,
hormis le téléchargement du modèle au premier usage.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Modèles disponibles, du plus rapide au plus précis.
# « vitesse » = facteur temps réel constaté sur un portable récent sans carte
# graphique (2 = deux fois plus rapide que la durée de l'audio).
MODELS = {
    "tiny":            dict(taille="75 Mo",  vitesse="~8x", qualite="brouillon"),
    "base":            dict(taille="145 Mo", vitesse="~5x", qualite="approximative"),
    "small":           dict(taille="480 Mo", vitesse="~2x", qualite="correcte"),
    "medium":          dict(taille="1,5 Go", vitesse="~1x", qualite="bonne"),
    "large-v3-turbo":  dict(taille="1,6 Go", vitesse="~2x", qualite="très bonne"),
    "large-v3":        dict(taille="3,1 Go", vitesse="~0,4x", qualite="la meilleure"),
}
DEFAULT_MODEL = "large-v3-turbo"

INSTALL_HINT = (
    "Le moteur de transcription n'est pas installé.\n"
    "Dans le dossier de l'outil, lancez :\n"
    "    .venv/bin/pip install faster-whisper        (macOS / Linux)\n"
    "    .venv\\Scripts\\pip install faster-whisper    (Windows)\n"
    "puis relancez. Le modèle se télécharge tout seul au premier usage."
)


@dataclass
class Segment:
    start: float
    end: float
    text: str
    speaker: str | None = None
    words: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TranscribeSettings:
    enabled: bool = False
    model: str = DEFAULT_MODEL
    language: str = "fr"          # "auto" pour laisser le moteur décider
    vocabulary: str = ""          # noms propres, sigles maison : améliore beaucoup
    diarize: bool = True
    max_speakers: int = 0         # 0 = automatique
    word_timestamps: bool = False
    formats: list = field(default_factory=lambda: ["docx", "txt", "json"])
    llm: bool = False             # synthèse rédigée par un modèle local (Ollama)
    llm_model: str = "llama3.1"
    engine: str = "faster-whisper"   # ou "mock" (tests)

    @classmethod
    def from_dict(cls, d: dict) -> "TranscribeSettings":
        return cls(**{k: v for k, v in (d or {}).items() if k in cls.__annotations__})

    def to_dict(self) -> dict:
        return asdict(self)


def is_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def model_is_downloaded(name: str) -> bool:
    """Cherche le modèle dans le cache HuggingFace, sans réseau."""
    cache = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    hub = cache / "hub" if (cache / "hub").exists() else cache
    if not hub.exists():
        return False
    return any(p.is_dir() and name in p.name.lower() for p in hub.glob("models--*"))


def status() -> dict:
    return dict(
        installed=is_available(),
        models={k: dict(v, telecharge=model_is_downloaded(k)) for k, v in MODELS.items()},
        default=DEFAULT_MODEL,
        hint=None if is_available() else INSTALL_HINT,
    )


# --------------------------------------------------------------------------- #
#  Moteurs
# --------------------------------------------------------------------------- #

_MODEL_CACHE: dict = {}


def _load_model(name: str):
    """Charge (et met en cache) le modèle. Le premier appel télécharge."""
    from faster_whisper import WhisperModel

    if name in _MODEL_CACHE:
        return _MODEL_CACHE[name]
    device, compute = "cpu", "int8"
    try:                                    # carte graphique NVIDIA si présente
        import torch
        if torch.cuda.is_available():
            device, compute = "cuda", "float16"
    except Exception:
        pass
    try:
        m = WhisperModel(name, device=device, compute_type=compute,
                         cpu_threads=max(1, (os.cpu_count() or 4) - 1))
    except Exception:                       # repli si le type de calcul n'est pas géré
        m = WhisperModel(name, device="cpu", compute_type="int8")
    _MODEL_CACHE[name] = m
    return m


def transcribe(wav_path: str, settings: TranscribeSettings, duration: float = 0.0,
               progress=None) -> tuple[list[Segment], dict]:
    """Renvoie (segments, informations). `progress` reçoit une fraction 0→1."""
    if settings.engine == "mock":
        return _mock(wav_path, duration, progress)

    if not is_available():
        raise RuntimeError(INSTALL_HINT)

    model = _load_model(settings.model)
    prompt = settings.vocabulary.strip() or None
    lang = None if settings.language in ("auto", "", None) else settings.language

    gen, info = model.transcribe(
        wav_path,
        language=lang,
        beam_size=5,
        vad_filter=True,                    # ignore les silences : plus rapide, moins d'hallucinations
        vad_parameters=dict(min_silence_duration_ms=500),
        word_timestamps=settings.word_timestamps,
        initial_prompt=prompt,
        condition_on_previous_text=True,
    )
    total = duration or getattr(info, "duration", 0.0) or 0.0
    out: list[Segment] = []
    for s in gen:                            # générateur : le calcul se fait ici
        words = [dict(start=w.start, end=w.end, word=w.word)
                 for w in (getattr(s, "words", None) or [])]
        text = s.text.strip()
        if text:
            out.append(Segment(round(s.start, 2), round(s.end, 2), text, words=words))
        if progress and total:
            progress(min(0.99, s.end / total))
    if progress:
        progress(1.0)
    return out, dict(langue=getattr(info, "language", settings.language),
                     modele=settings.model,
                     confiance_langue=round(float(getattr(info, "language_probability", 0) or 0), 2))


def _mock(wav_path: str, duration: float, progress=None):
    """Moteur factice : sert à tester toute la chaîne en aval sans modèle."""
    import wave
    import contextlib
    if not duration:
        try:
            with contextlib.closing(wave.open(wav_path)) as w:
                duration = w.getnframes() / w.getframerate()
        except Exception:
            duration = 60.0
    phrases = [
        "Bonjour à tous, merci d'être là pour ce point hebdomadaire.",
        "On commence par le budget : on est à quarante-deux mille euros sur le trimestre.",
        "Je pense qu'il faut décaler la mise en production, on n'est pas prêts.",
        "D'accord, on décide de reporter la livraison au quinze mars.",
        "Je m'occupe de prévenir le client avant vendredi.",
        "Est-ce qu'on a une visibilité sur les recrutements ?",
        "Deux profils sont en cours, réponse la semaine prochaine.",
        "Il faut que Marie prépare le support pour le comité de direction.",
        "On valide le principe, on rediscute des détails jeudi.",
        "Très bien, merci à tous, on se retrouve la semaine prochaine.",
    ]
    segs, t = [], 0.0
    i = 0
    while t < duration - 1 and i < 400:
        p = phrases[i % len(phrases)]
        d = min(2.0 + len(p) / 18.0, max(1.0, duration - t))
        segs.append(Segment(round(t, 2), round(t + d, 2), p))
        t += d + 0.4
        i += 1
        if progress and duration:
            progress(min(0.99, t / duration))
    if progress:
        progress(1.0)
    return segs, dict(langue="fr", modele="mock", confiance_langue=1.0)
