#!/usr/bin/env bash
# 一键分析(Linux / macOS):bash run.sh(或 ./run.sh)。
# 也可以 bash run.sh 某牌谱.json。
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "[x] 还没安装。请先跑 bash install.sh。"
  exit 1
fi

export PYTHONPATH="src:vendor/Mortal/mortal:."
export PYTHONIOENCODING=utf-8
exec .venv/bin/python run.py "$@"
