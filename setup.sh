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
  cp .env.example .env
  echo "  Windrose works right now with no keys at all (delayed prices via Yahoo)."
  echo "  Two optional free keys unlock extras:"
  echo "    · Finnhub  → news headlines + analyst outlook   https://finnhub.io/register"
  echo "    · Alpaca   → live ~2s prices (paper keys work)  https://app.alpaca.markets"
  echo ""
  printf "  Finnhub key (press Enter to skip): "
  read -r FKEY
  printf "  Alpaca key ID (press Enter to skip): "
  read -r AKEY
  if [ -n "$AKEY" ]; then printf "  Alpaca secret: "; read -r ASEC; else ASEC=""; fi

  echo ""
  printf "  Passcode for phone access (Enter = auto-generate a 6-digit code): "
  read -r PPIN

  {
    echo "# Windrose local configuration — this file is git-ignored, keep it private."
    echo ""
    echo "# Live market data (Alpaca paper keys are fine — data API is separate from trading)"
    if [ -n "$AKEY" ]; then
      echo "ALPACA_KEY=$AKEY"
      echo "ALPACA_SECRET=$ASEC"
    else
      echo "#ALPACA_KEY="
      echo "#ALPACA_SECRET="
    fi
    echo ""
    echo "# News + analyst outlook (Finnhub, free tier)"
    if [ -n "$FKEY" ]; then echo "FINNHUB_KEY=$FKEY"; else echo "#FINNHUB_KEY="; fi
    echo ""
    echo "# Passcode your phone needs when you start with --lan (phone access)"
    if [ -n "$PPIN" ]; then echo "WINDROSE_PIN=$PPIN"; else echo "#WINDROSE_PIN="; fi
  } > .env
  echo "  ✓ wrote .env  (edit it any time to add keys later)"
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
echo "   Then open  http://127.0.0.1:7070"
echo "   Your portfolio starts empty — add your first position in the"
echo "   Holdings panel, or click \"load a sample book\" to look around."
echo "  ────────────────────────────────────────────"
echo ""
