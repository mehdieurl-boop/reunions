"""Vérification du moteur de transcription sur la machine de l'utilisateur.

Le maillon le plus difficile à garantir à l'avance est la transcription : elle
dépend du modèle téléchargé, du processeur, et de la présence ou non d'une carte
graphique. Ce module la met à l'épreuve en local et rend trois chiffres :

* **vitesse** — combien de temps de calcul pour une minute d'audio ;
* **précision** — taux d'erreur sur des phrases dont on connaît le texte exact,
  lues par la voix de synthèse du système ;
* **hallucinations** — combien de mots le moteur invente sur du silence bruité,
  le défaut classique de Whisper sur les blancs de réunion.

Aucun fichier de référence n'est embarqué : tout est fabriqué à la volée.
"""
from __future__ import annotations

import platform
import re
import shutil
import subprocess
import tempfile
import time
import unicodedata
from pathlib import Path

import numpy as np

from . import ffmpeg_io

# Phrases de contrôle : tournures de réunion, sans chiffres — l'écriture des
# nombres varie d'un moteur à l'autre et fausserait la mesure.
PHRASES = [
    "Bonjour à tous, merci d'être présents pour ce point hebdomadaire.",
    "Nous avons décidé de reporter la livraison à la semaine prochaine.",
    "Je m'occupe de prévenir le client avant vendredi.",
]
REFERENCE = " ".join(PHRASES)


# --------------------------------------------------------------------------- #
#  Taux d'erreur sur les mots
# --------------------------------------------------------------------------- #


def normalize(text: str) -> list[str]:
    """Découpe en mots comparables : minuscules, sans ponctuation ni accents.

    Les accents sont retirés pour ne pas compter comme fautes les variations
    d'un moteur sur « décidé » / « decide ».
    """
    text = text.lower().replace("’", "'").replace("œ", "oe")
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^a-z0-9' ]+", " ", text)
    return [w for w in re.split(r"[\s']+", text) if w]


def word_error_rate(reference: str, hypothesis: str) -> dict:
    """Taux d'erreur classique : (substitutions + insertions + omissions) / mots."""
    ref, hyp = normalize(reference), normalize(hypothesis)
    if not ref:
        return dict(taux=1.0, mots=0, substitutions=0, omissions=0, insertions=0)
    # distance d'édition sur les mots, avec comptage des types d'erreur
    n, m = len(ref), len(hyp)
    d = np.zeros((n + 1, m + 1), dtype=np.int32)
    d[:, 0] = np.arange(n + 1)
    d[0, :] = np.arange(m + 1)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1, d[i - 1, j - 1] + cost)
    # remontée du chemin pour distinguer omissions / insertions / substitutions
    i, j, sub, dele, ins = n, m, 0, 0, 0
    while i > 0 or j > 0:
        if i > 0 and j > 0 and d[i, j] == d[i - 1, j - 1] + (ref[i - 1] != hyp[j - 1]):
            sub += ref[i - 1] != hyp[j - 1]
            i, j = i - 1, j - 1
        elif i > 0 and d[i, j] == d[i - 1, j] + 1:
            dele += 1
            i -= 1
        else:
            ins += 1
            j -= 1
    return dict(taux=float(d[n, m]) / n, mots=n, substitutions=int(sub),
                omissions=int(dele), insertions=int(ins))


# --------------------------------------------------------------------------- #
#  Voix de synthèse du système
# --------------------------------------------------------------------------- #


def _tts_windows(text: str, out: Path) -> bool:
    script = (
        "Add-Type -AssemblyName System.Speech;"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        "$fr = $s.GetInstalledVoices() | Where-Object {"
        " $_.VoiceInfo.Culture.Name -like 'fr*' -and $_.Enabled } |"
        " Select-Object -First 1;"
        "if ($fr) { $s.SelectVoice($fr.VoiceInfo.Name) } else { exit 3 };"
        "$s.Rate = 0;"
        f"$s.SetOutputToWaveFile('{out}');"
        f"$s.Speak(@'\n{text}\n'@);"
        "$s.Dispose();"
    )
    for exe in ("powershell", "pwsh"):
        if not shutil.which(exe):
            continue
        r = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-Command", script],
                           capture_output=True, text=True, timeout=120)
        if r.returncode == 0 and out.exists() and out.stat().st_size > 5000:
            return True
    return False


def _tts_macos(text: str, out: Path) -> bool:
    if not shutil.which("say"):
        return False
    voices = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
    voice = next((ln.split()[0] for ln in voices.splitlines() if "fr_FR" in ln), None)
    if not voice:
        return False
    aiff = out.with_suffix(".aiff")
    r = subprocess.run(["say", "-v", voice, "-o", str(aiff), text],
                       capture_output=True, timeout=120)
    if r.returncode != 0 or not aiff.exists():
        return False
    subprocess.run([ffmpeg_io.ffmpeg(), "-y", "-loglevel", "error", "-i", str(aiff),
                    "-ar", "16000", "-ac", "1", str(out)], check=True)
    aiff.unlink(missing_ok=True)
    return out.exists()


def _tts_linux(text: str, out: Path) -> bool:
    exe = shutil.which("espeak-ng") or shutil.which("espeak")
    if not exe:
        return False
    r = subprocess.run([exe, "-v", "fr", "-s", "150", "-w", str(out), text],
                       capture_output=True, timeout=120)
    return r.returncode == 0 and out.exists() and out.stat().st_size > 5000


def synthesize(text: str, out: Path) -> bool:
    """Fabrique un extrait parlé avec la voix française du système, si elle existe."""
    try:
        system = platform.system()
        if system == "Windows":
            return _tts_windows(text, out)
        if system == "Darwin":
            return _tts_macos(text, out)
        return _tts_linux(text, out)
    except Exception:
        return False


