# TransLinkBayes — Claude Cowork Guide

Claude Cowork is Anthropic's autonomous desktop agent (inside the Claude Desktop app).
It can read, write, and run scripts in folders you grant it access to, then deliver
finished file outputs. It is **not** Claude Code — it uses a bash sandbox and file
tools directly, not the desktop GUI or your Terminal app.

---

## Cowork Capabilities Relevant to This Project

**Can do:**
- Run Python scripts via the venv (`venv/bin/python3`) and shell scripts via bash
- Read and synthesize `.txt`, `.csv`, `.parquet`, `.md`, `.Rmd` files
- Produce written `.md` reports and save them to granted folders
- Execute `bash pipeline/refresh_analysis.sh` and capture its output
- Run R scripts (`Rscript -e "..."`) if R is installed at the system level

**Cannot / should not do:**
- Fit brms models (MCMC takes hours; Cowork sessions are not designed for that)
- Access launchd jobs or the live `database/` SQLite directly — let the Python scripts do it
- Touch `.env` or API credentials

---

## Folder Access to Grant in Claude Desktop

When creating a Cowork task, grant access to:

| Folder | Permission | Reason |
|---|---|---|
| `TranslinkBayes/` (root) | Read | `CLAUDE.md`, `STAT447_ORIGIN.md`, `COWORK.md` for context |
| `TranslinkBayes/exports/` | Read + Write | Quality reports, parquets, run_log.csv; output memos go here |
| `TranslinkBayes/pipeline/` | Read | Script source for context; Cowork runs them via bash |
| `TranslinkBayes/analysis/` | Read | Rmd files, rendered HTMLs, run_log context |
| `TranslinkBayes/docs/` | Read + Write | Stakeholder outputs (create if missing) |

**Do NOT grant access to:**
- `TranslinkBayes/database/` — live SQLite; access via Python scripts only
- `TranslinkBayes/.env` — contains the TransLink API key

---

## Prerequisites — Do These Manually First

Before handing off any task to Cowork:

1. **Confirm the collector is live:**
   ```bash
   launchctl list | grep translink
   ```
   Both `com.translink.collect` and `com.translink.sync-static` should appear.

2. **Run the refresh pipeline** (produces fresh parquets + quality report):
   ```bash
   bash pipeline/refresh_analysis.sh
   ```
   If this exits with an error (hard data quality failure), do **not** hand off — investigate first.

3. **Verify today's exports exist:**
   ```bash
   ls exports/quality_report_$(date +%Y-%m-%d).txt
   ls exports/all_routes_$(date +%Y-%m-%d).parquet
   ```

4. **For model interpretation tasks**, confirm `exports/run_log.csv` has a recent row and that `analysis/models/brms_m3_multiRoute.rds` (or whichever model you want interpreted) exists.

---

## Task Prompts — Ready to Paste into Cowork

Replace `<TODAY>` with the current date in `YYYY-MM-DD` format before pasting.

---

### Task 1 — Data Quality Memo

Synthesize the latest quality report into a written memo.

```
Read the file `exports/quality_report_<TODAY>.txt` in the TranslinkBayes project
at /Users/utsavsingh/Desktop/Post-Uni/Projects/TranslinkBayes/. Also read
`CLAUDE.md` in the same directory for background on the project.

Write a concise data quality memo (400–600 words) covering:

1. Collection health: how many days in the window, what fraction are dense vs.
   sparse, whether the collector is running on schedule (look for the "Collector
   last ran X min ago" line).

2. The most important warnings and what each implies for analysis — e.g.,
   sparse days (< 20% of median) should be excluded from model fitting; stale
   predictions (> 5%) indicate minor API latency but are not blockers; blank
   route_id rows suggest API quality drift.

3. Delay distribution: typical delay range (median, MAD-equivalent SD), any
   anomalous days flagged by the > 2.5×MAD threshold, and whether the
   distribution looks stable across the window.

4. Route coverage: how many routes have ≥ 500 rows (sufficient for the M3
   hierarchical model) vs. the total routes observed.

5. Overall verdict: one sentence — is the data ready for model fitting, or are
   there blockers?

Save the output as `exports/quality_memo_<TODAY>.md`.
```

