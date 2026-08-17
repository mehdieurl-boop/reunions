@echo off
REM Double-cliquez sur ce fichier pour lancer l'outil.
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
  echo Python 3 est introuvable.
  echo Installez-le depuis https://www.python.org/downloads/
  echo IMPORTANT : cochez "Add python.exe to PATH" pendant l'installation.
  pause
  exit /b 1
)

if not exist ".venv" (
  echo Premiere utilisation : installation des composants ^(une a deux minutes^)...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

echo.
python -m audiotool.cli --serveur
pause
