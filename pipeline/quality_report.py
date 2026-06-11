"""
Data quality checker for the TransLink Bayesian delay project.
Queries processed_stops and prints a structured report.
Exits with code 1 on hard failures so refresh_analysis.sh halts before
corrupted data reaches R.

Usage:
    python quality_report.py
    python quality_report.py --since 2026-05-09
"""
import argparse
import math
import sqlite3
import statistics
import sys
from datetime import date, datetime, timezone
from io import StringIO
from pathlib import Path

ROOT       = Path(__file__).parent.parent
DB         = str(ROOT / "database" / "gtfs_realtime_v2.db")
EXPORT_DIR = ROOT / "exports"

# ── Thresholds ───────────────────────────────────────────────────────────────
SPARSE_PCTILE      = 0.20   # < 20% of median daily count → sparse day
MAX_GAP_HOURS      = 2.0    # > 2h consecutive gap → possible Mac sleep
NULL_RATE_WARN     = 0.01   # > 1% NULLs for a model column → warn
PREV_NULL_EXPECTED = 0.07   # previous_stop_delay: first stops are structurally NULL;
                            #   warn only above 7% (expected NULL rate is ~4–5%)
GTFS_FAIL_WARN     = 0.10   # > 10% rows missing shape_dist_traveled → warn
OUTLIER_SECONDS    = 3600   # |delay| > 3600 = outlier (same cutoff used in R)
ANOMALY_MAD_K      = 2.5    # flag day if |mean − median| > 2.5 × MAD-equivalent-SD
                            #   MAD is robust to outlier days shifting the baseline;
                            #   replaces SD-based threshold which was sensitive to the
                            #   window composition
FRESHNESS_MAX_HOURS = 0.25  # last successful collect run > 15 min ago → warn
STALE_WARN_PCT      = 0.05  # > 5% predictions with actual_arrival < timestamp


class Report:
    def __init__(self):
        self._buf = StringIO()
        self.hard_failures = []
        self.warnings = []

    def _w(self, text=""):
        print(text)
        self._buf.write(text + "\n")

    def section(self, title):
        self._w()
        self._w("=" * 64)
        self._w(f"  {title}")
        self._w("=" * 64)

    def hfail(self, msg):
        self.hard_failures.append(msg)
        self._w(f"  [FAIL] {msg}")

    def warn(self, msg):
        self.warnings.append(msg)
        self._w(f"  [WARN] {msg}")

    def ok(self, msg):
        self._w(f"  [OK]   {msg}")

    def line(self, msg=""):
        self._w(msg)

    def save(self, path: Path):
        path.parent.mkdir(exist_ok=True)
        with open(path, "w") as f:
            f.write(self._buf.getvalue())


