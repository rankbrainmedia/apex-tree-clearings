# Wake County's canopy assessment against the clearing data (2026-11-24)

Adam's five questions: get the County's Land Cover Analysis / Tree Canopy Assessment layers, and set the clearing
detection beside them by block group, planting priority, jurisdiction and Peak Plan 2055 context area.
Run `../apex-canopy/df-venv/bin/python wake_tca.py` from `entitlement/`. The printed report is `summary.txt`.
Everything the script writes is in this folder. It reads the existing rasters, clearings and case layers and
changes none of them.

**Every canopy figure for a date after 2020 here is an estimate.** It is the County's 2020 canopy with detected
clearings taken off. It adds no growth and it misses what the detection misses.

**Conflict flag.** 23CZ13, the Seymour Mixed Use PUD, is next to the author's home. It is in `cases_used.csv` and
`ppa_by_case.csv`, flagged, and is left out of every total; reference lines give the totals with it. 24CZ08,
24CZ19 and 24CZ20 carry the same flags as in `office_period.py` and stay in the totals, as they do there.
Block groups that contain any of the four are marked in `block_groups.csv` (`conflict_flag`). They are disclosed on the methodology page.

**Names.** Case names are the Town's. Some zoning-map names are a private applicant's name. Take those out
before anything is published. The Place Type layer is a parcel layer with owner and address fields; those
fields were not downloaded.

## What was found and downloaded

All public, no login. Addresses, feature counts, pull date and each layer's last edit date are in
`layers/SOURCES.json`.

