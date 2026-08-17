"""Réglages persistants, stockés à côté des fichiers de sortie.

Évite toute variable d'environnement à définir à la main : le jeton
HuggingFace, le dossier surveillé et les derniers réglages sont écrits dans un
simple fichier JSON.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

_LOCK = threading.Lock()

DEFAULT_OUT = Path(os.environ.get("AUDIOTOOL_OUT", Path.home() / "Reunions_nettoyees"))
CONFIG_PATH = DEFAULT_OUT / "reglages.json"

DEFAULTS: dict = {
    "hf_token": "",
    "watch_folder": "",
    "watch_enabled": False,
    "settings": {},          # réglages audio
    "transcription": {},     # réglages de transcription
}


def _read() -> dict:
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return {**DEFAULTS, **(data if isinstance(data, dict) else {})}
    except Exception:
        return dict(DEFAULTS)


def load() -> dict:
    with _LOCK:
        return _read()


def get(key: str, default=None):
    return load().get(key, default)


def update(**kw) -> dict:
    with _LOCK:
        data = _read()
        data.update(kw)
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(CONFIG_PATH)
        # le jeton est aussi exposé au processus courant : les bibliothèques
        # tierces (HuggingFace) ne lisent que l'environnement
        if data.get("hf_token"):
            os.environ["HF_TOKEN"] = data["hf_token"]
        return data


def apply_env() -> None:
    """À appeler au démarrage : rend le jeton visible sans manipulation."""
    tok = load().get("hf_token")
    if tok:
        os.environ.setdefault("HF_TOKEN", tok)
