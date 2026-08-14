#!/bin/bash
# Start Windrose — double-click me (macOS).
# First run sets things up (one-time). After that it just starts.
# Close this window or press Ctrl+C to stop the dashboard.

cd "$(dirname "$0")"

# Already running? Just open the browser.
if curl -s --max-time 1 http://127.0.0.1:7070/api/status >/dev/null 2>&1; then
  open http://127.0.0.1:7070
  echo "Windrose is already running — opened your browser."
  echo "(This window can be closed.)"
  exit 0
fi

# One-time setup: private Python environment inside this folder.
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
    echo "Couldn't find Python 3. Install it from https://www.python.org/downloads/"
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
    if curl -s --max-time 1 http://127.0.0.1:7070/api/status >/dev/null 2>&1; then
      open http://127.0.0.1:7070 
      exit 0
    fi
    sleep 1
  done
) &

echo ""
echo "  Windrose  →  http://127.0.0.1:7070"
echo "  Leave this window open. Close it (or Ctrl+C) to stop."
echo ""
exec ./venv/bin/python app.py "$@"
