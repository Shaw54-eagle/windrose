#!/bin/bash
# ---------------------------------------------------------------------------
#  WINDROSE — double-click this file. That is the whole instruction.
#
#  It sets everything up the first time (a minute or two), starts the
#  dashboard, and opens your browser. After that it just starts.
#
#  ── If double-clicking does nothing ──────────────────────────────────────
#  You probably downloaded this as a ZIP. GitHub's "Download ZIP" strips the
#  permission that makes a file runnable, and macOS then treats this as a
#  plain text document. To fix it once, open Terminal and run:
#
#      chmod +x "/path/to/windrose/RUN-ME-mac.command"
#
#  (Type chmod +x, a space, then drag this file into the Terminal window —
#  that fills in the path for you. Press Return, then double-click again.)
#
#  Installing with `git clone` instead avoids this entirely.
#
#  ── If macOS says it "cannot be opened because it is from an
#     unidentified developer" ─────────────────────────────────────────────
#  That is Gatekeeper, and it is expected — this file is not signed with an
#  Apple developer certificate. Right-click (or Control-click) this file,
#  choose Open, then click Open in the dialog. You only do this once.
# ---------------------------------------------------------------------------

# A double-clicked .command starts in your home folder, not this one.
cd "$(dirname "$0")" || exit 1

say() { printf '%s\n' "$1"; }
hold() { say ""; read -n 1 -s -r -p "Press any key to close this window…"; say ""; }

say ""
say "  ┌────────────────────────────────────────┐"
say "  │  WINDROSE                              │"
say "  └────────────────────────────────────────┘"
say ""

# --- Python, checked in plain language before anything can fail loudly -----
# `command -v python3` is not enough on a clean Mac: python3 exists as a stub
# that only offers to install the developer tools. Actually run it.
if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
  say "  Windrose needs Python 3.10 or newer, and this Mac does not have it yet."
  say ""
  say "  1. Download it here:   https://www.python.org/downloads/"
  say "  2. Open the installer and click through it."
  say "  3. Come back and double-click this file again."
  say ""
  say "  (If macOS just offered to install \"command line developer tools\","
  say "   you can accept that instead — it includes Python. Wait for it to"
  say "   finish, then double-click this file again.)"
  say ""
  say "  Nothing is broken and nothing has been changed on your Mac."
  hold
  exit 1
fi

# --- Hand over to the real scripts. This file adds no logic of its own. ----
# Called through bash so a missing executable bit on them cannot stop us
# either — the ZIP problem in the header affects every script in the folder.
if [ ! -d venv ]; then
  say "  First run — setting up. This takes a minute and happens once."
  say ""
  if ! bash setup.sh; then
    say ""
    say "  Setup did not finish. The most common cause is being offline while"
    say "  it downloads the pieces it needs — check your connection and try"
    say "  again. Nothing outside this folder has been touched."
    hold
    exit 1
  fi
fi

exec bash "Start Windrose.command"
