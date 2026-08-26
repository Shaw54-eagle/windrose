# Windrose — working notes

Read this before changing anything. It is the accumulated hard-won context from
building this app, written for whoever picks it up next.

## What this is

A local, read-only investing console. Flask backend, vanilla-JS frontend, no
build step, no framework, no database. It runs on the user's own machine on
port 7070 and nothing leaves that machine except price and news requests.

It is deliberately **view-only**. It cannot place a trade and must never be able
to. It does not tell anyone what to buy.

## Layout

| File | Role |
| --- | --- |
| `app.py` | Flask routes, settings, holdings, orchestration. Start here. |
| `market.py` | Quotes. Alpaca when keys exist, batched yfinance otherwise. |
| `analysis.py` | Portfolio risk maths — VaR, beta, correlation, drawdown. |
| `models.py` / `strategies.py` | Workbench models and the backtest lab. |
| `extras.py` | Supply-chain loading, journal, dividends, misc. |
| `chokepoints.py` | Shared-dependency analysis over the supply graph. |
| `alerts.py` | Alert rules and evaluation loop. |
| `notify.py` | Desktop notifications, per OS. |
| `updater.py` / `update.sh` | Version check. Notify-only — never applies. |
| `selftest.py` | User-facing install diagnosis. |
| `static/app.js` | The entire frontend. One file, ~2600 lines. |
| `supply_chain.json` | 26 industries, ~430 companies. Hand-curated. |
| `tests/` | Browser-driven suites. Run them before pushing. |

## Rules that exist because something broke

**Escape untrusted text.** `supply_chain.json` is community-editable and the
README invites pull requests against it. A crafted company label was able to
execute arbitrary JavaScript with access to the local API that holds the user's
positions. There are now two locks: HTML is stripped server-side in
`extras._scrub_chain()`, and escaped at render with `esc()` in `app.js`. Keep
both. Anything from a user, a contributed file, or an external API goes through
`esc()` before it touches `innerHTML`.

**Validate tickers and numbers.** `TICKER_RE` in `app.py`. The holdings endpoint
used to accept `<script>` tags, `../../etc/passwd`, negative share counts (which
silently corrupt the risk maths as a negative weight) and 1e18 shares. Note the
regex must accept `^VIX`, `BRK-B` and `ES=F` — the first attempt broke indices.

**Keys are loopback-only.** `/api/setup/savekeys` and `/api/setup/testkeys`
refuse any request not from 127.0.0.1, so keys cannot be set over LAN access.

**Placeholders are not keys.** `.env.example` values like `your_alpaca_key_here`
must read as *unset* (`market._clean()`), or the app believes it has credentials
and hammers the API with 401s forever. That shipped and a Windows user found it.

**Never invoke `venv/bin/pip`.** A virtualenv bakes in its absolute path, so
renaming the folder breaks every script in `venv/bin`. Always
`venv/bin/python -m pip`, which uses the interpreter directly.

**Assert on what renders, not on state.** The analyze button shipped broken
because a test checked that `MW.sym` was correct. It was. Nothing appeared on
screen.

## The publish workflow

`main` is a **publish channel**. As of v5.3 it is no longer a deploy channel:
installs check for a newer version and print it, but nothing is applied until the
user runs `git pull` themselves. See `update.sh`.

That lowers the blast radius of a bad push from "every machine at next launch" to
"every machine whose owner chooses to pull". It does not make main casual. A
pushed mistake is still the thing people are being invited to take, and users who
pull are trusting that main is deliberate. Branch for experiments; merge with
intent.

The old behaviour is worth remembering when reading git history: anything before
v5.3 shipped under an auto-applying updater, which is why the rules in this file
are as paranoid as they are.

Machine roles:

- **Mac — admin.** Where the work happens. Holds the working clone.
- **Acer (Linux) — publishing and cross-platform testing.** Pushes to GitHub,
  and is where Linux and Windows behaviour gets verified.

Only one machine should be able to push. Disable it on the other with
`git remote set-url --push origin DISABLED-...` — pulls still work, pushes fail
loudly.

Before any push: `git diff --stat` and actually read it. Three regressions have
been caught this way, including `LICENSE` being reverted to a placeholder name.

## Honest limits

- The supply-chain map is curated by hand from filings and news. It is
  incomplete and drifts as companies are acquired. `selftest.py --online`
  verifies every mapped ticker still resolves.
- Chokepoint analysis measures **graph structure, not revenue**. A company
  behind 70% of a book means the holdings sit downstream of it, nothing more.
