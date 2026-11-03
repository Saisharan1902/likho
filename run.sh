#!/bin/zsh
# Start Dictly. First run creates the virtualenv and installs dependencies.
set -e
cd "$(dirname "$0")"
if [ "$(uname -m)" != "arm64" ]; then
  echo "Dictly needs an Apple Silicon Mac (M1 or later)."; exit 1
fi
if [ ! -d .venv ]; then
  if ! command -v python3.12 >/dev/null; then
    echo "Python 3.12 is required:  brew install python@3.12"; exit 1
  fi
  echo "First run: setting up (this downloads ~1 GB of libraries)…"
  python3.12 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.txt
fi
exec .venv/bin/python -m dictly
