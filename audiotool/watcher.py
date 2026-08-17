"""Dossier surveillé : tout enregistrement déposé est traité automatiquement.

Remplace la tâche planifiée en ligne de commande — l'utilisateur choisit un
dossier dans l'interface, et n'a plus rien à faire ensuite.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

EXTS = {".m4a", ".mp3", ".wav", ".mp4", ".mov", ".aac", ".flac", ".ogg",
        ".opus", ".mkv", ".webm", ".wma", ".aiff", ".m4v"}
POLL_S = 15
STABLE_S = 6          # un fichier encore en cours de copie ne doit pas être pris


class Watcher:
    """Surveille un dossier et confie les nouveaux fichiers à `submit`."""

    def __init__(self, submit, state_path: Path):
        self.submit = submit
        self.state_path = Path(state_path)
        self.folder: Path | None = None
        self.enabled = False
        self.last_scan = 0.0
        self.found = 0
        self._sizes: dict[str, tuple[int, float]] = {}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.done: set[str] = self._load()

    # -- mémoire des fichiers déjà traités ---------------------------------- #

    def _load(self) -> set[str]:
        try:
            return set(json.loads(self.state_path.read_text(encoding="utf-8")))
        except Exception:
            return set()

    def _save(self) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(sorted(self.done), ensure_ascii=False),
                                       encoding="utf-8")
        except Exception:
            pass

    # -- pilotage ------------------------------------------------------------ #

    def configure(self, folder: str | None, enabled: bool, mark_existing: bool = True):
        """Active la surveillance. Les fichiers déjà présents sont marqués comme
        vus : on ne retraite pas tout l'historique du dossier au démarrage."""
        self.folder = Path(folder).expanduser() if folder else None
        self.enabled = bool(enabled and self.folder and self.folder.is_dir())
        if self.enabled and mark_existing:
            for p in self._candidates():
                self.done.add(str(p))
            self._save()
        if self.enabled and (self._thread is None or not self._thread.is_alive()):
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
        return self.status()

    def status(self) -> dict:
        return dict(
            enabled=self.enabled,
            folder=str(self.folder) if self.folder else "",
            valide=bool(self.folder and self.folder.is_dir()),
            derniere_verification=round(self.last_scan, 0) or None,
            deja_traites=len(self.done),
            reperes=self.found,
        )

    def stop(self):
        self.enabled = False
        self._stop.set()

    # -- boucle -------------------------------------------------------------- #

    def _candidates(self):
        if not self.folder or not self.folder.is_dir():
            return []
        out = []
        for p in sorted(self.folder.iterdir()):
            if p.is_file() and p.suffix.lower() in EXTS and not p.name.startswith("."):
                out.append(p)
        return out

    def _loop(self):
        while not self._stop.is_set() and self.enabled:
            try:
                self._scan()
            except Exception:
                pass
            self._stop.wait(POLL_S)

    def _scan(self):
        self.last_scan = time.time()
        for p in self._candidates():
            key = str(p)
            if key in self.done:
                continue
            try:
                size = p.stat().st_size
            except OSError:
                continue
            prev = self._sizes.get(key)
            now = time.time()
            # on attend que la taille cesse de bouger : sinon on traiterait un
            # fichier encore en cours de copie ou d'export
            if prev is None or prev[0] != size:
                self._sizes[key] = (size, now)
                continue
            if now - prev[1] < STABLE_S or size < 10_000:
                continue
            self.done.add(key)
            self._save()
            self.found += 1
            self.submit(key)
