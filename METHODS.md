# Methods: new forest clearings ≥1 acre in Apex, NC, from Sentinel-2

**Release v1.1** · data through **2026-10-24** · analysis run 2026-10-27

v1.1 (2026-10-27) changes only the parcel join and the validation notes. The 238 events, acres and quarters are the same as v1.0:
- Chatham County parcels were joined for the events Wake parcels don't cover (§11).
- `case_join.xlsx` was added, with PINs stored as text (§11).
- A `manual_identification` column was added for the 22 events with no case match (§11). It isn't used in any total.
- The C005 description in §10c was corrected.

## What this measures, and what it doesn't

This study counts **gross new clearings of 2022 baseline forest**, in contiguous patches of at least 1 acre, from the
2022Q3 baseline through 24 Oct 2026. It does **not** measure net canopy change (regrowth, planting and infill are not
counted against the losses), tree counts, or land use. It finds where a dense green forest signal dropped and stayed
down; it doesn't say why.

**Headline:** 238 clearing events, **929.2 ac** total. 880.7 ac are confirmed and 48.5 ac are provisional.
By first-detection year: 2022Q4 10.9 · 2023 257.4 · 2024 152.2 · 2025 346.1 · 2026 to date 162.8 ac.

---

## 1. Study area

- The Town of Apex Corporate Limits plus ETJ, from the Town's ArcGIS services (`Corporate_Limits`, `ETJ`), dissolved.
  That's 25,043 ac measured on the polygon in NC State Plane (EPSG:2264).
- On the 10 m analysis grid, a cell is inside the study area if its **centre** is inside the boundary. That gives 25,049.7 ac.
- File: `code/inputs/boundary.gpkg`.

## 2. Data

| Data | Source | Use |
|---|---|---|
| Sentinel-2 Level-2A surface reflectance | Microsoft Planetary Computer STAC, collection `sentinel-2-l2a` (Copernicus/ESA) | Change detection |
| NAIP 2022 (2–14 Sep and 6 Oct 2022 flights, 0.6 m, 4-band) | USDA FSA via Planetary Computer, collection `naip` | Baseline forest mask |
| NAIP 2020 (11–12 Jul and 21 Sep 2020) | same | Validation only (pre-baseline loss check, sample images) |
| Wake County parcels; Apex rezoning, development and residential-phase layers | Wake County and Town of Apex ArcGIS services | `case_join.csv` only |
| Chatham County CAMA parcels (`Cadastral/Chatham_CamaParcels/MapServer/0`, gisservices.chathamcountync.gov), accessed 2026-10-27 | Chatham County GIS | `case_join.csv` only, for events with no Wake parcel |
| FIA EVALIDator | USDA Forest Service FIADB-API | County context only (`fia/`) |

**Sentinel-2 query** (`code/01_stac_items.py`):
- Collection `sentinel-2-l2a`, bbox = boundary bounds in EPSG:4326 (−78.96900, 35.66493, −78.80231, 35.77887),
  datetime 2022-07-01T00:00:00Z to 2026-10-24T23:59:59Z, MGRS tile 17SPV.
- That returned **802 items** (relative orbits 54 and 97). Re-running the query on 2026-10-27 returned the same 802 IDs.
- Items with the same acquisition time and relative orbit are reprocessings of one datatake, so only the newest product ID is kept.
  That leaves **663 unique scenes** (2022-07-02 to 2026-10-24).
- Every scene is processing baseline ≥ 04.00, so reflectance = (DN − 1000) / 10000 throughout.
- **379 of the 663 scenes passed the cloud test and went into the composites. The other 284 were skipped** (rule in §4).
  `scenes.csv` lists all 663 with `used_in_composite`, the AOI clear fraction, and the superseded duplicate IDs.

## 3. Grid

- 10 m, EPSG:32617 (WGS 84 / UTM 17N), aligned to the native S2 17SPV pixel grid: x 683800–698840, y 3948740–3961460 (1504 × 1272 px).
- 20 m bands (SCL, B11, B12) are nearest-neighbour upsampled to 10 m.
- 1 acre = 4,046.86 m² = 40.5 px, so the ≥1 ac rule is **≥41 px**.

