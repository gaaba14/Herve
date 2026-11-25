#!/bin/bash
# Installe Hervé comme service macOS (démarre à l'ouverture de session, redémarre en cas d'arrêt).
# Usage, depuis le dossier du projet : ./deploiement/mac/installer.sh
set -euo pipefail

DOSSIER="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$DOSSIER"
ETIQUETTE=fr.montcuit.herve
PLIST="$HOME/Library/LaunchAgents/$ETIQUETTE.plist"

# Python 3.11 ou plus récent (celui de macOS est trop ancien)
PY=""
for p in python3.13 python3.12 python3.11 /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
  if command -v "$p" >/dev/null && "$p" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
    PY="$(command -v "$p")"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.11+ introuvable. Installez-le avec : brew install python@3.12" >&2
  exit 1
fi
echo "Python : $PY"

[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
mkdir -p data

for f in .env config.yaml; do
  if [ ! -f "$f" ]; then
    echo "Il manque $f : créez-le avant de relancer ce script (voir README)." >&2
    exit 1
  fi
done
chmod 600 .env

# Vérifie la configuration avant d'installer le service
.venv/bin/python - <<'PY'
import os, sys
for ligne in open(".env"):
    ligne = ligne.strip()
    if ligne and not ligne.startswith("#") and "=" in ligne:
        k, v = ligne.split("=", 1)
        os.environ[k] = v
from herve.config import charger
cfg = charger("config.yaml")
if not cfg.telegram_token:
    sys.exit("TELEGRAM_TOKEN est vide dans .env")
if not cfg.administrateurs:
    sys.exit("Ajoutez votre identifiant Telegram dans telegram.administrateurs")
print(f"Configuration valide : électricité={cfg.electricite.source}, "
      f"alarme={cfg.alarme.source}, chauffage={cfg.chauffage.source}")
PY

mkdir -p "$HOME/Library/LaunchAgents"
sed "s#__DOSSIER__#$DOSSIER#g" deploiement/mac/$ETIQUETTE.plist > "$PLIST"
launchctl bootout "gui/$(id -u)/$ETIQUETTE" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo
echo "Hervé est lancé. Journal : tail -f \"$DOSSIER/data/herve.log\""
echo "Arrêter : launchctl bootout gui/$(id -u)/$ETIQUETTE"
