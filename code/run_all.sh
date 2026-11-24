#!/usr/bin/env bash
# End-to-end run of the Apex Sentinel-2 clearing pipeline, release v1.0.
# Usage:  ./run_all.sh            (uses ./work and ./out, or $APEX_WORK / $APEX_OUT)
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python}"

"$PY" 01_stac_items.py            # STAC query -> work/items.json (802 items for v1.0)
"$PY" 02_baseline.py              # NAIP 2022 canopy -> 10 m baseline forest
"$PY" 03_composites.py            # 18 quarterly composites (downloads; ~10-20 min)
"$PY" 04_detect.py --write        # calibration + persistent-drop detection
"$PY" 05_events.py                # events, full-geometry GeoJSON, quarterly CSV, validation, chips
"$PY" 06_release_files.py         # clearings.geojson/.csv (simplified) + scenes.csv
"$PY" 07_check.py                 # compares the run with the published v1.0 numbers
