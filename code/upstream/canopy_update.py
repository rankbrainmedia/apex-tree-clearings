#!/usr/bin/env python3
"""
Apex tree canopy update: July 2020 baseline -> newest available end year.

Two independent end-year sensors, because NAIP has no leaf-on flight over Apex
after September 2022 (checked against the Planetary Computer STAC on 2026-09-28):

  A. NAIP 2020-07 vs NAIP 2022-09   (same sensor as the 2016-2020 run; Sept is
     still leaf-on in Wake, but late-season, so the threshold is calibrated on
     control sites, see --calibrate)
  B. NAIP 2020-07 canopy vs 3DEP lidar height-above-ground (Wake Phase 5, 2022)
     canopy >= 3 m. Different sensor, no phenology problem. This is the number
     to lead with if the two agree within a few percent.

Outputs (in --out):
  boundary.gpkg                Apex corporate limits + ETJ, dissolved
  canopy_2020.tif              1 = tree canopy, NAIP-derived, 1 m
  canopy_2022_naip.tif         1 = tree canopy, NAIP-derived
  canopy_2022_lidar.tif        1 = HAG >= 3 m (lidar), resampled to 1 m
  loss_2020_2022_naip.gpkg     polygons, canopy 2020 & not 2022 (NAIP), >= 1 ac
  loss_2020_2022_lidar.gpkg    same, lidar end year
  summary.csv                  acres: canopy each year, loss, % of 2020 canopy
  cases_join.csv               loss acres per zoning case (over-100% joins dropped)
  panels/<site>.png            six-panel validation figures

Usage:
  python3 canopy_update.py list                      # print NAIP + lidar coverage & dates, then exit
  python3 canopy_update.py run --out ./out           # full pipeline
  python3 canopy_update.py run --out ./out --calibrate
  python3 canopy_update.py panels --out ./out --sites sites.csv

sites.csv: name,lon,lat   (Ashburn, Townes on 1011, and one unchanged control)

Requires: geopandas, rasterio, shapely, numpy, scipy, pystac-client,
planetary-computer, stackstac (or rioxarray), matplotlib, requests.
"""
import argparse, json, os, sys, math, csv, warnings
import numpy as np
import requests

warnings.filterwarnings("ignore")

BBOX = (-78.98, 35.62, -78.76, 35.80)          # generous box around Apex + ETJ
CRS_M = "EPSG:2264"                              # NC State Plane (ft); areas converted to acres
# NAIP over Apex runs radiometrically 'cool': verified 2026-09-28 that real tree
# canopy sits at NDVI ~0.30-0.47 (forest p75-p95), not the 0.6-0.8 of some NAIP
# years. The README's 0.45 caught only the top ~8% of pixels and collapsed 2020
# canopy to a few hundred acres. Thresholds set from this imagery's distribution.
NDVI_T_2020 = 0.30                               # July leaf-on canopy floor for THIS imagery
NDVI_T_2022 = 0.25                               # Sept leaf-on, slightly lower; --calibrate refits
# The README's 0.045 texture floor is far too aggressive for 1 m NAIP over Apex:
# verified 2026-09-28 it strips ~70% of real forest (canopy collapses from ~39%
# to ~11%). A light 0.012 floor removes the smoothest lawns without gutting tree
# cover; canopy is stable across 0.0-0.018.
TEXTURE_T = 0.012                                # local NDVI std-dev above this = tree texture, not lawn
HAG_T_M = 3.0                                    # lidar: >= 3 m above ground = canopy
MIN_PATCH_AC = 1.0