## 4. Clear-pixel masking (`code/03_composites.py`)

1. Keep only Scene Classification (SCL) classes **4 vegetation, 5 bare soil, 6 water**. Class 7 "unclassified" is dropped too.
2. Remove SCL **3 cloud shadow, 8 cloud medium, 9 cloud high, 10 thin cirrus**, each buffered by **2 SCL pixels (40 m)**.
3. Also drop pixels with B04 ≤ −0.05 or B08 ≤ 0 (no-data).
4. **Skip the whole scene** if under 1% of the AOI window is clear, **or** if under **20%** of the data-covered part of the AOI is clear.
   The few "clear" pixels in mostly cloudy scenes sit next to cloud and haze and contaminate medians.
   Partial-swath scenes that are clear where they have data are kept.

## 5. Quarterly composites (composite rule)

- For each calendar quarter, and each pixel, take the **median** of NDVI = (B08−B04)/(B08+B04), NBR = (B08−B12)/(B08+B12),
  NDMI = (B08−B11)/(B08+B11), and B02/B03/B04 over every clear observation from the used scenes.
- A composite pixel is **valid** only if it has **≥2 clear observations**.
- 18 composites: **2022Q3 (Jul–Sep 2022) is the baseline**, and 2022Q4 through 2026Q4 are the detection quarters.
  2026Q4 is partial: 1–24 Oct 2026, 9 of 12 scenes used.
- Valid-pixel coverage of the study area was 99.8–100% in every quarter. Scenes used and median clear observations
  per quarter are in `clearings_by_quarter.csv`.

## 6. Baseline forest definition (`code/02_baseline.py`)

**Baseline forest is the NAIP 2022 canopy mask, aggregated to 10 m.** A 10 m cell is baseline forest if it has ≥50 valid 1 m pixels
and **≥50% of its valid 1 m pixels are canopy**. Result: **9,265.5 ac (37.0% of the study area)**. File: `baseline_forest_10m.tif`.

How the 1 m NAIP canopy mask was made (`code/upstream/canopy_update.py`, run 2026-09-28):
- NAIP 2022 tiles were mosaicked onto a 1 m EPSG:32617 grid. NDVI = (NIR − Red)/(NIR + Red), using bands 4 and 1.
- Canopy = NDVI ≥ **0.469** AND local NDVI standard deviation (5 × 5 m window) ≥ **0.012**. The texture test drops smooth lawns and hayfields.
  This is followed by a morphological opening (1 iteration) and closing (2 iterations).
- The 0.469 threshold comes from **distribution matching** to the July 2020 NAIP. The 2020 threshold of 0.30 sits at a given percentile
  of the 2020 NDVI distribution, and 0.469 is the same percentile of the 2022 distribution. The two flights are on different
  radiometric scales. No public lidar covers Apex, so no lidar check was possible.

**S2 agreement check:**
- Only NAIP-forest cells that also look forest-like in the 2022Q3 S2 composite (§7 test) become candidates: **8,445.3 ac**.
- The other **820.2 ac** of NAIP forest, mostly partial-canopy edge cells, is "baseline-ambiguous" and excluded.
- A cross-correlation of NAIP canopy fraction against S2 2022Q3 NDVI, shifted ±1 px, peaks at zero shift, so the grids are aligned.

## 7. Seasonal calibration and the "cleared-like" test (`code/04_detect.py`)

Forest and bare ground look different every quarter (leaf-off, sun angle), so every index is rescaled **per quarter**:

  s = (x − bare_median_Q) / (stable_forest_median_Q − bare_median_Q)

On this scale 1 = typical stable forest that quarter and 0 = typical bare or impervious ground that quarter.

**Reference pixels:**
- **Stable forest** (9,536 px, 235.6 ac):
  - NAIP interior forest: ≥90% canopy, eroded 2 px (20 m).
  - Also NBR > 0.6 in 2022Q3, 2025Q3 and 2026Q3, and NDVI > 0.6 in the final composite. So it is forest at both ends of the period.
- **Bare** (121,462 px): in-boundary cells with 0% NAIP canopy and 2022Q3 NDVI < 0.25.

