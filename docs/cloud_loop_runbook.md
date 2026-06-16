# Cloud Loop Runbook — running the 10-candidate model-search loop on a cloud box

This 16 GB laptop has failed the workload too many times to host the actual
loop: two system-sleep deaths, two 16 GB eval OOMs (one on `posterior_predict`,
one on `log_lik`), a marginal 35 W adapter that flickers off AC under 4-core
load. Multiple multi-hour fits have completed only because of layered
work-arounds (`caffeinate -s`, line-buffered logs, chunked eval). **The loop
itself must not run here.** This document is everything needed to run it
elsewhere.

Status when this was written (2026-06-16): a **reference model** has been
selected on this laptop (see `baseline_registry.md`; outcome is either
`C_m2nu4` clean / `C_m2nu4` near-clean-with-documented-relaxation / fallback to
an earlier simpler fit). The cloud loop walks `loop_candidates.tsv` from C0
onward, evaluating every candidate against this reference on the frozen test
set.

---

## 1. Box spec

| Dim | Min | Comfortable |
|---|---|---|
| RAM | **32 GB** (16 GB OOM'd both an unbatched `log_lik` and a `posterior_predict` on the 104k-row frozen test) | **64 GB** |
| vCPU | 4 (one chain each) | 8 (lets `loo::loo_compare` etc. run in parallel) |
| Disk | 20 GB (fits in `models/` are 100 MB–600 MB; ~10 candidates × ~400 MB = ~4 GB; logs + parquets minor) | 50 GB |
| OS | Linux x86_64 (Ubuntu 22.04 / 24.04 LTS) | same |

Cost reference points (no endorsement, just so the order of magnitude is real):
AWS `m6i.2xlarge` (8 vCPU / 32 GB), GCP `n2-standard-8`, Hetzner CX52 — all
under $0.40/h on demand. Total loop spend ≈ $20–40 even at unhurried pace.

A non-sleeping server **eliminates the entire sleep-proofing layer**:
`caffeinate`, the `script -q /dev/null` pty wrapper, and the CPU-time-delta
liveness check are macOS-laptop workarounds. On Linux they're unneeded — just
run under `nohup … &` or systemd / tmux / screen.

---

## 2. Provision and reproduce the environment

```bash
sudo apt update && sudo apt -y install \
    git build-essential gfortran \
    r-base r-base-dev \
    libcurl4-openssl-dev libssl-dev libxml2-dev libjpeg-dev libpng-dev \
    libv8-dev libfontconfig1-dev libfreetype6-dev libharfbuzz-dev libfribidi-dev

git clone https://github.com/Utsav02/TranslinkBayes.git
cd TranslinkBayes
```

R toolchain (pinned via `renv.lock`):
- R **4.5.0** (rbig.com / `rig install 4.5.0` is the easiest non-apt path)
- brms **2.22.0** + Stan stack — restored by `renv::restore()`, not installed
  by hand.

```bash
Rscript -e 'install.packages("renv", repos="https://cloud.r-project.org")'
Rscript -e 'renv::restore()'   # installs the locked stack incl. brms+Stan
```

A first `brm()` call compiles Stan models from C++ on this box; that costs
~2 min per unique formula and is reusable across iterations. Budget ~10 min on
first run.

Python env is unnecessary on the cloud box — the loop does not call
`process_delays.py` / `export_route.py`. Owner-run data prep stays on the
laptop (see "What runs on cloud vs. laptop" below).

---

## 3. What to ship onto the box

Everything below is small (under 5 MB combined) **except** the chosen
reference model. The frozen test set and reference are what make the cloud
loop reproducible.

| Path | Source | Why |
|---|---|---|
| **the repo at the chosen commit** | `git clone …; git checkout <SHA>` | code + scripts + docs + `renv.lock` |
| `exports/loop_train.parquet` | scp from laptop | frozen TRAIN; gitignored |
| `exports/loop_test.parquet` | scp from laptop | frozen TEST; gitignored |
| `exports/loop_split_manifest.txt` | already in git | SHA-256 the launcher checks |
| `exports/run_log.csv` | already in git for now | loop memory — every iteration appends |
| `exports/elpd_pointwise_<REF>.rds` | scp from laptop | reference's pointwise ELPD; loop computes ΔELPD vs this |
| `analysis/models/brms_<REF>.rds` | scp from laptop | the reference fit itself (100–600 MB) |
| `analysis/loop_candidates.tsv` | already in git | the queue |
| `analysis/fit_candidate_TEMPLATE.R` | already in git | scaffold the loop agent copies per candidate |

Concretely, from the laptop:

```bash
ssh user@cloudbox 'mkdir -p TranslinkBayes/exports TranslinkBayes/analysis/models'
REF=C_m2nu4   # whichever reference baseline_registry.md names
scp exports/loop_train.parquet exports/loop_test.parquet \
    exports/elpd_pointwise_${REF}.rds \
    user@cloudbox:TranslinkBayes/exports/
scp analysis/models/brms_${REF}.rds \
    user@cloudbox:TranslinkBayes/analysis/models/
```

On the cloud box, verify the hashes match the manifest (this is the same check
the launcher does):

```bash
cd TranslinkBayes
shasum -a 256 exports/loop_train.parquet exports/loop_test.parquet
# compare against exports/loop_split_manifest.txt — must match BYTE FOR BYTE
```

If they don't, the launcher aborts with "ABORT: hash drift" and you re-scp
rather than re-materialize. The frozen split is never regenerated on cloud.

---

## 4. What runs on cloud vs. what stays on the laptop

**Cloud (this loop):**
- One iteration at a time: author `analysis/fit_candidate_<ID>.R` from the
  template, fit, evaluate on the frozen TEST, append the `run_log.csv` row.
- All ten candidates C0–C7 (the queue) plus the already-completed C0_notrip /
  C0_nu4 / C_m2nu4 rows (which arrive in `run_log.csv` from the laptop).

**Laptop only (do not move):**
- The live collector and `com.translink.sync-static` launchd jobs (these write
  to `database/gtfs_realtime_v2.db` and must keep running for FIFA snapshots).
- `pipeline/process_delays.py`, `pipeline/export_route.py`,
  `pipeline/sync_static_gtfs.py`, the static DB sync. The frozen split is
  *frozen* — the cloud loop never regenerates parquets.
- `pipeline/fetch_weather_eccc.py` if/when C7 needs `weather_hourly.parquet`
  (scp it over alongside the other parquets).

---

## 5. Running one iteration on the cloud

Each iteration the loop agent does the following (manually or under a
`tmux`/`systemd` shell — there is no `caffeinate` here):

1. **Verify the frozen split.** `scripts/run_loop_iteration.sh` does this on
   macOS; on Linux a one-liner replaces the laptop-specific assertion checks:

   ```bash
   cd TranslinkBayes
   want_train=$(awk '/loop_train\.parquet/{getline;print}' exports/loop_split_manifest.txt | grep -oE 'sha256=[0-9a-f]+' | cut -d= -f2)
   have_train=$(sha256sum exports/loop_train.parquet | cut -d' ' -f1)
   [ "$want_train" = "$have_train" ] || { echo "ABORT: train hash drift"; exit 5; }
   ```

2. **Resolve the next candidate.** Lowest-numbered id in
   `analysis/loop_candidates.tsv` with no row in `exports/run_log.csv`.

3. **Author the fit script.** Copy `analysis/fit_candidate_TEMPLATE.R` to
   `analysis/fit_candidate_<ID>.R`, edit the three marked blocks
   (`CANDIDATE_ID`, any candidate-specific data prep, the formula +
   `adapt_delta`). The template already reads the frozen parquets, evaluates
   via memory-safe `loop_eval.R`, and appends the `run_log.csv` row.

4. **Fit + auto-eval** in a detached shell (use `tmux` or systemd):

   ```bash
   cd analysis
   nohup Rscript fit_candidate_<ID>.R > ../logs/fit_<ID>.log 2>&1 &
   ```

   Cadence: one fit per ~4 h. With 8 vCPU and 32 GB, fits should be faster
   than the laptop's 3–5 h.

5. **Gate.** The template prints `rhat_max`, divergences, ELPD, MAE, RMSE,
   cov90. Pass on G1 (R-hat < 1.01), G2 (0 div), G3 (ESS ≥ 400), and on G4
   (ΔELPD vs reference > 2×SE, computed inside `loop_eval.R`). Append the row
   regardless (pass AND fail are both information; this is pre-registered).

6. **Commit + push.** Every iteration:

   ```bash
   git add analysis/fit_candidate_<ID>.R exports/run_log.csv \
           exports/elpd_pointwise_<ID>.rds
   git commit -m "loop iter <ID>: <one-line verdict>"
   git push origin main
   ```

   This synchronizes back to the laptop and gives the loop a durable audit
   trail. Model `.rds` files stay on the cloud (gitignored, scp on demand if
   you want them locally).

7. **STOP conditions** (per `model_loop_spec.md` §3):
   queue exhausted, **or** three consecutive G4 non-improvements, **or**
   manifest hash drift, **or** the reference itself is invalidated (do not
   re-fit the reference here — that decision goes back to the laptop /
   modeler).

---

## 6. Starting the Ralph /loop on the cloud box

Inside `tmux` so the session survives disconnects:

```bash
tmux new -s tlb-loop
cd TranslinkBayes
claude  # or whichever CLI you're using
```

Per-iteration prompt (from `model_loop_spec.md` §3.1, adapted: no
caffeinate/script-pty, no CPU-time check — just nohup + tmux):

> Read `docs/model_loop_spec.md` §4 and `exports/run_log.csv`. Identify the
> lowest-numbered candidate with no run_log row. Verify
> `exports/loop_{train,test}.parquet` against `loop_split_manifest.txt` — abort
> on hash drift. Copy `analysis/fit_candidate_TEMPLATE.R` to
> `analysis/fit_candidate_<ID>.R` and apply the §4 formula. Launch:
> `cd analysis && nohup Rscript fit_candidate_<ID>.R > ../logs/fit_<ID>.log
> 2>&1 &`. When it returns, gate (R-hat<1.01, 0 div, ESS≥400, ΔELPD vs
> reference > 2×SE). Append a 5-line verdict to `docs/loop_journal.md`. Commit
> + push. STOP at queue end or 3 consecutive G4 non-improvements.

Cadence is generous (one fit per session) — this is not a tight poll loop.

---

## 7. What changes from the laptop spec

These laptop-only constructs become no-ops on cloud (kept in the repo as
macOS-specific; the cloud iteration shell skips them):

- `scripts/sleepproof_run.sh` — server doesn't sleep; `nohup … &` is enough.
- `script -q /dev/null` pty wrapper for line-buffered logs — Linux R doesn't
  block-buffer stdout under nohup nearly as aggressively, and `tail -f` works
  fine without it.
- CPU-time-delta liveness check — process either runs or doesn't on a
  non-sleeping box.
- The 35 W adapter / AC-Power assertion warnings.

The `scripts/run_loop_iteration.sh` launcher is macOS-specific; the
laptop-derived hash-verify + candidate-resolve logic can be ported in 20 lines
of bash, or the loop agent can do the equivalent inline (it's not load-bearing
infrastructure — the model_loop_spec contract is).

---

## 8. Receiving cloud results back

`exports/run_log.csv` accumulates one row per candidate. After each iteration
commit, `git pull` on the laptop synchronizes new rows. The
`elpd_pointwise_<ID>.rds` files (tiny — one float per test row) come along
too, so you can compute pairwise ΔELPD comparisons offline on the laptop
without the heavy `.rds` model files.

When the loop finishes (queue exhausted or stop condition), the cloud box's
job is done — destroy it. The frozen test set, the reference model on the
laptop, the per-candidate pointwise ELPD vectors in git, and the
`run_log.csv` are the durable record.

---

## 9. Do NOT start the loop here

This runbook is documentation only. The actual cloud loop launch happens when
the user requests it, after reviewing the reference model's outcome in
`baseline_registry.md` and choosing whether to (a) start the loop or (b) wait
for the dataset to fatten (FIFA + snapshot collector) before running. **No
fits run on this laptop after C_m2nu4 lands.**
