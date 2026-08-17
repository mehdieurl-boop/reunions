"""Nettoyage audio et transcription de réunions, en local."""
import sys

__version__ = "1.3.0"


def console_utf8() -> None:
    """Force la sortie console en UTF-8.

    Sans cela, la console Windows (page de code 1252) lève une
    UnicodeEncodeError sur les caractères « ✓ », « → » ou « █ » que les scripts
    affichent — le programme s'arrête avant d'avoir montré le moindre résultat.
    """
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(encoding="utf-8", errors="replace")
        except Exception:      # flux redirigé ou Python trop ancien
            pass