**Rule:**
- A valid pixel is **cleared-like** in quarter Q if s_NDVI < T_NDVI,Q, **or**, in leaf-on quarters only, s_NBR < T_NBR,Q.
- Nominal thresholds are **T_NDVI = 0.50** (midway between forest and bare) and **T_NBR = 0.65**.
  Each is capped at the stable-forest 1st percentile for that quarter.
  - The cap only binds in Q1 (leaf-off), where it holds single-composite false positives in stable forest to about 1%.
- **Leaf-on** means a Q2 or Q3 quarter whose stable-forest NBR-s 1st percentile is ≥ 0.75. Every Q2/Q3 composite passed.
  Q4 (including partial 2026Q4) and Q1 count as leaf-off/transition.
- NBR is what stops graded-then-sodded lawns from looking like "recovered" forest in summer: lawn NBR-s is about 0.55–0.6, against ≥0.85 for forest.
  It isn't used in leaf-off quarters, because deciduous forest NBR collapses then.

Per-quarter medians, thresholds (in s and raw units) and stable-forest false-positive rates:

| quarter | leaf-on | NDVI forest / bare median | T_NDVI s / raw | NBR forest / bare median | T_NBR s / raw | stable-forest FP |
|---|---|---|---|---|---|---|
| 2022Q3 | yes (baseline) | 0.849 / 0.138 | 0.50 / 0.493 | 0.695 / 0.047 | 0.65 / 0.468 | 0.0% |
| 2022Q4 | no | 0.814 / 0.149 | 0.50 / 0.482 | 0.618 / 0.058 | not used | 0.0% |
| 2023Q1 | no | 0.734 / 0.116 | 0.49 / 0.418 | 0.490 / 0.032 | not used | 1.01% |
| 2023Q2 | yes | 0.839 / 0.174 | 0.50 / 0.506 | 0.666 / 0.068 | 0.65 / 0.457 | 0.01% |
| 2023Q3 | yes | 0.853 / 0.173 | 0.50 / 0.513 | 0.710 / 0.070 | 0.65 / 0.486 | 0.0% |
| 2023Q4 | no | 0.813 / 0.162 | 0.50 / 0.487 | 0.619 / 0.062 | not used | 0.21% |
| 2024Q1 | no | 0.762 / 0.114 | 0.47 / 0.418 | 0.537 / 0.005 | not used | 0.98% |
| 2024Q2 | yes | 0.833 / 0.183 | 0.50 / 0.508 | 0.671 / 0.071 | 0.65 / 0.461 | 0.0% |
| 2024Q3 | yes | 0.846 / 0.186 | 0.50 / 0.516 | 0.708 / 0.069 | 0.65 / 0.485 | 0.0% |
| 2024Q4 | no | 0.821 / 0.182 | 0.50 / 0.501 | 0.603 / 0.057 | not used | 0.28% |
| 2025Q1 | no | 0.751 / 0.124 | 0.46 / 0.414 | 0.550 / 0.018 | not used | 1.02% |
| 2025Q2 | yes | 0.838 / 0.191 | 0.50 / 0.514 | 0.675 / 0.075 | 0.65 / 0.465 | 0.0% |
| 2025Q3 | yes | 0.853 / 0.188 | 0.50 / 0.520 | 0.702 / 0.065 | 0.65 / 0.479 | 0.0% |
| 2025Q4 | no | 0.825 / 0.187 | 0.50 / 0.506 | 0.638 / 0.072 | not used | 0.4% |
| 2026Q1 | no | 0.798 / 0.137 | 0.45 / 0.437 | 0.583 / 0.047 | not used | 1.01% |
| 2026Q2 | yes | 0.824 / 0.182 | 0.50 / 0.503 | 0.660 / 0.069 | 0.65 / 0.453 | 0.0% |
| 2026Q3 | yes | 0.842 / 0.182 | 0.50 / 0.512 | 0.681 / 0.049 | 0.65 / 0.460 | 0.0% |
| 2026Q4 (partial) | no | 0.839 / 0.197 | 0.50 / 0.518 | 0.679 / 0.078 | not used | 0.0% |

