"""Installation des composants optionnels depuis l'interface.

L'utilisateur n'a rien à taper : les commandes pip et le téléchargement des
modèles sont lancés ici, en tâche de fond, et le journal est renvoyé à la page.
"""
from __future__ import annotations

import importlib
import subprocess
import sys
import threading
from collections import deque

from . import config

# --------------------------------------------------------------------------- #

TASK = {
    "running": False,
    "name": "",
    "log": deque(maxlen=400),
    "ok": None,
    "message": "",
}
_LOCK = threading.Lock()

PACKAGES = {
    "transcription": dict(
        label="Moteur de transcription",
        pip=["faster-whisper"],
        module="faster_whisper",
        note="Environ 200 Mo de composants. À faire une seule fois.",
    ),
    "intervenants": dict(
        label="Identification avancée des intervenants",
        pip=["pyannote.audio"],
        module="pyannote.audio",
        note="Environ 2 Go (PyTorch). Nécessite un jeton HuggingFace gratuit.",
    ),
}


def _log(line: str) -> None:
    TASK["log"].append(line.rstrip())


def is_installed(module: str) -> bool:
    try:
        importlib.invalidate_caches()
        importlib.import_module(module)
        return True
    except Exception:
        return False


def status() -> dict:
    from . import transcribe as tr

    return dict(
        python=sys.version.split()[0],
        dans_environnement_isole=sys.prefix != getattr(sys, "base_prefix", sys.prefix),
        composants={
            key: dict(label=p["label"], note=p["note"], installe=is_installed(p["module"]))
            for key, p in PACKAGES.items()
        },
        modeles={k: dict(v, telecharge=tr.model_is_downloaded(k))
                 for k, v in tr.MODELS.items()},
        jeton_hf=bool(config.get("hf_token")),
        tache=dict(running=TASK["running"], name=TASK["name"], ok=TASK["ok"],
                   message=TASK["message"], log=list(TASK["log"])[-40:]),
    )


def _run(name: str, fn) -> None:
    with _LOCK:
        if TASK["running"]:
            return
        TASK.update(running=True, name=name, ok=None, message="")
        TASK["log"].clear()

    def worker():
        try:
            fn()
            TASK.update(ok=True, message="Terminé.")
        except Exception as e:  # noqa: BLE001
            TASK.update(ok=False, message=str(e))
            _log(f"ERREUR : {e}")
        finally:
            TASK["running"] = False

    threading.Thread(target=worker, daemon=True).start()


def _pip(args: list[str]) -> None:
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", *args]
    _log("$ " + " ".join(cmd[2:]))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1)
    for line in proc.stdout:
        _log(line)
    if proc.wait() != 0:
        # environnement Python géré par le système (Debian, Homebrew) : on
        # retente avec l'option qui l'autorise explicitement
        _log("Nouvelle tentative avec --break-system-packages…")
        proc = subprocess.Popen(cmd + ["--break-system-packages"],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1)
        for line in proc.stdout:
            _log(line)
        if proc.wait() != 0:
            raise RuntimeError("l'installation a échoué — voir le journal ci-dessus")


def install(component: str) -> None:
    p = PACKAGES[component]

    def job():
        _log(f"Installation : {p['label']}")
        _pip(p["pip"])
        importlib.invalidate_caches()
        if not is_installed(p["module"]):
            raise RuntimeError("le composant ne se charge pas après installation ; "
                               "fermez puis relancez l'outil")
        _log("Composant installé et détecté.")

    _run(p["label"], job)


def download_model(name: str) -> None:
    from . import transcribe as tr

    def job():
        if not tr.is_available():
            raise RuntimeError("installez d'abord le moteur de transcription")
        size = tr.MODELS.get(name, {}).get("taille", "")
        _log(f"Téléchargement du modèle « {name} » ({size})…")
        _log("Le premier téléchargement peut prendre plusieurs minutes.")
        tr._load_model(name)
        _log("Modèle prêt : les prochains lancements fonctionnent hors ligne.")

    _run(f"Modèle {name}", job)