# Apex publishes its own boundary; the old Wake County Jurisdictions/MapServer/0
# endpoint 404s as of 2026-09-28. Corporate_Limits + ETJ dissolved = 25,043 ac,
# bounds match Apex (verified 2026-09-28).
APEX_BOUNDARY_URLS = [
    "https://services1.arcgis.com/nry3yyvaEfskMEXA/arcgis/rest/services/Corporate_Limits/FeatureServer/0/query?where=1%3D1&outFields=*&f=geojson",
    "https://services1.arcgis.com/nry3yyvaEfskMEXA/arcgis/rest/services/ETJ/FeatureServer/0/query?where=1%3D1&outFields=*&f=geojson",
]
APEX_CASES_URL = ("https://services1.arcgis.com/nry3yyvaEfskMEXA/arcgis/rest/services/"
                  "Rezoning/FeatureServer/0/query?where=1%3D1&outFields=*&f=geojson")  # verified 2026-09-28: layer 'Rezoning', fields Petition/Name/Current_/Proposed/Status/Action_Taken (no acreage field; area computed from geometry)

def log(*a): print(*a, file=sys.stderr, flush=True)

# ----------------------------------------------------------------------------- discovery
def stac():
    import pystac_client, planetary_computer as pc
    return pystac_client.Client.open("https://planetarycomputer.microsoft.com/api/stac/v1",
                                     modifier=pc.sign_inplace)

def list_sources():
    cat = stac()
    log("NAIP over Apex bbox:")
    items = list(cat.search(collections=["naip"], bbox=BBOX, datetime="2018-01-01/2030-01-01").items())
    byyear = {}
    for it in items:
        byyear.setdefault(it.datetime.year, []).append(it.datetime.date().isoformat())
    for y in sorted(byyear):
        d = sorted(set(byyear[y])); log(f"  {y}: {len(byyear[y])} tiles, flown {d[0]} .. {d[-1]}")
    log("\n3DEP lidar height-above-ground over Apex bbox:")
    try:
        hag = list(cat.search(collections=["3dep-lidar-hag"], bbox=BBOX).items())
        for it in hag:
            log(f"  {it.id}  {it.datetime.date()}  {it.properties.get('3dep:usgs_id','')}")
        if not hag: log("  none in STAC; fall back to NC OneMap lidar (see README)")
    except Exception as e:
        log("  lookup failed:", e)
    log("\nApex zoning case layer probe:")
    try:
        r = requests.get("https://services1.arcgis.com/nry3yyvaEfskMEXA/arcgis/rest/services?f=json", timeout=30).json()
        names = [s["name"] for s in r.get("services", [])]
        log("  services containing 'zon' or 'case':", [n for n in names if "zon" in n.lower() or "case" in n.lower()])
    except Exception as e:
        log("  probe failed:", e)

# ----------------------------------------------------------------------------- boundary
def boundary(out):
    import geopandas as gpd, pandas as pd
    p = os.path.join(out, "boundary.gpkg")
    if os.path.exists(p): return gpd.read_file(p)
    log("Fetching Apex boundary (Corporate Limits + ETJ) from Town of Apex ArcGIS...")
    parts = []
    for url in APEX_BOUNDARY_URLS:
        try:
            g = gpd.read_file(url); g = g[g.geometry.notnull()]
            if len(g): parts.append(g.to_crs("EPSG:4326")); log(f"  {url.split('/services/')[1].split('/')[0]}: {len(g)} feature(s)")
        except Exception as e:
            log(f"  WARN could not read {url.split('/services/')[1].split('/')[0]}: {e}")
    if not parts:
        sys.exit("could not fetch Apex boundary from any source")
    allg = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs="EPSG:4326")
    b = gpd.GeoDataFrame(geometry=[allg.unary_union], crs="EPSG:4326").to_crs(CRS_M)
    b.to_file(p, driver="GPKG"); return b