"Stable-forest FP" is the share of stable-forest pixels that are cleared-like in that one composite, before the persistence test.

## 8. Persistent-drop rule (when a pixel counts as cleared)

1. A candidate pixel (§6) is **cleared** in the **first quarter Q, from 2022Q4 on,** where it is cleared-like **and** it stays
   cleared-like in **every later valid leaf-on (Q2/Q3) composite**. A single forest-like leaf-on composite afterwards vetoes it,
   so cleared-then-regrown areas are not counted.
2. Leaf-off/transition quarters (Q1, Q4) can be the first-detection quarter, but they are **not** used to test persistence.
   Winter lawn and leaf-off deciduous forest can't be told apart, so a winter "veto" would delete real clearings that later became lawn.
3. A pixel is **confirmed** if the drop shows again in any later valid composite, of any season. Otherwise it is **provisional**.
   An event is provisional when fewer than 50% of its pixels are confirmed.
4. Checks on the data:
   - 3,464 pixel-quarter acres were cleared-like and later regreened, and none of them were assigned as clearings.
   - Winter-only dips (7–448 ac per winter) produced no detections.
   - The stable-forest reference ended with 0.00 ac cleared. This check is circular, because those pixels were picked to be forest at both ends.

## 9. Patches → events (`code/05_events.py`)

1. Cleared pixels are joined **8-connected**. Patches under **41 px (1 ac)** are dropped.
   About 264 ac of scattered cleared pixels and small patches is not reported.
2. Each remaining patch (91 patches) is split into same-first-quarter connected pieces. Any piece under 1 ac is merged into the
   neighbouring piece it shares the longest border with, and this repeats until every piece is ≥1 ac.
   The result is **238 events**, each with its own `first_quarter`. Event acres sum exactly to the patch totals.
3. Events are polygonised on the 10 m pixel edges, and acres are computed in UTM 17N.
   Recomputing them in EPSG:2264 gives 928.9 ac, a rounding-level difference.
4. IDs run C001 (largest) to C238 (smallest). Centroids are polygon centroids in EPSG:4326.

**Geometry in `clearings.geojson`:** pixel-edge polygons, **not simplified**, with coordinates rounded to 6 decimal places (~0.1 m).
The file is 0.77 MB, well under the 5 MB target, so simplifying wasn't needed and the polygons still match the stated acres exactly.
`code/06_release_files.py --simplify-m N` will produce a simplified version if one is ever needed.

## 10. Validation

### 10a. Control sites

Each control is a 300 m radius circle (~64–70 ac) inside the study area. The coordinates are the OpenStreetMap feature points
returned by Nominatim on 2026-10-27.

| Site | Coordinates (lon, lat) | OSM feature | Baseline forest in window | Cleared pixels, any size | In ≥1 ac events |
|---|---|---|---|---|---|
| Apex Community Park | −78.82364, 35.75136 | relation 8264995 | 34.4 ac | 1.04 ac | **0 ac** |
| Apex Nature Park | −78.90746, 35.72028 | relation 8257028 | 49.3 ac | 0.05 ac | **0 ac** |
| Kelly Road Park | −78.89389, 35.73166 | way 33111540 | 32.5 ac | 0.72 ac | **0 ac** |

Corrections from the working draft:
- An earlier draft used −78.8615, 35.7420 for "Apex Community Park". That point is a residential subdivision about 3 km from the park.
- The draft's other park points were 75–280 m from the OSM features.
- All controls were re-run at the coordinates above, and all still show 0 ac in reported events.

Chips: `validation_chips/control_*.png`.

### 10b. Pre-baseline loss is not re-detected

The 102 NAIP 2020→2022 loss polygons (514.3 ac) were cleared before the baseline:
- Only 15.5 ac of that area is baseline forest at 10 m.
- 6.67 ac is flagged as new clearing at pixel level, and **4.23 ac (0.8%)** falls inside reported events.
  These are edge contacts where a new clearing abuts an old one.

### 10c. Largest 5 events

C001–C005 (45.1, 24.9, 22.3, 19.3 and 16.6 ac) were inspected in S2 before / first-detection / after composites.
All five show grading or construction. Chips: `validation_chips/C00*.png`.

