#!/data/data/com.termux/files/usr/bin/bash
set -e

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  python -m venv .venv
fi

source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

python bot_yt.py
