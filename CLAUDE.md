# TransLinkBayes — Project Guide

Hierarchical Bayesian pipeline modeling bus delay propagation across Vancouver's TransLink network. Live GTFS-RT collection + brms analysis + automated quality checking.

Originated as a STAT 447C (UBC) course project. See `STAT447_ORIGIN.md` for provenance.

## Workspace
Part of the Post-Uni Projects workspace. See `../PROJECTS.md` for the full project index.

---

## Directory layout

```
pipeline/          Python collection + processing scripts
analysis/          R Markdown analysis files
  models/          Fitted brms .rds files (gitignored — large binaries)
docs/              schema.md (DB tables), known_baseline.md
renv/, renv.lock   R dependency lockfile (restore with renv::restore())
database/          SQLite databases (gitignored)
exports/           Parquets, run_log.csv, quality reports (gitignored)
logs/              launchd stdout/stderr (gitignored)
venv/              Python 3.12 venv (gitignored — re-create with requirements.txt)
```

---

## Running things

### Python pipeline
Common invocations are wrapped in the `Makefile` (`make help` lists targets:
`process`, `quality`, `export`, `refresh`, `dashboard`, `render`, …).
Always call the venv Python directly — `source activate` does not persist in bash subprocesses:
```bash
venv/bin/python3 pipeline/quality_report.py --since 2026-05-09
venv/bin/python3 pipeline/process_delays.py --since 2026-05-09
venv/bin/python3 pipeline/export_route.py --route 6641 --direction 0 --since 2026-05-09
venv/bin/python3 pipeline/export_route.py --route all --since 2026-05-09
```

### Full refresh (process + quality check + export + optionally re-render)
```bash
bash pipeline/refresh_analysis.sh             # data only
bash pipeline/refresh_analysis.sh --rerender  # also renders the Rmds
```

### R analysis (from analysis/)
```bash
cd analysis
Rscript -e "rmarkdown::render('brms_analysis.Rmd')"
Rscript -e "rmarkdown::render('multi_route_analysis.Rmd')"
Rscript -e "rmarkdown::render('viz_showcase.Rmd')"   # visualizations only, fast
```

### Live collection
Two launchd jobs manage continuous collection:
- `com.translink.collect` — runs `collect_realtime_v2.py` every 5 minutes
- `com.translink.sync-static` — runs `sync_static_gtfs.py` every Saturday at 10am

```bash
launchctl list | grep translink              # check both are loaded
launchctl unload ~/Library/LaunchAgents/com.translink.collect.plist   # stop
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
- `processed_stops` table is rebuilt by `process_delays.py`; it is safe to truncate and reprocess.

**viz_showcase.Rmd:**
- Auto-discovers the latest parquet via `tail(sort(list.files(..., pattern=...)), 1)`.
- Animated viz (gganimate) and leaflet map use `eval=requireNamespace(...)` for graceful fallback if packages are absent.

---

## Data quality baseline (since 2026-05-09)

- Dense collection started **2026-05-16** — days before that are sparse (Mac sleep, collector not yet running 24/7).
- 2026-05-09 is the `--since` cutoff for all scripts; anomaly detection in the Rmds auto-excludes outlier days.
- `quality_report.py` exits 1 on hard failures and is called inside `refresh_analysis.sh` with `set -e`, so a bad data day halts the refresh.
