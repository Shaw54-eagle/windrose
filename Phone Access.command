#!/bin/bash
# Windrose — phone access. Double-click me, then scan the QR with your iPhone.
#
# Starts Windrose so other devices on YOUR Wi-Fi can reach it, protected by a
# passcode. Your Mac must stay awake and this window must stay open.
# For normal desktop-only use, launch "Start Windrose.command" instead.
cd "$(dirname "$0")"
if [ ! -d venv ]; then
  echo "Run setup first (double-click \"Setup Windrose.command\")."
  read -n 1 -s -r -p "Press any key to close…"; exit 1
fi
./venv/bin/python -c "import qrcode" 2>/dev/null || ./venv/bin/python -m pip install --quiet qrcode 2>/dev/null
exec bash "Start Windrose.command" --lan
