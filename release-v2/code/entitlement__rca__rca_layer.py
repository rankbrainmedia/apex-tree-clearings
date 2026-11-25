#!/usr/bin/env python
"""rca_layer.py: what is on the ground inside the Town's mapped Resource Conservation Areas.

    ../../apex-canopy/df-venv/bin/python rca_layer.py

Inputs
  ../inputs/town_hoa_os_rca_<date>.geojson   the Town's public HOA_OS_RCA layer (open space, buffers, easements, RCA ...)
  ../../apex-canopy/release-v1/code/inputs/canopy_2022_naip.tif   the 1 m NAIP 2022 canopy mask behind the release
  ../../apex-canopy/rca_cache/naip2022.npz    NAIP 2022 NDVI and NDWI at 1.25 m (naip2022_bands.py)
  ../../apex-canopy/s2/cache/detect.npz       Sentinel-2 state per 10 m cell; the release's clearing outlines
NAIP 2022 (flown 2 and 14 September and 6 October 2022) is the latest NAIP over Apex, so the 1 m picture is 2022.
The 2026 picture is the 10 m Sentinel-2 state for July-September 2026.

Each 1.25 m pixel inside an RCA polygon is one of:
  tree canopy   canopy in the 2022 mask
  water         not canopy, NDVI under -0.2 and NDWI over 0.3 (open water; ponds mostly)
  open ground   everything else: grass, bare soil, pavement, roofs
Writes ../out/rca_layer_by_polygon.csv, ../out/rca_layer_by_project.csv, ../out/rca_layer_summary.txt.
"""
import glob, os, re, sys
import numpy as np, pandas as pd, geopandas as gpd, rasterio, shapely
from affine import Affine
from rasterio import features
from rasterio.warp import reproject, Resampling

HERE = os.path.dirname(os.path.abspath(__file__))
ENT = os.path.join(HERE, ".."); AC = os.path.join(HERE, "..", "..", "apex-canopy"); OUT = os.path.join(ENT, "out")
X0, Y1, W, H, SUB = 683800, 3961460, 1504, 1272, 8
T125 = Affine(1.25, 0, X0, 0, -1.25, Y1)
SHAPE = (H * SUB, W * SUB)
PX_AC = 1.25 * 1.25 / 4046.8564
MIN_PROJECT_AC = 1.0
CONFLICT = re.compile(r"SEYMOUR", re.I)      # the Seymour PUD, next to the author's home: flagged, kept, and left out of the project table's headline rows

fix = lambda g: gpd.GeoSeries(shapely.make_valid(g.geometry.values), index=g.index, crs=g.crs)

# ---- rasters on the 1.25 m grid
with rasterio.open(os.path.join(AC, "release-v1", "code", "inputs", "canopy_2022_naip.tif")) as src:
    can = np.full(SHAPE, 255, np.uint8)
    reproject(rasterio.band(src, 1), can, dst_transform=T125, dst_crs="EPSG:32617", resampling=Resampling.nearest, src_nodata=255, dst_nodata=255)
z = np.load(os.path.join(AC, "rca_cache", "naip2022.npz"))
ndvi, ndwi = z["ndvi"], z["ndwi"]
seen = (can != 255) & np.isfinite(ndvi)
tree = seen & (can == 1)
water = seen & ~tree & (ndvi < -0.2) & (ndwi > 0.3)
openg = seen & ~tree & ~water
D = np.load(os.path.join(AC, "s2", "cache", "detect.npz"))
b = np.load(os.path.join(AC, "s2", "cache", "baseline.npz"))
up = lambda a: np.repeat(np.repeat(a, SUB, 0), SUB, 1)
forest22, now, kept = up(b["forest"]), up(D["state_2026Q3"]), up(D["kept"])        # 10 m cells spread onto the 1.25 m grid

# ---- the Town's layer
g = gpd.read_file(sorted(glob.glob(os.path.join(ENT, "inputs", "town_hoa_os_rca_*.geojson")))[-1]).to_crs(32617)
g["geometry"] = fix(g)
g["TYPE"] = g.TYPE.fillna("").str.strip(); g["PROPDESC"] = g.PROPDESC.fillna("").str.strip()
rca = g[(g.TYPE == "RCA")].copy().reset_index(drop=True)
also = g[(g.TYPE != "RCA") & g.PROPDESC.str.contains(r"\bRCA\b|RESOURCE CONSERVATION", case=False)]
rca["acres"] = rca.area / 4046.8564
rca["plat_year"] = rca.PROPDESC.str.extract(r"BM\s?((?:19|20)\d{2})")[0].astype(float)
rca["conflict_flag"] = rca.PROPDESC.str.contains(CONFLICT)

