"""Ligne de commande : nettoyage par lot, sans interface.

Exemples
--------
    python -m audiotool.cli reunion.m4a
    python -m audiotool.cli *.m4a --preset salle_bruyante --out ./nettoyes
    python -m audiotool.cli reunion.m4a --exports transcribe --segment-minutes 20
    python -m audiotool.cli --serveur          # lance l'interface web
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import console_utf8
from .pipeline import PRESETS, Settings, process_file, run_transcription
from .transcribe import DEFAULT_MODEL, MODELS, TranscribeSettings, status as tr_status


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="audiotool",
        description="Nettoyage d'enregistrements de réunion avant transcription.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("fichiers", nargs="*", help="fichiers audio ou vidéo à traiter")
    p.add_argument("--out", "-o", default="./nettoyes", help="dossier de sortie")
    p.add_argument("--preset", choices=sorted(PRESETS), help="réglage de départ")
    p.add_argument("--denoise", type=int, help="force du débruitage (0-100)")
    p.add_argument("--softness", type=int, help="douceur des aigus (0-100)")
    p.add_argument("--compression", type=int, help="compression (0-100)")
    p.add_argument("--presence", type=int, help="intelligibilité (0-100)")
    p.add_argument("--highpass", type=int, help="coupe-grave en Hz")
    p.add_argument("--hum", choices=["auto", "50", "60", "off"], help="ronflement secteur")
    p.add_argument("--no-gate", action="store_true", help="ne pas atténuer le fond")
    p.add_argument("--stereo", action="store_true",
                   help="conserver la stéréo (par défaut : traitement mono, 2x plus rapide)")
    p.add_argument("--exports", nargs="+", choices=["listen", "transcribe"],
                   help="exports voulus (défaut : les deux)")
    p.add_argument("--listen-format", choices=["mp3", "wav", "flac"])
    p.add_argument("--trim-silence", action="store_true",
                   help="raccourcir les longs silences (export transcription)")
    p.add_argument("--segment-minutes", type=int, help="découper l'export transcription")
    g = p.add_argument_group("transcription")
    g.add_argument("--transcrire", action="store_true", help="transcrire après le nettoyage")
    g.add_argument("--modele", choices=list(MODELS), default=DEFAULT_MODEL)
    g.add_argument("--langue", default="fr", help="fr, en… ou auto")
    g.add_argument("--vocabulaire", default="", help="noms propres et sigles à souffler au moteur")
    g.add_argument("--intervenants", type=int, default=0,
                   help="nombre d'intervenants (0 = automatique)")
    g.add_argument("--sans-locuteurs", action="store_true",
                   help="ne pas identifier les intervenants")
    g.add_argument("--livrables", nargs="+", default=["docx", "txt", "json"],
                   choices=["docx", "txt", "srt", "json"])
    g.add_argument("--llm", action="store_true",
                   help="synthèse rédigée par un modèle local (Ollama)")
    g.add_argument("--moteur", default="faster-whisper", choices=["faster-whisper", "mock"])
    p.add_argument("--telecharger-modele", metavar="NOM", choices=list(MODELS),
                   help="télécharger un modèle de transcription à l'avance")
    p.add_argument("--verifier", action="store_true",
                   help="afficher l'état de l'environnement de transcription")
    p.add_argument("--serveur", action="store_true", help="lancer l'interface web")
    p.add_argument("--port", type=int, default=7862)
    return p


def settings_from_args(a) -> Settings:
    s = Settings(**PRESETS[a.preset]) if a.preset else Settings()
    for k in ("denoise", "softness", "compression", "presence", "highpass", "hum",
              "listen_format", "segment_minutes"):
        v = getattr(a, k, None)
        if v is not None:
            setattr(s, k, v)
    if a.no_gate:
        s.gate = False
    if a.stereo:
        s.keep_stereo = True
    if a.exports:
        s.exports = list(a.exports)
    if a.trim_silence:
        s.trim_silence = True
    return s


def transcribe_settings_from_args(a) -> TranscribeSettings:
    return TranscribeSettings(
        enabled=a.transcrire, model=a.modele, language=a.langue,
        vocabulary=a.vocabulaire, diarize=not a.sans_locuteurs,
        max_speakers=a.intervenants, formats=list(a.livrables),
        llm=a.llm, engine=a.moteur)


def main(argv=None) -> int:
    console_utf8()
    a = build_parser().parse_args(argv)
    if a.telecharger_modele:
        from .transcribe import _load_model, is_available, INSTALL_HINT
        if not is_available():
            print(INSTALL_HINT)
            return 1
        print(f"Téléchargement du modèle « {a.telecharger_modele} » "
              f"({MODELS[a.telecharger_modele]['taille']})… "
              "cela peut prendre quelques minutes.")
        _load_model(a.telecharger_modele)
        print("Modèle prêt. Les prochains lancements fonctionnent hors ligne.")
        return 0
    if a.verifier:
        st = tr_status()
        print("Moteur de transcription :", "installé" if st["installed"] else "ABSENT")
        if st["hint"]:
            print(st["hint"])
        print("\nModèles :")
        for k, m in st["models"].items():
            print(f"  {k:16s} {m['taille']:>7s}  {m['vitesse']:>5s}  {m['qualite']:14s}"
                  f"{'  ✓ téléchargé' if m['telecharge'] else ''}")
        from . import minutes as _m
        print("\nModèle de langue local (Ollama) :",
              "détecté" if _m.llm_available() else "absent")
        return 0
    if a.serveur or not a.fichiers:
        from .server import main as serve
        serve(port=a.port)
        return 0

    s = settings_from_args(a)
    ts = transcribe_settings_from_args(a)
    if ts.enabled and "transcribe" not in s.exports:
        s.exports = list(s.exports) + ["transcribe"]
    total_ok = 0
    for f in a.fichiers:
        path = Path(f)
        if not path.exists():
            print(f"  ! introuvable : {f}", file=sys.stderr)
            continue
        print(f"\n▸ {path.name}")
        t0 = time.time()
        last = [-1]

        def prog(frac, msg=None):
            pct = int(frac * 100)
            if pct != last[0]:
                last[0] = pct
                bar = "█" * (pct // 4) + "·" * (25 - pct // 4)
                print(f"\r  {bar} {pct:3d}%  {msg or '':<22}", end="", flush=True)

        try:
            res = process_file(str(path), a.out, s, progress=prog)
        except Exception as e:  # noqa: BLE001
            print(f"\r  échec : {e}{' ' * 30}")
            continue
        print(f"\r  nettoyage terminé en {time.time() - t0:.0f} s{' ' * 30}")
        outputs = list(res["outputs"])
        report = dict(res["report"])

        if ts.enabled:
            wav = next((o["path"] for o in outputs if o["kind"] == "transcribe"), None)
            t1, last[0] = time.time(), -1
            try:
                tres = run_transcription(wav, a.out, ts, duration=res["report"]["duree_s"],
                                         progress=prog, titre=path.stem)
                outputs += tres["outputs"]
                report.update(tres["report"])
                print(f"\r  transcription terminée en {time.time() - t1:.0f} s{' ' * 30}")
            except Exception as e:  # noqa: BLE001
                print(f"\r  transcription impossible : {e}{' ' * 20}")

        for k, v in report.items():
            print(f"    {k:28s} {v}")
        for o in outputs:
            print(f"    → {o['path']}")
        total_ok += 1
    print(f"\n{total_ok} fichier(s) traité(s). Sortie : {Path(a.out).resolve()}")
    return 0 if total_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
