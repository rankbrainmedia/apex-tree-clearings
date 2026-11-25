# Verification set (built 2026-11-24)

Everything this folder writes goes into `../out_verify/`. Nothing else is touched.

| Step | Script | What it does |
|---|---|---|
| 1 | `build_sets.py` | Cuts the 2017-2026 detection into clearings, draws the stratified random sample of 100 (seed in `sample_draw.json`), writes `items.csv`, `outlines.geojson`, `sample_frame.csv` and the blank `verify_log.csv`. Re-running reproduces the same draw. It will not overwrite a log that has entries. |
| 2 | `render.py` | One PNG per clearing: `release/C001.png` ... and `sample/D0106.png` ... Skips images already made; `--redo` remakes them; `--only C001,D0106` does a few. |
| 3 | `make_index.py` | `index.html` (front page), `review.html` (the reviewer: 10 per page, verdict buttons, share slider, notes, export), the three `*/index.html` files that open it on each set, `image_dates.csv`. It reads `verify_log.csv` for its row order and never writes it. |
| 4 | `verify_report.py` | After the log is filled in: share confirmed, acres-weighted share, 95% interval, by year and size. Writes `verify_report.txt` and `verify_report_groups.csv`. |
| 5 | `parcels_check.py` | Current county parcels under each sample and large-set outline: which clearings sit on a single residential parcel. Writes `single_parcel_check.csv` (no private owner names). |

Run each with `../apex-canopy/df-venv/bin/python <script>`.

## The optional large set

`out_verify/large/` holds the 37 clearings over 10 acres that the random draw did not pick, with their own log,
`verify_log_large_optional.csv`. Clearings over 10 acres are 49 of the 497 in the 2017-2026 detection but 44% of its
acres, and the draw takes one from most of their strata. An independent check of the report's maths found that the
acres-weighted interval can be too narrow when the failures sit in those few large clearings (real coverage near 80%
in a simulation on this frame). Reviewing all of them makes that size class a full count. It is optional: leave the
file blank and the report runs on the 100.

## Things to know

- **The latest NAIP flight over Apex is July 25, 2025 (30 cm).** It is in Planetary Computer's public storage but not yet
  in its search catalogue, which is why the first build of this set missed it and said NAIP stopped in 2022; the Wake
  County run (`entitlement/wake_tca.py`) found it. `render.py` lists its tiles from the storage itself. Every clearing
  first detected before July 2025 now has a NAIP "after"; for those first detected from October 2025 on, the 2025
  flight is the "before". A 2024 flight exists in the storage as metadata only.
- For clearings first detected from July 2025 on, the only "after" image is Sentinel-2 at 10 m.
- The State's aerial photo (NC OneMap, flown 2025-02-14, leaves off) is kept as an extra panel. It is not NAIP.
- Older sampled clearings get an extra panel, "NAIP first after": the first flight after the detection, which shows the
  ground nearer the time than the 2025 flight does.
- Sample ids (D0001...) are numbered by size across the whole 2017-2026 detection (497 clearings, 2,291.8 acres). They
  are not release ids. 47 of the 100 sampled clearings overlap a release clearing; `items.csv` says which.
- A sampled clearing that has since regrown or been built on is still a clearing: judge it on the before and after
  NAIP pair, not on what stands there now. `regrown_share` in `items.csv` is the share of its cells that look like
  forest again in 2026.
- The PNGs are about 560 MB in all and are ignored by git (`out_verify/**/*.png`). The CSV, JSON and HTML files are small.
- The NAIP and State photo frames as fetched are kept in `apex-canopy/verify_cache/`, so `render.py --redo` does not download them again.
- Both Sentinel-2 panels use one fixed stretch (reflectance / 0.32, gamma 2.2), chosen so bare ground keeps its detail.

## Reviewing in the browser

Open `out_verify/index.html`, then a set. Everything is reviewed in one file, `review.html`, because the verdicts are saved
in the browser's storage for that file and some browsers keep a separate store per local file. Keys: 1 cleared, 2 partly,
3 not cleared, 4 can't tell, 0 clear, [ and ] move the share by 5 points, j or Enter next, k previous, n notes, u first
unreviewed, arrows turn the page, ? shows the list. The reviewer name is asked once.

The browser store is a working copy, not the record. "Export to verify_log.csv" writes every row in the blank log's order
and format (shares as percents with a % sign); save it over `out_verify/verify_log.csv` and run `verify_report.py`.
"Load a saved log" reads an export back in. Tested 2026-11-24 in Chromium: name prompt, keys, slider, notes with commas
and quotes, page turn at the end of a page, export, reload from the export, and `verify_report.py` on the exported file.
