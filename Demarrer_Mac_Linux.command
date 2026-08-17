#!/usr/bin/env bash
# Double-cliquez sur ce fichier pour lancer l'outil.
# (macOS : si le double-clic est refusé, faites clic droit > Ouvrir la première fois.)
set -e
cd "$(dirname "$0")"

PY=""
for c in python3.12 python3.11 python3 python; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "Python 3 est introuvable."
  echo "Installez-le depuis https://www.python.org/downloads/ puis relancez ce fichier."
  read -r -p "Appuyez sur Entrée pour fermer." _; exit 1
fi

if [ ! -d ".venv" ]; then
  echo "Première utilisation : installation des composants (une à deux minutes)…"
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

echo
python -m audiotool.cli --serveur
read -r -p "Serveur arrêté. Appuyez sur Entrée pour fermer." _
