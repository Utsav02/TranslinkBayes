#!/bin/bash
# Refresh processed data and exports for analysis.
# Run this weekly before re-rendering the Rmd files.
#
# Usage:
#   bash pipeline/refresh_analysis.sh
#   bash pipeline/refresh_analysis.sh --rerender   # also re-renders the Rmds

set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/venv/bin/python3"
QUALITY_START="2026-05-09"   # first day of dense, reliable collection
EXPORT_START="2026-05-23"    # clean collection window (May 19-22 dead zone excluded)

echo "=== Clearing processed_stops ==="
"$PY" -c "
import sqlite3
conn = sqlite3.connect('$ROOT/database/gtfs_realtime_v2.db')
conn.execute('DELETE FROM processed_stops')
conn.commit()
print('Cleared.')
conn.close()
"

echo ""
echo "=== Processing delays from $QUALITY_START ==="
"$PY" "$ROOT/pipeline/process_delays.py" --since "$QUALITY_START"

echo ""
echo "=== Data quality check ==="
"$PY" "$ROOT/pipeline/quality_report.py" --since "$QUALITY_START"
# quality_report.py exits 1 on hard failures; set -e above halts the refresh

echo ""
echo "=== Exporting route 6641 ==="
"$PY" "$ROOT/pipeline/export_route.py" --route 6641 --direction 0 --since "$EXPORT_START"

echo ""
echo "=== Exporting all routes ==="
"$PY" "$ROOT/pipeline/export_route.py" --route all --since "$EXPORT_START"

echo ""
echo "=== Clearing knitr caches ==="
rm -rf "$ROOT/analysis/brms_analysis_cache"
rm -rf "$ROOT/analysis/multi_route_analysis_cache"

echo ""
echo "=== Done. Both Rmds auto-discover the latest parquet — no filename patching needed ==="
echo ""
echo "To re-render:"
echo "  cd $ROOT/analysis"
echo "  Rscript -e \"rmarkdown::render('multi_route_analysis.Rmd')\""
echo "  Rscript -e \"rmarkdown::render('brms_analysis.Rmd')\""

if [[ "$1" == "--rerender" ]]; then
  echo ""
  echo "=== Rendering Rmds ==="
  cd "$ROOT/analysis"
  Rscript -e "rmarkdown::render('multi_route_analysis.Rmd')"
  Rscript -e "rmarkdown::render('brms_analysis.Rmd')"
  echo ""
  echo "=== Run log ==="
  echo "run_log.csv updated by run_tracker chunks inside each Rmd."
  [ -f "$ROOT/exports/run_log.csv" ] && tail -2 "$ROOT/exports/run_log.csv" || echo "(no run_log.csv yet)"
fi