| id | acres | first quarter | What it is |
|---|---|---|---|
| C001 | 45.1 | 2023Q2 | Large graded pad on a Wake County Board of Education parcel. Bare soil in 2023Q2, buildings and pavement by 2026Q3. |
| C002 | 24.9 | 2023Q3 | Apex Gateway (23CZ15). Haul roads cut through forest in 2023Q3, whole site graded by 2026Q3. |
| C003 | 22.3 | 2026Q3 | Apex Gateway Phase 2C. Fresh bare soil along the W/S margin of a woodlot. |
| C004 | 19.3 | 2025Q1 | Utley Farms (KB Home). Grading visible in the 2025Q1 composite, bare soil in 2026Q3. |
| C005 | 16.6 | 2024Q2 | **Pleasant Plains Elementary School** site (Wake County Board of Education parcel). Forest cleared and bare in 2024Q2, partly grassed by 2026Q3. |

Correction: an earlier version of these notes, and the `sample30/tags.csv` reason for C005, called C005 a clearing
"beside a highway interchange". It is the Pleasant Plains Elementary School site, identified by eye from Google Earth history on 2026-10-27
and consistent with the parcel owner. The "real clearing" verdict is unchanged.

### 10d. Random sample of 30 events (`sample30/`)

**Selection:**
- Stratified by size: 1–2 ac 10, 2–5 ac 9, 5–15 ac 7, 15+ ac 4.
- Also stratified by first-detection season: 16 leaf-off/transition (Q4/Q1) and 14 leaf-on.
- Two of the 30 are provisional.
- *The random seed and the selection script were not preserved.* The drawn sample is published as-is in `sample30/sample.csv`.

**Tags:**
- CONFIRMED = an event outline is mostly real forest clearing. FALSE = no forest removal. UNSURE.
- Result: **30 CONFIRMED, 0 FALSE, 0 UNSURE**. The observed false-positive rate is 0%, with an exact binomial 95% upper bound of **9.5%**.

**Cleared-fraction method (`real_frac`):**
- For each sampled event, the analyst visually estimated the share of the outlined area that is actually cleared, in steps of 0.05.
  Event outlines include mixed edge pixels and retained tree strips.
- This is a judgement from imagery, not a measurement.
- The area-weighted mean is **0.84**: 143.3 of 170.8 outlined acres.
  - By size class: 1–2 ac 0.78, 2–5 ac 0.76, 5–15 ac 0.82, 15+ ac 0.89.
- Applied to the full 929.2 ac, this implies roughly **780 ac actually cleared within the outlines**. That's an estimate from a 30-event sample, not a census.

**Imagery used for tagging, disclosed in full:**
- All 30 tags used the Sentinel-2 quarterly composites.
- For **16 of the 30**, the analyst also looked at the Esri World Imagery basemap.
- The other 14 were tagged on Sentinel-2 alone, because the Esri imagery predated the clearing.
- Wake County 2021/2025 ortho panels were requested but came back blank, so they were not used.
- `sample30/tags.csv` records the evidence used for each tag.
- **The images published in `sample30/images/` use only NAIP (2020, 2022) and Sentinel-2.** No Esri, Google or county imagery is included.

### 10e. Sensitivity (total acres in ≥1 ac patches)

| Run | Acres |
|---|---|
| Default (T_NDVI 0.50, T_NBR 0.65, ≥2 obs) | 929 |
| T_NDVI 0.40 / 0.60 | 923 / 941 |
| T_NBR 0.55 / 0.75 | 894 / 968 |
| Minimum observations 1 / 3 | 929 / 928 |
| Alternative baseline: also allow NAIP non-forest cells that are clearly forest in S2 2022Q3 (NDVI-s and NBR-s ≥ 0.8; adds 1,943 ac of candidates) | 1,359 |

Threshold choices move the total by about ±4%. **The baseline forest definition matters much more**: the NAIP 2022 mask
under-calls some dense forest at 10 m. That makes 929 ac a **conservative** figure.

## 11. Parcel and case join (`case_join.csv`)

