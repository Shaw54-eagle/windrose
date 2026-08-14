#!/bin/bash
# One-time: installs the native-window engine, after which Windrose.app opens
# as a real desktop app (its own window, no browser).
cd "$(dirname "$0")"
[ -x venv/bin/python ] || { echo "Run Windrose once first (builds the environment)."; read -n1 -s -r; exit 1; }
echo "Installing app-mode engine (pywebview)…"
venv/bin/python -m pip install --quiet pywebview && echo "Done — double-click Windrose.app from now on." || echo "Install failed — check internet."
read -n 1 -s -r -p "Press any key to close…"
