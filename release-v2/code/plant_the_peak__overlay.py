#!/usr/bin/env python3
"""overlay.py: the Town of Apex's Plant the Peak planting points against Wake County's priority planting areas.

    ../apex-canopy/df-venv/bin/python overlay.py [--pull]

Points: the public layer behind the Town's "Plant the Peak" map (https://experience.arcgis.com/experience/08e9408f68a84aaf9c52f6ca3f11cfe7),
  https://services1.arcgis.com/nry3yyvaEfskMEXA/arcgis/rest/services/Plant_the_Peak_Plantings_Timeline_Function/FeatureServer/0
  --pull fetches it again into inputs/ under today's date; without it the newest saved pull is used.
Planting areas: Wake County's "Tree Planting Priorities" layer (Potential Planting Area 2020, composite priority), as pulled
  2026-11-24 by entitlement/wake_tca.py (the polygons that touch Apex's bounding box).

PRIVATE: the Town's layer carries a street address for most points and the points sit on private homes. The inputs/ file and
out/PRIVATE_points_with_priority.* are not for publication. out/summary_* hold counts only.
"""
import glob, json, os, sys, datetime, urllib.request
import numpy as np, pandas as pd, geopandas as gpd

HERE = os.path.dirname(os.path.abspath(__file__))
T = os.path.normpath(os.path.join(HERE, ".."))
OUT = os.path.join(HERE, "out")
URL = "https://services1.arcgis.com/nry3yyvaEfskMEXA/arcgis/rest/services/Plant_the_Peak_Plantings_Timeline_Function/FeatureServer/0/query?where=1%3D1&outFields=*&outSR=4326&orderByFields=FID&resultRecordCount=2000&f=geojson"
ORDER = ["Very High", "High", "Moderate", "Low", "Very Low"]
if "--pull" in sys.argv:
    fn = os.path.join(HERE, "inputs", f"PRIVATE_plant_the_peak_points_{datetime.date.today()}.geojson")
    with urllib.request.urlopen(urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 (research script)"}), timeout=60) as r, open(fn, "wb") as f: f.write(r.read())
SRC = sorted(glob.glob(os.path.join(HERE, "inputs", "PRIVATE_plant_the_peak_points_*.geojson")))[-1]
raw = json.load(open(SRC))
assert not raw.get("exceededTransferLimit") and not raw.get("properties", {}).get("exceededTransferLimit"), "the pull was cut short"
g = gpd.GeoDataFrame.from_features(raw["features"], crs=4326)
g["lon"], g["lat"] = g.geometry.x.round(6), g.geometry.y.round(6)
g = g.to_crs(32617)
for c in ("planting_d", "FY_Date", "EditDate"): g[c] = pd.to_datetime(g[c], unit="ms", errors="coerce")
g["season"] = g.YearMarker.astype(int)                                  # the Town's own year field: a planting season, fall into the next spring
g["calendar_year"] = g.FY_Date.dt.year.astype("Int64")                  # year of the layer's date field (alias Fiscal_Date)
ppa = gpd.read_file(os.path.join(T, "entitlement", "out_wake_tca", "cache", "wake_priority_planting_areas_2026-11-24.geojson")).to_crs(32617)[["CompositePri", "geometry"]]
inside = gpd.sjoin(g[["FID", "geometry"]], ppa, how="left", predicate="within").drop_duplicates("FID").set_index("FID").CompositePri
near = gpd.sjoin_nearest(g[["FID", "geometry"]], ppa, how="left", distance_col="d").drop_duplicates("FID").set_index("FID")
g["priority_inside"] = g.FID.map(inside).fillna("Outside all planting areas")
g["nearest_priority"] = g.FID.map(near.CompositePri); g["nearest_metres"] = g.FID.map(near.d).round(1)
for r in (5, 10):
    g[f"priority_within_{r}m"] = np.where(g.nearest_metres <= r, g.nearest_priority, f"More than {r} m from any planting area")
# where the points are: town limits, planning area; and ground the 2017-2026 series counts as forest cleared
L = os.path.join(T, "entitlement", "out_wake_tca", "layers")
def latest(stem): return sorted(glob.glob(os.path.join(L, stem + "*.geojson")) + glob.glob(os.path.join(T, "entitlement", "out_wake_tca", "cache", stem + "*.geojson")))[-1]
town = gpd.read_file(latest("apex_corporate_limits")).to_crs(32617).geometry.union_all()
g["inside_town_limits_today"] = g.geometry.within(town)
D = np.load(os.path.join(T, "apex-canopy", "prerezoning_cache", "detect_2017.npz"))
col = ((g.geometry.x - 683800) // 10).astype(int); row = ((3961460 - g.geometry.y) // 10).astype(int)
ok = (col >= 0) & (col < 1504) & (row >= 0) & (row < 1272)
ev = np.zeros(len(g), bool); ev[ok.values] = D["kept_event"][row[ok].values, col[ok].values]
g["on_forest_cleared_2017_2026"] = ev

# ---------------------------------------------------------------- tables
def table(col_, groups):
    t = pd.crosstab(g[col_], g[groups]).reindex([c for c in ORDER if c in set(g[groups])] + [c for c in sorted(set(g[groups])) if c not in ORDER], axis=1, fill_value=0)
    t["All"] = t.sum(axis=1); t.loc["All years"] = t.sum()
    return t
S = []
say = S.append
say(f"PLANT THE PEAK planting points against Wake County's priority planting areas. Run {datetime.date.today()}.")
say(f"Points: {len(g)} in the Town's public layer ({os.path.basename(SRC)}); data last edited {g.EditDate.max().date()}; dated plantings run {g.FY_Date.min().date()} to {g.FY_Date.max().date()}. One point is taken as one tree.")
say(f"  {int((g.address.fillna('').str.strip() == '').sum())} points carry no address (all in the {', '.join(str(int(v)) for v in sorted(g[g.address.fillna('').str.strip() == ''].season.unique()))} season). {int(g.duplicated(['lon', 'lat'], keep=False).sum())} points share their exact position with another point,")
say("  so at least some points mark the property and not the trunk. That matters below: the County's planting areas are small.")
say(f"  {int(g.inside_town_limits_today.sum())} of {len(g)} are inside today's town limits.")
say("\n1. TREES BY YEAR")
y = pd.DataFrame({"by the Town's season field (YearMarker)": g.season.value_counts().sort_index(), "by calendar year of the date field": g.calendar_year.value_counts().sort_index()}).fillna(0).astype(int)
y.loc["Total"] = [len(g), int(g.calendar_year.notna().sum())]
say(y.to_string()); say(f"  A season runs from fall into the next spring. {int(g.calendar_year.isna().sum())} point has no date. Nothing dated 2026 is in the layer.")
say("\n2. PRIORITY OF THE PLANTING AREA EACH POINT FALLS IN (strict: the point is inside the polygon)")
t1 = table("season", "priority_inside"); say(t1.to_string())
tot = t1.loc["All years"]
say(f"  Very High {tot.get('Very High', 0)}, High {tot.get('High', 0)}, lower (Moderate {tot.get('Moderate', 0)}, Low {tot.get('Low', 0)}, Very Low {tot.get('Very Low', 0)}) {tot.get('Moderate', 0) + tot.get('Low', 0) + tot.get('Very Low', 0)}, outside all planting areas {tot.get('Outside all planting areas', 0)}.")
say(f"\n3. HOW CLOSE POINTS ARE TO A PLANTING AREA (all points; one inside a planting area counts as 0 m). Median planting area: {ppa.area.median() / 4046.8564:.3f} acre ({ppa.area.median():.0f} square metres). Distance from a point to the nearest planting area:")
say(f"  median {g.nearest_metres.median():.1f} m; 75% within {g.nearest_metres.quantile(.75):.1f} m; 90% within {g.nearest_metres.quantile(.9):.1f} m; farthest {g.nearest_metres.max():.0f} m.")
for r in (5, 10):
    t = table("season", f"priority_within_{r}m"); say(f"\n  Counting a point with the nearest planting area if it is within {r} metres:"); say(t.to_string())
say("\n4. CONTEXT")
pa = pd.read_csv(os.path.join(T, "entitlement", "out_wake_tca", "ppa_priority_overlay.csv")).set_index("composite_priority").planting_area_acres_in_jurisdiction
say("  Planting-area acres inside Apex's planning jurisdiction, by priority (ppa_priority_overlay.csv): " + ", ".join(f"{k} {pa[k]:,.0f}" for k in ORDER) + f"; Very High + High = {100 * (pa['Very High'] + pa['High']) / pa['All classes']:.0f}% of the acres.")
ins = g[g.priority_inside != "Outside all planting areas"]
say(f"  Of the {len(ins)} points inside a planting area, {int(ins.priority_inside.isin(['Very High', 'High']).sum())} ({100 * ins.priority_inside.isin(['Very High', 'High']).mean():.0f}%) are in Very High or High. "
    f"Within 5 m: {int(g.priority_within_5m.isin(['Very High', 'High']).sum())} of {int((g.nearest_metres <= 5).sum())} ({100 * g.priority_within_5m.isin(['Very High', 'High']).sum() / (g.nearest_metres <= 5).sum():.0f}%).")
say(f"  {int(g.on_forest_cleared_2017_2026.sum())} points sit on ground the 2017-2026 series counts as forest cleared (10 m cells; same caution about point position).")
say("\nREAD WITH CARE")
say("  - The County's planting areas are places that were plantable in 2020 (lawn and open ground, after its exclusions), ranked for stormwater, heat and social equity. 'Outside' means the point is not on one of those polygons. It does not mean a low priority, and it does not mean the spot could not be planted.")
say("  - A home built after 2020 stood on ground the County did not map as plantable, so points in newer neighbourhoods will mostly fall outside whatever their merit.")
say("  - The strict count depends on where the Town put each point. With polygons this small, a point a few metres off its tree changes the answer; sections 2 and 3 bracket it.")
say("  - Plant the Peak plants on request at residents' homes. This overlay describes where the trees went. It is not evidence about how sites were chosen.")
os.makedirs(OUT, exist_ok=True)
open(os.path.join(OUT, "summary.txt"), "w").write("\n".join(S) + "\n")
rows = []
for basis, col_ in (("inside the polygon", "priority_inside"), ("nearest polygon within 5 m", "priority_within_5m"), ("nearest polygon within 10 m", "priority_within_10m")):
    t = table("season", col_).reset_index().rename(columns={"season": "season"}); t.insert(0, "basis", basis); rows.append(t)
pd.concat(rows).fillna(0).to_csv(os.path.join(OUT, "summary_by_year_priority.csv"), index=False)
y.to_csv(os.path.join(OUT, "summary_by_year.csv"))
keep = ["FID", "season", "calendar_year", "FY_Date", "planting_d", "SpeciMark", "tree_selec", "treeSprd", "address", "lon", "lat", "priority_inside", "nearest_priority", "nearest_metres", "priority_within_5m", "priority_within_10m", "inside_town_limits_today", "on_forest_cleared_2017_2026"]
g[keep].to_csv(os.path.join(OUT, "PRIVATE_points_with_priority.csv"), index=False)
g[keep + ["geometry"]].to_crs(4326).to_file(os.path.join(OUT, "PRIVATE_points_with_priority.geojson"), driver="GeoJSON")
print("\n".join(S))
