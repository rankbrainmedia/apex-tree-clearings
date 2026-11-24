# Apex, NC: new forest clearings ≥1 acre from Sentinel-2, release v1.1

**Data through 2026-10-24.** Gross clearing of the 2022 baseline forest, 2022Q4 to Oct 2026, inside Apex Corporate Limits + ETJ.

**238 clearing events, 929.2 ac** (880.7 ac confirmed, 48.5 ac provisional).
By first-detection year: 2022Q4 10.9 · 2023 257.4 · 2024 152.2 · 2025 346.1 · 2026 to date 162.8 ac.
This is not a net canopy change figure. The full method is in **METHODS.md**.

| File | Contents |
|---|---|
| `METHODS.md` | Every step, threshold and composite rule, plus the baseline definition, validation, cleared-fraction method, limitations and software versions |
| `clearings.geojson` | 238 event polygons, EPSG:4326, pixel-edge geometry (0.77 MB) |
| `clearings.csv` | The same attributes: `id`, `acres`, `first_quarter`, `status` (confirmed/provisional), `confirmed_px_share`, `pixels_10m`, `patch_id`, `centroid_lon`, `centroid_lat` |
| `clearings_by_quarter.csv` | Events, acres, coverage, scenes used and provisional acres per quarter |
| `scenes.csv` | All 663 unique Sentinel-2 scenes in the window, with `used_in_composite` (379 yes, 284 skipped by the cloud rule) and the superseded reprocessing IDs |
| `case_join.csv` | Each clearing matched to Wake parcels (or Chatham parcels where Wake has none; see `parcel_county`) and to Apex rezoning, development and residential-phase cases. Private individuals' names and PINs are withheld. PINs keep their leading zeros, but Excel/Numbers strip them on open, so use the .xlsx or import the PIN column as Text. |
| `case_join.xlsx` | The same table, with PINs stored as text |
| `baseline_forest_10m.tif` | 10 m baseline forest mask (1 forest, 0 not, 255 outside the study area) |
| `validation_summary.json`, `validation_chips/` | Control parks, the NAIP 2020–22 overlap check, and the five largest events |
| `sample30/` | 30-event random sample: tags, cleared fractions, and NAIP/Sentinel-2 before/after images |
| `fia/` | FIA EVALIDator query parameters and raw API output (Wake County context) |
| `code/` | End-to-end pipeline with README, pinned requirements and bundled inputs |

`case_join` also has `manual_identification`: what the 22 events with no case match turned out to be, identified by eye from Google Earth history on 27 Oct 2026. It is context only and isn't used in any total (METHODS §11).

**Credits:** Contains modified Copernicus Sentinel data 2022–2026 (ESA), via Microsoft Planetary Computer.
USDA NAIP. Wake County and Chatham County parcels. Town of Apex boundary and case layers. USDA Forest Service FIA.