---

### Task 2 — brms Model Results Interpretation

Translate run_log.csv metrics into plain-English model commentary.

```
Read `exports/run_log.csv` and `CLAUDE.md` in
/Users/utsavsingh/Desktop/Post-Uni/Projects/TranslinkBayes/.

The CSV columns are: run_date, data_from, data_to, n_train, n_test, n_routes,
b_prev_delay_mean, b_prev_delay_q2.5, b_prev_delay_q97.5, sigma_mean, nu_mean,
route_sd_mean, rhat_max, ess_min, n_divergences, mae, rmse, coverage_90,
model_file.

Write a 500–700 word model results summary covering:

1. Core finding: how strongly does previous-stop delay predict current-stop
   delay? (b_prev_delay ≈ 0.997 means that if a bus is 60s late at stop N, it
   is expected to be ~59.8s late at stop N+1 — explain this as a decay rate, not
   a coefficient).

2. Heavy-tailed residuals: nu ≈ 2 means a Student-t with near-Cauchy tails.
   Explain in plain English that extreme delays occur far more often than a
   normal distribution would predict.

3. Residual noise (sigma, in seconds) across models and what it means: even
   with perfect delay propagation, individual stop predictions carry ~20–31s
   of unexplained variance.

4. MCMC diagnostics: rhat_max < 1.01 and ess_min > 400 indicate convergence;
   comment on n_divergences and what elevated counts would mean.

5. Predictive performance: MAE and RMSE in seconds; coverage_90 near 0.90
   means 90% credible intervals are well-calibrated — explain what this means
   for riders who want a "how late will my bus be?" estimate.

6. Route-level variation (route_sd_mean): what it means that some routes are
   systematically more or less delayed than the network average.

Save the output as `exports/model_summary_<TODAY>.md`.
```

---

### Task 3 — Stakeholder Findings Brief

One-page non-technical summary suitable for a TransLink manager or UBC administrator.

```
Read the following files in /Users/utsavsingh/Desktop/Post-Uni/Projects/TranslinkBayes/:
- CLAUDE.md
- STAT447_ORIGIN.md
- exports/run_log.csv
- The most recent exports/quality_report_*.txt file (pick the one with the
  latest date in the filename)

Write a one-page findings brief (600–800 words, no statistical jargon) for a
non-technical reader. Structure it as follows:

**What we studied** (1 paragraph): The question — how does bus lateness spread
through Vancouver's transit network? Why does this matter operationally?

**How we studied it** (1 paragraph): Live GPS data collection every 5 minutes,
~1.5 million observations, 200+ routes, Bayesian statistical model. Keep it
accessible — no mention of "brms", "MCMC", or "posterior distributions".

**Key finding 1 — Delays are contagious** (1 paragraph): A bus running late
at one stop will almost certainly still be running late at the next stop.
Express this using b_prev_delay_mean: e.g., "97% of a delay at stop N persists
to stop N+1". Discuss the compounding implication over many stops.

**Key finding 2 — Extreme delays are far more common than expected** (1
paragraph): The data has heavy tails — occasional very large delays dominate.
Express nu ≈ 2 as: "delays this severe occur [X] times more often than standard
statistical models would predict". Do not use the word "nu".

**Key finding 3 — Some routes are systematically worse** (1 paragraph): The
hierarchical model reveals between-route variation. Name the two routes with
mean filtered delay > 300s from the quality report (routes 39305 and 29039 as
of the last report) as examples, but frame it as a pattern, not an outlier.

**What this means** (3 bullet points): Practical operational implications for
riders and schedulers.

**Limitations** (1 short paragraph): Data gaps in early May 2026, model does
not yet account for weather or special events, predictions are probabilistic.

Create the docs/ folder if it does not exist, then save the output as
docs/findings_brief_<TODAY>.md.
```

