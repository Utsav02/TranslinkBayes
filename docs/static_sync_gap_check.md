# Static-Sync Gap Check — the June 6 question, settled

**Question:** did realtime→static joins lose or corrupt rows while
`gtfs_static.db` was frozen (2026-06-06 → fix)?

**Answer: No rows were corrupted, and no processed rows were lost.** The freeze
was real — and actually longer than believed (it started 2026-05-30, not
06-06) — but a combination of schedule timing and an unrelated pipeline
failure meant the frozen DB was never the *wrong* schedule for any row that
got processed. The only real consequence is that `processed_stops` is stale
(ends at service_date 2026-06-07). Evidence below; all checks run read-only on
2026-06-12.

---

## 1. Reconstructed timeline (from `logs/sync_static_gtfs.log`, snapshot dirs, calendars)

| When | Event | DB content after |
|---|---|---|
| 2026-05-23 | Downloaded May-22-published schedule (8,952 stops); loaded into DB | **May-22 schedule** |
| 2026-05-30 10:00 | Downloaded May-29 schedule (8,955 stops) → `process_static.py` integrity floor (`stops ≥ 10,000`) **rejected it** | May-22 schedule (frozen) |
| 2026-06-06 10:00 | Downloaded Jun-5 schedule (8,919 stops) → **rejected again** by the same floor | May-22 schedule (frozen) |
| 2026-06-07 22:12 | `process_delays.py --since 2026-05-09` — last rebuild of `processed_stops`, joined against the May-22 schedule | — |
| 2026-06-08 | Daily refresh **failed for an unrelated reason** (missing venv in the cloud-session mount, `exports/daily_error.txt`) — no processing happened during the at-risk window | — |
| 2026-06-11 00:03 | Floor recalibrated 10,000 → 8,000; Jun-5 schedule loaded (8,919 stops / 134,677 trips / 3,730,279 stop_times) | **Jun-5 schedule (current)** |

Note the floor blocked **two** consecutive legitimate updates; the feed
genuinely carries ~8.9K stops. The "June 6 failure" was the second failure,
not the first.

## 2. Why the freeze did no damage: the schedule boundary was 2026-06-08

The GTFS calendars make the service periods explicit:

- May-22 schedule (`data/static/2026-05-23/calendar.txt`): service IDs valid
  **2026-04-20 → 2026-06-07**.
- Jun-5 schedule (`data/static/2026-06-11/calendar.txt`): new service period
  **2026-06-08 → 2026-09-06** (TransLink summer signup).

So for every service date up to and including 2026-06-07, the frozen May-22
schedule was the *operationally correct* join target. The new schedule only
started describing reality on Jun 8 — and nothing was processed between Jun 8
and the Jun 11 fix (the Jun-8 refresh failure was accidentally protective).

## 3. Join match-rates, measured

### 3a. As stored in `processed_stops` (joined vs frozen May-22 schedule on Jun 7)

`% NULL shape_dist_traveled` per service date — the freeze window shows **no
degradation** relative to the pre-freeze baseline:

| Service date | Rows | % NULL shape_dist | % NULL direction_id |
|---|---|---|---|
| 05-30 | 404,295 | 6.52% | 0.00% |
| 05-31 | 450,180 | 6.54% | 0.00% |
| 06-03 | 519,842 | 7.35% | 0.00% |
| 06-04 | 127,789 | 8.23% | 0.00% |
| 06-05 | 553,658 | 5.77% | 0.00% |
| **06-06** | 500,108 | **5.83%** | 0.00% |
| **06-07** | 373,800 | **5.86%** | 0.00% |

(Pre-dense days 05-23 → 05-29 run 15–27% NULL, but that is the sparse-capture
era artifact — few stop-updates per trip, more orphan fragments — not the
freeze.)

### 3b. Fresh join vs the CURRENT (Jun-5) schedule, per service date

`% of stop_delays rows matching stop_times (trip_id, stop_id, stop_sequence)`:

| Service date | stop_times match | trips match |
|---|---|---|
| 05-30 … 06-07 | 81.6 – 88.4% | 100.00% |
| **06-08** | **99.87%** | 100.00% |
| 06-09 … 06-12 | 100.00% | 100.00% |

Two conclusions: (i) the new schedule fits Jun-8+ data essentially perfectly,
confirming the boundary; (ii) the new schedule is the *wrong* join target for
pre-Jun-8 dates — reprocessing old dates against it would **raise** their
shape_dist NULL rate from ~6.5% to ~15%.

### 3c. No silent drift where both schedules match

For 2026-05-31 (365,526 rows matching both schedules): per-trip-normalized
`shape_dist_traveled` from the old vs new schedule differs by **mean 0.3m;
zero rows differ by > 50m**. `trips` join (direction_id) is 100% under both.
trip_id/stop_id numbering did not shift between schedules.

## 4. Affected date range — and the required action

- **Corrupted rows: none.** Nothing was ever joined against a schedule that
  wasn't in effect for its service date.
- **Stale/missing rows: service dates 2026-06-08 → present** (~1.6M rows in
  `stop_delays`) are absent from `processed_stops` entirely.

**Action (incremental, not full rebuild):**

```bash
venv/bin/python3 pipeline/process_delays.py --since 2026-06-08
```

This processes only the new-schedule dates against the now-correct static DB,
and leaves the pre-Jun-8 rows on their correct old-schedule joins. A full
rebuild (`--since 2026-05-09`) would silently degrade pre-Jun-8 joins (§3b)
— avoid it unless the old-schedule snapshot is reloaded first.

**Watch item:** the weekly sync runs Saturdays 10:00; the next schedule
publication will again be guarded by the (recalibrated) floor. If TransLink's
stop count drifts below 8,000 the same freeze recurs — the floor is a
deliberate tripwire, that's fine, but `quality_report.py` has no check that
`gtfs_static_meta.json`'s schedule vintage matches the service dates being
processed. Adding a "static DB older than the active service period" warning
would catch the *dangerous* version of this failure (a freeze that spans a
service-period boundary while processing keeps running — exactly what almost
happened here).
