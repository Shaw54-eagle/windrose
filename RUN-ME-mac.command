#!/bin/bash
# ---------------------------------------------------------------------------
#  WINDROSE — double-click this file. That is the whole instruction.
#
#  It sets everything up the first time (a minute or two), starts the
#  dashboard, and opens your browser. After that it just starts.
#
#  ── If macOS refuses to open this ────────────────────────────────────────
#  "cannot be opened because it is from an unidentified developer", or the
#  double-click does nothing at all.
#
#  Nothing is broken and nothing is wrong with your Mac. Anything a browser
#  downloads gets tagged com.apple.quarantine, the tag survives unzipping,
#  and macOS will not run a tagged script that is not signed with an Apple
#  developer certificate. `chmod +x` does NOT fix this — the tag and the
#  permission are two separate things, and you may need both.
#
#  Clear the tag. Open Terminal (press Cmd-Space, type "Terminal"), type
#  this much:
#
#      xattr -dr com.apple.quarantine
#
#  then type a space, drag the *windrose folder* from Finder into the
#  Terminal window — that fills in the path for you — and press Return.
#  It clears the tag from everything in the folder at once, so the other
#  launchers and the app bundle work too. Then double-click this again.
#
#  Rather not touch Terminal? Either of these also works:
#    * Right-click (or Control-click) this file, choose Open, then Open
#      again in the dialog.
#    * On macOS 15 and newer that option may be missing. Double-click it,
#      let it be refused, then open System Settings > Privacy & Security,
#      scroll to the bottom, and click "Open Anyway".
#
#  None of this happens if you install with `git clone` — a clone is never
#  tagged, so the double-click just works. That is why the README puts the
#  clone first for macOS.
#
#  ── If it opens in TextEdit instead of running ───────────────────────────
#  A downloaded ZIP also strips the permission that makes a file runnable.
#  In Terminal, type `chmod +x ` (with the space), drag this file in, and
#  press Return.
# ---------------------------------------------------------------------------

# A double-clicked .command starts in your home folder, not this one.
SELF="$0"
cd "$(dirname "$0")" || exit 1
HERE="$(pwd)"

say() { printf '%s\n' "$1"; }
hold() { say ""; read -n 1 -s -r -p "Press any key to close this window…"; say ""; }

say ""
say "  ┌────────────────────────────────────────┐"
say "  │  WINDROSE                              │"
say "  └────────────────────────────────────────┘"
say ""

# --- The download tag, which is what actually stops most people ------------
# If this is running at all, the tag did not stop *this* launch — the user got
# through with right-click > Open, or ran it from Terminal. But the tag is on
# the whole folder, so the next plain double-click fails exactly the same way,
# and Windrose.app and the other .command files stay blocked. So: say what it
# is, show the command, and offer to run it. Clearing it touches nothing
# outside this folder.
tagged() {
  command -v xattr >/dev/null 2>&1 || return 1
  xattr "$1" 2>/dev/null | grep -q '^com\.apple\.quarantine$'
}

if tagged "$SELF" || tagged "$HERE"; then
  say "  First, one thing about this folder."
  say ""
  say "  macOS has it tagged as downloaded from the internet. That tag is"
  say "  why double-clicking gets refused, and it is on every file here —"
  say "  the other launchers and the app bundle are blocked by it too."
  say ""
  say "  Clearing it affects nothing outside this folder:"
  say ""
  say "      xattr -dr com.apple.quarantine \"$HERE\""
  say ""
  if [ -t 0 ]; then
    printf '  Clear it now, so double-clicking works from here on? [Y/n] '
    # Note the `if read`: on end-of-input `read` fails and leaves reply empty,
    # which would otherwise fall through to the default and clear the tag
    # without anyone having said yes. A non-answer is not consent.
    if ! read -r reply; then
      say ""
      say "  No answer — leaving it alone. Run the line above whenever you like."
    else
      case "$reply" in
        [Nn]*)
          say "  Left as it is. Run the line above whenever you like."
          ;;
        *)
          if xattr -dr com.apple.quarantine "$HERE" 2>/dev/null; then
            say "  Cleared. Double-clicking will work from now on."
          else
            say "  Could not clear it — run the line above in Terminal instead."
          fi
          ;;
      esac
    fi
  else
    say "  Run that line in Terminal and the double-click will work."
  fi
  say ""
fi

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