def make_silence(out: Path, seconds: float = 15.0, level_db: float = -48.0) -> Path:
    """Silence légèrement bruité : ce sur quoi un moteur a tendance à inventer."""
    sr = 16000
    rng = np.random.default_rng(4)
    x = (rng.normal(0, 1, int(sr * seconds)) * 10 ** (level_db / 20)).astype(np.float32)
    w = ffmpeg_io.RawWriter(str(out), sr, 1)
    w.write(x)
    w.close()
    return out


# --------------------------------------------------------------------------- #
#  Vérification complète
# --------------------------------------------------------------------------- #


def run(model: str, log=print, engine: str = "faster-whisper") -> dict:
    """Exécute la vérification et renvoie un rapport lisible."""
    from .transcribe import TranscribeSettings, is_available, transcribe

    if engine != "mock" and not is_available():
        raise RuntimeError("le moteur de transcription n'est pas installé")

    settings = TranscribeSettings(model=model, language="fr", diarize=False, engine=engine)
    rapport: dict = dict(modele=model, systeme=platform.system())
    tmp = Path(tempfile.mkdtemp(prefix="verif_"))

    try:
        # --- 1. précision et vitesse, sur une voix de synthèse ------------- #
        parle = tmp / "reference.wav"
        log("Fabrication d'un extrait parlé avec la voix du système…")
        if synthesize(REFERENCE, parle):
            duree = ffmpeg_io.probe(str(parle))["duration"]
            log(f"Extrait obtenu ({duree:.1f} s). Transcription en cours…")
            t0 = time.time()
            segs, info = transcribe(str(parle), settings, duree)
            calcul = time.time() - t0
            texte = " ".join(s.text for s in segs).strip()
            wer = word_error_rate(REFERENCE, texte)
            rapport["precision"] = dict(
                taux_erreur=round(wer["taux"] * 100, 1),
                mots_attendus=wer["mots"],
                substitutions=wer["substitutions"],
                omissions=wer["omissions"],
                insertions=wer["insertions"],
                texte_obtenu=texte,
                texte_attendu=REFERENCE,
            )
            rapport["vitesse"] = dict(
                duree_audio_s=round(duree, 1),
                temps_calcul_s=round(calcul, 1),
                facteur=round(duree / max(calcul, 1e-6), 2),
                minutes_calcul_par_heure_audio=round(3600 / max(duree / max(calcul, 1e-6), 1e-6) / 60, 1),
            )
            log(f"Taux d'erreur : {rapport['precision']['taux_erreur']} % — "
                f"vitesse : {rapport['vitesse']['facteur']}x le temps réel")
        else:
            rapport["precision"] = None
            rapport["vitesse"] = None
            log("Aucune voix de synthèse française n'est installée sur ce système : "
                "la précision et la vitesse ne peuvent pas être mesurées ici.")

        # --- 2. tendance à inventer du texte sur du silence ---------------- #
        log("Contrôle des hallucinations sur du silence bruité…")
        blanc = make_silence(tmp / "silence.wav")
        segs2, _ = transcribe(str(blanc), settings, 15.0)
        invente = " ".join(s.text for s in segs2).strip()
        rapport["hallucinations"] = dict(
            mots_inventes=len(normalize(invente)),
            texte=invente[:300],
        )
        log(f"Silence de 15 s → {rapport['hallucinations']['mots_inventes']} mot(s) produit(s).")

        rapport["verdict"] = _verdict(rapport)
        log("Vérification terminée : " + rapport["verdict"]["resume"])
        return rapport
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _verdict(r: dict) -> dict:
    points, niveau = [], "ok"
    p = r.get("precision")
    if p is None:
        points.append("Précision non mesurée : pas de voix de synthèse française sur ce "
                      "système. Testez avec un vrai enregistrement.")
        niveau = "partiel"
    else:
        t = p["taux_erreur"]
        if t <= 12:
            points.append(f"Précision : {t} % d'erreur sur une voix de synthèse — très bon.")
        elif t <= 30:
            points.append(f"Précision : {t} % d'erreur. Correct pour de la relecture ; "
                          "un modèle plus gros ferait mieux.")
            niveau = "moyen"
        else:
            points.append(f"Précision : {t} % d'erreur, c'est beaucoup. Essayez un modèle "
                          "plus gros, ou vérifiez que la langue est bien réglée sur français.")
            niveau = "faible"

    v = r.get("vitesse")
    if v:
        points.append(f"Vitesse : {v['facteur']}x le temps réel, soit environ "
                      f"{v['minutes_calcul_par_heure_audio']} minutes de calcul "
                      "pour une heure de réunion.")
        if v["facteur"] < 0.5:
            points.append("C'est lent pour cette machine : un modèle plus petit "
                          "(small, large-v3-turbo) serait plus confortable.")
            niveau = "moyen" if niveau == "ok" else niveau

    h = r.get("hallucinations", {})
    n = h.get("mots_inventes", 0)
    if n == 0:
        points.append("Aucun texte inventé sur du silence.")
    elif n <= 3:
        points.append(f"{n} mot(s) inventé(s) sur 15 s de silence — négligeable.")
    else:
        points.append(f"{n} mots inventés sur du silence : montez le débruitage et gardez "
                      "l'option « atténuer le fond » cochée.")
        niveau = "moyen" if niveau == "ok" else niveau

    resume = {"ok": "le moteur fonctionne bien sur cette machine",
              "partiel": "le moteur fonctionne, mesure incomplète",
              "moyen": "le moteur fonctionne, quelques réserves",
              "faible": "résultat insuffisant, voir les remarques"}[niveau]
    return dict(niveau=niveau, resume=resume, points=points)
