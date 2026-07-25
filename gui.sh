#!/usr/bin/env bash
# dareda graphical interface (Linux / macOS).
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "[x] Not installed yet. Run: bash install.sh"
  exit 1
fi

export PYTHONPATH="src:vendor/Mortal/mortal:."
export PYTHONIOENCODING=utf-8
exec .venv/bin/python gui.py