def run(since: str | None = None) -> int:
    rpt   = Report()
    today = date.today().isoformat()

    header = f"TransLink Data Quality Report — {today}"
    if since:
        header += f"  (since {since})"
    rpt.line(header)
    rpt.line(f"DB: {DB}")

    where    = f"WHERE timestamp >= '{since}'"   if since else ""
    ts_and   = f"AND timestamp >= '{since}'"     if since else ""

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    # ── 1. Collection completeness ────────────────────────────────────────────
    rpt.section("1. COLLECTION COMPLETENESS")

    daily = conn.execute(f"""
        SELECT date(timestamp) AS day, COUNT(*) AS n
        FROM processed_stops {where}
        GROUP BY day ORDER BY day
    """).fetchall()

    total_rows = sum(r["n"] for r in daily)
    n_days     = len(daily)
    rpt.line(f"  Total rows:        {total_rows:,}  across {n_days} days")

    if total_rows == 0:
        rpt.hfail("processed_stops is EMPTY — nothing to analyse")
        conn.close()
        out = EXPORT_DIR / f"quality_report_{today}.txt"
        rpt.save(out)
        rpt.line(f"\nReport saved: {out}")
        return len(rpt.hard_failures)

    counts = [r["n"] for r in daily]
    med    = statistics.median(counts)
    rpt.line(f"  Median daily rows: {med:,.0f}")

    if total_rows < 500_000 and n_days >= 7:
        rpt.warn(f"Total rows {total_rows:,} < 500K for {n_days}-day window (expected ~1M+)")

    rpt.line()
    rpt.line(f"  {'Day':<12} {'Rows':>10}  Status")
    rpt.line(f"  {'-'*40}")
    sparse_days = []
    for r in daily:
        if r["n"] < SPARSE_PCTILE * med:
            sparse_days.append(r["day"])
            rpt.line(f"  {r['day']:<12} {r['n']:>10,}  <-- SPARSE (< 20% of median)")
        else:
            rpt.line(f"  {r['day']:<12} {r['n']:>10,}")

    if sparse_days:
        rpt.warn(f"Sparse days (< 20% of median): {', '.join(sparse_days)}")
    else:
        rpt.ok("No sparse collection days")

    # ── Collector freshness ───────────────────────────────────────────────────
    # Hard failure if the collector has never run OK; warning if stale.
    # Note: FRESHNESS_MAX_HOURS (15 min) suits monitoring mode. During a
    # scheduled weekly refresh the collector may legitimately be between 5-min
    # cycles — adjust the threshold if this fires spuriously in your workflow.
    last_ok = conn.execute(
        "SELECT MAX(started) FROM collection_runs WHERE status = 'ok'"
    ).fetchone()[0]
    if last_ok is None:
        rpt.hfail("collection_runs has no successful runs — collector has never run OK")
    else:
        try:
            last_dt = datetime.fromisoformat(last_ok)
            age_hrs = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
            if age_hrs > FRESHNESS_MAX_HOURS:
                rpt.warn(
                    f"Last successful collection was {age_hrs:.1f}h ago "
                    f"(threshold {FRESHNESS_MAX_HOURS}h) — check collector"
                )
            else:
                rpt.ok(f"Collector last ran {age_hrs * 60:.0f} min ago")
        except Exception as exc:
            rpt.warn(f"Could not parse last collection timestamp: {exc}")

    # ── 2. Timestamp gap check ────────────────────────────────────────────────
    rpt.section("2. TIMESTAMP GAP CHECK  (flags Mac sleep / collector outages)")

    gap_rows = conn.execute(f"""
        SELECT day, MAX(gap_hrs) AS max_gap_hrs FROM (
            SELECT date(timestamp) AS day,
                   (julianday(LEAD(timestamp) OVER (
                       PARTITION BY date(timestamp) ORDER BY timestamp))
                    - julianday(timestamp)) * 24.0 AS gap_hrs
            FROM processed_stops {where}
        ) WHERE gap_hrs IS NOT NULL
        GROUP BY day ORDER BY day
    """).fetchall()

    for r in gap_rows:
        hrs = r["max_gap_hrs"] or 0.0
        if hrs > MAX_GAP_HOURS:
            rpt.warn(f"{r['day']}: max gap {hrs:.1f}h > 2h  (Mac sleep?)")
        else:
            rpt.ok(f"{r['day']}: max gap {hrs:.2f}h")

    # ── 3. Field integrity ────────────────────────────────────────────────────
    rpt.section("3. FIELD INTEGRITY")

    # Columns with strict 1% NULL threshold
    model_cols = [
        "delay_seconds", "shape_dist_traveled",
        "hour", "dow", "trip_id", "stop_id", "route_id",
    ]
    for col in model_cols:
        rate = conn.execute(f"""
            SELECT CAST(SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END) AS REAL)
                   / COUNT(*)
            FROM processed_stops {where}
        """).fetchone()[0] or 0.0
        if rate > NULL_RATE_WARN:
            rpt.warn(f"{col}: {100*rate:.2f}% NULL")
        else:
            rpt.ok(f"{col}: {100*rate:.3f}% NULL")

    # previous_stop_delay has a higher NULL threshold: the first stop of every
    # trip is structurally NULL (no LAG exists). Expected NULL rate is ~4–5%.
    # Only warn if it exceeds PREV_NULL_EXPECTED (7%), which would suggest
    # something beyond normal first-stop NULLs.
    prev_rate = conn.execute(f"""
        SELECT CAST(SUM(CASE WHEN previous_stop_delay IS NULL THEN 1 ELSE 0 END) AS REAL)
               / COUNT(*)
        FROM processed_stops {where}
    """).fetchone()[0] or 0.0
    if prev_rate > PREV_NULL_EXPECTED:
        rpt.warn(
            f"previous_stop_delay: {100*prev_rate:.2f}% NULL "
            f"(threshold {100*PREV_NULL_EXPECTED:.0f}%; first stops are expected NULL)"
        )
    else:
        rpt.ok(
            f"previous_stop_delay: {100*prev_rate:.2f}% NULL "
            f"(within expected range — first stops of each trip are structurally NULL)"
        )

    blank = conn.execute(f"""
        SELECT COUNT(*) FROM processed_stops
        WHERE route_id = '' {ts_and}
    """).fetchone()[0]
    if blank > 0:
        rpt.warn(f"Blank route_id: {blank:,} rows  (API quality drift?)")
    else:
        rpt.ok("No blank route_id rows")

    gtfs_null = conn.execute(f"""
        SELECT CAST(SUM(CASE WHEN shape_dist_traveled IS NULL THEN 1 ELSE 0 END) AS REAL)
               / COUNT(*)
        FROM processed_stops {where}
    """).fetchone()[0] or 0.0
    if gtfs_null > GTFS_FAIL_WARN:
        rpt.warn(f"GTFS join failure: {100*gtfs_null:.1f}% rows missing shape_dist_traveled "
                 f"(threshold 10%)")
    else:
        rpt.ok(f"GTFS join: {100*gtfs_null:.1f}% rows missing shape_dist_traveled")

    # ── 4. Delay distribution ─────────────────────────────────────────────────
    rpt.section("4. DELAY DISTRIBUTION")

    dist = conn.execute(f"""
        SELECT date(timestamp)                                                         AS day,
               AVG(delay_seconds)                                                      AS mean_d,
               MAX(ABS(delay_seconds))                                                 AS max_d,
               SUM(CASE WHEN ABS(delay_seconds) > {OUTLIER_SECONDS} THEN 1 ELSE 0 END) AS outliers,
               COUNT(*)                                                                AS n
        FROM processed_stops {where}
        GROUP BY day ORDER BY day
    """).fetchall()

    means = [r["mean_d"] for r in dist if r["mean_d"] is not None]
    if len(means) >= 2:
        med_mean = statistics.median(means)
        mad      = statistics.median([abs(m - med_mean) for m in means])
        # Scale MAD to be a consistent estimator of SD (factor 1.4826 holds for normal)
        mad_sd   = 1.4826 * mad if mad > 0 else max(statistics.stdev(means), 1.0)
    else:
        med_mean, mad_sd = 0.0, 1.0

    threshold = ANOMALY_MAD_K * mad_sd
    rpt.line(f"  Window median delay: {med_mean:.1f}s   MAD-equivalent SD: {mad_sd:.1f}s")
    rpt.line(f"  Anomaly threshold:   |mean − median| > {ANOMALY_MAD_K} × {mad_sd:.1f}s = ±{threshold:.1f}s")
    rpt.line()
    rpt.line(f"  {'Day':<12} {'Mean(s)':>8} {'Max|d|(s)':>10} {'Outliers':>10} {'Rows':>8}  Flag")
    rpt.line(f"  {'-'*72}")

    anomaly_days = []
    for r in dist:
        md   = r["mean_d"] or 0.0
        mxd  = r["max_d"]  or 0.0
        flag = ""
        if abs(md - med_mean) > threshold:
            flag = f"<-- ANOMALY (>{ANOMALY_MAD_K:.1f}×MAD)"
            anomaly_days.append(r["day"])
        rpt.line(f"  {r['day']:<12} {md:>8.1f} {mxd:>10.0f} {r['outliers']:>10,} {r['n']:>8,}  {flag}")

    total_out = sum(r["outliers"] for r in dist)
    rpt.line(f"\n  Total outliers (|delay| > 1hr):   {total_out:,}")
    if anomaly_days:
        rpt.warn(f"Anomalous mean-delay days: {', '.join(anomaly_days)}")
    else:
        rpt.ok("No anomalous days by mean delay")

    # ── 5. Route coverage ─────────────────────────────────────────────────────
    rpt.section("5. ROUTE COVERAGE")

    routes = conn.execute(f"""
        SELECT route_id,
               COUNT(*) AS n,
               AVG(CASE WHEN ABS(delay_seconds) <= {OUTLIER_SECONDS}
                        THEN delay_seconds END) AS mean_d
        FROM processed_stops {where}
        GROUP BY route_id
        ORDER BY n DESC
    """).fetchall()

    n_routes = len(routes)
    n_rich   = sum(1 for r in routes if r["n"] >= 500)
    rpt.line(f"  Total routes in window:          {n_routes}")
    rpt.line(f"  Routes with >= 500 rows (M3):    {n_rich}")

    odd = [r for r in routes
           if r["mean_d"] is not None and abs(r["mean_d"]) > 300]
    if odd:
        rpt.warn(
            "Routes with |mean filtered delay| > 300s: "
            + ", ".join(f"{r['route_id']} ({r['mean_d']:.0f}s)" for r in odd)
        )
    else:
        rpt.ok("No routes with |mean delay| > 300s after outlier filter")

    # ── 6. Stale predictions ──────────────────────────────────────────────────
    rpt.section("6. STALE PREDICTIONS  (actual_arrival < fetch timestamp)")
    # A prediction is stale if the predicted arrival time had already passed
    # when we fetched it.  These rows are included in stop_delays and survive
    # into processed_stops; they represent the RT feed still broadcasting
    # outdated stop times after the bus has passed.  A high rate may indicate
    # a feed quality problem or a vehicle that went off-route.

    total_sd = conn.execute(f"""
        SELECT COUNT(*) FROM stop_delays
        WHERE actual_arrival IS NOT NULL {ts_and}
    """).fetchone()[0]

    stale_n = conn.execute(f"""
        SELECT COUNT(*) FROM stop_delays
        WHERE actual_arrival IS NOT NULL
          AND actual_arrival < timestamp {ts_and}
    """).fetchone()[0]

    if total_sd == 0:
        rpt.warn("No stop_delays rows with actual_arrival — cannot check staleness")
    else:
        stale_pct = stale_n / total_sd
        msg = (f"{stale_n:,} / {total_sd:,} rows ({100*stale_pct:.2f}%) "
               f"where predicted arrival < fetch timestamp")
        if stale_pct > STALE_WARN_PCT:
            rpt.warn(f"Stale predictions: {msg}")
        else:
            rpt.ok(f"Stale predictions: {msg}")

    # ── 7. Stop-sequence integrity ────────────────────────────────────────────
    rpt.section("7. STOP-SEQUENCE INTEGRITY")
    # The LAG() window function in process_delays.py assumes stop_sequence is
    # strictly increasing within each (trip_id, service_date) partition.
    # Non-monotone sequences within a single service-day produce wrong
    # previous_stop_delay values silently.
    #
    # IMPORTANT: partition must include service_date — the same trip_id recurs
    # on multiple calendar dates (TransLink reuses IDs for recurring scheduled
    # trips), so pooling across dates produces apparent duplicates that are not
    # real data problems.  process_delays.py already uses (trip_id, service_date).

    seq_bad = conn.execute(f"""
        SELECT COUNT(DISTINCT trip_id) FROM (
            SELECT trip_id,
                   stop_sequence - LAG(stop_sequence) OVER (
                       PARTITION BY trip_id, service_date ORDER BY stop_sequence
                   ) AS seq_gap
            FROM stop_delays {where}
        ) WHERE seq_gap IS NOT NULL AND seq_gap <= 0
    """).fetchone()[0]

    trip_total = conn.execute(f"""
        SELECT COUNT(DISTINCT trip_id) FROM stop_delays {where}
    """).fetchone()[0]

    if seq_bad > 0:
        rpt.warn(
            f"{seq_bad:,} / {trip_total:,} trips have non-monotone stop_sequence "
            f"within a single service_date — previous_stop_delay may be incorrect "
            f"for these trips (note: cross-date trip_id reuse is excluded)"
        )
    else:
        rpt.ok(f"All {trip_total:,} trips have strictly increasing stop_sequence within each service_date")

    # ── Summary ───────────────────────────────────────────────────────────────
    rpt.section("SUMMARY")
    rpt.line(f"  Hard failures: {len(rpt.hard_failures)}")
    rpt.line(f"  Warnings:      {len(rpt.warnings)}")
    if rpt.hard_failures:
        rpt.line("\n  HARD FAILURES:")
        for f in rpt.hard_failures:
            rpt.line(f"    - {f}")
    if rpt.warnings:
        rpt.line("\n  WARNINGS:")
        for w in rpt.warnings:
            rpt.line(f"    - {w}")

    conn.close()

    out = EXPORT_DIR / f"quality_report_{today}.txt"
    rpt.save(out)
    rpt.line(f"\nReport saved: {out}")

    return len(rpt.hard_failures)


def main():
    parser = argparse.ArgumentParser(
        description="TransLink data quality checker — exits 1 on hard failures"
    )
    parser.add_argument("--since", help="ISO date lower bound, e.g. 2026-05-09")
    args    = parser.parse_args()
    n_fail  = run(since=args.since)
    if n_fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
