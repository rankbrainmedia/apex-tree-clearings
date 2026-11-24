# FIA EVALIDator queries (Wake County, NC)

These two queries went through the USDA Forest Service FIADB-API (`fullreport` endpoint, which is what EVALIDator uses).
The first run was on 2026-10-27 at 05:02 UTC. I ran the exact parameters again at 16:54 UTC the same day,
and the estimates, SE, plot counts and generated SQL came back identical. Both raw responses are included.

| | Forest land area | Live trees ≥5.0" DBH on forest land |
|---|---|---|
| Endpoint | `https://apps.fs.usda.gov/fiadb-api/fullreport` | same |
| `snum` (estimate attribute) | `2`: Area of forest land, in acres | `4`: Number of live trees (at least 1 inch d.b.h./d.r.c.), in trees, on forest land |
| `wc` (evaluation group) | `372024`: North Carolina 2024 | `372024` |
| `rselected` / `cselected` (row/column grouping) | `None` / `None` (single total) | `None` / `None` |
| `strFilter` | `cond.countycd=183` (Wake County) | `cond.countycd=183 and tree.dia>=5.0` |
| `outputFormat` | `NJSON` | `NJSON` |
| Database | FIADB_1.9.5.00 | FIADB_1.9.5.00 |

Full request URLs:

```
https://apps.fs.usda.gov/fiadb-api/fullreport?snum=2&wc=372024&rselected=None&cselected=None&strFilter=cond.countycd%3D183&outputFormat=NJSON
https://apps.fs.usda.gov/fiadb-api/fullreport?snum=4&wc=372024&rselected=None&cselected=None&strFilter=cond.countycd%3D183+and+tree.dia%3E%3D5.0&outputFormat=NJSON
```

## Results

| Estimate | Value | SE | SE % | Plots |
|---|---|---|---|---|
| Forest land, Wake County | 162,807 ac | 28,279 ac | 17.4% | 40 |
| Live trees ≥5.0" DBH on forest land, Wake County | 26,677,123 | 4,941,286 | 18.5% | 38 |
| Ratio (trees ≥5" per acre of forest land) | **163.9** | not returned by the API | about ±20% (see note) | |

Note on the ratio: it is the second estimate divided by the first. The API doesn't return a ratio-of-means SE,
so "about ±20%" is a rough figure taken from the two component SEs, not a computed confidence interval.
This is a **county-wide average for FIA forest land** (≥10% canopy, ≥1 ac, ≥120 ft wide). It isn't a measured count for any
clearing, and dense or young stands can be well above or below it.

## Files

- `raw_2026-10-27_original/`: the responses from the first run, as saved during the analysis.
- `raw_2026-10-27_rerun/`: the responses from the verification rerun.
  - `forest_land_area_snum2.json` and `live_trees_ge5in_snum4.json` in each folder. `metadata.sql` holds the SQL that FIADB generated.

## Citation (as returned by the API)

USDA Forest Service, Forest Inventory and Analysis Program, Tue, 27 Oct 2026. Forest Inventory EVALIDator web-application /
FIADB-API Version 2.0. St. Paul, MN: U.S. Department of Agriculture, Forest Service, Northern Research Station.
<http://apps.fs.usda.gov/fiadb-api/evalidator>