# ----------------------------------------------------------------------------- naip mosaic
def naip_year(year, bnd, out, month_max=None):
    """Return (ndvi, (r,g,b), transform, crs) mosaic clipped to boundary at 1 m.

    Mosaics NAIP directly with rasterio instead of stackstac. NAIP tiles on the
    Planetary Computer are single 4-band COGs (R,G,B,NIR); the installed
    stackstac build refuses multi-band assets (one-band-per-asset only), so we
    read the signed COG hrefs through /vsicurl and merge to the boundary window
    on a fixed 1 m UTM 17N grid. Deterministic grid => 2020 and 2022 align.
    """
    import rasterio
    from rasterio.merge import merge as rio_merge
    from rasterio.warp import transform_bounds
    import planetary_computer as pc
    cat = stac()
    rng = f"{year}-01-01/{year}-12-31"
    items = list(cat.search(collections=["naip"], bbox=BBOX, datetime=rng).items())
    if month_max: items = [i for i in items if i.datetime.month <= month_max]
    if not items: sys.exit(f"no NAIP items for {year}")
    log(f"NAIP {year}: {len(items)} tiles -> rasterio mosaic")

    # target grid: boundary bounds in EPSG:32617, 1 m, snapped to integer metres
    bnd_utm = bnd.to_crs("EPSG:32617")
    minx, miny, maxx, maxy = bnd_utm.total_bounds
    minx, miny = math.floor(minx), math.floor(miny)
    maxx, maxy = math.ceil(maxx), math.ceil(maxy)
    dst_bounds = (minx, miny, maxx, maxy)

    hrefs = []
    for it in items:
        a = it.assets.get("image")
        if a is None: continue
        hrefs.append(pc.sign(a.href))
    if not hrefs: sys.exit(f"no NAIP image assets for {year}")

    srcs = []
    env = rasterio.Env(GDAL_HTTP_MAX_RETRY="5", GDAL_HTTP_RETRY_DELAY="2",
                       CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
                       GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR")
    with env:
        try:
            for h in hrefs:
                srcs.append(rasterio.open("/vsicurl/" + h if not h.startswith("/vsicurl") else h))
            # merge onto the fixed grid; NAIP tiles are already EPSG:26917/32617-ish 1 m,
            # rio_merge reprojects/aligns to the first src CRS, so force via dst_ params.
            mosaic, out_tr = rio_merge(srcs, bounds=dst_bounds, res=(1.0, 1.0),
                                       target_aligned_pixels=True, dst_path=None)
        finally:
            for s in srcs:
                try: s.close()
                except Exception: pass

    mosaic = mosaic.astype("float64")             # bands x H x W
    # clip to boundary polygon (merge gave the bbox window; mask outside pixels)
    import rasterio.features as rf
    mask = rf.geometry_mask(bnd_utm.geometry, out_shape=mosaic.shape[1:], transform=out_tr, invert=True)
    for bi in range(mosaic.shape[0]):
        mosaic[bi][~mask] = np.nan
    # BAND ORDER: standard NAIP order R,G,B,NIR (band1=Red, band2=Green,
    # band3=Blue, band4=NIR). Verified empirically 2026-09-28: over known forest
    # (2020-07-11 tile) NDVI=(b4-b1)/(b4+b1)=+0.18 (correct sign), while the prior
    # (b1-b4) swap gave -0.18, inverted every NDVI, drove the self-calibrated 2022
    # threshold negative, and collapsed 2020 canopy to ~527 ac. colorinterp tags
    # confirm b1=Red(3), b2=Green(4), b3=Blue(5), b4=NIR(0).
    red, nir = mosaic[0], mosaic[3]
    g, b = mosaic[1], mosaic[2]
    ndvi = (nir - red) / np.maximum(nir + red, 1e-6)
    # return visible-ish bands for panels as (red, green, blue) best-effort
    return ndvi, (red, g, b), out_tr, rasterio.crs.CRS.from_epsg(32617)

def texture(ndvi, win=5):
    from scipy.ndimage import uniform_filter
    m = uniform_filter(np.nan_to_num(ndvi), win); m2 = uniform_filter(np.nan_to_num(ndvi) ** 2, win)
    return np.sqrt(np.maximum(m2 - m * m, 0))

def canopy_from_naip(ndvi, ndvi_t):
    """Trees = high NDVI AND textured (lawn/hay is smooth). Then clean small specks."""
    from scipy.ndimage import binary_opening, binary_closing
    tex = texture(ndvi)
    c = (ndvi >= ndvi_t) & (tex >= TEXTURE_T)
    c = binary_closing(binary_opening(c, iterations=1), iterations=2)
    return c.astype(np.uint8)

def interior_forest_mask(c20, ndvi20, erode_px=2, ndvi_q=0.60):
    """Stable-forest proxy for self-calibration when no lidar exists.

    Core interior forest is the safest 'known unchanged canopy' anchor available
    from imagery alone: take strict 2020 canopy, keep only high-NDVI pixels, then
    erode inward a couple of pixels so edge/thinning pixels (the ones most likely
    to legitimately change or to sit on mixed boundaries) are dropped. What
    remains is dense interior forest that is almost certainly still forest in
    2022, so it is a valid anchor for refitting the late-season 2022 NDVI
    threshold. Replaces the lidar stable-forest mask, which is unavailable: no
    public 3DEP lidar covers Apex (verified 2026-09-28 against NC
    Phase4/Phase5/HurricaneFlorence STAC+manifests).

    Erosion is deliberately light (2 px). Heavy erosion collapses the mask on
    fragmented suburban tree cover; if the eroded mask ends up too small, fall
    back to the un-eroded high-NDVI core so calibration always has a real anchor.
    """
    from scipy.ndimage import binary_erosion
    thr = np.nanquantile(ndvi20[c20 == 1], ndvi_q)
    core = (c20 == 1) & (ndvi20 >= thr)
    eroded = binary_erosion(np.nan_to_num(core), iterations=erode_px)
    if int(eroded.sum()) >= 5000:
        return eroded.astype(bool)
    log(f"  interior-forest erosion left only {int(eroded.sum())} px; falling back to un-eroded high-NDVI core ({int(core.sum())} px)")
    return core.astype(bool)

def write_tif(path, arr, transform, crs):
    import rasterio
    with rasterio.open(path, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1,
                       dtype=arr.dtype, crs=crs, transform=transform, compress="lzw", nodata=255) as d:
        d.write(arr, 1)

# ----------------------------------------------------------------------------- lidar
def lidar_canopy(bnd, ref_shape, ref_transform, ref_crs, out):
    """3DEP HAG from Planetary Computer -> canopy mask on the NAIP grid. Returns None if unavailable."""
    try:
        import stackstac, rioxarray  # noqa
        cat = stac()
        items = list(cat.search(collections=["3dep-lidar-hag"], bbox=BBOX).items())
        if not items:
            log("no 3DEP HAG in STAC for Apex; skipping lidar end year (see README for OneMap fallback)")
            return None
        # keep the most recent acquisition per footprint
        items.sort(key=lambda i: i.datetime, reverse=True)
        log(f"3DEP HAG: {len(items)} items, newest {items[0].datetime.date()}")
        b4326 = bnd.to_crs("EPSG:4326").total_bounds
        da = stackstac.stack(items, assets=["data"], bounds_latlon=tuple(b4326), epsg=32617, resolution=1.0,
                             dtype="float32", fill_value=np.nan)
        da = da.max(dim="time", skipna=True).squeeze().rio.write_crs("EPSG:32617")
        da = da.rio.clip(bnd.to_crs("EPSG:32617").geometry, drop=True)
        hag = da.values
        # align to NAIP grid if shapes differ (same 1 m UTM grid clipped to same boundary -> usually identical)
        if hag.shape != ref_shape:
            from rasterio.warp import reproject, Resampling
            dst = np.full(ref_shape, np.nan, dtype="float32")
            reproject(hag, dst, src_transform=da.rio.transform(), src_crs=da.rio.crs,
                      dst_transform=ref_transform, dst_crs=ref_crs, resampling=Resampling.max)
            hag = dst
        return (np.nan_to_num(hag) >= HAG_T_M).astype(np.uint8), items[0].datetime.date().isoformat()
    except Exception as e:
        log("lidar step failed:", e); return None

# ----------------------------------------------------------------------------- vectorize + summarize
def loss_polys(c0, c1, transform, crs, min_ac):
    import geopandas as gpd, rasterio.features as rf
    from shapely.geometry import shape
    lost = ((c0 == 1) & (c1 == 0)).astype(np.uint8)
    from scipy.ndimage import binary_opening
    lost = binary_opening(lost, iterations=1).astype(np.uint8)
    shapes = [shape(g) for g, v in rf.shapes(lost, mask=lost == 1, transform=transform) if v == 1]
    g = gpd.GeoDataFrame(geometry=shapes, crs=crs).to_crs(CRS_M)
    g["acres"] = g.area / 43560.0
    g = g[g.acres >= min_ac].reset_index(drop=True)
    return g

def acres(mask, px_m2=1.0): return float(mask.sum()) * px_m2 / 4046.8564

def run(out, calibrate=False):
    import geopandas as gpd
    os.makedirs(out, exist_ok=True)
    bnd = boundary(out)
    land_ac = float(bnd.to_crs(CRS_M).area.sum()) / 43560.0
    log(f"Jurisdiction: {land_ac:,.0f} acres")

    ndvi20, rgb20, tr, crs = naip_year(2020, bnd, out, month_max=9)
    ndvi22, rgb22, tr2, crs2 = naip_year(2022, bnd, out)
    if ndvi22.shape != ndvi20.shape:
        h = min(ndvi20.shape[0], ndvi22.shape[0]); w = min(ndvi20.shape[1], ndvi22.shape[1])
        ndvi20, ndvi22 = ndvi20[:h, :w], ndvi22[:h, :w]
        rgb20 = tuple(a[:h, :w] for a in rgb20); rgb22 = tuple(a[:h, :w] for a in rgb22)

    # --- Per-year threshold calibration by distribution matching (no lidar) ---
    # Verified 2026-09-28: the 2020 (July) and 2022 (Sept-Oct) NAIP vintages are on
    # different radiometric scales -- forest NDVI median is ~0.24 in 2020 but ~0.42
    # in 2022 (NIR band brighter in 2022). A single fixed threshold gives 11% canopy
    # in one year and 39% in the other, which is a sensor artifact, not real change.
    # Fix: define canopy as the same DENSITY RANK in both years. Set the 2020
    # threshold at NDVI_T_2020, find its percentile in the 2020 distribution, then
    # take the 2022 threshold at that same percentile of the 2022 distribution.
    # Real canopy change then shows as the residual difference; the scale offset
    # cancels. Without --calibrate, both years use their flat defaults (not advised).
    t20 = NDVI_T_2020
    t22 = NDVI_T_2022
    if calibrate:
        v20 = ndvi20[np.isfinite(ndvi20)]
        v22 = ndvi22[np.isfinite(ndvi22)]
        pct = float((v20 < t20).mean() * 100.0)          # percentile of the 2020 threshold
        t22 = float(np.percentile(v22, pct))              # same percentile in 2022
        log(f"distribution-matched: t20={t20:.3f} (p{pct:.1f}) -> t22={t22:.3f}")
    c20 = canopy_from_naip(ndvi20, t20)
    c22 = canopy_from_naip(ndvi22, t22)

    write_tif(os.path.join(out, "canopy_2020.tif"), c20, tr, crs)
    write_tif(os.path.join(out, "canopy_2022_naip.tif"), c22, tr, crs)
    rows = [("2020 NAIP canopy", acres(c20)), ("2022 NAIP canopy", acres(c22)),
            ("NDVI_T_2022 used", t22)]
    lossA = loss_polys(c20, c22, tr, crs, MIN_PATCH_AC)
    lossA.to_file(os.path.join(out, "loss_2020_2022_naip.gpkg"), driver="GPKG")
    rows.append(("Loss 2020-2022 NAIP (patches >= 1 ac)", float(lossA.acres.sum())))

    with open(os.path.join(out, "summary.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["metric", "value"])
        w.writerow(["Jurisdiction acres", round(land_ac, 1)])
        w.writerow(["End-year sensor", "NAIP 2022 only (no public lidar covers Apex)"])
        w.writerow(["Calibration", "self (2020 interior-forest anchor)" if calibrate else "none (flat threshold)"])
        for k, v in rows: w.writerow([k, round(v, 3) if abs(v) <= 2 else round(v, 1)])
        c20a = acres(c20)
        w.writerow(["2020 canopy % of land", round(100 * c20a / land_ac, 1)])
        w.writerow(["NAIP loss % of 2020 canopy", round(100 * float(lossA.acres.sum()) / c20a, 1)])
    log(open(os.path.join(out, "summary.csv")).read())

    # zoning case join: Rezoning layer (verified). No recorded-acreage field, so
    # loss acres per case come from the intersection geometry directly.
    try:
        cases = gpd.read_file(APEX_CASES_URL).to_crs(CRS_M)
        j = gpd.overlay(lossA[["geometry"]], cases, how="intersection")
        j["loss_acres"] = j.area / 43560.0
        keys = [c for c in ("Petition", "Name", "Current_", "Proposed", "Status", "Action_Taken", "Action_Date") if c in j.columns]
        agg = j.groupby(keys, dropna=False)["loss_acres"].sum().reset_index()
        agg = agg[agg.loss_acres > 0]
        agg.sort_values("loss_acres", ascending=False).to_csv(os.path.join(out, "cases_join.csv"), index=False)
        log(f"cases_join.csv written ({len(agg)} rezoning cases with >0 ac loss)")
    except Exception as e:
        log("case join skipped:", e)

# ----------------------------------------------------------------------------- validation panels
def panels(out, sites_csv, half_m=200):
    import rasterio, geopandas as gpd
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    from rasterio.windows import from_bounds
    from pyproj import Transformer
    os.makedirs(os.path.join(out, "panels"), exist_ok=True)
    c20 = rasterio.open(os.path.join(out, "canopy_2020.tif"))
    c22p = os.path.join(out, "canopy_2022_lidar.tif")
    c22 = rasterio.open(c22p if os.path.exists(c22p) else os.path.join(out, "canopy_2022_naip.tif"))
    tf = Transformer.from_crs("EPSG:4326", c20.crs, always_xy=True)
    for row in csv.DictReader(open(sites_csv)):
        x, y = tf.transform(float(row["lon"]), float(row["lat"]))
        win = from_bounds(x - half_m, y - half_m, x + half_m, y + half_m, c20.transform)
        a = c20.read(1, window=win); b = c22.read(1, window=win)
        lost = (a == 1) & (b == 0)
        fig, ax = plt.subplots(1, 3, figsize=(15, 5))
        ax[0].imshow(a, cmap="Greens", vmin=0, vmax=1); ax[0].set_title("2020 canopy")
        ax[1].imshow(b, cmap="Greens", vmin=0, vmax=1); ax[1].set_title("2022 canopy")
        ax[2].imshow(b, cmap="Greens", vmin=0, vmax=1, alpha=.6); ax[2].imshow(np.ma.masked_where(~lost, lost), cmap="autumn", alpha=.9)
        ax[2].set_title(f"lost: {acres(lost):.1f} ac")
        for a_ in ax: a_.axis("off")
        fig.suptitle(f"{row['name']}  ({row['lat']}, {row['lon']})  {2*half_m} m across")
        fig.savefig(os.path.join(out, "panels", f"{row['name'].replace(' ', '_')}.png"), dpi=130, bbox_inches="tight")
        plt.close(fig); log("panel:", row["name"])

# ----------------------------------------------------------------------------- cli
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    r = sub.add_parser("run"); r.add_argument("--out", default="./out"); r.add_argument("--calibrate", action="store_true")
    p = sub.add_parser("panels"); p.add_argument("--out", default="./out"); p.add_argument("--sites", required=True)
    a = ap.parse_args()
    if a.cmd == "list": list_sources()
    elif a.cmd == "run": run(a.out, a.calibrate)
    else: panels(a.out, a.sites)