- Alerts only fire while the server runs. `Run at Login.command` mitigates it;
  the Alerts panel says so plainly and should keep saying so.
- Windows toast notifications and the pywebview native window are code-verified
  but have never been executed by their author. Treat as unproven.
- Nothing self-updates any more. Every install needs a deliberate `git pull`, so
  assume the field is running a spread of versions indefinitely — a fix is not
  "shipped" the moment it lands on main. Versions before 4.7 have no `update.sh`
  at all and will not even tell their owner that something newer exists.

## Tone

The writing in this app is part of the product. It states what a number means,
where it comes from, and where it lies to you. No hype, no false precision, no
implying certainty that isn't there. If a feature can't be described honestly,
that's a signal the feature is wrong. Match that voice.

## Where things stand

Published on GitHub: **v5.2**. v5.3 is committed on the `v5.3-staging` branch,
**not pushed** — five commits, unmerged to `main`.

In v5.3: notify-only updater, the non-destructive test fixture, `WINDROSE_PORT`,
supply-chain schema v2, the Advanced walkthrough, the `reportProblem` fix, four
new themes, five layout presets, and colour-blind safe mode.

Shelved, deliberately: opt-in anonymous ticker sharing. Built and passing, then
removed before any commit — too few users for a cohort threshold to return
anything meaningful, and position-collecting code should not sit in a public repo
in the meantime. The design and a re-apply patch are outside the repo in
`~/windrose-shelved/opt-in-sharing-v5.3/`.

Cleared since this list was written:

- **`WINDROSE_PORT` is finished.** All five remaining files honour it.
  `app_native.py` now binds `ledger.PORT` rather than a literal, so there is one
  parser and not two. Verified live: with 7070 occupied, a second instance came
  up on 7099. The pywebview window itself is still unproven — see Honest limits.
- **`tests/sweep3.py` is 31/31.** The suite kept KO after adding it and now
  deletes it in a `CLEANUP` block at the end, so the checks that need a holding
  have one. The `&&` guards throw instead of silently doing nothing.
- **The suites no longer eat your data.** `tests/fixture.py` snapshots the eight
  private state files and restores them on exit, exception, Ctrl-C and SIGTERM.
  This exists because a sweep run deleted a real KO position out of a real book.
  See `tests/README.md`.
- **`reportProblem` is defined.** It was referenced at `app.js:2986` and existed
  nowhere, so the Report a Problem button threw a `ReferenceError`. It now opens
  a prefilled GitHub issue built from `/api/diagnostics`, which carries no
  holdings, keys or notes. `/api/diagnostics` gained a `repo` field so a fork
  files against itself.
- **`tests/v4test.py` is 47/47.** It asserted the welcome overlay closed when a
  mode was picked, which stopped being true when v5.2 made it a four-step wizard;
  it aborted around check 22. It now walks mode → keys → portfolio → finish.
- **The Advanced walkthrough is built** — `WALK` in `app.js`, four steps that
  drive the real UI and quote the numbers back out of what rendered rather than
  out of the API. Reachable from ⚙ settings and from `learn` via `/?walk=1`.
  `tests/walk.py`, 62 checks, run twice: with a book and with an empty one.

### The queue, in order

**1. Verify `start.bat` on Windows.** It honours `WINDROSE_PORT` now, but the
change is code-verified only and has never been executed. Acer's job.

**2. Decide whether 3 hops is too generous for chokepoints.** Building the
walkthrough surfaced this: a book of AAPL/NVDA/XOM reports twelve suppliers all
tied at 61%, and reaches AMC Theatres downstream. Not wrong — they genuinely sit
within three hops — but a tie that wide is closer to noise than signal. The
walkthrough now says "one dependency wearing twelve names" rather than picking a
fake winner, which is honest but treats the symptom.

## Before you finish anything

    python3 selftest.py                  # install health, map consistency
    python3 tests/sweep3.py              # 31 checks across the whole UI
    python3 tests/v4test.py              # 47 checks: wizard, modes, settings
    python3 tests/wizt.py                # 16 checks: setup wizard, both branches
    python3 tests/final47.py             # 13 checks — needs a server already up
    python3 tests/walk.py                # 62 checks: the advanced walkthrough
    git diff --stat                      # read it

The suites restore your holdings, journal, alerts, settings and `.env` when they
finish, so they are safe to run against a live install. `kill -9` is the one
exception; see `tests/README.md`.

Bump `APP_VERSION` in `app.py`, the topbar string in `templates/index.html`, and
`CFBundleVersion` in `Windrose.app/Contents/Info.plist` together — they drift
otherwise, and the version is the only signal a user has about what they're on.
