#!/bin/bash
# Install Windrose — run me after downloading windrose.zip from the chat.
# Finds the newest windrose*.zip anywhere in ~/Downloads, installs it to
# ~/Downloads/windrose, keeps your settings, keys, holdings, journal, alerts
# and Python environment, prints the version, and starts it.
#
# First time (downloads have no run permission):  bash "Install Windrose.command"
set -u
cd ~/Downloads || exit 1

NEWEST=$(find . -maxdepth 3 \( -name "windrose*.zip" -o -name "ledger*.zip" \) -print0 2>/dev/null | xargs -0 ls -t 2>/dev/null | head -1)
if [ -z "${NEWEST}" ]; then
  echo "No windrose*.zip found in ~/Downloads."
  echo "Download it from the chat first, then run me again."
  read -n 1 -s -r -p "Press any key to close…"; exit 1
fi
echo "Installing from: ${NEWEST}"

pkill -f "windrose/venv/bin/python" 2>/dev/null
pkill -f "ledger/venv/bin/python" 2>/dev/null
pkill -f "python3 app.py" 2>/dev/null
sleep 1

OLD=""
[ -d windrose ] && OLD=windrose
[ -z "$OLD" ] && [ -d ledger ] && OLD=ledger      # upgrading from the old name
rm -rf windrose.old
[ -n "$OLD" ] && mv "$OLD" windrose.old

unzip -q "${NEWEST}" || { echo "Unzip failed — is the download complete?"; read -n 1 -s -r; exit 1; }
[ -d ledger ] && [ ! -d windrose ] && mv ledger windrose

if [ -d windrose.old ]; then
  # Carry the venv over only if it still works from the new path. A virtualenv
  # bakes in its own absolute location, so a renamed folder leaves every script
  # inside venv/bin pointing at a directory that no longer exists.
  if [ -d windrose.old/venv ]; then
    mv windrose.old/venv windrose/venv
    if ! ( cd windrose && ./venv/bin/python -c "import sys" >/dev/null 2>&1 ); then
      echo "Old Python environment was tied to the previous folder — rebuilding it."
      rm -rf windrose/venv
    fi
  fi
  for f in .env holdings.json journal.json alerts.json settings.json .tutorial_seen .lan_pin; do
    [ -f "windrose.old/$f" ] && cp "windrose.old/$f" "windrose/$f"
  done
  rm -rf windrose.old
fi

chmod +x "$0" 2>/dev/null
chmod +x windrose/*.command 2>/dev/null
chmod +x "windrose/Windrose.app/Contents/MacOS/Windrose" 2>/dev/null

cd windrose
V=$(grep -m1 'APP_VERSION = ' app.py | cut -d'"' -f2)
echo ""
echo "  Installed Windrose v${V:-?} — the top bar will say WINDROSE · V${V:-?}"
echo ""
exec bash "Start Windrose.command"
