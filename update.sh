#!/bin/bash
# update.sh — tell you when a newer Windrose exists. Never installs it.
#
# This used to fast-forward on every launch. It doesn't any more, and the reason
# matters: an auto-applying updater means whatever is on main executes on your
# machine without you agreeing to it. A one-line change pushed by mistake reached
# every install at the next launch. Checking is useful; applying was not ours to
# decide.
#
# So: it fetches, it compares, it prints. Updating is `git pull`, by you, when
# you want it.
#
# Rules it will not break:
#   · it never merges, rewrites, resets or checks anything out
#   · if you have edited tracked files, it stays quiet and leaves your work alone
#   · if your history has diverged from the published version, it says so and stops
#   · any failure is non-fatal: the app starts on the version you already have
#
# Set auto_update to false in settings.json, or WINDROSE_NO_UPDATE=1, to skip the
# check entirely. That setting used to mean "don't apply updates"; it now means
# "don't look". Anyone who set it to false wanted to be left alone, and still is.

windrose_update() {
  [ "${WINDROSE_NO_UPDATE:-}" = "1" ] && return 0

  # honour the in-app toggle without needing a JSON parser
  if [ -f settings.json ] && grep -q '"auto_update"[[:space:]]*:[[:space:]]*false' settings.json; then
    return 0
  fi

  [ -d .git ] || return 0                       # zip install: no git, nothing to compare
  command -v git >/dev/null 2>&1 || return 0

  # Uncommitted changes to tracked files? Say nothing — you are mid-something,
  # and a pull would not be clean anyway.
  if [ -n "$(git status --porcelain --untracked-files=no 2>/dev/null)" ]; then
    echo "  Local changes present — skipping the update check."
    echo "  Commit or stash them if you want to see what's published."
    return 0
  fi

  echo "  Checking for updates…"
  git fetch --quiet origin 2>/dev/null || { echo "  (offline — starting the version you have)"; return 0; }

  local branch local_sha remote_sha
  branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null) || return 0
  local_sha=$(git rev-parse HEAD 2>/dev/null)
  remote_sha=$(git rev-parse "origin/${branch}" 2>/dev/null) || return 0
  [ "$local_sha" = "$remote_sha" ] && { echo "  Already up to date."; return 0; }

  # Diverged histories are not something a notice can fix. Say so plainly.
  if ! git merge-base --is-ancestor "$local_sha" "$remote_sha" 2>/dev/null; then
    echo "  Your copy has diverged from the published version."
    echo "  Nothing has been changed. Resolve it with git when you get a chance."
    return 0
  fi

  # Behind, and cleanly so. Report it and stop — this is the whole job now.
  local new_ver cur_ver behind reqs_changed
  new_ver=$(git show "origin/${branch}:app.py" 2>/dev/null | grep -m1 'APP_VERSION = ' | cut -d'"' -f2)
  cur_ver=$(grep -m1 'APP_VERSION = ' app.py 2>/dev/null | cut -d'"' -f2)
  behind=$(git rev-list --count "HEAD..origin/${branch}" 2>/dev/null)

  echo ""
  if [ -n "$new_ver" ] && [ "$new_ver" != "$cur_ver" ]; then
    echo "  Windrose ${new_ver} is available. You are on ${cur_ver:-an older build}."
  else
    echo "  A newer build is available (${behind:-some} commit(s) ahead)."
  fi
  echo "  Nothing has been changed — Windrose no longer updates itself."
  echo ""

  # A pull that needs new dependencies and doesn't get them fails confusingly.
  reqs_changed=$(git diff --name-only "HEAD..origin/${branch}" -- requirements.txt 2>/dev/null)
  if [ -n "$reqs_changed" ]; then
    echo "      git pull && ./venv/bin/python -m pip install -r requirements.txt"
    echo ""
    echo "  (that version changes dependencies, so the second half matters)"
  else
    echo "      git pull"
  fi
  echo ""
}