zn = gpd.read_file(os.path.join(ENT, "inputs", "town_zoning_2026-11-24.geojson")).to_crs(32617); zn["geometry"] = fix(zn)
zn["case"] = zn.CASE_NUMBE.fillna("").str.strip().str.upper()
j = gpd.overlay(rca[["FID", "geometry"]], zn[["case", "NAME", "geometry"]], how="intersection", keep_geom_type=True)
j["a"] = j.area
top = j.sort_values("a", ascending=False).drop_duplicates("FID").set_index("FID")
rca["zoning_case"] = rca.FID.map(top.case).fillna(""); rca["zoning_name"] = rca.FID.map(top.NAME).fillna("").str.strip()
P = pd.read_csv(os.path.join(OUT, "pipeline_2022plus.csv")).fillna("").set_index("case")
PT = pd.read_csv(os.path.join(OUT, "parent_projects.csv")).fillna("")
par = {}
for r in PT.itertuples():
    for c in [r.original_case] + re.findall(r"\b\d{2}CZ\d{2}\b", r.amendments_2022plus) + r.lineage.split(" + "):
        par.setdefault(c, r.parent_project)
rca["project"] = [par.get(c) or (f"{c} {n}".strip() if c else "(no zoning case)") for c, n in zip(rca.zoning_case, rca.zoning_name)]

lab = features.rasterize([(geom, i + 1) for i, geom in enumerate(rca.geometry)], out_shape=SHAPE, transform=T125, fill=0, dtype="int32")
n = len(rca) + 1
cnt = lambda m: np.bincount(lab[m], minlength=n)[1:] * PX_AC
rca["mapped_acres_on_grid"] = cnt(lab > 0)
for k, m in (("tree_canopy_2022", tree), ("water_2022", water), ("open_ground_2022", openg), ("no_image", ~seen),
             ("in_2022_baseline_forest_cells", forest22), ("forestlike_2026Q3", (now == 0) & forest22), ("in_clearing_outlines_2022_2026", kept)):
    rca[k + "_acres"] = cnt((lab > 0) & m)
cols = ["tree_canopy_2022_acres", "water_2022_acres", "open_ground_2022_acres"]
for c in cols:
    rca[c.replace("_acres", "_share")] = (rca[c] / rca[cols].sum(axis=1)).round(3)
rca.drop(columns="geometry").round(3).to_csv(os.path.join(OUT, "rca_layer_by_polygon.csv"), index=False)

num = ["acres", "mapped_acres_on_grid"] + [c for c in rca.columns if c.endswith("_acres")]
B = rca.groupby("project").agg(polygons=("FID", "size"), first_plat_year=("plat_year", "min"), last_plat_year=("plat_year", "max"), conflict_flag=("conflict_flag", "any"), **{c: (c, "sum") for c in num}).reset_index()
tot = B[cols].sum(axis=1)
B["tree_canopy_share_2022"], B["water_share_2022"], B["open_ground_share_2022"] = B[cols[0]] / tot, B[cols[1]] / tot, B[cols[2]] / tot
B["share_of_2022_forest_still_forestlike_2026"] = np.where(B.in_2022_baseline_forest_cells_acres > 0.5, B.forestlike_2026Q3_acres / B.in_2022_baseline_forest_cells_acres.replace(0, np.nan), np.nan)
B["share_inside_clearing_outlines"] = B.in_clearing_outlines_2022_2026_acres / B.mapped_acres_on_grid.replace(0, np.nan)
B["in_2022plus_case_table"] = B.project.str[:6].isin(P.index) | B.project.isin(PT.parent_project)
B = B.sort_values("acres", ascending=False)
B.round(3).to_csv(os.path.join(OUT, "rca_layer_by_project.csv"), index=False)

