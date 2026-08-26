#!/bin/bash
# Start Windrose — double-click me (Linux Mint / any Linux).
# If Nemo asks, choose "Run in Terminal" (plain "Run" works too).
# First run sets things up (one-time). Ctrl+C or close the window to stop.

cd "$(dirname "$0")"
export WINDROSE_PORT="${WINDROSE_PORT:-7070}"

# If launched without a terminal (Nemo "Run"), reopen inside one so logs show.
if [ ! -t 1 ] && [ -z "$LEDGER_NOTERM" ]; then
  export LEDGER_NOTERM=1
  for T in x-terminal-emulator gnome-terminal xfce4-terminal konsole xterm; do
    if command -v "$T" >/dev/null 2>&1; then
      case "$T" in
        gnome-terminal) exec "$T" -- "$0" ;;
        *)              exec "$T" -e "$0" ;;
      esac
    fi
  done
  # No terminal emulator found — carry on headless; the browser still opens.
fi

# Already running? Just open the browser.
if curl -s --max-time 1 http://127.0.0.1:${WINDROSE_PORT:-7070}/api/status >/dev/null 2>&1; then
  xdg-open http://127.0.0.1:${WINDROSE_PORT:-7070} >/dev/null 2>&1 || true
  echo "Windrose is already running — opened your browser."
  exit 0
fi

# One-time setup: private Python environment inside this folder.
# Pull the latest published version first (fast-forward only, never destructive).
if [ -f update.sh ]; then
  . ./update.sh
  windrose_update
fi

# A virtualenv hardcodes its own absolute path, so renaming or moving the
# folder breaks every script inside venv/bin. The interpreter itself still
# works, so we always call pip through it — and if even that is broken
# (moved between machines, Python upgraded), rebuild the venv from scratch.
venv_ok() { [ -x venv/bin/python ] && ./venv/bin/python -c "import sys" >/dev/null 2>&1; }
if [ -d venv ] && ! venv_ok; then
  echo "The Python environment was built for a different folder — rebuilding it…"
  rm -rf venv
fi
if [ ! -d venv ]; then
  echo "First run — setting up Windrose (takes a minute, happens once)…"
  python3 -m venv venv || {
    echo ""
    echo "venv creation failed. On Mint/Ubuntu run:  sudo apt install python3-venv"
    echo "then double-click this again."
    read -n 1 -s -r -p "Press any key to close…"; exit 1
  }
  ./venv/bin/python -m pip install --quiet --upgrade pip
fi

# Install/refresh dependencies only when requirements.txt changes.
STAMP="venv/.reqs.cksum"
WANT=$(cksum requirements.txt | cut -d' ' -f1)
HAVE=$(cat "$STAMP" 2>/dev/null)
if [ "$WANT" != "$HAVE" ]; then
  echo "Installing dependencies…"
  ./venv/bin/python -m pip install --quiet -r requirements.txt && echo "$WANT" > "$STAMP" || {
    echo "Could not install dependencies. If you are online, delete the venv folder and run this again."
    read -n 1 -s -r -p "Press any key to close…"; exit 1
  }
fi

# Open the browser only once the server actually answers (first runs are slow).
(
  for i in $(seq 1 120); do
    if curl -s --max-time 1 http://127.0.0.1:${WINDROSE_PORT:-7070}/api/status >/dev/null 2>&1; then
      xdg-open http://127.0.0.1:${WINDROSE_PORT:-7070} >/dev/null 2>&1 || true
      exit 0
    fi
    sleep 1
  done
) &

echo ""
echo "  Windrose  →  http://127.0.0.1:${WINDROSE_PORT:-7070}"
echo "  Leave this window open. Close it (or Ctrl+C) to stop."
echo ""
exec ./venv/bin/python app.py "$@"