---

### Task 4 — Run Pipeline + Synthesize in One Pass

Runs the full refresh and immediately produces a quality memo. Use this when
the data refresh has **not** been run today and you want Cowork to do both steps.

```
Working in /Users/utsavsingh/Desktop/Post-Uni/Projects/TranslinkBayes/:

Step 1: Run:
  bash pipeline/refresh_analysis.sh

Wait for it to finish. If it exits with a non-zero status or prints "[FAIL]",
stop immediately and report the exact error message — do not proceed.

Step 2: Once it succeeds, identify the quality report it just produced:
the newest file matching exports/quality_report_*.txt (it will be dated today).

Step 3: Write a quality analysis memo following this structure (400–600 words):
  - Collection health (days in window, dense vs. sparse split, collector
    freshness from the "Collector last ran X min ago" line)
  - Top warnings and their implications for analysis
  - Delay distribution summary (median, MAD-equivalent SD, anomalous days)
  - Route coverage for the hierarchical model (routes with ≥ 500 rows)
  - One-sentence overall verdict

Save the memo as exports/quality_memo_<TODAY>.md.

Step 4: Report back: what date range is now in the data, how many total rows,
and whether there are any anomalous-day or hard-failure warnings that would
block model fitting.
```

---

### Task 5 — Route Delay Leaderboard

Compute and narrate a ranked summary of route-level delays from the latest parquet.

```
Run from /Users/utsavsingh/Desktop/Post-Uni/Projects/TranslinkBayes/:

venv/bin/python3 -c "
import pandas as pd, glob

f = sorted(glob.glob('exports/all_routes_*.parquet'))[-1]
print('Reading:', f)
df = pd.read_parquet(f)
df = df[(df['delay_seconds'].abs() <= 3600) & df['delay_seconds'].notna()]

summary = (
    df.groupby('route_id')
      .agg(
          n            = ('delay_seconds', 'count'),
          mean_delay   = ('delay_seconds', 'mean'),
          median_delay = ('delay_seconds', 'median'),
          p90_delay    = ('delay_seconds', lambda x: x.quantile(0.9))
      )
      .query('n >= 500')
      .sort_values('mean_delay', ascending=False)
      .reset_index()
)

summary.to_csv('exports/route_delay_summary.csv', index=False)
print(summary.head(10).to_string(index=False))
print('...')
print(summary.tail(10).to_string(index=False))
print(f'Total routes with >= 500 rows: {len(summary)}')
"

Then read exports/route_delay_summary.csv and write a 300–400 word commentary:
- The 5 most-delayed routes: mean delay in seconds, what the gap between
  median and p90 says about tail risk on each route
- The 5 least-delayed routes and what makes them comparatively reliable
- Any visible patterns (e.g., express vs. local, if route IDs cluster)
- One sentence on what a scheduler could do with this information

Save the commentary as exports/route_delay_commentary_<TODAY>.md.
Also keep exports/route_delay_summary.csv as a machine-readable artifact.
```

---

## Output File Map

| Task | Output file | Format |
|---|---|---|
| Task 1 — Quality memo | `exports/quality_memo_YYYY-MM-DD.md` | Markdown prose |
| Task 2 — Model interpretation | `exports/model_summary_YYYY-MM-DD.md` | Markdown prose |
| Task 3 — Stakeholder brief | `docs/findings_brief_YYYY-MM-DD.md` | Markdown prose |
| Task 4 — Run + memo | `exports/quality_memo_YYYY-MM-DD.md` | Markdown prose |
| Task 5 — Route leaderboard | `exports/route_delay_commentary_YYYY-MM-DD.md` + `exports/route_delay_summary.csv` | Markdown + CSV |