pd.set_option("display.width", 300, "display.max_columns", 40, "display.max_rows", 200, "display.max_colwidth", 44)
L = []
say = L.append
say(f"The Town's HOA_OS_RCA layer (public, pulled 2026-11-24): {len(g)} polygons of all types. Typed RCA: {len(rca)} polygons, {rca.acres.sum():,.1f} acres.")
say(f"Another {len(also)} polygons ({also.area.sum() / 4046.8564:,.1f} ac) mention RCA in their description but are typed otherwise (mostly BUFFER); they are not in the numbers below.")
say(f"Plat year from the description: {int(rca.plat_year.notna().sum())} of {len(rca)} polygons; {int((rca.plat_year >= 2023).sum())} ({rca.acres[rca.plat_year >= 2023].sum():,.1f} ac) were platted in 2023 or later, after the NAIP 2022 flight.")
A = rca[cols].sum()
say(f"\nAll mapped RCA, NAIP 2022 at 1.25 m: tree canopy {A.iloc[0]:,.1f} ac ({A.iloc[0] / A.sum():.0%}), water {A.iloc[1]:,.1f} ac ({A.iloc[1] / A.sum():.0%}), open ground {A.iloc[2]:,.1f} ac ({A.iloc[2] / A.sum():.0%}).")
old, new = rca[rca.plat_year < 2023], rca[rca.plat_year >= 2023]
for label, d in (("platted 2022 or earlier (the photo shows them after development)", old), ("platted 2023 or later (the photo is from before the plat)", new), ("no plat year in the description", rca[rca.plat_year.isna()])):
    a = d[cols].sum()
    say(f"   {label}: {d.acres.sum():,.1f} ac; tree canopy {a.iloc[0] / a.sum():.0%}, water {a.iloc[1] / a.sum():.0%}, open ground {a.iloc[2] / a.sum():.0%}")
say(f"Sentinel-2, 10 m cells: {rca.in_2022_baseline_forest_cells_acres.sum():,.1f} ac of mapped RCA sits in cells that were forest in the 2022 baseline; {rca.forestlike_2026Q3_acres.sum():,.1f} ac of that is still forest-like in Jul-Sep 2026.")
say(f"Mapped RCA inside the release's clearing outlines (cleared since late 2022): {rca.in_clearing_outlines_2022_2026_acres.sum():,.1f} ac in {int((rca.in_clearing_outlines_2022_2026_acres >= 0.1).sum())} polygons.")
show = B[(B.acres >= MIN_PROJECT_AC) & ~B.conflict_flag]
c5 = ["project", "polygons", "last_plat_year", "acres", "tree_canopy_share_2022", "water_share_2022", "open_ground_share_2022", "in_clearing_outlines_2022_2026_acres", "share_of_2022_forest_still_forestlike_2026"]
ren = {"last_plat_year": "plat_yr", "tree_canopy_share_2022": "tree", "water_share_2022": "water", "open_ground_share_2022": "open", "in_clearing_outlines_2022_2026_acres": "cleared_ac", "share_of_2022_forest_still_forestlike_2026": "forest_kept_2026"}
say(f"\nBy project (the zoning case under each RCA polygon; parent project where one is defined), {MIN_PROJECT_AC:g} ac or more: {len(show)} projects. Largest 40:")
say(show[c5].rename(columns=ren).head(40).round(2).to_string(index=False))
say("\nProjects in the 2022+ case table or a parent project:")
say(show[show.in_2022plus_case_table][c5].rename(columns=ren).round(2).to_string(index=False))
low = show[(show.acres >= 2) & (show.last_plat_year < 2023)].sort_values("tree_canopy_share_2022")
say("\nLowest tree share among projects platted by 2022, 2 ac or more:")
say(low[c5].rename(columns=ren).head(15).round(2).to_string(index=False))
hit = show[show.in_clearing_outlines_2022_2026_acres >= 0.5].sort_values("in_clearing_outlines_2022_2026_acres", ascending=False)
say("\nMapped RCA inside clearing outlines, half an acre or more:")
say(hit[c5].rename(columns=ren).round(2).to_string(index=False))
if B.conflict_flag.any():
    say(f"\nFlagged: {int(B.conflict_flag.sum())} project(s) whose RCA description names the Seymour PUD are in the CSVs with conflict_flag = True and are left out of the tables above.")
open(os.path.join(OUT, "rca_layer_summary.txt"), "w").write("\n".join(L) + "\n")
print("\n".join(L))
