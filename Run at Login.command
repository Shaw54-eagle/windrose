#!/bin/bash
# ---------------------------------------------------------------------------
# Run at Login — keep Windrose running so alerts actually fire.
#
# Alerts are evaluated by the server. No server, no alerts: close the window
# or sleep the machine and nothing is watching. This registers Windrose to
# start quietly when you log in, and to restart if it ever dies.
#
#   macOS  : a LaunchAgent in ~/Library/LaunchAgents
#   Linux  : a systemd --user service
#
# Run it again to remove it — it toggles.
# ---------------------------------------------------------------------------
set -u
cd "$(dirname "$0")" || exit 1
DIR="$(pwd)"

case "$(uname)" in

Darwin)
  PLIST="$HOME/Library/LaunchAgents/local.windrose.plist"
  if [ -f "$PLIST" ]; then
    launchctl unload "$PLIST" 2>/dev/null
    rm -f "$PLIST"
    echo ""
    echo "  Windrose will no longer start at login."
    echo "  (It is still running right now if you started it manually.)"
    echo ""
    read -n 1 -s -r -p "Press any key to close…"; exit 0
  fi

  if [ ! -x venv/bin/python ]; then
    echo "  Run setup first — there is no Python environment yet."
    read -n 1 -s -r -p "Press any key to close…"; exit 1
  fi

  mkdir -p "$HOME/Library/LaunchAgents"
  cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>local.windrose</string>
  <key>ProgramArguments</key>
  <array>
    <string>${DIR}/venv/bin/python</string>
    <string>${DIR}/app.py</string>
  </array>
  <key>WorkingDirectory</key><string>${DIR}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>${DIR}/windrose.log</string>
  <key>StandardErrorPath</key><string>${DIR}/windrose.log</string>
</dict>
</plist>
PLISTEOF

  launchctl unload "$PLIST" 2>/dev/null
  if launchctl load "$PLIST" 2>/dev/null; then
    echo ""
    echo "  ✓ Windrose now starts at login and stays running."
    echo "    Dashboard:  http://127.0.0.1:7070"
    echo "    Log file:   ${DIR}/windrose.log"
    echo "    Run this again to undo it."
    echo ""
    echo "  Two things it cannot do: run while the machine is fully"
    echo "  shut down, or wake a sleeping Mac. Alerts resume on wake."
    echo ""
  else
    echo "  Could not register the login item. Remove it with:"
    echo "    rm \"$PLIST\""
  fi
  read -n 1 -s -r -p "Press any key to close…"
  ;;

Linux)
  UNIT="$HOME/.config/systemd/user/windrose.service"
  if [ -f "$UNIT" ]; then
    systemctl --user disable --now windrose.service 2>/dev/null
    rm -f "$UNIT"
    systemctl --user daemon-reload 2>/dev/null
    echo "  Windrose will no longer start at login."
    exit 0
  fi

  if [ ! -x venv/bin/python ]; then
    echo "  Run setup first — there is no Python environment yet."
    exit 1
  fi

  mkdir -p "$HOME/.config/systemd/user"
  cat > "$UNIT" <<UNITEOF
[Unit]
Description=Windrose investing console
After=network-online.target

[Service]
Type=simple
WorkingDirectory=${DIR}
ExecStart=${DIR}/venv/bin/python ${DIR}/app.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
UNITEOF

  systemctl --user daemon-reload 2>/dev/null
  if systemctl --user enable --now windrose.service 2>/dev/null; then
    echo "  ✓ Windrose now starts at login and stays running."
    echo "    Dashboard: http://127.0.0.1:7070"
    echo "    Logs:      journalctl --user -u windrose -f"
    echo "    Run this again to undo it."
  else
    echo "  Could not enable the service. Check: systemctl --user status windrose"
  fi
  ;;

*)
  echo "  On Windows, register it with Task Scheduler instead:"
  echo ""
  echo "    schtasks /create /tn Windrose /sc onlogon ^"
  echo "      /tr \"'%CD%\\venv\\Scripts\\pythonw.exe' '%CD%\\app.py'\""
  echo ""
  echo "  Remove it with:  schtasks /delete /tn Windrose /f"
  ;;
esac
