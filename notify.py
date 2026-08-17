"""
notify.py — desktop notifications on macOS, Windows and Linux.

The browser already handles notifications when a Windrose tab is open, and it
does that identically on every platform. This module covers the other case:
the server is running, an alert fires, and no tab is open to see it.

Everything here is best-effort. A missing tool, a locked screen, a distro
without libnotify — all of it fails quietly. An alert that cannot be displayed
must never take the alert loop down with it.
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import time

_SYSTEM = platform.system()
_last_sent = 0.0
_MIN_GAP = 2.0          # a burst of alerts shouldn't become a burst of popups


def available() -> bool:
    """Can we plausibly show a notification on this machine?"""
    if _SYSTEM == "Darwin":
        return shutil.which("osascript") is not None
    if _SYSTEM == "Windows":
        return shutil.which("powershell") is not None or shutil.which("powershell.exe") is not None
    return shutil.which("notify-send") is not None


def _q(s: str) -> str:
    """Neutralise quotes so a ticker or note can't break out of the command."""
    return str(s).replace('"', "'").replace("\\", "/")[:200]


def send(title: str, body: str) -> bool:
    """Show one notification. Returns whether it was dispatched."""
    global _last_sent
    now = time.time()
    if now - _last_sent < _MIN_GAP:
        return False
    _last_sent = now

    title, body = _q(title), _q(body)
    try:
        if _SYSTEM == "Darwin":
            script = f'display notification "{body}" with title "{title}"'
            subprocess.run(["osascript", "-e", script], timeout=5,
                           capture_output=True, check=False)
            return True

        if _SYSTEM == "Windows":
            # Balloon tips are rendered as normal toasts on Windows 10/11 and
            # still work on 8.1 — more portable than the WinRT toast API, which
            # needs an installed AppUserModelID to behave.
            ps = (
                'Add-Type -AssemblyName System.Windows.Forms;'
                'Add-Type -AssemblyName System.Drawing;'
                '$n = New-Object System.Windows.Forms.NotifyIcon;'
                '$n.Icon = [System.Drawing.SystemIcons]::Information;'
                '$n.BalloonTipTitle = "' + title + '";'
                '$n.BalloonTipText = "' + body + '";'
                '$n.Visible = $true;'
                '$n.ShowBalloonTip(6000);'
                'Start-Sleep -Milliseconds 6500;'
                '$n.Dispose();'
            )
            exe = shutil.which("powershell") or shutil.which("powershell.exe") or "powershell"
            subprocess.Popen([exe, "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True

        # Linux / BSD
        if shutil.which("notify-send"):
            subprocess.run(["notify-send", "-a", "Windrose", "-u", "normal", title, body],
                           timeout=5, capture_output=True, check=False)
            return True
    except Exception:
        pass
    return False
