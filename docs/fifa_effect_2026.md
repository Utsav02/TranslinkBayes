# FIFA World Cup 2026 — Bus Delay Effect at BC Place Match Days

A descriptive analysis. **Not a model.** Uses raw `stop_delays` observations
during the 2026-06-08 → 2026-07-19 FIFA service window in Vancouver, with a
day-of-week-and-hour-matched control design to isolate the incremental delay
premium attributable to each specific match. The v2 cloud model
([`fit_candidate_C_fifa.R`](../analysis/fit_candidate_C_fifa.R)) tests whether
these empirical numbers can be recovered as a coefficient with a tight
credible interval; this document reports what the raw data says without any
modelling.

---

## Setting

Vancouver's BC Place stadium hosted **7 FIFA World Cup 2026 matches** between
2026-06-13 and 2026-07-07. TransLink pre-announced a service regime spanning
2026-06-08 → 2026-07-19 with:

- **Route 130 detoured** via McGill / Renfrew / East Hastings (avoiding BC
  Place area during game-window road closures)
- **Extra service on routes 14, 19, 23, 28, 222** to absorb match-day
  ridership pulse

These 6 routes (short names 014, 019, 023, 028, 130, 222 — TransLink internal
IDs 16718, 6624, 30055, 6630, 6651, 39305) are the ones this analysis calls
"FIFA-affected". Every other route is the network baseline.

The 7 matches, in order (kickoff Pacific time):

| Date | dow | Match | Kickoff PT | Complete capture? |
|---|---|---|---|---|
| 2026-06-13 | Sat | Australia v Türkiye | 21:00 | ✓ (141 collector runs) |
| 2026-06-18 | Thu | Canada v Qatar | 15:00 | ✗ collector outage — pre-match rows only |
| 2026-06-21 | Sun | New Zealand v Egypt | 18:00 | ✓ |
| 2026-06-24 | Wed | Switzerland v Canada | 12:00 | ✓ |
| 2026-06-26 | Fri | New Zealand v Belgium | 20:00 | ✓ |
| 2026-07-02 | Thu | Round of 32 | 20:00 | ✓ |
| 2026-07-07 | Tue | Round of 16 | 13:00 | ✓ |

The Jun 18 outage is documented in [`data_gaps.md`](data_gaps.md); the
Canada-Qatar match window is not analysable. The 6 remaining match days are
the analytical set below.

---

## Design

For each of the 6 fully-captured match days, define a **kickoff window** of
kickoff hour −1 through kickoff hour +3 (5 hours total, chosen from prior
descriptive exploration to capture pre-match buildup + post-match dispersal).
Compare mean delay and late-arrival rate in that window against the mean over
the **same set of hours on same-day-of-week non-match days within the FIFA
service window**. Restricted to affected routes.

The dow-hour matching is what distinguishes this from a naïve match-vs-non-
match comparison. Without it:

- Match days sit disproportionately on weekdays (5 of 6 captured), so a match-
  vs-non-match average confounds match effect with weekday-vs-weekend effect.
- Match windows sit disproportionately in afternoon/evening rush hours, so a
  match-vs-non-match average confounds match effect with rush-hour effect.

The pairing controls for both simultaneously — for each match day we compare
its kickoff window against the *same* clock hours on non-match days of *the
same dow*. Any residual delta after that is a match-day effect.

Filters throughout: `abs(delay_seconds) ≤ 3600`, `delay_seconds IS NOT NULL`,
`actual_arrival_pacific IS NOT NULL`, `route_id IN (affected)`. Data source
is `stop_delays` directly — no `processed_stops` joins (they had known
boundary-date silent losses fixed in July, but simpler to query the raw table
which never lost rows).

---

## Result

Six paired comparisons, one per match day:

| Match | dow | Kickoff | Window (hrs) | Match window n | Match mean | Ctrl mean | **Δ mean** | Match late-5m | Ctrl late-5m | **Δ late-5m** | Control dates |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-06-13 | Sat | 21:00 | 20–23 | 5,263 | 289.4 s | 188.0 s | **+101.3 s** | 27.4% | 19.1% | **+8.3 pp** | Jun 27, Jul 4 |
| 2026-06-21 | Sun | 18:00 | 17–21 | 8,408 | 416.7 s | 143.6 s | **+273.2 s** | 41.7% | 20.1% | **+21.6 pp** | Jun 14, 28, Jul 5 |
| 2026-06-24 | Wed | 12:00 | 11–15 | 9,990 | 241.3 s | 112.7 s | **+128.7 s** | 28.7% | 14.7% | **+14.0 pp** | Jun 10, 17, Jul 1, 8 |
| 2026-06-26 | Fri | 20:00 | 19–23 | 7,714 | 416.9 s | 141.3 s | **+275.6 s** | 37.2% | 18.0% | **+19.2 pp** | Jun 12, Jul 3 |
| 2026-07-02 | Thu | 20:00 | 19–23 | 7,693 | 402.7 s | 219.5 s | **+183.1 s** | 34.5% | 23.2% | **+11.3 pp** | Jun 11, 25 |
| 2026-07-07 | Tue | 13:00 | 12–16 | 10,091 | 193.9 s | 106.6 s | **+87.4 s** | 24.2% | 16.0% | **+8.2 pp** | Jun 9, 16, 23, 30 |
| **Mean across matches** | | | | | | | **~+175 s** | | | **~+14 pp** | |

