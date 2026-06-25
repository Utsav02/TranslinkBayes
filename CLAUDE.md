# CLAUDE.md — TransLinkBayes

Guidance for Claude Code agents working in this repository.

> **House style.** The "Agent behavior" section below is shared across all of Utsav's
> personal repos — keep it consistent. Project-specific overrides are called out
> explicitly at the point of override.

## Project
Hierarchical Bayesian pipeline modeling bus delay propagation across Vancouver's
TransLink network. Live GTFS-RT collection + brms analysis + automated quality
checking. Originated as a STAT 447C (UBC) course project — see `STAT447_ORIGIN.md`.

- **Stack:** Python 3.12 (venv, requirements.txt) for the pipeline; R + brms (renv-locked)
  for analysis; SQLite for storage; launchd for live collection; Streamlit for the
  dashboard.
- **Run:** `make help` lists every entry point. Routine ones: `make test`,
  `make quality`, `make process`, `make export-all`, `make refresh`,
  `make refresh-render`, `make dashboard`, `make render`, `make collect-status`.
- **Deployed / lives at:** local only. Remote: `Utsav02/TranslinkBayes` (private).
- **Status:** active.
- **Key context:** `docs/schema.md` (full DB schema), `docs/known_baseline.md`
  (quality baseline), `STAT447_ORIGIN.md`, `COWORK.md`.

## Workspace
Part of the Post-Uni Projects workspace. See `../PROJECTS.md` for the full project index.

## Data & secrets — handle with care
- **`.env`** holds the TransLink GTFS-RT API key (`API_KEY`). Gitignored — never
  committed, never pasted into logs, commits, or docs. Only `.env.example`-style
  placeholders are safe to share. `pipeline/config.py` loads it from the project root.
- **SQLite databases (`database/*.db`) are IRREPLACEABLE and gitignored.** The git
  remote does NOT back them up. The live realtime DB (`gtfs_realtime_v2.db`) grows
  every 5 minutes via the launchd collector and cannot be re-fetched from TransLink
  retroactively. Static snapshots and parquet exports are similarly local-only.
  **Anything irreplaceable here needs a separate off-machine backup** — that's on you,
  not git.
- **Production launchd jobs run continuously** (`com.translink.collect`,
  `com.translink.sync-static`). Do not unload, restart, or modify them, or their
  plists, without explicit user approval — every gap is permanently lost data.
- `logs/`, `exports/`, `data/`, `analysis/models/` are all gitignored. Treat them as
  precious where the underlying data is hard to regenerate.

## Agent behavior
Shared working norms. Follow them unless the user says otherwise in-session.

### Verification — verify, show evidence, verify the *real* path
- Never report a number, test result, or "it works" without running it and showing the
  real output. No fabricated or projected results.
- Verify against the **real artifact and the real path**, not a stand-in. A passing
  unit test or a fresh-environment check is not proof it works in the live path — the
  seams (wiring, deploy target, the live DB, the running process) are where things
  actually break.
- For long-running jobs (brms fits, full refreshes), verify *genuine progress*, not
  just "started" — a launched process that silently died or hung is the default
  failure mode. Report liveness with evidence, and make long jobs survivable
  (checkpoint / log so an interruption resumes, not restarts).
- If a step was skipped or estimated, say so. When done and verified, say it plainly
  with the evidence.

### Documentation & reproducibility — as you go
- Document decisions, tradeoffs, and results as you go — don't wait to be asked. Keep
  it proportionate: short for routine work, fuller for significant/architectural
  decisions.
- Record versions, configs, environment, and the exact commands behind any result
  worth reproducing. `exports/run_log.csv` already captures model fits via
  `run_tracker.R` — use it.

### Git & durability
- Commit in logical, scoped chunks; don't sweep unrelated changes into a commit.
- **Push your work** — local-only commits aren't backed up. Flag when the repo is
  ahead of its remote.
- **Never run two write-sessions in one working tree.** If another session or the
  user may be editing this checkout, pathspec only your own files and re-check
  `git diff --cached` before each commit.
- Secrets never get committed (`.env` especially); check before every push. Remote
  is private — keep it that way unless explicitly told otherwise.

### Confirmation — confirm heavy / external / irreversible actions
- Ask first before: installing deps, downloading large files, kicking off long jobs
  (brms fits, `make refresh`), touching launchd, deploying, changing repo visibility,
  or anything outward-facing.
- Proceed freely on: file reads, smoke tests (`make test`), small local edits.
- Always stop for destructive or irreversible actions, and for anything that
  publishes to the outside world. Approval in one context does not carry to the next.