| Asked for | Found | Where it is |
|---|---|---|
| 2020 tree canopy | The County's 1 m raster (deciduous and coniferous canopy, NAIP 2020), served by the City of Raleigh's image server. Downloaded at its own pixels over Apex. | `cache/wake_canopy_2020_1m_apex.tif` |
| 2010-2020 change by block group | County layer "Land Cover Canopy Change Metrics", block groups (648, the County's study area). Canopy acres and percent for 2010 and 2020, and the change. | `layers/wake_block_groups_*.geojson` |
| The same for jurisdictions | Corporate limits, planning jurisdiction, and planning jurisdiction outside city limits, each with an Apex row. | `layers/wake_corporate_limits_*`, `wake_planning_*` |
| Potential Planting Areas with composite priority | County layer "Tree Planting Priorities", 404,803 polygons countywide; the 40,625 that touch the Apex bounding box were pulled. Fields: composite, stormwater, heat and social equity means and classes. | `cache/wake_priority_planting_areas_*.geojson` |
| Social equity index by block group | Two things. The index the assessment used is carried on each planting area (`SocialEquMean`, 0 to 4). The County's own combined index by 2020 block group is published for 2023 and 2024 (score 1 to 597, higher is more vulnerable). | `layers/wake_equity_combined_2023_*`, `_2024_*` |
| 2010 canopy | No raster download. The County's 2010 canopy exists as map tiles, drawn down to about 4 m. | inside `cache/wake_canopy_10m.npz` |
| The County's whole land cover | A public file geodatabase, `WAKE_LAND_COVER.zip` (1 GB): the 2020 land cover as 574,170 polygons. Downloaded, not used. | `cache/wake_land_cover_fgdb/` |
| Peak Plan 2055 Context Areas | **Published by the Town**: "Peak Plan 2055 Context Areas STAFF DRAFT", four polygons, last edited 2026-09-17. No georeferencing of the September 1 slide was needed. | `layers/apex_context_areas_2055_*.geojson` |
| Peak Plan 2055 Place Types | **Published by the Town**: "Peak Plan 2055 Public Forum 3", 32,830 parcels with a place type (field `PT_RD6`), last edited 2026-11-06. Both are in the Town's public "Peak Plan 2055 Public Comment" web map. | `cache/apex_place_types_2055_*.geojson` |
| Latest NAIP | July 25, 2025, 30 cm. It is in Planetary Computer's public storage but not yet in its search catalog. (A 2024 flight exists too; only its metadata is there.) | `cache/naip/canopy_2025.npz` |

`cache/` is 1.3 GB and is ignored by git (`.gitignore` in this folder). The script rebuilds it.

## Method

- **Grid.** The release's 10 m grid. A cell's 2020 canopy is the share of its 1 m pixels the County calls canopy.
  Check: on 33 block groups that lie wholly on the grid, this copy adds up to 13,838 acres against the County's
  13,834, and no block group is off by more than 0.3%.
- **Clearing since mid-2020.** The 2017-2026 detection (`../prerezoning/detect_2017.py`), event rule, patches of
  an acre or more, first detected in July-September 2020 or later. That quarter is the first after the NAIP 2020
  flight (July 11-12, 2020 over most of Apex), the same cut `office_period.py` uses. It runs to October 24, 2026.
  1,616 acres of cells. Per-year totals match `out/office_clearings_by_year.csv`.
- **Canopy cleared** is the County's 2020 canopy on those cells, not the cell count: 1,520 acres. The County's
  raster shows 96% canopy on cells cleared since, and 17% on cells cleared before mid-2020, so the two sources
  agree on what stood in July 2020.
- **Canopy now** = 2020 canopy minus canopy cleared since. Three other readings are given beside it:
  the release's stricter rule (still bare in every later summer); with event patches under an acre added; and
  with those plus cells that were forest by both sources in summer 2020, are not forest-like in July-September
  2026 and have no event on record. That last group is 544 acres. Nearly all of it was never in the 2017 forest
  baseline, so the detection could not have seen it. **The last reading is Claude's addition.**
- **Forest standing now**: cells at least half canopy in the County's 2020 raster, with no clearing event since,
  that are forest-like in the July-September 2026 composite. It is a count of forest cells, so it is smaller than
  canopy acres: 1,224 acres of the 2020 canopy cells are tree cover mixed with roofs, pavement or lawn that the
  satellite test does not read as forest in either year. Those are in "canopy now" and not in "forest standing".
- **2010, inside a boundary.** The County publishes 2010 only as figures per block group and as map tiles. To
  split a block group at the jurisdiction line, the script reads the 2010 and 2020 tiles and converts tile
  coverage to canopy share with a curve learned from the 2020 tiles against the 2020 raster. Check on the same
  33 block groups: change of -1,575 acres against the County's -1,698, correlation 0.9999. **It understates the
  loss by about 7%**, so `est_canopy_2010_*` and `in_jur_est_change_*` are estimates, and the County's own
  figure is the one to quote for a whole block group.
- **Cases.** Conditional zoning cases numbered 2020 or later that are approved (in the Rezoning layer, or on the
  zoning map), plus every case the Rezoning layer lists as Proposed. 121 approved (79 numbered 2022 or later,
  the same list as `out/pipeline_2022plus.csv`; 42 numbered 2020 or 2021) and 16 pending. Boundaries and manual
  statuses as in `entitlement.py`. 2020 is the cut because the County's map is from July 2020. **The cut is
  Claude's.** 18CZ21 is still listed as Proposed from 2018; it is 0.6 acre.
- **Planting areas.** Vector overlay. The published outlines are simplified and add up to about 5% more than
  the layer's own `ACRES` field. `ACRES` is kept; a polygon cut by a boundary counts `ACRES` times the share of
  its outline inside.
- **Geographies.** Corporate limits and ETJ from the Town's layers (last edited 2026-11-16). The planning
  jurisdiction is the two together, 24,988 acres. The County's own Apex polygons are also reported, because its
  published percentages are on those: 16,217 acres of corporate limits against 18,079 today.
- **Chatham side.** The County's study area stops short of 250 acres of the jurisdiction in Chatham County.
  Their 2020 canopy (64 acres) comes from NAIP 2020 by the release's recipe. Planting areas, block groups and
  the 2010 tiles do not cover them.
- **NAIP 2025.** The recipe of `../prerezoning/naip_canopy.py`, unchanged, on the 2025 tiles.

## Block-group classes (Claude's thresholds)

- 2010-2020, from the County's figure for the whole block group: **lost** if canopy acres fell 2% or more,
  **gained** if they rose 2% or more, otherwise flat.
- Since mid-2020: **clearing** if 2% or more of the 2020 canopy inside the jurisdiction, and at least 5 acres,
  was cleared.
- **kept losing** = lost, then clearing. **started** = flat or gained, then clearing.
- `class_measured_inside_jurisdiction` repeats it with the 2010-2020 change measured only on the part inside
  the jurisdiction. Five block groups differ.
- The two periods are not measured the same way. The County's number is a net change over ten years, growth
  included. The clearing number is gross, six years and four months, patches of an acre or more only.

## What came out

1. **Block groups.** 37 have an acre or more inside the jurisdiction. 14 kept losing (1,246 acres of canopy
   cleared since), 3 started (254 acres), 8 lost in 2010-2020 with little since, 12 show no loss in either.
   - The largest: 371830534321, 341 acres cleared since mid-2020, 22% of its 2020 canopy in the jurisdiction.
   - **Started**: 371830534312. The County has it at -11 acres for the decade (under 1%). Since mid-2020,
     235 acres, a fifth of its canopy. The other two are small (12 and 7 acres).
   - 371830534331 lost the largest share: 114 acres, 49% of its 2020 canopy.
2. **Planting areas.** 4,689 acres mapped inside the jurisdiction, 787 of them Very High or High priority.
   23.9 acres of Very High or High (3.0%) are now inside a case or a clearing: 12.2 in cases approved and
   numbered 2022 or later, 10.8 in 2020-2021 cases, 0.5 in pending ones, 0.7 in a clearing. For all classes it
   is 662 acres (14%), and it rises as priority falls: 27% of the Very Low class.
3. **Canopy now.**

   | | Acres | 2020 | Cleared since | Now, estimate | Range of the other readings |
   |---|---|---|---|---|---|
   | Corporate limits | 18,079 | 46.9% | 1,452 ac | **38.8%** | 35.8% to 39.1% |
   | ETJ outside them | 6,909 | 60.6% | 68 ac | **59.6%** | 57.5% to 59.9% |
   | Planning jurisdiction | 24,988 | 50.7% | 1,520 ac | **44.6%** | 41.8% to 44.8% |

   On the County's own boundaries: corporate limits 44.6% (its figure) to 37.9%; planning jurisdiction 50.4% to
   44.6%. The County's report has the corporate limits at 58.2% in 2010.
4. **NAIP 2025 cross-check** (`naip_crosscheck.csv`). Cells the detection calls cleared between the flights
   went from 80% canopy to 7%. Cells first seen cleared after the flight were still 67% canopy on it. The cells
   with a two-date change and no event went from 50% to 21%. **The recipe's totals are not a second estimate of
   the level**: forest that stood the whole time reads 79% in 2020 and 73% in 2025, so the recipe drifts between
   flights by more than the change being measured, and it counts less canopy than the County's map throughout
   (41% against 51% in 2020).
5. **Context areas**, inside the jurisdiction:

   | | Acres | Canopy 2020 | Cleared since | Now, est. | Forest standing | In approved 2022+ cases | Pending |
   |---|---|---|---|---|---|---|---|
   | Town Center | 1,472 | 570 ac, 38.7% | 11 ac | 38.0% | 336 ac | 2 ac | 1 ac |
   | Rural | 1,636 | 1,196 ac, 73.1% | 79 ac | 68.3% | 1,033 ac | 11 ac | 0 ac |
   | Suburban | 18,222 | 8,735 ac, 47.9% | 1,102 ac | 41.9% | 6,096 ac | 745 ac | 24 ac |
   | Transit-Oriented Development | 3,649 | 2,153 ac, 59.0% | 327 ac | 50.1% | 1,566 ac | 626 ac | 73 ac |

   - 40% of the forest standing in the Transit-Oriented Development area is inside a case approved since 2022.
   - Rural is 8,376 acres in all; four fifths of it is outside the planning jurisdiction, where there is no
     clearing detection. The 5,488 of those acres on the grid were 71% canopy in 2020.
   - With cases numbered 2020 and 2021 added, forest in approved cases is 1,610 acres across the four areas.
   - `place_types.csv` gives the same columns by place type. Mixed-Use Centers and Corridors holds the most
     standing forest inside approved 2022+ cases: 492 of its 1,520 acres.

## Caveats

- **Not interchangeable with the other tables.** Forest inside approved 2022+ cases is 1,383 acres here and
  1,187 in `entitlement/NOTES.md`. Same cases, same 2026 composite, different starting map: the County's 2020
  canopy counts more than the release's 2022 mask. On the release's baseline this script gets 1,190.
- The detection only exists inside the planning jurisdiction and only on cells that were forest in 2017. It
  drops patches under an acre. So "cleared since" is a floor, and "canopy now" leans high for that reason and
  low for having no growth in it.
- Corporate limits are today's. Land annexed since 2020 moved from the ETJ row to the corporate row, which is
  why the ETJ shows 68 acres cleared on today's line and 321 on the County's.
- A block group that straddles the jurisdiction line has the County's figure for all of it and the clearing
  figure for the part inside. `share_in_jurisdiction` says how much that is.
- The Context Areas layer is titled a staff draft. Place types are the Public Forum 3 version. Both can change.
- The assessment's social equity value and the County's current index are different vintages on different
  block-group editions. Across the block groups pulled they rank the same way (rank correlation 0.68 with the
  2023 index), not identically.
- A planting area inside a case is a place the County marked as plantable in 2020 that now has a rezoning on
  it. It does not show that it cannot be planted.
- The first-detection quarter is not the cut date, and an overlap shows where, not why.
