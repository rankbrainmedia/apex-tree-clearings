#!/usr/bin/env python
"""Step 6: write the public release tables.

- OUT/clearings.geojson : one feature per clearing event, EPSG:4326.
- OUT/clearings.csv     : the same attributes, without geometry.
- OUT/scenes.csv        : every unique Sentinel-2 scene in the query window, used or skipped.

Geometry: the event polygons follow the 10 m pixel edges. They are written unsimplified, with
coordinates rounded to 6 decimal places (about 0.1 m), because the file is already ~1.2 MB.
Pass --simplify-m N to apply a topology-preserving simplification of N metres in UTM 17N first.
"""
import argparse, json, os
import geopandas as gpd, pandas as pd
from shapely import set_precision
import config as C

ap = argparse.ArgumentParser()
ap.add_argument("--simplify-m", type=float, default=0.0)
args = ap.parse_args()

g = gpd.read_file(os.path.join(C.OUT, "events_full_geometry.geojson")).to_crs(C.EPSG)
t = pd.read_csv(os.path.join(C.WORK, "events_table.csv"))[["clear_id", "confirmed_frac", "npx", "patch_id"]]
g = g.merge(t, on="clear_id", how="left")
if args.simplify_m > 0:
    g["geometry"] = g.geometry.simplify(args.simplify_m, preserve_topology=True)
g = g.to_crs(4326)
g["geometry"] = set_precision(g.geometry.values, 1e-6)
out = gpd.GeoDataFrame({
    "id": g.clear_id,
    "acres": g.acres.round(2),
    "first_quarter": g.first_quarter,
    "status": g.provisional.map({True: "provisional", False: "confirmed"}),
    "confirmed_px_share": g.confirmed_frac.round(3),
    "pixels_10m": g.npx.astype(int),
    "patch_id": g.patch_id.astype(int),
    "centroid_lon": g.cent_lon.round(6),
    "centroid_lat": g.cent_lat.round(6),
}, geometry=g.geometry, crs=4326).sort_values("id")
fn = os.path.join(C.OUT, "clearings.geojson")
if os.path.exists(fn):
    os.remove(fn)
out.to_file(fn, driver="GeoJSON", COORDINATE_PRECISION=6)
out.drop(columns="geometry").to_csv(os.path.join(C.OUT, "clearings.csv"), index=False)
print(f"clearings: {len(out)} events, {out.acres.sum():.1f} ac "
      f"({out[out.status == 'confirmed'].acres.sum():.1f} confirmed, "
      f"{out[out.status == 'provisional'].acres.sum():.1f} provisional); "
      f"geojson {os.path.getsize(fn) / 1e6:.2f} MB")

# ---- scenes ----
raw = json.load(open(os.path.join(C.WORK, "items.json")))
meta = {d["id"]: d["properties"] for d in raw}
best = {}
for d in raw:
    p = d["properties"]; key = (p["datetime"][:19], p["sat:relative_orbit"])
    if key not in best or d["id"] > best[key]["id"]:
        best[key] = d
kept = {d["id"] for d in best.values()}
log = pd.read_csv(os.path.join(C.WORK, "scenes.csv"), header=None,
                  names=["quarter", "scene_id", "status", "aoi_clear_fraction"]).drop_duplicates("scene_id")
assert set(log.scene_id) == kept, "scenes.csv does not match the de-duplicated item list"
rows = []
for r in log.itertuples():
    p = meta[r.scene_id]
    superseded = sorted(i for i, q in meta.items() if i != r.scene_id and
                        (q["datetime"][:19], q["sat:relative_orbit"]) == (p["datetime"][:19], p["sat:relative_orbit"]))
    rows.append(dict(scene_id=r.scene_id, datetime_utc=p["datetime"], quarter=r.quarter,
                     platform=p.get("platform"), relative_orbit=p["sat:relative_orbit"], mgrs_tile=p["s2:mgrs_tile"],
                     processing_baseline=p.get("s2:processing_baseline"),
                     tile_cloud_cover_pct=round(p.get("eo:cloud_cover", float("nan")), 2),
                     used_in_composite="yes" if r.status == "ok" else "no",
                     reason=("" if r.status == "ok" else "skipped: <20% of data-covered AOI clear (or <1% of AOI clear)"),
                     aoi_clear_fraction=r.aoi_clear_fraction,
                     superseded_duplicates=";".join(superseded)))
sc = pd.DataFrame(rows).sort_values("datetime_utc")
sc.to_csv(os.path.join(C.OUT, "scenes.csv"), index=False)
print(f"scenes: {len(sc)} unique ({(sc.used_in_composite == 'yes').sum()} used, "
      f"{(sc.used_in_composite == 'no').sum()} skipped); {len(raw)} STAC items incl. reprocessed duplicates")