### Sessions — fresh one when context degrades
- Recommend a new session when responses slow, context clutters, or you're
  re-deriving established facts. Summarize state when you do, so the next session
  picks up cleanly.

### Scope — reasonable initiative
- Do what's asked; handle obvious adjacent work en route (e.g. a clear bug hit along
  the way). Flag anything larger **before** acting — surface it as a suggestion,
  don't silently expand scope.

### Communication — lead with recommendations
- Concise and direct; lead with a recommendation, not an option-survey. Expand
  rationale for significant decisions, keep it short for routine work.

### Workspace — structured directories
- Keep intermediate and final artifacts in clear subfolders (`data/`, `pipeline/`,
  `analysis/`, `exports/`, `docs/`). Commit durable artifacts; scratch files stay
  throwaway and gitignored.

## Repo-specific overrides (LOAD-BEARING — read before acting)
- **Do NOT modify the collector or its launchd jobs without explicit approval.**
  `com.translink.collect` and `com.translink.sync-static` are production data
  collection. Every 5-minute gap is permanently lost realtime data.
- **Databases are read-only from an agent's perspective.** Read with `sqlite3` or
  pandas; never `DROP`, never schema-migrate, never blow away `database/*.db`. They
  are gitignored and irreplaceable — see Data & secrets above.
