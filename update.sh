#!/bin/bash
# update.sh — pull the newest Windrose before the app starts.
#
# Sourced by the launchers. Rules it will not break:
#   · fast-forward only — never merges, never rewrites, never force-resets
#   · if you have edited tracked files, it stops and leaves your work alone
#   · your data (.env, holdings, journal, alerts, settings) is git-ignored,
#     so it is never touched either way
#   · any failure is non-fatal: the app starts on the version you already have
#
# Set auto_update to false in settings.json, or WINDROSE_NO_UPDATE=1, to skip.

windrose_update() {
  [ "${WINDROSE_NO_UPDATE:-}" = "1" ] && return 0

  # honour the in-app toggle without needing a JSON parser
  if [ -f settings.json ] && grep -q '"auto_update"[[:space:]]*:[[:space:]]*false' settings.json; then
    return 0
  fi

  [ -d .git ] || return 0                       # zip install: nothing safe to do here
  command -v git >/dev/null 2>&1 || return 0

  # Uncommitted changes to tracked files? Leave everything alone and say so.
  if [ -n "$(git status --porcelain --untracked-files=no 2>/dev/null)" ]; then
    echo "  Local changes present — skipping auto-update so nothing is lost."
    echo "  Commit or stash them, then relaunch to pick up the latest."
    return 0
  fi

  echo "  Checking for updates…"
  git fetch --quiet origin 2>/dev/null || { echo "  (offline — starting the version you have)"; return 0; }

  local branch local_sha remote_sha
  branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null) || return 0
  local_sha=$(git rev-parse HEAD 2>/dev/null)
  remote_sha=$(git rev-parse "origin/${branch}" 2>/dev/null) || return 0
  [ "$local_sha" = "$remote_sha" ] && { echo "  Already up to date."; return 0; }

  # Only move forward. If histories diverged, refuse and tell the truth.
  if ! git merge-base --is-ancestor "$local_sha" "$remote_sha" 2>/dev/null; then
    echo "  Your copy has diverged from the published version — skipping auto-update."
    echo "  Resolve it with git when you get a chance."
    return 0
  fi

  local before_reqs after_reqs
  before_reqs=$(cksum requirements.txt 2>/dev/null | cut -d' ' -f1)
  if git merge --ff-only "origin/${branch}" >/dev/null 2>&1; then
    after_reqs=$(cksum requirements.txt 2>/dev/null | cut -d' ' -f1)
    echo "  Updated to $(grep -m1 'APP_VERSION = ' app.py | cut -d'"' -f2)."
    if [ "$before_reqs" != "$after_reqs" ] && [ -x venv/bin/python ]; then
      echo "  Dependencies changed — installing…"
      ./venv/bin/python -m pip install --quiet -r requirements.txt \
        || echo "  (dependency update failed; the app may still run)"
    fi
  else
    echo "  Update skipped — the app will start on your current version."
  fi
}
