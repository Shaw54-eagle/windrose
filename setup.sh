#!/bin/bash
# ---------------------------------------------------------------------------
# Windrose — one-time setup.
#   macOS:  double-click "Setup Windrose.command", or run:  bash setup.sh
#   Linux:  bash setup.sh
# Creates a private Python environment, installs dependencies, and (optionally)
# saves free API keys. Everything stays inside this folder. Nothing is uploaded.
# ---------------------------------------------------------------------------
set -u
cd "$(dirname "$0")" || exit 1

echo ""
echo "  ┌──────────────────────────────────────────┐"
echo "  │  WINDROSE · setup                        │"
echo "  └──────────────────────────────────────────┘"
echo ""

# ---- 1. Python -------------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
  echo "  ✗ Python 3 not found."
  echo "    Install it from https://www.python.org/downloads/ and run this again."
  exit 1
fi
PYV=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
# Report the version AND act on it. This used to only print, so a Mac with
# nothing but Apple's command line tools (Python 3.9) built a venv, installed
# everything, and failed later at something unrelated-looking. RUN-ME-mac.command
# and selftest.py both refuse 3.9 already; this is the path that did not.
#
# 3.9 does in fact run Windrose — but Apple's build links against LibreSSL 2.8.3,
# which urllib3 v2 says it does not support, and every price fetch is an HTTPS
# request. Failing here with a sentence beats flaky network errors later.
if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "  ✗ Python $PYV found — Windrose needs 3.10 or newer."
  echo ""
  echo "    If you just installed Apple's command line developer tools, that"
  echo "    is where this 3.9 came from. It is not enough on its own."
  echo ""
  echo "    Install Python from https://www.python.org/downloads/, then run"
  echo "    this again. Nothing has been changed."
  exit 1
fi
echo "  ✓ Python $PYV"

# ---- 2. Virtual environment ------------------------------------------------
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
  echo "  · creating a private environment (venv/)…"
  python3 -m venv venv || { echo "  ✗ could not create venv"; exit 1; }
fi
./venv/bin/python -m pip install --quiet --upgrade pip
echo "  · installing dependencies (a minute the first time)…"
./venv/bin/python -m pip install --quiet -r requirements.txt || {
  echo "  ✗ dependency install failed — check your internet connection."
  exit 1
}
cksum requirements.txt | cut -d' ' -f1 > venv/.reqs.cksum
echo "  ✓ dependencies installed"

# ---- 3. API keys (both optional) -------------------------------------------
echo ""
if [ -f .env ]; then
  echo "  ✓ .env already exists — leaving your keys alone."
else
  : # .env is written from scratch below — copying the example would
     # leave placeholder values that read as real keys
  {
    echo "# Windrose configuration — add keys through the in-app setup wizard,"
    echo "# or uncomment and fill these in by hand. All of them are optional."
    echo "#FINNHUB_KEY="
    echo "#ALPACA_KEY="
    echo "#ALPACA_SECRET="
  } > .env
  echo "  ✓ created .env — the app will offer to set up keys on first run"
fi

# ---- 4. Done ---------------------------------------------------------------
chmod +x "Start Windrose.command" start.sh "Setup Windrose.command" 2>/dev/null
chmod +x "Windrose.app/Contents/MacOS/Windrose" 2>/dev/null
echo ""
echo "  ────────────────────────────────────────────"
echo "   Setup complete. Start Windrose with:"
if [ "$(uname)" = "Darwin" ]; then
  echo "     double-click \"Start Windrose.command\""
  echo "     (or run:  bash \"Start Windrose.command\")"
else
  echo "     bash start.sh"
fi
echo ""
echo "   Then open  http://127.0.0.1:${WINDROSE_PORT:-7070}"
echo "   It opens with five example holdings so nothing is blank."
echo "   Delete any row with the x and add your own."
echo "  ────────────────────────────────────────────"
echo ""