- **Use `venv/bin/python3` directly.** `source venv/bin/activate` does not persist
  across bash subprocesses (or Make's per-line subshells). The Makefile already does
  the right thing — call `make` targets when one exists.
- **Use the renv-locked R environment** for any R work. `cd analysis && Rscript ...`
  picks up `.Rprofile` which activates renv. Don't install R packages outside renv.
- **Do NOT full-rebuild `processed_stops` casually.** The static GTFS DB has rolled
  since early data was processed, so a from-scratch rebuild of the whole table may
  not reproduce historical rows. Incremental `make process SINCE=<date>` is the
  default; full rebuilds need explicit user approval.

---

## Directory layout

```
pipeline/          Python collection + processing scripts
tests/             pure-logic smoke tests — `make test`, no DB needed
analysis/          R Markdown analysis files
  models/          Fitted brms .rds files (gitignored — large binaries)
docs/              schema.md (DB tables), known_baseline.md
renv/, renv.lock   R dependency lockfile (restore with renv::restore())
database/          SQLite databases (gitignored, IRREPLACEABLE)
exports/           Parquets, run_log.csv, quality reports (gitignored)
logs/              launchd stdout/stderr (gitignored)
venv/              Python 3.12 venv (gitignored — re-create with `make venv`)
```

---

## Running things

### Python pipeline
Common invocations are wrapped in the `Makefile` — `make help` lists targets
(`venv`, `test`, `process`, `quality`, `export`, `export-all`, `refresh`,
`refresh-render`, `dashboard`, `render`, `collect-status`). CI
(`.github/workflows/ci.yml`) runs install + syntax check + `pytest tests/` on every
push; R/renv is deliberately excluded from CI as too heavy.

Always call the venv Python directly — `source activate` does not persist in bash
subprocesses:
```bash
venv/bin/python3 pipeline/quality_report.py --since 2026-05-09
venv/bin/python3 pipeline/process_delays.py --since 2026-05-09
venv/bin/python3 pipeline/export_route.py --route 6641 --direction 0 --since 2026-05-09
venv/bin/python3 pipeline/export_route.py --route all --since 2026-05-09
```

### Full refresh (process + quality check + export + optionally re-render)
```bash
bash pipeline/refresh_analysis.sh             # data only — same as `make refresh`
bash pipeline/refresh_analysis.sh --rerender  # also renders the Rmds — `make refresh-render`
```

### R analysis (from analysis/)
```bash
cd analysis
Rscript -e "rmarkdown::render('brms_analysis.Rmd')"
Rscript -e "rmarkdown::render('multi_route_analysis.Rmd')"
Rscript -e "rmarkdown::render('viz_showcase.Rmd')"   # visualizations only, fast
```

### Live collection
Two launchd jobs manage continuous collection — **do not touch without approval**:
- `com.translink.collect` — runs `collect_realtime_v2.py` every 5 minutes
- `com.translink.sync-static` — runs `sync_static_gtfs.py` every Saturday at 10am

```bash
make collect-status                           # quick check both are loaded
launchctl list | grep translink               # same, raw
launchctl unload ~/Library/LaunchAgents/com.translink.collect.plist   # stop  (don't)
launchctl load   ~/Library/LaunchAgents/com.translink.collect.plist   # start
```

### launchd troubleshooting

`launchctl list | grep translink` prints `PID  last-exit-code  label`. A `-` PID is
normal (the job runs on an interval, it isn't resident). What matters is the exit code:
- `0` — last run succeeded.
- `1` (or anything non-zero) — last run failed. Check stderr first:
  `tail -50 logs/<label>.err.log` (paths are set via `StandardErrorPath` in the plist).
- Job missing from the list entirely — it isn't loaded; `launchctl load` it (see above).

Common failure causes, in the order to check them:
1. **Wrong Python** — the plist must invoke `venv/bin/python3` with an absolute path,
   not system `python3`. If the venv was rebuilt, the old interpreter path still works,
   but missing packages mean requirements weren't reinstalled (`make venv`).
2. **`.env` not found** — `config.py` loads `ROOT/.env` relative to the script file,
   so this only breaks if the project directory moved. Re-check plist paths after any
   folder rename.
3. **SQLite `database is locked`** — a long-running query (dashboard, quality report)
   held the write lock while the collector fired. The collector logs the error and the
   next 5-minute run usually succeeds; only investigate if `collection_runs.status`
   shows repeated `'error'` rows.
4. **Mac was asleep** — launchd does not retro-run missed intervals. Gaps in
   `collection_runs.started` correlate with sleep, not failures.
5. **API failures** — TransLink returns 401 on a bad/rotated key, and the feed
   occasionally 500s. Check `collection_runs` for the error text.

To re-run a job manually with the exact launchd environment:
```bash
launchctl kickstart -k gui/$(id -u)/com.translink.collect
```
Collector health at a glance:
```bash
sqlite3 database/gtfs_realtime_v2.db \
  "SELECT started, status, rows_inserted, net_new_rows FROM collection_runs ORDER BY run_id DESC LIMIT 10;"
```

---

## brms models

| File | Formula summary | Key result |
|---|---|---|
| `models/brms_m0.rds` | `delay ~ prev_stop_delay` | baseline |
| `models/brms_m1.rds` | + `shape_dist_traveled` | adds spatial |
| `models/brms_m2.rds` | + splines(hour, dow) + `(1\|trip_id)` + `(1\|stop_id)` | full single-route |
| `models/brms_m3_multiRoute.rds` | same + `(1\|route_id)` | multi-route hierarchical |

All use **Student-t likelihood**. Typical posteriors: `b_previous_stop_delay ≈ 0.997–0.999`, `nu ≈ 2.01` (near-Cauchy tails), `sigma ≈ 20–31s`. Run history in `exports/run_log.csv`.

---

## Non-obvious conventions

**R Rmd chunks:**
- `{r libs, cache=FALSE}` — library() calls must never be cached; knitr restores R objects but does not re-execute code, so `%>%` and other package exports would be missing.
- `{r data_quality, cache=FALSE}` — anomaly detection mutates `raw`; needs fresh eval.
- `{r split, cache=FALSE}` — train/test split; includes `stopifnot(nrow(test_df) >= 100)`.
- Use `posterior_summary(model)` (returns a stable numeric matrix) over `summary()$spec_pars` for parameter extraction — the latter varies across brms versions.
- `run_tracker.R` — `source("run_tracker.R"); track_run(model=m2, ...)` — appends a 19-column row to `exports/run_log.csv` after each fit.

**Python config:**
- `pipeline/config.py` is the single source of truth for all paths and URLs. `ROOT = Path(__file__).parent.parent` — works correctly from `pipeline/`.
- `.env` contains the TransLink API key (`API_KEY`). Never commit it.

**Databases:**
- Full table-by-table schema for both DBs: `docs/schema.md`.
- `gtfs_static.db` has a `stops` table (lat/lon) but **no `shapes` table**. Use stop coordinates for spatial work.
- `processed_stops` is rebuilt incrementally by `process_delays.py --since <date>`. A
  full from-scratch rebuild is **not** safe to run casually — the static GTFS DB has
  rolled since older rows were processed. See the override above.

**viz_showcase.Rmd:**
- Auto-discovers the latest parquet via `tail(sort(list.files(..., pattern=...)), 1)`.
- Animated viz (gganimate) and leaflet map use `eval=requireNamespace(...)` for graceful fallback if packages are absent.

---

## Data quality baseline (since 2026-05-09)

- Dense collection started **2026-05-16** — days before that are sparse (Mac sleep, collector not yet running 24/7).
- 2026-05-09 is the `--since` cutoff for all scripts; anomaly detection in the Rmds auto-excludes outlier days.
- `quality_report.py` exits 1 on hard failures and is called inside `refresh_analysis.sh` with `set -e`, so a bad data day halts the refresh.
