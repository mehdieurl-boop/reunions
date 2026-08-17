"""Serveur local : interface web complète.

Tout se pilote depuis la page — y compris l'installation des composants
optionnels et la surveillance d'un dossier. Aucune commande à taper.
Rien ne quitte la machine.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import threading
import time
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory
from werkzeug.utils import secure_filename

from . import config, ffmpeg_io, minutes, setup_tools
from . import transcribe as tr
from .pipeline import (PRESETS, Settings, analyze, make_preview, process_file,
                       run_transcription)
from .watcher import Watcher

APP_DIR = Path(__file__).parent

app = Flask(__name__, static_folder=str(APP_DIR / "static"))
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 ** 3      # 8 Go par envoi

JOBS: dict[str, dict] = {}
FILES: dict[str, dict] = {}
ANALYSES: dict[str, object] = {}
LOCK = threading.Lock()
POOL = ThreadPoolExecutor(max_workers=1)   # traitement sérialisé (gourmand en CPU)


# --------------------------------------------------------------------------- #
#  Dossiers
# --------------------------------------------------------------------------- #


def _out_dir() -> Path:
    d = Path(config.get("out_dir") or config.DEFAULT_OUT).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    (d / ".travail").mkdir(parents=True, exist_ok=True)
    return d


def _work() -> Path:
    return _out_dir() / ".travail"


def _analysis_for(fid: str, settings: Settings):
    key = f"{fid}:{settings.hum}"
    with LOCK:
        cached = ANALYSES.get(key)
    if cached is None:
        cached = analyze(FILES[fid]["path"], settings)
        with LOCK:
            ANALYSES[key] = cached
    return cached


# --------------------------------------------------------------------------- #
#  Page et configuration
# --------------------------------------------------------------------------- #


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/config")
def get_config():
    saved = config.load()
    return jsonify(
        defaults=Settings().to_dict(),
        presets=PRESETS,
        out_dir=str(_out_dir()),
        ffmpeg=ffmpeg_io.check_environment(),
        transcription=dict(tr.status(),
                           defaults=tr.TranscribeSettings().to_dict(),
                           llm=minutes.llm_available()),
        enregistre=dict(settings=saved.get("settings") or {},
                        transcription=saved.get("transcription") or {}),
        watch=WATCH.status(),
        setup=setup_tools.status(),
        systeme=platform.system(),
    )


@app.post("/api/settings")
def save_settings():
    """Mémorise les réglages : ils sont retrouvés au prochain démarrage."""
    d = request.json or {}
    config.update(settings=d.get("settings") or {},
                  transcription=d.get("transcription") or {})
    return jsonify(ok=True)


# --------------------------------------------------------------------------- #
#  Installation des composants (aucune commande à taper)
# --------------------------------------------------------------------------- #


@app.get("/api/setup")
def setup_status():
    return jsonify(setup_tools.status())


@app.post("/api/setup/install")
def setup_install():
    comp = (request.json or {}).get("component")
    if comp not in setup_tools.PACKAGES:
        return jsonify(error="composant inconnu"), 400
    setup_tools.install(comp)
    return jsonify(ok=True)


@app.post("/api/setup/model")
def setup_model():
    name = (request.json or {}).get("name")
    if name not in tr.MODELS:
        return jsonify(error="modèle inconnu"), 400
    setup_tools.download_model(name)
    return jsonify(ok=True)


@app.post("/api/setup/selftest")
def setup_selftest():
    d = request.json or {}
    name = d.get("model")
    if name not in tr.MODELS:
        return jsonify(error="modèle inconnu"), 400
    setup_tools.check_transcription(name, d.get("engine") or "faster-whisper")
    return jsonify(ok=True)


@app.post("/api/setup/token")
def setup_token():
    token = ((request.json or {}).get("token") or "").strip()
    config.update(hf_token=token)
    return jsonify(ok=True, defini=bool(token))


# --------------------------------------------------------------------------- #
#  Explorateur de dossiers (pour ne rien avoir à saisir)
# --------------------------------------------------------------------------- #


@app.get("/api/browse")
def browse():
    raw = request.args.get("path") or str(Path.home())
    p = Path(raw).expanduser()
    if not p.is_dir():
        p = Path.home()
    try:
        dirs = sorted((d for d in p.iterdir() if d.is_dir() and not d.name.startswith(".")),
                      key=lambda d: d.name.lower())
    except PermissionError:
        dirs = []
    fichiers = []
    if request.args.get("files"):
        from .watcher import EXTS
        for f in sorted(p.iterdir(), key=lambda f: f.name.lower()):
            if f.is_file() and f.suffix.lower() in EXTS and not f.name.startswith("."):
                fichiers.append(dict(name=f.name, path=str(f),
                                     size=round(f.stat().st_size / 1048576, 1)))
    home = Path.home()
    raccourcis = [d for d in (home, home / "Desktop", home / "Bureau", home / "Downloads",
                              home / "Téléchargements", home / "Documents",
                              home / "Documents" / "Zoom", home / "Zoom", home / "Movies",
                              home / "Vidéos", home / "Videos") if d.is_dir()]
    return jsonify(
        path=str(p),
        parent=str(p.parent) if p.parent != p else None,
        dirs=[dict(name=d.name, path=str(d)) for d in dirs[:400]],
        fichiers=fichiers[:400],
        raccourcis=[dict(name=d.name or str(d), path=str(d)) for d in raccourcis],
    )


@app.post("/api/out_dir")
def set_out_dir():
    raw = ((request.json or {}).get("path") or "").strip()
    p = Path(raw).expanduser()
    if not p.is_dir():
        return jsonify(ok=False, error="dossier introuvable"), 400
    config.update(out_dir=str(p))
    return jsonify(ok=True, path=str(_out_dir()))


# --------------------------------------------------------------------------- #
#  Fichiers
# --------------------------------------------------------------------------- #


@app.post("/api/files")
def add_files():
    """Réception par glisser-déposer (copie dans le dossier de travail)."""
    added = []
    for f in request.files.getlist("files"):
        fid = uuid.uuid4().hex[:12]
        dest = _work() / f"{fid}_{secure_filename(f.filename)}"
        f.save(dest)
        added.append(_register(fid, dest, f.filename))
    return jsonify(files=added)


@app.post("/api/files_by_path")
def add_by_path():
    """Ajout par chemin local : évite de recopier un fichier de 1 Go."""
    added, errors = [], []
    for raw in (request.json or {}).get("paths", []):
        p = Path(os.path.expanduser(raw.strip().strip('"')))
        if not p.exists() or not p.is_file():
            errors.append(str(p))
            continue
        added.append(_register(uuid.uuid4().hex[:12], p, p.name))
    return jsonify(files=added, errors=errors)


def _register(fid: str, path: Path, name: str) -> dict:
    info = ffmpeg_io.probe(str(path))
    rec = dict(id=fid, name=name, path=str(path), duration=round(info["duration"], 1),
               channels=info["channels"], sample_rate=info["sample_rate"])
    with LOCK:
        FILES[fid] = rec
    return rec


@app.delete("/api/files/<fid>")
def del_file(fid):
    with LOCK:
        rec = FILES.pop(fid, None)
    if rec and str(_work()) in rec["path"]:
        Path(rec["path"]).unlink(missing_ok=True)
    return jsonify(ok=True)


# --------------------------------------------------------------------------- #
#  Aperçu 20 s (avant / après)
# --------------------------------------------------------------------------- #


@app.post("/api/preview")
def preview():
    data = request.json or {}
    fid = data["file_id"]
    settings = Settings.from_dict(data.get("settings", {}))
    rec = FILES[fid]
    start = float(data.get("start", min(30.0, max(0.0, rec["duration"] * 0.25))))
    seconds = float(data.get("seconds", 20))
    start = max(0.0, min(start, max(0.0, rec["duration"] - seconds)))

    out = _work() / f"apercu_{fid}"
    if out.exists():
        shutil.rmtree(out, ignore_errors=True)
    res = make_preview(rec["path"], settings, str(out), start, seconds,
                       analysis=_analysis_for(fid, settings))
    stamp = int(time.time() * 1000)
    return jsonify(
        before=f"/api/preview_audio/{fid}/avant?v={stamp}",
        after=f"/api/preview_audio/{fid}/apres?v={stamp}",
        start=round(start, 1), analysis=res["analysis"],
    )


@app.get("/api/preview_audio/<fid>/<which>")
def preview_audio(fid, which):
    name = "apercu_avant.wav" if which == "avant" else "apercu_apres.wav"
    return send_file(_work() / f"apercu_{fid}" / name, mimetype="audio/wav")


# --------------------------------------------------------------------------- #
#  Traitement
# --------------------------------------------------------------------------- #


@app.post("/api/process")
def process():
    data = request.json or {}
    settings = Settings.from_dict(data.get("settings", {}))
    ts = tr.TranscribeSettings.from_dict(data.get("transcription", {}))
    if ts.enabled and "transcribe" not in settings.exports:
        settings.exports = list(settings.exports) + ["transcribe"]
    ids = [_submit(fid, settings, ts) for fid in data.get("file_ids", [])]
    return jsonify(job_ids=ids)


def _submit(fid: str, settings: Settings, ts) -> str:
    jid = uuid.uuid4().hex[:12]
    JOBS[jid] = dict(id=jid, file_id=fid, name=FILES[fid]["name"], state="en attente",
                     progress=0.0, message="En attente…", outputs=[], report=None,
                     error=None, auto=FILES[fid].get("auto", False))
    POOL.submit(_run, jid, fid, settings, ts)
    return jid


def _run(jid: str, fid: str, settings: Settings, ts=None):
    job = JOBS[jid]
    job["state"] = "en cours"
    # quand la transcription est demandée, le nettoyage n'occupe qu'une part
    # de la barre de progression : la transcription est bien plus longue
    share = 0.35 if (ts and ts.enabled) else 1.0

    def add_outputs(outs):
        job["outputs"] = job["outputs"] + [
            dict(kind=o["kind"], path=o["path"], name=Path(o["path"]).name,
                 size=Path(o["path"]).stat().st_size) for o in outs]

    try:
        def prog(f, msg=None):
            job["progress"] = round(float(f) * share, 3)
            if msg:
                job["message"] = msg

        res = process_file(FILES[fid]["path"], str(_out_dir()), settings,
                           progress=prog, analysis=_analysis_for(fid, settings))
        add_outputs(res["outputs"])
        job["report"] = res["report"]

        if ts and ts.enabled:
            wav = next((o["path"] for o in res["outputs"] if o["kind"] == "transcribe"), None)
            if not wav:
                raise RuntimeError("export « transcription » manquant")

            def prog2(f, msg=None):
                job["progress"] = round(share + (1 - share) * float(f), 3)
                if msg:
                    job["message"] = msg

            tres = run_transcription(wav, str(_out_dir()), ts,
                                     duration=res["report"]["duree_s"],
                                     progress=prog2, titre=Path(FILES[fid]["name"]).stem)
            add_outputs(tres["outputs"])
            job["report"] = dict(job["report"], **tres["report"])

        job["state"] = "terminé"
        job["progress"] = 1.0
        job["message"] = "Terminé"
    except Exception as e:  # noqa: BLE001
        job["state"] = "erreur"
        job["error"] = str(e)
        job["message"] = f"Erreur : {e}"


@app.get("/api/jobs")
def jobs():
    return jsonify(jobs=list(JOBS.values())[-40:])


@app.get("/api/download")
def download():
    p = Path(request.args["path"])
    if not p.exists():
        return jsonify(error="fichier introuvable"), 404
    return send_file(p, as_attachment=True, download_name=p.name)


@app.post("/api/open_folder")
def open_folder():
    d = (request.json or {}).get("path") or str(_out_dir())
    try:
        if platform.system() == "Darwin":
            subprocess.Popen(["open", d])
        elif platform.system() == "Windows":
            os.startfile(d)  # noqa: S606
        else:
            subprocess.Popen(["xdg-open", d])
        return jsonify(ok=True, dir=d)
    except Exception as e:  # noqa: BLE001
        return jsonify(ok=False, dir=d, error=str(e))


# --------------------------------------------------------------------------- #
#  Dossier surveillé
# --------------------------------------------------------------------------- #


def _auto_submit(path: str) -> None:
    """Appelé par le surveillant : traite le fichier avec les réglages mémorisés."""
    saved = config.load()
    settings = Settings.from_dict(saved.get("settings") or {})
    ts = tr.TranscribeSettings.from_dict(saved.get("transcription") or {})
    if ts.enabled and "transcribe" not in settings.exports:
        settings.exports = list(settings.exports) + ["transcribe"]
    fid = uuid.uuid4().hex[:12]
    rec = _register(fid, Path(path), Path(path).name)
    rec["auto"] = True
    _submit(fid, settings, ts)


WATCH = Watcher(_auto_submit, config.DEFAULT_OUT / ".surveillance.json")


@app.get("/api/watch")
def watch_status():
    return jsonify(WATCH.status())


@app.post("/api/watch")
def watch_set():
    d = request.json or {}
    folder = (d.get("folder") or "").strip()
    enabled = bool(d.get("enabled"))
    config.update(watch_folder=folder, watch_enabled=enabled)
    st = WATCH.configure(folder, enabled)
    return jsonify(st)


# --------------------------------------------------------------------------- #


def main(port: int = 7862, open_browser: bool = True):
    config.apply_env()
    _out_dir()
    saved = config.load()
    if saved.get("watch_enabled") and saved.get("watch_folder"):
        WATCH.configure(saved["watch_folder"], True)
    url = f"http://127.0.0.1:{port}"
    print("=" * 64)
    print("  Réunions — nettoyage audio et transcription")
    print(f"  Interface : {url}")
    print(f"  Fichiers produits : {_out_dir()}")
    print(f"  ffmpeg : {ffmpeg_io.check_environment()}")
    print("  (fermez cette fenêtre pour arrêter)")
    print("=" * 64)
    if open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, threaded=True)


if __name__ == "__main__":
    main()
