# TransLinkBayes

Hierarchical Bayesian modelling of bus delay propagation across Vancouver's
TransLink network, fed by a live GTFS-realtime collection pipeline.

A collector polls TransLink's GTFS-RT feed every 5 minutes and stores stop-level
delays in SQLite. A processing layer joins them with the static GTFS schedule and
derives features (previous-stop delay, distance along route, time-of-day). The
analysis side fits hierarchical regressions in R with **brms** — Student-t
likelihood to handle heavy-tailed delays, splines for time effects, and random
effects per trip, stop, and route. Automated quality reports gate every data
refresh.

## Layout

| Path | What |
|---|---|
| `pipeline/` | Python collection, processing, export, and dashboard code |
| `analysis/` | R Markdown analyses (brms models, multi-route, visualizations) |
| `docs/` | Database schema (`schema.md`), data-quality baseline |
| `tests/` | Pure-logic smoke tests (`make test`) |
| `database/`, `exports/`, `logs/` | Generated data — gitignored |

## Getting started

```bash
make venv                 # Python 3.12 venv + pinned requirements
cp .env.example .env      # add your TransLink API key
make test                 # smoke tests, no database needed
make help                 # all pipeline targets (process, quality, export, …)
```

The R side uses [renv](https://rstudio.github.io/renv/): open R in the repo and
run `renv::restore()`, then `make render` to rebuild the Rmd reports.

Continuous collection runs via two macOS launchd jobs (5-minute realtime poll,
weekly static GTFS sync) — setup and troubleshooting are covered in
[CLAUDE.md](CLAUDE.md), which is the operational source of truth for this repo.

## Models

Four nested brms models, from a `delay ~ previous_stop_delay` baseline up to a
multi-route hierarchical model with temporal splines. Posteriors consistently
show near-unit delay propagation (≈0.997–0.999) with near-Cauchy tails — delays
persist stop-to-stop and extreme events dominate the variance. Details and run
history: CLAUDE.md and `exports/run_log.csv`.

## Provenance

Originated as a UBC STAT 447C (Bayesian Statistics) course project — see
[STAT447_ORIGIN.md](STAT447_ORIGIN.md). The original course submission is
archived at `Utsav02/TranslinkBayes-stat447-archive`; this repo is the
continuation with live collection, automated quality checks, and multi-route
models.
