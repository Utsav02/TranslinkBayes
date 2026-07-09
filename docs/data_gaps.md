# Data Gaps and Known Outages

Living document of collector outages, data losses, and known-partial windows
that any downstream consumer (v2 split, cloud loop, FIFA analysis, retrospective
reports) must treat as first-class caveats. Adding a row here is mandatory
whenever the collector goes down, static-sync fails, or a service-date is
processed with less than 90% of its raw-stop_delays row count preserved.

Companion documents: [`data_validation_2026-06-12.md`](data_validation_2026-06-12.md)
for the original validation baseline, [`static_sync_gap_check.md`](static_sync_gap_check.md)
for the June-6 static-schedule integrity question.

---

## Outage — 2026-06-17 19:37 PDT → 2026-06-21 09:00 PDT (~85 h)

**Cause.** macOS `launchd` under Sonoma+ requires Full Disk Access to read files
under `~/Desktop/`. A silent TCC (Transparency, Consent, Control) reset
revoked the venv's Python interpreter grant sometime around 2026-06-17. Every
subsequent 5-minute launchd fire failed with
`OSError: [Errno 11] Resource deadlock avoided` inside `python-dotenv`'s
`.env` read (the file lives under `~/Desktop/` and the launchd-context process
could not access it). `collect_realtime_v2.py` errored before it could
write a `collection_runs` row, so the failure was silent for ~3 days. Sync of
the static schedule (`sync_static_gtfs.py`) failed the same way.

`stop_delays` last successful run: 2026-06-18 02:37 UTC (= 2026-06-17 19:37 PDT).
Restart: manual TCC grant to `python3.12` + Terminal + iCloud "Keep Downloaded"
on the project folder (venv `.py` files had also been partially evicted from
local storage by iCloud Optimize).

**Rows lost.**

| Date | `stop_delays` rows captured | Expected (~) | Notes |
|---|---|---|---|
| 2026-06-17 | 625,667 | ~625K | complete before outage |
| 2026-06-18 | **24,518** | ~600K | 24K captured in the early UTC hours before the 02:37 UTC crash. Includes **FIFA Canada vs Qatar** match day; the match itself (15:00 PT kickoff) was NOT captured. |
| **2026-06-19** | **0** | ~600K | ENTIRELY LOST |
| **2026-06-20** | **0** | ~600K | ENTIRELY LOST |
| 2026-06-21 | 377,000 | ~500K | captured from 09:00 PDT recovery onward. Includes **FIFA NZ vs Egypt** match (18:00 PT kickoff — captured). |

Snapshot table (`stop_delays_snapshots`) has the identical outage window (same
script). Nothing else on the pipeline was affected.

**Recoverability.** None. Post-outage searches (2026-07-08) of:
- Transitland (`f-r7h-translink` feed): only versioned static GTFS is archived; no realtime trip-updates history.
- `carsonyl/translink-derived-datasets` (GitHub): static-derived only.
- General web: no independent archive of TransLink Vancouver's live trip-updates feed.

Search + confirmation logged in the 2026-07-09 session transcript. The
GTFS-realtime trip-updates feed is ephemeral by design; nothing recovers the
Jun 19–20 window.

**Impact on downstream analyses.**

- **FIFA match-day analysis**: 1 of 7 Vancouver match days lost (Canada v Qatar,
  Jun 18). The remaining 6 (Jun 13, 21, 24, 26, Jul 2, 7) captured cleanly.
- **v2 loop split**: exclude `2026-06-18`, `2026-06-19`, `2026-06-20` from both
  TRAIN and TEST. All three are gaps, not zeros — do NOT let a naïve
  `service_date >= X AND service_date <= Y` filter treat them as valid empty
  days.
- **Snapshot-trajectory analysis**: unaffected outside this window (snapshots
  continued growing normally from 06-22 through 07-08 at ~5.3 snaps/key).
- **Data-quality baseline (dow balance)**: the outage removes 1 Thu, 1 Fri,
  1 Sat, 1 Sun. dow imbalance for the pre-Jun-22 window widens accordingly.

**Prevention going forward.** The root cause (project living under `~/Desktop/`)
is unresolved. Two mitigations in place today:
1. `python3.12` and Terminal have Full Disk Access explicitly granted (System
   Settings → Privacy & Security → Full Disk Access, both toggles ON).
2. iCloud "Keep Downloaded" applied to the project folder — venv `.py` files
   stay local.

A durable fix is to move the project OUT of `~/Desktop/` (e.g. `~/TranslinkBayes/`).
Planned for after FIFA analysis wraps.

---

## Silent-loss episode — `processed_stops` boundary dates (fixed 2026-07-08)

`process_delays.py --since X` writes only what exists in `stop_delays` at run
time. Two dates were left partial by the historical `--since` sequence and
never refreshed:

| Date | `stop_delays` (raw) | `processed_stops` **before fix** | after fix |
|---|---|---|---|
| 2026-06-13 | 443,232 | 108,202 (24.4%) | 443,232 (100%) |
| 2026-06-25 | 636,304 | 203 (0.03%) | 636,304 (100%) |

Both reprocessed via scoped `--since D --until D+1` on 2026-07-08. Adjacent
dates untouched. Now-current audit table:

- 2026-06-07: raw 396K, processed 374K (94.3%) — left as-is; joined against
  the pre-Jun-8 static schedule which has since rolled out of `gtfs_static.db`.
  Reprocessing against current static would DESTROY the valid shape_dist
  joins on the 374K rows already there (0 of 15,146 Jun 7 trip_ids match
  the current summer-signup schedule).
- 2026-06-24: raw 637K, processed 632K (99.2%) — de minimis, skipped.
- 2026-07-08: partial by definition (today, in progress at re-audit time).

**Prevention**. A `--refresh-boundary` flag on `process_delays.py` (or a
default-safe reprocess of `service_date = MAX(service_date)` on every run)
would close this. Not implemented yet.

---

## Static-schedule rollover — 2026-05-30 → 2026-06-11

Covered in depth in [`static_sync_gap_check.md`](static_sync_gap_check.md).
Summary: `gtfs_static.db` was frozen on the May-22 schedule from 2026-05-30
through 2026-06-11 (a `stops`-count floor of 10,000 was blocking the
legitimate ~8,900-stop schedule). No processed rows were corrupted because
the schedule boundary was 2026-06-08 and the frozen May-22 schedule remained
the operationally-correct join target for service_dates ≤ 06-07. From 06-08
onward, the summer-signup schedule became active, and its full contents
loaded on the 2026-06-11 fix.

The pre-Jun-8 schedule has since rolled entirely out of `gtfs_static.db`
(`trips` dropped from ~134k to ~73k). Reprocessing any service_date ≤ 06-07
against the current static WOULD produce silent join loss. Do not
`process_delays.py --since 2026-05-09` — always scope to post-06-08 windows.

Archives of the pre-Jun-8 static live at `data/static_archive/GTFS_2026-06-06`;
a temporary swap could restore reprocess capability if ever needed.
