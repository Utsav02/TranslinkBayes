# Origin: STAT 447C Course Project (UBC)

This project grew out of a course deliverable for STAT 447C (Bayesian Statistics) at UBC, completed May 2025.

The original course submission lives at:

```
~/Desktop/University/STAT 447/Project/TranslinkBayes/
```

(Eventually to be archived under `~/Desktop/University/Courses/STAT 447/`.)

## What was the course deliverable?

- Hierarchical Stan models (`delay_model_hier.stan`, `delay_model_ar_spatial.stan`) fitted on a single route (6641, direction 0) over ~1 week of manually collected GTFS-RT data.
- A written report (`docs/Bayesian_Transit_Delay_Report.Rmd/PDF`) analyzing stop-level delay propagation for STAT 447C.
- Exploratory analysis Rmds (`EDA.Rmd`, `Final_Script*.Rmd`).

## What this project adds

- A live Python collection pipeline (`pipeline/`) polling the TransLink GTFS-RT API every 5 minutes via launchd.
- A production-grade SQLite schema (`gtfs_realtime_v2.db`) accumulating real-time stop-level delay observations across all routes.
- brms models (M0–M3) re-fitted on weeks of live data, with a multi-route hierarchical extension (M3).
- Automated data quality checks, anomaly detection, and a run log (`exports/run_log.csv`) tracking model diagnostics over time.
- A visualization showcase (`analysis/viz_showcase.Rmd`) for research communication.

The course project established the research question and model architecture. Everything else was built after the course ended.
