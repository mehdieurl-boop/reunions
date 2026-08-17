"""Rapport JSON de nettoyage, destiné à l'outil de transcription en aval.

Le format est figé avec Verbatim (issue #1). Deux règles à ne pas perdre de vue
en le faisant évoluer :

* **jamais de chemin absolu** — uniquement des noms de fichiers. Ce rapport peut
  être joint à un échange, il ne doit rien dire de l'arborescence de la machine ;
* **`schema_version` d'abord** — le consommateur ignore les champs qu'il ne
  connaît pas et se fie à ce numéro. Ajouter un champ ne le change pas ;
  en renommer un ou en changer le sens, si.
"""
from __future__ import annotations

import json
from pathlib import Path

SCHEMA_VERSION = "1.0"
OUTIL = "reunions"

# Retard constant de la chaîne, mesuré par corrélation croisée entre l'entrée et
# la sortie : 1,3 ms de temps de propagation des filtres IIR de l'égalisation,
# le reste au rééchantillonnage 48 → 16 kHz. Voir CHANGELOG 1.2.0.
RETARD_ESTIME_MS = 5.0

# Seuils de déclenchement des avertissements.
SEUIL_DENOISE_ELEVE = 75          # au-delà, le débruitage s'entend
SEUIL_VOIX_FAIBLE_DB = 15.0       # écart parole / plancher de bruit


def _avertissement(code: str, niveau: str, message: str) -> dict:
    return dict(code=code, niveau=niveau, message=message)


def avertissements(settings, ana, sortie_segmentee: bool) -> list[dict]:
    """Ce que l'aval doit savoir avant d'exploiter le fichier."""
    out: list[dict] = []

    if settings.denoise > SEUIL_DENOISE_ELEVE:
        out.append(_avertissement(
            "DENOISE_ELEVE", "attention",
            f"Débruitage réglé à {settings.denoise} : au-delà de "
            f"{SEUIL_DENOISE_ELEVE}, la voix peut sonner métallique et les "
            "débuts de mots s'affaiblir."))

    ecart = ana.speech_level_db - ana.noise_floor_db
    if ecart < SEUIL_VOIX_FAIBLE_DB:
        out.append(_avertissement(
            "VOIX_FAIBLE", "attention",
            f"Écart parole / bruit de fond de seulement {ecart:.1f} dB à la "
            "source : la transcription sera difficile, en particulier pour les "
            "intervenants éloignés du micro."))

    if settings.trim_silence:
        out.append(_avertissement(
            "SILENCES_RACCOURCIS", "attention",
            "Les longs silences ont été raccourcis."))
        out.append(_avertissement(
            "CHRONOLOGIE_MODIFIEE", "critique",
            "Les horodatages du fichier nettoyé ne correspondent plus à ceux "
            "de l'enregistrement d'origine."))

    if sortie_segmentee:
        out.append(_avertissement(
            "FICHIER_SEGMENTE", "info",
            f"La sortie est découpée en segments de {settings.segment_minutes} "
            "minutes ; chaque segment repart de zéro."))

    return out


def detecter_preset(settings, presets: dict) -> str | None:
    """Nom du préréglage si les curseurs y correspondent encore, sinon None."""
    for nom, valeurs in presets.items():
        if all(getattr(settings, k, object()) == v for k, v in valeurs.items()):
            return nom
    return None


def construire(*, source: str, sortie: str, settings, ana, presets: dict,
               version: str, duree_source_s: float, duree_sortie_s: float,
               format_audio: dict, plancher_apres_dbfs: float | None,
               sonie_lufs: float, gain_db: float,
               sortie_segmentee: bool = False) -> dict:
    ecart_ms = round((duree_sortie_s - duree_source_s) * 1000, 1)
    return {
        "schema_version": SCHEMA_VERSION,
        "outil": OUTIL,
        "outil_version": version,
        "preset": detecter_preset(settings, presets),

        "fichier_source_nom": Path(source).name,      # nom seul, jamais de chemin
        "fichier_sortie_nom": Path(sortie).name,

        "duree_source_s": round(duree_source_s, 3),
        "duree_sortie_s": round(duree_sortie_s, 3),
        "ecart_duree_ms": ecart_ms,
        "retard_estime_ms": RETARD_ESTIME_MS,
        "horodatages_preserves": not settings.trim_silence,

        "trim_silence": bool(settings.trim_silence),
        "segment_minutes": int(settings.segment_minutes or 0),

        "format_audio": format_audio,
        "canaux_source": int(ana.channels),
        "canaux_traites": int(format_audio.get("canaux", 1)),

        "plancher_bruit_avant_dbfs": round(ana.noise_floor_db, 1),
        "plancher_bruit_apres_dbfs": (None if plancher_apres_dbfs is None
                                      else round(plancher_apres_dbfs, 1)),
        "niveau_parole_dbfs": round(ana.speech_level_db, 1),
        "ronflement_secteur_hz": ana.hum_hz,
        "sonie_lufs": round(sonie_lufs, 1),
        "gain_applique_db": round(gain_db, 1),

        "reglages": settings.to_dict(),
        "avertissements": avertissements(settings, ana, sortie_segmentee),
    }


def ecrire(chemin: str, rapport: dict) -> str:
    Path(chemin).write_text(json.dumps(rapport, indent=1, ensure_ascii=False),
                            encoding="utf-8")
    return chemin
