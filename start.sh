#!/usr/bin/env bash
# Démarre le serveur Flask dans le virtualenv local.
# Usage : ./start.sh [PORT]

set -euo pipefail

PORT="${1:-5000}"
VENV="$(dirname "$0")/venv"

if [[ ! -f "$VENV/bin/python" ]]; then
  echo "[start.sh] Création du virtualenv…"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q -r requirements.txt
fi

echo "[start.sh] Démarrage sur http://localhost:${PORT}"
PORT="$PORT" "$VENV/bin/python" app.py