- Each event was intersected with current Wake County parcels, Apex rezoning cases, the Apex development-project layer and
  recorded residential phases.
- An overlap is kept if it is **≥0.05 ac**.
- 224 of 238 events overlap a Wake parcel.
- **Chatham County parcels (v1.1).** The 14 events with no Wake parcel (85.4 ac) are all on the Chatham side of the Apex ETJ
  or in road right-of-way. They were intersected with Chatham County CAMA parcels using the same ≥0.05 ac rule and the same redaction rule
  (`code/09_chatham_parcels.py`). **12 of the 14 overlap Chatham parcels** (82.5 ac). v1.0 said 7; that count was wrong.
  - The `parcel_county` column (`Wake`, `Chatham`, or empty) gives the parcel source.
  - For Chatham rows, `org_parcel_pins` holds Chatham parcel numbers: 7 digits, often with leading zeros, e.g. `0017900`.
    Wake PINs are 10 digits. `land_class` and `planning_jurisdiction` are empty because Chatham's layer has no equivalent fields.
  - Organisations on these parcels: Mills Chatham Develop Group LLC, LIPT West Raleigh Distribution I/II/III LLC, BIN-AG2 LLC,
    and BIN - AG1C / AG2A / AGP LLC. One private individual parcel (0.13 ac in C002) is withheld.
  - **C168 and C186** (2.9 ac, both provisional 2026Q4) overlap no parcel in either county. They lie 210–240 ft from the nearest Wake parcels,
    and one of the neighbouring owners is the NC DOT Turnpike Authority. That points to road right-of-way. The manual review below
    identifies both as the Peakway bridge.
- 216 events (829.6 ac) overlap at least one rezoning, development or recorded-phase case. The other 22 events (99.6 ac) don't.
- **Apex Gateway events with no case match (C074, C131, C133, C144, C177; 10.8 ac, first detected 2023Q3–Q4).**
  These sit beside events that matched 23CZ15 (C002, C003, C006, C085, C106, C164) but didn't match it themselves. Checked on 2026-10-27:
  - The cause is not polygon edges or the overlap threshold. All five lie **outside** the 23CZ15 polygon, by 79 ft (C177), 307 ft (C131),
    396 ft (C074), 615 ft (C144) and 961 ft (C133). The next nearest rezoning case is 22CZ22, 2,300–3,700 ft away.
  - They are all within 0–88 ft of the "Apex Gateway Utility Expansion" development record. Only C144 touches it, and its 0.04 ac overlap
    is below the 0.05 ac threshold.
  - They are on Chatham parcels zoned LI-CZ, owned by LIPT West Raleigh Distribution I/II/III LLC and Mills Chatham Develop Group LLC,
    in New Hope township. That is why they had no Wake parcels.
  - Most likely they are the earlier Apex Gateway phase(s). The Town's rezoning layer has no case polygon covering those parcels.
  - Case matching stays strictly rule-based, so they are still listed as unmatched. The parcel owners are now shown.

**Manual identification of unmatched events (`manual_identification`, v1.1).**
- The 22 events with no rezoning, development or residential-phase match (99.6 ac) were identified **by eye from Google Earth
  historical imagery on 27 Oct 2026** by the analyst. The column is empty for the other 216 events.
- It is descriptive context only. It is **not used in any total**: event counts, acres, the 216 / 22 case-match split and the owner shares
  are all unchanged.
- The text is recorded as entered. Some entries are uncertain (C176: "Some building - cant tell"), and "Private Property" (C092) and
  "Private Residence" (C212) are kept generic, with no names.
- Google Earth imagery isn't redistributable, so none of it is included. The input is `code/inputs/manual_identification_2026-10-27.csv`,
  merged by `code/10_manual_identification.py`.
- Identified (events): Felton Grove High School (C001, C069, C099, C237, C238); Apex Gateway (C074, C131, C133, C144, C177);
  Retreat at Friendship (C160, C196); Peakway Bridge (C168, C186); Pleasant Plains Elementary School (C005); Peak Rehabilitation
  Hospital (C084); Holleman Hills South subdivision (C137); Wake County EMS Facility (C208); Calyx Living of Apex (C217);
  Private Property (C092); Private Residence (C212); Some building - cant tell (C176).
