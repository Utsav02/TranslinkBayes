# Model-Search Loop Journal

Append-only log of loop iterations. Each candidate fit writes a 5-line entry
here in reverse-chronological order (newest on top), per the per-iteration
prompt in `model_loop_spec.md` §3 and `cloud_loop_runbook.md` §6.

Entry template:

```
## <ID> — <YYYY-MM-DD HH:MM tz>  <PASS|FAIL>

Hypothesis: <one line — copy from loop_candidates.tsv>
Fit: <wall time, cores, converge diagnostics (R-hat max, div count, ESS min)>
ELPD: <held-out ELPD ± SE>   ΔELPD vs C_m2nu4: <±X (SE ...)>   G4: <PASS|FAIL>
Verdict: <one sentence — why we accept/reject; note anything surprising>
```

The corresponding `run_log.csv` row and `elpd_pointwise_<ID>.rds` are the
authoritative machine-readable record. This journal is for the human-readable
narrative that a reader can skim to reconstruct the loop's decisions without
re-running any code.

---

<!-- iterations append below this line, newest on top -->