Every single match day shows a positive mean-delay premium during its
kickoff window on affected routes. The lightest premium (Jul 7 R16, +87 s)
is on a Tuesday early-afternoon kickoff; the heaviest (Jun 26 Fri evening,
+276 s) is on a Friday-evening kickoff overlapping rush hour. The pattern
is consistent with a match-generated demand shock that compounds when it
coincides with existing rush-hour capacity strain — an interaction the
model will attempt to recover.

## What the effect is *not*

Prior exploratory analyses in this project overstated the match-day effect
in two ways, both worth being explicit about here:

1. **The naïve "match vs. non-match FIFA-window" bucket average is not the
   right comparison.** A first pass showed **+94 s** on that basis, which is
   biased by the day-of-week composition of the match set and the hours it
   captures. Dow-hour matching (above) is the honest number.

2. **`processed_stops` had silent boundary-date row losses** for Jun 13 (24%
   preserved), Jun 25 (0.03% preserved) and Jul 8 (72.3%) before those were
   fixed in July. A second pass using `processed_stops` showed a *smaller*
   effect than raw `stop_delays` — that was the data-integrity artifact, not
   a real reversal. Every number in the table above uses raw `stop_delays`.

## What the effect is not measuring

Two important caveats a reader should carry into any downstream use of these
numbers:

1. **`delay_seconds` in `stop_delays` is TransLink's own predicted delay
   from the GTFS-realtime trip-updates feed**, not an observation. It is
   updated with each 5-minute fetch and upserted (only the last snapshot per
   trip-stop-date is preserved in the primary table; the full trajectory
   lives in `stop_delays_snapshots` since 2026-06-12). Therefore what this
   analysis measures is a match-day *broadcast* delay premium — the difference
   between what TransLink's operations system reported to riders on match days
   vs. matched-comparison days. It correlates with, but is not identical to,
   physically observed delay.

2. The affected-route roster is TransLink's pre-announced FIFA service list,
   not an outcome-derived selection. Routes not on that list (e.g. SkyTrain
   feeder routes serving stations near BC Place) may have absorbed some
   match-day demand too; those are the "other routes" network baseline and
   showed a small but consistent premium as well (+13 to +42 s across
   kickoff hours), not reported in detail here.

## Reproducibility

All figures above were computed by direct SQL against
`database/gtfs_realtime_v2.db` on 2026-07-08. Query outline (per match day):

```sql
-- match window
SELECT AVG(delay_seconds), SUM(delay_seconds > 300) * 1.0 / COUNT(*)
FROM stop_delays
WHERE service_date = <match_date>
  AND route_id IN (<affected>)
  AND CAST(strftime('%H', actual_arrival_pacific) AS INT) IN (<kickoff-1..kickoff+3>)
  AND ABS(delay_seconds) <= 3600 AND delay_seconds IS NOT NULL
  AND actual_arrival_pacific IS NOT NULL;

-- same-dow control (aggregated over the qualifying non-match dates)
SELECT AVG(delay_seconds), SUM(delay_seconds > 300) * 1.0 / COUNT(*)
FROM stop_delays
WHERE service_date IN (<same-dow-nonmatch-FIFA-window-dates>)
  AND route_id IN (<affected>)
  AND CAST(strftime('%H', actual_arrival_pacific) AS INT) IN (<same kickoff window>)
  AND ABS(delay_seconds) <= 3600 AND delay_seconds IS NOT NULL
  AND actual_arrival_pacific IS NOT NULL;
```

Complete same-dow control dates per match, as listed in the table above,
were the FIFA-window (Jun 8 → Jul 19) dates matching the match day's
day-of-week, minus the match dates themselves and minus the Jun 19–20
outage days.

## Modelling handoff

The pre-registered candidate [`C_fifa`](../analysis/fit_candidate_C_fifa.R)
adds the interaction

```
+ is_match_day + is_affected_route
+ is_match_day : is_affected_route
+ s(hour_from_kickoff,
    by = interaction(is_match_day, is_affected_route),
    bs = "cs", k = 6)
```

to the C_m2nu4 base and fits it against the frozen loop split. The primary
finding it will report is:
1. The main-effect `is_match_day:is_affected_route` coefficient and 95% CrI.
   This should approximate the ~+175 s across-match average above.
2. The smooth's implied per-hour premium for match-affected slices, which
   should approximate the per-match rows above when integrated over the
   kickoff windows.
3. Held-out ELPD against C_m2nu4. Not expected to shift RMSE much (the
   affected slice is a small fraction of the test set), but the coefficient
   and CrI are the deliverable.

A failure mode to watch for: if the C0_notrip_99 reference-tension resolver
lands as the new reference (in progress on this laptop as of 2026-07-10),
this analysis is unaffected — the empirical baseline is model-independent —
but the C_fifa comparison will be against a different reference and the
ΔELPD numbers will not be directly comparable to a version fit against
C_m2nu4.