- Development-layer records overlap each other, so their acreages are not additive.

**Owner names:**
- Companies, HOAs/owner associations, churches and public bodies are shown as recorded.
- Parcels owned by **private individuals** (including individual trustees) appear only as a count and a total overlap acreage.
  Their names and PINs are withheld.
- The classification is rule-based: legal-entity or public-body words in the owner field (LLC, INC, LP, CORPORATION, COMPANY,
  ASSOCIATION, HOA, TOWN OF, COUNTY, BOARD OF EDUCATION, CHURCH…).
- All 608 distinct Wake owner strings were reviewed by hand: 87 organisations and 521 individuals.
  The 9 Chatham owner strings were also reviewed: 8 organisations and 1 individual.

**PINs are text.** In `case_join.csv` every PIN is written with its leading zeros (e.g. C005 `0731640642`). Excel and Numbers
turn a cell holding a single PIN into a number when they open a CSV, which drops the leading zero. Cells with several PINs
stay text because of the `;` separator. `case_join.xlsx` has the same data with the PIN column stored as text.
If you open the CSV in a spreadsheet, import `org_parcel_pins` as Text.

## 12. FIA context (`fia/`)

- FIADB-API (EVALIDator) query for Wake County (`cond.countycd=183`), evaluation group 372024, FIADB 1.9.5.00.
- Forest land: 162,807 ac (SE 17.4%). Live trees ≥5.0" DBH on forest land: 26,677,123 (SE 18.5%).
  That works out to **~164 trees ≥5" per forest acre** (county average, roughly ±20%).
- Exact parameters, URLs and both raw responses are in `fia/QUERY.md`.
- In this release it is context only. **No tree counts are claimed for any clearing.**
- The Peak Weekly's published tree estimate (about 128,000) multiplies the estimated cleared acres (§10d) by this county average.
  That calculation is written out on the methodology page, thepeakway.com/tree-count. It is not in the data files.

## 13. Limitations

- **10 m pixels.** Edges are mixed pixels, and linear clearings narrower than about 20 m (roads, utility and greenway cuts) are mostly missed.
- **Single-sensor spectral method.** It can't tell grading from storm blowdown, fire, timber harvest or herbicide die-off.
  Every inspected event looked like grading or construction.
- **Baseline.** Forest the NAIP 2022 mask missed isn't counted (see sensitivity). Clearings between the S2 Jul–Sep 2022 median
  and the Sep–Oct 2022 NAIP flight can fall through the gap.
- **Timing.**
  - `first_quarter` is the first composite where the drop appears and persists, not the clearing date.
  - Leaf-off/transition quarters can run up to about one quarter early.
  - Phased projects are split across quarters.
  - **Annual or half-year totals are more reliable than single quarters.**
- **Recent data.** 2026Q4 covers only 1–24 Oct 2026, and all 44.6 ac of it is provisional. 2026Q3 is confirmed only by that partial quarter.
  These figures will change once more imagery is processed.
- **Cloud masking.** SCL misses some thin cloud and shadow. The medians and the persistence test absorb most of that.
- **No net canopy change** is reported or implied.

## 14. Software

Python 3.12.13 · numpy 2.5.3 · scipy 1.18.1 · rasterio 1.5.1 (GDAL 3.12.4) · geopandas 1.2.0 · shapely 2.1.2 (GEOS 3.13.1) ·
pyproj 3.8.0 (PROJ 9.8.1) · pandas 2.3.3 · pyogrio 0.13.0 · pystac 1.15.2 · pystac-client 0.9.0 · planetary-computer 1.0.0 ·
matplotlib 3.11.2 · affine 3.0.1 · requests 2.34.2. Pinned in `code/requirements.txt`.

## 15. Data credits

- Contains modified Copernicus Sentinel data 2022–2026 (ESA), accessed via Microsoft Planetary Computer.
- NAIP imagery: USDA Farm Production and Conservation Business Center. Parcels: Wake County and Chatham County. Boundary and case layers: Town of Apex.
- FIA: USDA Forest Service.
