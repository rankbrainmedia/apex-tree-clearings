# Code: Apex Sentinel-2 forest-clearing pipeline (release v1.0)

This folder rebuilds every number in the release from public data. No API keys are needed.

## Setup

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

These are the versions the release was produced with. Newer versions will probably work, but they haven't been tested.

## Run

```bash
./run_all.sh                    # writes ./work (cache, ~600 MB) and ./out (products)
# or pick the folders yourself:
APEX_WORK=/scratch/apex APEX_OUT=./out ./run_all.sh
```

| Step | Script | What it does | Time |
|---|---|---|---|
| 1 | `01_stac_items.py` | Planetary Computer STAC query, saved to `work/items.json` (802 items) | <1 min |
| 2 | `02_baseline.py` | NAIP 2022 1 m canopy aggregated to the 10 m baseline forest (`out/baseline_forest_10m.tif`) | <1 min |
| 3 | `03_composites.py` | Cloud masking, then 18 quarterly median composites (663 scenes, 379 used). Resumable. | 10–20 min |
| 4 | `04_detect.py --write` | Per-quarter calibration and the persistent-drop rule | ~1 min |
| 5 | `05_events.py` | Event splitting, full-geometry GeoJSON, `clearings_by_quarter.csv`, validation (controls, NAIP 2020–22 overlap), chips | ~1 min |
| 6 | `06_release_files.py` | `clearings.geojson`, `clearings.csv`, `scenes.csv` | <1 min |
| 7 | `07_check.py` | Compares your run with `reference/clearings_v1.0.csv` and exits 1 on any mismatch | instant |
| 8 | `08_sample_panels.py` (optional) | NAIP and Sentinel-2 before/after panels for the 30-event sample | ~5 min |

Every threshold and setting is in `config.py`. Step 4 also takes options for the sensitivity runs:
`--t-ndvi 0.4`, `--t-nbr 0.75`, `--min-obs 3` and `--alt-baseline`. Add `--tag X` so they don't overwrite the main run.

## Inputs (`inputs/`)

| File | What | Where it came from |
|---|---|---|
| `canopy_2022_naip.tif` | 1 m canopy mask (1 canopy, 0 not, 255 no data), EPSG:32617 | Made by `upstream/canopy_update.py run --calibrate` on 2026-09-28 from NAIP 2022 (Planetary Computer). See METHODS §6. |
| `boundary.gpkg` | Apex Corporate Limits + ETJ, dissolved | Town of Apex ArcGIS `Corporate_Limits` and `ETJ` layers, fetched 2026-09-28 |
| `loss_2020_2022_naip.gpkg` | NAIP 2020→2022 loss polygons, ≥1 ac | Same upstream run. Used only for validation 10b. |
| `manual_identification_2026-10-27.csv` | Analyst's by-eye identification of the 22 events with no case match | Google Earth history, 2026-10-27. Used only by `10_manual_identification.py`, not in any total. |

SHA-256:
```
791c2a04ce7b173a9d7dbb55f4239ddd4b8709244b37f5dd6e53e89c7cada319  canopy_2022_naip.tif
7c16605e7a284d090e9df4dfb0725408f9934fa8add380ff0bf5c8a7fc1d4605  boundary.gpkg
e5b8f6512398d90c1ac485468af32f591100e3ba73d590ec197f6351cd6044e4  loss_2020_2022_naip.gpkg
977ea46cb5def39790f2cb7dc05942760f53a6840043f06d98c994ae111268db  manual_identification_2026-10-27.csv
```

The live Town boundary and NAIP services may change, so the exact inputs are bundled. `upstream/canopy_update.py` is
included so the canopy mask is documented. Re-running it takes 20–60 minutes and about 4 GB of NAIP reads.

## Reproducibility notes

- The STAC query has a fixed end date (2026-10-24), so new scenes don't change the result.
  If ESA or Microsoft reprocess archived scenes, the newest product per datatake is used, and a rerun could then differ slightly.
  `07_check.py` will report any such difference.
- `03_composites.py` stops if any scene fails to download, rather than quietly building a composite from fewer scenes. Re-run it to resume.
- The parcel and case join (`../case_join.csv`) came from live Wake County and Town of Apex layers on 2026-10-27.
  It isn't part of this pipeline. The owner-name redaction rule is in METHODS §11.
- `09_chatham_parcels.py` (v1.1) fills the Chatham County parcel columns for events with no Wake parcel and writes
  `case_join.csv` plus `case_join.xlsx` (PINs as text; needs `openpyxl`). Usage:
  `python 09_chatham_parcels.py <case_join.csv> <clearings.geojson> <out dir>`. It queries Chatham's live layer.
- `10_manual_identification.py` (v1.1) adds the `manual_identification` column from `inputs/manual_identification_2026-10-27.csv`
  and rewrites both files: `python 10_manual_identification.py <case_join.csv> <out dir>`.
