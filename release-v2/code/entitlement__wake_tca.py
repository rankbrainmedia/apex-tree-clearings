#!/usr/bin/env python
"""wake_tca.py: Wake County's Land Cover Analysis / Tree Canopy Assessment (NAIP 2010 and 2020) against the clearing data.

    ../apex-canopy/df-venv/bin/python wake_tca.py            # every step; finished steps are read from cache
    ../apex-canopy/df-venv/bin/python wake_tca.py report     # only the tables (pull, rasters, naip must have run)

Steps
  pull      public layers from Wake County and the Town of Apex -> out_wake_tca/layers/ (small) and cache/ (large)
  rasters   the County's 2020 canopy raster at 1 m over Apex, and its 2010 and 2020 canopy map tiles, on the 10 m grid
  naip      tree canopy per 10 m cell from the July 25, 2025 NAIP flight, with the recipe of ../prerezoning/naip_canopy.py
  report    the five tables and summary.txt

Reads, and never writes: ../apex-canopy/s2/cache/baseline.npz, ../apex-canopy/prerezoning_cache/ (detect_2017, NAIP 2020),
inputs/town_*.geojson, out/pipeline_2022plus.csv, ../prerezoning/naip_canopy.py (imported for its functions).
Everything this script writes is under out_wake_tca/. Method, definitions and caveats: out_wake_tca/NOTES.md.
"""
import glob, io, json, math, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import numpy as np, pandas as pd, geopandas as gpd, requests, shapely
import rasterio
from affine import Affine
from pyproj import Transformer
from rasterio import features
from rasterio.warp import reproject, Resampling

HERE = os.path.dirname(os.path.abspath(__file__))
AC = os.path.join(HERE, "..", "apex-canopy")
PRE = os.path.join(AC, "prerezoning_cache")
OUT = os.path.join(HERE, "out_wake_tca")
LAYERS = os.path.join(OUT, "layers")
CACHE = os.path.join(OUT, "cache")
for d in (OUT, LAYERS, CACHE):
    os.makedirs(d, exist_ok=True)

TODAY = time.strftime("%Y-%m-%d")
UA = {"User-Agent": "canopy-layers/1.0"}
M2_AC = 4046.8564
X0, X1, Y0, Y1 = 683800, 698840, 3948740, 3961460          # the release's 10 m grid, EPSG:32617
W, H = (X1 - X0) // 10, (Y1 - Y0) // 10
T10 = Affine(10, 0, X0, 0, -10, Y1)
SHAPE = (H, W)
PX = 100 / M2_AC
BBOX84 = [-78.969003, 35.664933, -78.802403, 35.778735]     # as in ../prerezoning/naip_canopy.py

WAKE = "https://services1.arcgis.com/a7CWfuGP5ZnLYE7I/arcgis/rest/services/"
APEX = "https://services1.arcgis.com/nry3yyvaEfskMEXA/arcgis/rest/services/"
# name: (url, attribute fields or "*", clip to the Apex bounding box?, large -> cache/ instead of layers/)
SOURCES = {
    "wake_block_groups":          (WAKE + "Land_Cover_Canopy_Change_Metrics/FeatureServer/6", "*", False, False),
    "wake_planning_jurisdiction": (WAKE + "Land_Cover_Canopy_Change_Metrics/FeatureServer/5", "*", False, False),
    "wake_planning_excl_city":    (WAKE + "Land_Cover_Canopy_Change_Metrics/FeatureServer/4", "*", False, False),
    "wake_corporate_limits":      (WAKE + "Land_Cover_Canopy_Change_Metrics/FeatureServer/3", "*", False, False),
    "wake_county_boundary":       (WAKE + "Land_Cover_Canopy_Change_Metrics/FeatureServer/0", "*", False, False),
    "wake_project_boundary":      (WAKE + "Land_Cover_Canopy_Change_Metrics/FeatureServer/1", "*", False, False),
    "wake_equity_combined_2023":  (WAKE + "Equity_Combined_2023/FeatureServer/0", "GEOID,TOTAL_SCORE,TOTAL_SCORE_1,COMBINED_SCORE,COMBINED_RANK", False, False),
    "wake_equity_combined_2024":  (WAKE + "EQUITY_COMBINED_2024/FeatureServer/0", "GEOID,TOTAL_SCORE,TOTAL_SCORE_1,COMBINED_SCORE", False, False),
    "wake_priority_planting_areas": (WAKE + "Tree_Planting_Priorities_WFL1/FeatureServer/1",
                                     "OBJECTID,ACRES,City_County,PublicLand_Owner,StormMean,StormPri,TempMean,TempPri,SocialEquMean,SocialEquPri,SocialCompMean,SocialCompPri,CompositeMean,CompositePri", True, True),
    "apex_context_areas_2055":    (APEX + "Peak_Plan_2055_Context_Areas_STAFF_DRAFT/FeatureServer/209", "FID,Name", False, False),
    # the parcel fields of this layer (owner, address) are not requested: private individuals
    "apex_place_types_2055":      (APEX + "Peak_Plan_2055_Public_Forum_3/FeatureServer/238", "FID,PT_RD6,PT_CAT,SCENARIO,DEV_CON,DEV_STAT", False, True),
    "apex_corporate_limits":      (APEX + "Corporate_Limits/FeatureServer/0", "*", False, False),
    "apex_etj":                   (APEX + "ETJ/FeatureServer/0", "*", False, False),
    "apex_future_planning_area":  (APEX + "Apex_Future_Planning_Area/FeatureServer/5", "*", False, False),
}
CANOPY_2020_IMG = "https://maps.raleighnc.gov/images/rest/services/DeciduousConiferousCanopy2020/ImageServer"   # the County's 1 m raster, served by Raleigh
TILES = "https://tiles.arcgis.com/tiles/a7CWfuGP5ZnLYE7I/arcgis/rest/services/{}/MapServer/tile/{}/{}/{}"       # Canopy2010, TotalCanopy2020
TILE_Z = 15                                                                                                     # deepest level the County cached (about 3.9 m on the ground)
NAIP_2025_PREFIX = "v002/nc/2025/nc_030cm_2025/35078/"                                                          # Planetary Computer storage; not yet in its search catalog
NAIP_SEAMLINES_2025 = "https://services.arcgis.com/LLVEmB8Lsae3Um4s/arcgis/rest/services/2025_North_Carolina_Image_Dates/FeatureServer/0"

SINCE_Q = "2020Q3"            # first quarter after the NAIP 2020 flight (July 11-12, 2020 over most of Apex), as in office_period.py
NAIP25_LAST_Q = "2025Q2"      # last full quarter before the July 25, 2025 flight
FOREST_FRAC = 0.5             # a 10 m cell is forest if at least half of it is canopy (the release's rule)
LOST_PCT, CLEARING_PCT, CLEARING_MIN_AC = 2.0, 2.0, 5.0     # Claude's thresholds for the block-group classes: see NOTES.md
COI = {"23CZ13": "Seymour Mixed Use PUD is next to the author's home: left out of totals and disclosed",
       "24CZ19": "applicant is Barnett Properties, LLC: disclosed (the applicant is named in Barnett v. Seymour)",
       "24CZ20": "its PUD text names the Seymour PUD as the adjacent neighbourhood: held",
       "24CZ08": "its application lists the proposed Seymour Mixed Use PUD as adjacent: disclosed (connected to the Seymour PUD)"}
HEADLINE_OUT = {"23CZ13"}     # left out of headline totals, as in entitlement.py
MANUAL_STATUS = {"26CZ05": "Approved", "25CZ13": "Approved"}       # Adam, 2026-11-24 (the Rezoning layer says Proposed)
PRI = ["Very High", "High", "Moderate", "Low", "Very Low"]


def get(url, params=None, tries=5, **kw):
    for i in range(tries):
        try:
            r = requests.get(url, params=params, timeout=180, headers=UA, **kw)
            if r.status_code == 200:
                return r
        except Exception:
            pass
        time.sleep(2 + 3 * i)
    raise SystemExit(f"request failed: {url}")


def latest(name, folder=None):
    f = sorted(glob.glob(os.path.join(folder or LAYERS, name + "_2*.geojson")) + glob.glob(os.path.join(CACHE, name + "_2*.geojson")))
    if not f:
        raise SystemExit(f"{name}: not pulled yet, run the pull step")
    return f[-1]


def load(name, crs=32617):
    g = gpd.read_file(latest(name)).to_crs(crs)
    g["geometry"] = shapely.make_valid(g.geometry.values)
    return g


def burn(geoms, value=1, dtype="uint8", all_touched=False):
    geoms = [g for g in geoms if g is not None and not g.is_empty]
    if not geoms:
        return np.zeros(SHAPE, dtype)
    return features.rasterize([(g, value) for g in geoms], out_shape=SHAPE, transform=T10, fill=0, dtype=dtype, all_touched=all_touched)


def parse_case(c):
    m = re.match(r"^0?(\d{2})([A-Z]{2,3})\d", str(c).strip().upper())
    if not m:
        return None, None
    y = int(m.group(1))
    return (2000 + y if y <= 30 else 1900 + y), m.group(2)


# ------------------------------------------------------------------------------------------------ 1. pull
def pull(force=False):
    src_file = os.path.join(LAYERS, "SOURCES.json")
    meta = json.load(open(src_file)) if os.path.exists(src_file) else {}
    for name, (url, fields, clip, big) in SOURCES.items():
        folder = CACHE if big else LAYERS
        if not force and glob.glob(os.path.join(folder, name + "_2*.geojson")):
            continue
        info = get(url, {"f": "json"}).json()
        oid = next(f["name"] for f in info["fields"] if f["type"] == "esriFieldTypeOID")
        page = min(int(info.get("maxRecordCount", 1000)), 2000)
        p = {"where": "1=1", "outFields": fields, "f": "geojson", "outSR": 4326, "orderByFields": oid, "resultRecordCount": page}
        if clip:
            p |= {"geometry": ",".join(map(str, BBOX84)), "geometryType": "esriGeometryEnvelope", "inSR": 4326, "spatialRel": "esriSpatialRelIntersects"}
        feats, off = [], 0
        while True:
            fc = get(url + "/query", p | {"resultOffset": off}).json()
            if "features" not in fc:
                raise SystemExit(f"{name}: {str(fc)[:300]}")
            feats += fc["features"]
            off += len(fc["features"])
            if len(fc["features"]) < page:
                break
        fn = os.path.join(folder, f"{name}_{TODAY}.geojson")
        json.dump({"type": "FeatureCollection", "features": feats}, open(fn, "w"))
        edit = (info.get("editingInfo") or {}).get("dataLastEditDate") or (info.get("editingInfo") or {}).get("lastEditDate")
        meta[name] = dict(url=url, fields=fields, clipped_to_apex_bbox=clip, features=len(feats), pulled=TODAY, file=os.path.relpath(fn, OUT),
                          layer_last_edit=time.strftime("%Y-%m-%d", time.gmtime(edit / 1000)) if edit else None)
        print(f"pulled {name}: {len(feats)} features", flush=True)
        json.dump(meta, open(src_file, "w"), indent=1)
    return meta


# ------------------------------------------------------------------------------------------------ 2. rasters
def to_grid(src100, src_transform, src_crs):
    """a 0/100 uint8 array -> share (0..1) of each 10 m cell, by averaging"""
    dst = np.zeros(SHAPE, np.float32)
    reproject(src100, dst, src_transform=src_transform, src_crs=src_crs, dst_transform=T10, dst_crs="EPSG:32617", resampling=Resampling.average)
    return dst / 100


def canopy_2020_1m():
    """The County's 2020 canopy raster (1 deciduous, 2 coniferous) at its own 1 m pixels, over the grid. Cached as a GeoTIFF."""
    fn = os.path.join(CACHE, "wake_canopy_2020_1m_apex.tif")
    if os.path.exists(fn):
        return fn
    info = get(CANOPY_2020_IMG, {"f": "json"}).json()
    e, px = info["extent"], info["pixelSizeX"]
    tr = Transformer.from_crs(32617, 2264, always_xy=True)
    xs, ys = tr.transform([X0, X1, X0, X1], [Y0, Y0, Y1, Y1])
    c0, c1 = int((min(xs) - e["xmin"]) / px) - 4, int((max(xs) - e["xmin"]) / px) + 5
    r0, r1 = int((e["ymax"] - max(ys)) / px) - 4, int((e["ymax"] - min(ys)) / px) + 5
    out = np.zeros((r1 - r0, c1 - c0), np.uint8)
    B = 3500
    jobs = [(r, c) for r in range(r0, r1, B) for c in range(c0, c1, B)]

    def one(rc):
        r, c = rc
        h, w = min(B, r1 - r), min(B, c1 - c)
        bb = (e["xmin"] + c * px, e["ymax"] - (r + h) * px, e["xmin"] + (c + w) * px, e["ymax"] - r * px)
        t = get(CANOPY_2020_IMG + "/exportImage", dict(bbox=",".join(f"{v:.6f}" for v in bb), size=f"{w},{h}", format="tiff", pixelType="U8", interpolation="RSP_NearestNeighbor", f="image"))
        with rasterio.open(io.BytesIO(t.content)) as s:
            a = s.read(1)
        assert a.shape == (h, w), (a.shape, h, w)
        out[r - r0:r - r0 + h, c - c0:c - c0 + w] = np.where((a == 1) | (a == 2), a, 0)
        return rc

    with ThreadPoolExecutor(4) as ex:
        for i, _ in enumerate(ex.map(one, jobs)):
            print(f"  2020 canopy raster block {i + 1}/{len(jobs)}", flush=True)
    tf = Affine(px, 0, e["xmin"] + c0 * px, 0, -px, e["ymax"] - r0 * px)
    with rasterio.open(fn, "w", driver="GTiff", height=out.shape[0], width=out.shape[1], count=1, dtype="uint8", crs="EPSG:2264", transform=tf, compress="deflate", tiled=True, nodata=255) as d:
        d.write(out, 1)
        d.update_tags(source=CANOPY_2020_IMG, pulled=TODAY, values="0 not canopy or outside Wake County, 1 deciduous canopy, 2 coniferous canopy")
    return fn


def tile_mosaic(service):
    """Canopy map tiles (transparent = not canopy) at TILE_Z over the grid, as a 0/100 array in web mercator."""
    n = 2 ** TILE_Z
    xs = [int((lon + 180) / 360 * n) for lon in (BBOX84[0] - 0.01, BBOX84[2] + 0.01)]
    ys = [int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n) for lat in (BBOX84[3] + 0.01, BBOX84[1] - 0.01)]
    out = np.zeros(((ys[1] - ys[0] + 1) * 256, (xs[1] - xs[0] + 1) * 256), np.uint8)
    import cv2

    def one(xy):
        x, y = xy
        r = requests.get(TILES.format(service, TILE_Z, y, x), timeout=120, headers=UA)
        if r.status_code == 404:          # no tile: nothing drawn there
            return
        r.raise_for_status()
        im = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_UNCHANGED)
        a = (im[..., 3] > 0) if im.ndim == 3 and im.shape[-1] == 4 else np.ones(im.shape[:2], bool)       # a tile with no alpha band is fully drawn
        out[(y - ys[0]) * 256:(y - ys[0] + 1) * 256, (x - xs[0]) * 256:(x - xs[0] + 1) * 256] = a * 100

    with ThreadPoolExecutor(8) as ex:
        list(ex.map(one, [(x, y) for x in range(xs[0], xs[1] + 1) for y in range(ys[0], ys[1] + 1)]))
    R = 20037508.342787
    res = 2 * R / (256 * n)
    return out, Affine(res, 0, -R + xs[0] * 256 * res, 0, -res, R - ys[0] * 256 * res)


def rasters():
    fn = os.path.join(CACHE, "wake_canopy_10m.npz")
    if os.path.exists(fn):
        return fn
    tif = canopy_2020_1m()
    with rasterio.open(tif) as s:
        a, tf = s.read(1), s.transform
    frac20 = to_grid(((a > 0) * 100).astype(np.uint8), tf, "EPSG:2264")
    conif20 = to_grid(((a == 2) * 100).astype(np.uint8), tf, "EPSG:2264")
    del a
    z = {"frac2020": frac20, "conif2020": conif20}
    for svc, key in (("Canopy2010", "tiles2010"), ("TotalCanopy2020", "tiles2020")):
        m, mtf = tile_mosaic(svc)
        z[key] = to_grid(m, mtf, "EPSG:3857")
        print(f"  {svc} tiles: {m.shape[0] // 256 * (m.shape[1] // 256)} tiles, drawn share {m.mean() / 100:.3f}", flush=True)
    np.savez_compressed(fn, **z)
    return fn


# ------------------------------------------------------------------------------------------------ 3. NAIP 2025
def naip_2025():
    fn = os.path.join(CACHE, "naip", "canopy_2025.npz")
    if os.path.exists(fn):
        return fn
    sys.path.insert(0, os.path.join(HERE, "..", "prerezoning"))
    import naip_canopy as NC                      # functions only; its own cache folder is not written to
    import planetary_computer as pc
    NC.CACHE = os.path.join(CACHE, "naip")
    os.makedirs(os.path.join(NC.CACHE, "tiles"), exist_ok=True)
    tok = get("https://planetarycomputer.microsoft.com/api/sas/v1/token/naipeuwest/naip").json()["token"]
    xml = get(f"https://naipeuwest.blob.core.windows.net/naip?restype=container&comp=list&prefix={NAIP_2025_PREFIX}&{tok}").text
    names = sorted(n for n in re.findall(r"<Name>([^<]+\.tif)</Name>", xml) if re.search(r"m_35078(09|10|17|18)_", n))
    items = [SimpleNamespace(id="nc_" + os.path.basename(n)[:-4], datetime=pd.Timestamp(re.search(r"_(\d{8})\.tif$", n).group(1)).to_pydatetime(),
                             assets={"image": SimpleNamespace(href=pc.sign("https://naipeuwest.blob.core.windows.net/naip/" + n))}) for n in names]
    print(f"  NAIP 2025: {len(items)} candidate tiles", flush=True)
    with ThreadPoolExecutor(4) as ex:
        tiles = [t for t in ex.map(NC.read_tile, items) if t]
    pool = {}
    for tid, date, r0, r1, c0, c1 in tiles:
        nd, valid = NC.load_ndvi(tid)
        pool.setdefault(date, []).append(nd[NC.up(NC.STABLE[r0:r1, c0:c1]) & valid])
    thr = {d: float(np.quantile(np.concatenate(v), NC.NDVI_Q)) for d, v in pool.items()}
    frac = np.full(SHAPE, np.nan, np.float32); infos = []
    for tid, date, r0, r1, c0, c1 in tiles:
        nd, valid = NC.load_ndvi(tid)
        sl = (slice(r0, r1), slice(c0, c1))
        can = (nd >= thr[date]) & (NC.texture(nd) >= NC.TEXTURE_T) & valid
        can = NC.ndimage.binary_closing(NC.ndimage.binary_opening(can, iterations=1), iterations=2)
        st, br = NC.up(NC.STABLE[sl]) & valid, NC.up(NC.BARE[sl]) & valid
        h, w = r1 - r0, c1 - c0
        nval = valid.reshape(h, NC.SUB, w, NC.SUB).sum((1, 3))
        f = np.where(nval >= NC.SUB * NC.SUB // 2, can.reshape(h, NC.SUB, w, NC.SUB).sum((1, 3)) / np.maximum(nval, 1), np.nan).astype(np.float32)
        infos.append(dict(id=tid, date=date, ndvi_t=round(thr[date], 4), stable_px=int(st.sum()), stable_canopy_share=round(float(can[st].mean()), 4) if st.sum() else None,
                          bare_in_2022_canopy_share=round(float(can[br].mean()), 4) if br.sum() else None))
        print("  ", json.dumps(infos[-1]), flush=True)
        fill = np.isnan(frac[sl]) & np.isfinite(f)
        frac[sl][fill] = f[fill]
    np.savez_compressed(fn, frac=frac)
    json.dump(dict(year=2025, source="https://naipeuwest.blob.core.windows.net/naip/" + NAIP_2025_PREFIX, ndvi_q=NC.NDVI_Q, texture_t=NC.TEXTURE_T, tiles=infos), open(fn[:-4] + ".json", "w"), indent=1)
    return fn


# ------------------------------------------------------------------------------------------------ 4. report
PT_LABELS = {"POS": "Passive Open Space", "AOS": "Active Open Space and Recreation Areas", "SF1": "Single-Family 1", "SF2": "Single-Family 2", "SF3": "Single-Family 3",
             "MHP": "Manufactured Home Community", "MXD1": "Mixed-Density Community 1", "MXD2": "Mixed-Density Community 2", "MFC": "Multi-Family Community", "FARM": "Working Farm",
             "BUS": "Commercial", "OI": "Office and Institutional", "IND1": "Industrial 1", "IND2": "Industrial 2", "IND1&2": "Industrial 1 or 2", "SCH": "School", "LF": "Landfill",
             "MUCC": "Mixed-Use Centers and Corridors"}      # the layer's own legend (field PT_RD6), read 2026-11-24


def report():
    L = []

    def say(s=""):
        L.append(s); print(s, flush=True)

    r1 = lambda v: round(float(v), 1)
    pct = lambda a, b: round(100 * float(a) / float(b), 1) if b else ""

    # ---------------------------------------------------------------- grids (all read-only)
    b = np.load(os.path.join(AC, "s2", "cache", "baseline.npz"))
    inb = b["inb"]
    D = np.load(os.path.join(PRE, "detect_2017.npz"))
    DET_Q = json.load(open(os.path.join(PRE, "detect_2017.json")))["det_quarters"]
    i0, i25 = DET_Q.index(SINCE_Q), DET_Q.index(NAIP25_LAST_Q)
    fe, ke, fs, ks, regrew, now, s20 = (D[k] for k in ("first_event", "kept_event", "first_strict", "kept_strict", "regrew", "state_now", "state_2020Q3"))
    since = ke & (fe >= i0)                         # event rule, patches of an acre or more, first detected Jul-Sep 2020 or later
    since_small = (fe >= i0) & ~ke                  # event cells in patches under an acre
    since_strict = ks & (fs >= i0)                  # the release's rule: still bare in every later summer
    before = ke & (fe >= 0) & (fe < i0)             # first detected Oct 2017 to Jun 2020
    q_year = np.array([int(q[:4]) for q in DET_Q])
    ev_year = np.where(fe >= 0, q_year[np.maximum(fe, 0)], 0)
    YEARS = list(range(2020, 2027))
    span_years = (pd.Timestamp("2026-10-24") - pd.Timestamp("2020-07-01")).days / 365.25

    Z = np.load(rasters())
    f20, t10, t20 = Z["frac2020"], Z["tiles2010"], Z["tiles2020"]
    n20 = np.load(os.path.join(PRE, "naip", "canopy_2020.npz"))["frac"]
    n25 = np.load(naip_2025())["frac"]
    proj = burn(load("wake_project_boundary").geometry).astype(bool)          # where the County's rasters have data
    can20 = np.where(proj, f20, np.nan_to_num(n20, nan=0.0)).astype(np.float32)   # outside the County's study area: NAIP 2020 by the release's recipe
    F20 = can20 >= FOREST_FRAC
    # the 2010 tiles: a calibration curve (mean 1 m canopy share for a given tile share) learned from the 2020 pair
    bins = np.linspace(0, 1, 41)
    k20 = np.clip(np.digitize(t20[proj], bins) - 1, 0, 39)
    curve = np.bincount(k20, weights=f20[proj], minlength=40) / np.maximum(np.bincount(k20, minlength=40), 1)
    G = lambda t: curve[np.clip(np.digitize(t, bins) - 1, 0, 39)]
    chg = np.where(proj, G(t20) - G(t10), 0.0)      # estimated change in canopy share, 2010 to 2020, per cell

    ev_since = fe >= i0
    standing = F20 & ~ev_since & (now == 0)         # forest in 2020, no clearing event since, forest-like in Jul-Sep 2026
    changed = F20 & ~ev_since & (s20 == 0) & (now == 1)     # forest by both sources in summer 2020, not forest-like in Jul-Sep 2026, and no event recorded
    unread = F20 & ~ev_since & (now != 0) & ~changed        # canopy cells the satellite test does not read as forest in either year (trees mixed with roofs, pavement, lawn), or no clear look

    def stats(m, prefix=""):
        """the standard columns for a mask (cells inside the planning jurisdiction only: detection exists nowhere else)"""
        m = m & inb
        a = m.sum() * PX
        c20 = float(can20[m].sum()) * PX
        lost = float(can20[m & since].sum()) * PX
        d = {"acres": r1(a), "canopy_2020_acres": r1(c20), "canopy_2020_pct": pct(c20, a),
             "est_canopy_2010_acres": r1(c20 - float(chg[m].sum()) * PX), "est_canopy_2010_pct": pct(c20 - float(chg[m].sum()) * PX, a),
             "est_change_2010_2020_acres": r1(float(chg[m].sum()) * PX),
             "cleared_since_mid2020_cell_acres": r1((m & since).sum() * PX), "canopy_cleared_since_mid2020_acres": r1(lost),
             "pct_of_2020_canopy_cleared": pct(lost, c20), "of_which_greened_over_since_acres": r1(float(can20[m & since & regrew].sum()) * PX),
             "est_canopy_now_acres": r1(c20 - lost), "est_canopy_now_pct": pct(c20 - lost, a),
             "forest_cells_2020_acres": r1((m & F20).sum() * PX), "forest_standing_now_acres": r1((m & standing).sum() * PX),
             "forest_cells_cleared_since_acres": r1((m & F20 & since).sum() * PX), "forest_cells_event_under_an_acre_acres": r1((m & F20 & since_small).sum() * PX),
             "forest_cells_changed_no_event_acres": r1((m & changed).sum() * PX), "canopy_cells_satellite_cannot_read_acres": r1((m & unread).sum() * PX)}
        return {prefix + k: v for k, v in d.items()}

    # ---------------------------------------------------------------- geographies
    corp_g, etj_g = load("apex_corporate_limits").geometry.union_all(), load("apex_etj").geometry.union_all()
    corp = burn([corp_g]).astype(bool)
    etj = burn([etj_g]).astype(bool) & ~corp
    pj = corp | etj
    assert not (pj & ~inb).any(), "today's jurisdiction reaches outside the detection area"
    PJ_G = shapely.union_all([corp_g, etj_g])

    # ---------------------------------------------------------------- cases
    ms = lambda s: pd.to_datetime(s, unit="ms", errors="coerce") if "datetime" not in str(s.dtype) else s.dt.tz_localize(None)
    rz = gpd.read_file(os.path.join(HERE, "inputs", "town_rezoning_2026-11-24.geojson")).to_crs(32617)
    rz["geometry"] = shapely.make_valid(rz.geometry.values)
    rz["case"] = rz.Petition.str.strip().str.upper()
    rz["filed"], rz["action"] = ms(rz.Submitted), ms(rz.Action_Date)
    rz = rz.set_index("case", drop=False)
    zn = gpd.read_file(os.path.join(HERE, "inputs", "town_zoning_2026-11-24.geojson")).to_crs(32617)
    zn["geometry"] = shapely.make_valid(zn.geometry.values)
    zn["case"] = zn.CASE_NUMBE.fillna("").str.strip().str.upper()
    PIPE = pd.read_csv(os.path.join(HERE, "out", "pipeline_2022plus.csv")).fillna("").set_index("case")
    names = sorted({c for c in list(zn.case) + list(rz.index) if parse_case(c)[1] == "CZ" and (parse_case(c)[0] or 0) >= 2020} | set(rz.index[rz.Status == "Proposed"]))
    crow, cgeom, cmask = [], {}, {}
    for c in names:
        yr = parse_case(c)[0]
        r = rz.loc[c] if c in rz.index else None
        cur = zn[zn.case == c]
        geom, src = (r.geometry, "Rezoning layer (petition area)") if r is not None else (cur.geometry.union_all(), "zoning map (districts now under this case)")
        status = MANUAL_STATUS.get(c) or (r.Status if r is not None else "on zoning map")
        group = "pending" if status == "Proposed" else "approved" if status in ("Approved", "on zoning map") else "not counted"
        if group == "approved" and yr < 2020:
            group = "not counted"
        era = "pending" if group == "pending" else ("2022 or later" if yr >= 2022 else "2020-2021") if group == "approved" else ""
        note = "listed as Proposed since " + str(r.filed.date()) if (group == "pending" and r is not None and pd.notna(r.filed) and r.filed < pd.Timestamp("2025-01-01")) else ""
        cgeom[c], cmask[c] = geom, burn([geom]).astype(bool) & inb
        crow.append(dict(case=c, name=(r.Name if r is not None else "") or (cur.NAME.iloc[0] if len(cur) else ""), status=status, group=group, approved_era=era,
                         filed=r.filed.date() if r is not None and pd.notna(r.filed) else "", approved=(PIPE.loc[c].approved if c in PIPE.index else (r.action.date() if r is not None and pd.notna(r.action) and group == "approved" else "")),
                         case_acres=r1(geom.area / M2_AC), boundary_from=src, in_entitlement_pipeline_2022plus=c in PIPE.index, note=note, conflict_flag=COI.get(c, "")))
    CASES = pd.DataFrame(crow).set_index("case", drop=False)
    a22 = [c for c in CASES.index if CASES.approved_era[c] == "2022 or later"]
    a20 = [c for c in CASES.index if CASES.approved_era[c] == "2020-2021"]
    pend = [c for c in CASES.index if CASES.group[c] == "pending"]
    hl = lambda cs: [c for c in cs if c not in HEADLINE_OUT]
    um = lambda cs: np.any([cmask[c] for c in cs], axis=0) if cs else np.zeros(SHAPE, bool)
    M22, M20, MP = um(hl(a22)), um(hl(a22 + a20)), um(hl(pend))
    M22c = um(a22)                                   # with 23CZ13, for the reference line only
    ug = lambda cs: shapely.union_all([cgeom[c] for c in cs]) if cs else shapely.Polygon()
    G22, G2021, GP = ug(hl(a22)), ug(hl(a20)), ug(hl(pend))

    say(f"Wake County Land Cover Analysis / Tree Canopy Assessment against the clearing data. Run {TODAY}.")
    say("Estimates, not measurements. Definitions and caveats: NOTES.md. Layers and pull dates: layers/SOURCES.json.")
    say(f"Conflict flag: 23CZ13 (Seymour Mixed Use PUD) is next to the author's home. It is in the case tables, flagged, and is left out of every total below unless a line says otherwise.")
    say()
    say("0. Checks")
    tot = since.sum() * PX
    say(f"   Clearing first detected {SINCE_Q} to {DET_Q[-1]} (2017 baseline, event rule, patches of an acre or more): {tot:,.1f} acres of cells in the planning jurisdiction.")
    say(f"   The County's 2020 raster on those cells: {100 * float(f20[since & proj].mean()):.0f}% canopy on average, so {float(can20[since].sum()) * PX:,.1f} acres of 2020 canopy. "
        f"On cells cleared before mid-2020 ({before.sum() * PX:,.0f} acres) it shows {100 * float(f20[before & proj].mean()):.0f}%.")
    oc = os.path.join(HERE, "out", "office_clearings_by_year.csv")
    if os.path.exists(oc):
        o = pd.read_csv(oc)
        mine = {y: (ke & (ev_year == y)).sum() * PX for y in o.year}
        say("   Per-year acres against out/office_clearings_by_year.csv: " + ", ".join(f"{y} {mine[y]:.1f}/{v:.1f}" for y, v in zip(o.year, o.event_acres)))
    miss = sorted(set(PIPE.index) ^ set(a22))
    say(f"   Approved cases numbered 2022 or later: {len(a22)} here, {len(PIPE)} in out/pipeline_2022plus.csv" + (f"; not in both: {', '.join(miss)}" if miss else "; the same list."))
    say(f"   Forest inside them (without 23CZ13), three baselines: release 2022 forest cells that are forest-like in Jul-Sep 2026, {(b['forest'] & (now == 0) & M22).sum() * PX:,.0f} acres (entitlement/NOTES.md has 1,187); "
        f"2017 forest cells, {(D['cand'] & (now == 0) & M22).sum() * PX:,.0f}; County 2020 forest cells with no event since, {(standing & M22).sum() * PX:,.0f}. The County's map counts more canopy than either satellite-era baseline.")

    # ---------------------------------------------------------------- 2. block groups
    bg = load("wake_block_groups").reset_index(drop=True)
    bg["geoid"] = bg.GISJOIN.str.replace(r"^G(\d{2})0(\d{3})0(\d{7})$", r"\1\2\3", regex=True)
    lab = features.rasterize([(g, i + 1) for i, g in enumerate(bg.geometry)], out_shape=SHAPE, transform=T10, fill=0, dtype="int32")
    grid_ac = np.bincount(lab.ravel(), minlength=len(bg) + 1)[1:] * PX
    # validation of the raster copy and of the 2010 tiles, on block groups that lie wholly on the grid
    whole = (np.abs(grid_ac - bg.ACRES) / bg.ACRES < 0.005) & (bg.ACRES > 20)
    agg = lambda a, m=None: np.bincount(lab.ravel() if m is None else lab[m], weights=(a.ravel() if m is None else a[m]), minlength=len(bg) + 1)[1:] * PX
    mine20, mchg = agg(f20), agg(chg)
    v = bg[whole]
    say(f"   2020 canopy, this copy of the County raster against the County's own figure, {int(whole.sum())} block groups wholly on the grid: "
        f"{mine20[whole].sum():,.0f} against {v.CANOPY_ACRES.sum():,.0f} acres; block-group ratio {np.min(mine20[whole] / v.CANOPY_ACRES):.3f} to {np.max(mine20[whole] / v.CANOPY_ACRES):.3f}.")
    say(f"   2010-2020 change from the County's map tiles against its figure, same block groups: {mchg[whole].sum():,.0f} against {v.DIFFERENCE_ACRES_10_20.sum():,.0f} acres "
        f"(correlation {np.corrcoef(mchg[whole], v.DIFFERENCE_ACRES_10_20)[0, 1]:.4f}; mean miss {np.mean(np.abs(mchg[whole] - v.DIFFERENCE_ACRES_10_20)):.1f} acres a block group). The tiles understate the loss a little.")

    eq23 = load("wake_equity_combined_2023").set_index("GEOID").COMBINED_SCORE
    eq24 = load("wake_equity_combined_2024").set_index("GEOID").COMBINED_SCORE
    ppa = gpd.read_file(latest("wake_priority_planting_areas")).to_crs(32617)
    ppa["geometry"] = shapely.make_valid(ppa.geometry.values)
    ppa = ppa[~ppa.geometry.is_empty].reset_index(drop=True)
    ppa["a"] = ppa.area / M2_AC
    # the published outlines are simplified, so their areas add up to about 5% more than the layer's own ACRES field. ACRES is kept:
    # a polygon cut by a boundary counts ACRES times the share of its outline that falls inside
    ppa["w"] = np.where(ppa.a > 0, ppa.ACRES / ppa.a.where(ppa.a > 0, 1), 0)
    cen = ppa.geometry.representative_point()
    ppa["bg"] = gpd.sjoin(gpd.GeoDataFrame(geometry=cen, crs=32617), bg[["geoid", "geometry"]], predicate="within", how="left").groupby(level=0).geoid.first()
    se = ppa.groupby("bg").apply(lambda d: float(np.average(d.SocialEquMean, weights=np.maximum(d.ACRES, 1e-9))), include_groups=False)

    rows = []
    for i, r in bg.iterrows():
        m = (lab == i + 1) & pj
        if m.sum() * PX < 1:
            continue
        s = stats(m)
        c20 = float(can20[m].sum()) * PX
        rel_in = 100 * s["est_change_2010_2020_acres"] / s["est_canopy_2010_acres"] if s["est_canopy_2010_acres"] else 0
        past = "lost" if r.PERCENT_CHANGE10_20 <= -LOST_PCT else "gained" if r.PERCENT_CHANGE10_20 >= LOST_PCT else "flat"
        past_in = "lost" if rel_in <= -LOST_PCT else "gained" if rel_in >= LOST_PCT else "flat"
        clearing = s["pct_of_2020_canopy_cleared"] != "" and s["pct_of_2020_canopy_cleared"] >= CLEARING_PCT and s["canopy_cleared_since_mid2020_acres"] >= CLEARING_MIN_AC
        cls = lambda p: ("kept losing" if clearing else "lost 2010-2020, little clearing since") if p == "lost" else ("started" if clearing else "no loss in either period")
        share = min(1.0, m.sum() * PX / r.ACRES)
        cc = [c for c in COI if c in cmask and (cmask[c] & m).sum() * PX >= 0.5]
        row = dict(geoid=r.geoid, county="Wake" if r.geoid[2:5] == "183" else "Chatham" if r.geoid[2:5] == "037" else r.geoid[2:5],
                   **{"class": cls(past), "class_measured_inside_jurisdiction": cls(past_in)},
                   block_group_acres=r1(r.ACRES), acres_in_jurisdiction=s["acres"], share_in_jurisdiction=round(share, 2),
                   report_canopy_2010_acres=r1(r.CANOPY_ACRES2010), report_canopy_2010_pct=r1(r.CANOPY_PERCENT2010), report_canopy_2020_acres=r1(r.CANOPY_ACRES), report_canopy_2020_pct=r1(r.CANOPY_PERCENT),
                   report_change_2010_2020_acres=r1(r.DIFFERENCE_ACRES_10_20), report_change_2010_2020_pct=r1(r.PERCENT_CHANGE10_20), report_change_points=r1(r.ABSOLUTE_CHANGE),
                   report_change_acres_per_year=r1(r.DIFFERENCE_ACRES_10_20 / 10),
                   in_jur_canopy_2020_acres=s["canopy_2020_acres"], in_jur_canopy_2020_pct=s["canopy_2020_pct"],
                   in_jur_est_change_2010_2020_acres=s["est_change_2010_2020_acres"], in_jur_est_change_2010_2020_pct=r1(rel_in), in_jur_est_change_acres_per_year=r1(s["est_change_2010_2020_acres"] / 10),
                   cleared_since_mid2020_cell_acres=s["cleared_since_mid2020_cell_acres"], canopy_cleared_since_mid2020_acres=s["canopy_cleared_since_mid2020_acres"],
                   pct_of_2020_canopy_cleared=s["pct_of_2020_canopy_cleared"], canopy_cleared_acres_per_year=r1(s["canopy_cleared_since_mid2020_acres"] / span_years),
                   of_which_greened_over_since_acres=s["of_which_greened_over_since_acres"],
                   **{f"canopy_cleared_{y}_acres" + ("_jul_dec" if y == 2020 else "_to_oct" if y == 2026 else ""): r1(float(can20[m & since & (ev_year == y)].sum()) * PX) for y in YEARS},
                   cleared_oct2017_to_jun2020_cell_acres=r1((m & before).sum() * PX),
                   est_canopy_now_acres=s["est_canopy_now_acres"], est_canopy_now_pct=s["est_canopy_now_pct"], forest_standing_now_acres=s["forest_standing_now_acres"],
                   forest_standing_now_in_approved_2022plus_acres=r1((m & standing & M22).sum() * PX), forest_standing_now_in_pending_acres=r1((m & standing & MP).sum() * PX),
                   tca_social_equity_mean_0_to_4=round(se[r.geoid], 2) if r.geoid in se.index else "", county_equity_score_2023_of_597=eq23.get(r.geoid, ""), county_equity_score_2024_of_597=eq24.get(r.geoid, ""),
                   conflict_flag="; ".join(f"{c}: {COI[c]}" for c in cc))
        rows.append(row)
    BG = pd.DataFrame(rows).sort_values("canopy_cleared_since_mid2020_acres", ascending=False)
    BG.to_csv(os.path.join(OUT, "block_groups.csv"), index=False)
    gj = bg[["geoid", "geometry"]].merge(BG, on="geoid")
    fn = os.path.join(OUT, "block_groups.geojson")
    if os.path.exists(fn):
        os.remove(fn)
    gpd.GeoDataFrame(gj, crs=32617).to_crs(4326).to_file(fn, driver="GeoJSON")
    nobg = pj & (lab == 0)

    say()
    say(f"2. Block groups (block_groups.csv, {len(BG)} with an acre or more inside the planning jurisdiction)")
    say(f"   The County's report, Apex rows: " + "; ".join(
        f"{lbl} {r.ACRES:,.0f} acres, canopy {r.CANOPY_PERCENT2010:.1f}% in 2010 and {r.CANOPY_PERCENT:.1f}% in 2020 ({r.DIFFERENCE_ACRES_10_20:+,.0f} acres)"
        for lbl, r in (("corporate limits", load("wake_corporate_limits").query("LONG_NAME == 'APEX'").iloc[0]), ("ETJ outside them", load("wake_planning_excl_city").query("JURISDICTION == 'APEX'").iloc[0]),
                       ("planning jurisdiction", load("wake_planning_jurisdiction").query("JURISDICTION == 'APEX'").iloc[0]))) + ". Wake County side only, boundaries as the County had them.")
    say(f"   Since mid-2020, inside the jurisdiction: {BG.canopy_cleared_since_mid2020_acres.sum():,.1f} acres of 2020 canopy cleared in these block groups"
        f" ({float(can20[nobg & since].sum()) * PX:,.1f} more on {nobg.sum() * PX:,.0f} acres the block-group layer does not cover).")
    say(f"   Classes (Claude's thresholds: lost or gained = the report's canopy acres moved {LOST_PCT:g}% or more; clearing = {CLEARING_PCT:g}% or more of the 2020 canopy inside the jurisdiction, and at least {CLEARING_MIN_AC:g} acres, cleared since):")
    for c in ("kept losing", "started", "lost 2010-2020, little clearing since", "no loss in either period"):
        d = BG[BG["class"] == c]
        say(f"     {c}: {len(d)} block groups, report change {d.report_change_2010_2020_acres.sum():+,.0f} acres (whole block groups), cleared since {d.canopy_cleared_since_mid2020_acres.sum():,.1f} acres")
    say(f"   {int((BG['class'] != BG.class_measured_inside_jurisdiction).sum())} block groups change class when 2010-2020 is measured only inside the jurisdiction (from the map tiles): "
        + ", ".join(f"{r.geoid} ({r['class']} -> {r.class_measured_inside_jurisdiction}, {int(100 * r.share_in_jurisdiction)}% inside)" for _, r in BG[BG["class"] != BG.class_measured_inside_jurisdiction].iterrows()))
    say("   geoid         class                                  in-jur%  report 2010-20  per yr | in-jur 2010-20 | cleared since  %2020  per yr | canopy 2020 -> now")
    for _, r in BG.head(25).iterrows():
        say(f"   {r.geoid}  {r['class']:<38} {int(100 * r.share_in_jurisdiction):>5}%  {r.report_change_2010_2020_acres:>+8.1f} ac {r.report_change_acres_per_year:>+7.1f} | {r.in_jur_est_change_2010_2020_acres:>+9.1f} ac   | "
            f"{r.canopy_cleared_since_mid2020_acres:>8.1f} ac {r.pct_of_2020_canopy_cleared:>5}% {r.canopy_cleared_acres_per_year:>6.1f} | {r.in_jur_canopy_2020_pct}% -> {r.est_canopy_now_pct}%" + ("   [conflict flag]" if r.conflict_flag else ""))

    # ---------------------------------------------------------------- 3. planting areas against cases and clearings
    cl_shapes = [shapely.geometry.shape(s) for s, _ in features.shapes(since.astype("uint8"), mask=since, transform=T10)]
    GC = shapely.union_all(cl_shapes)
    tree = shapely.STRtree(ppa.geometry.values)

    def inter(geom):
        """acres of each planting area inside geom"""
        out = np.zeros(len(ppa))
        if geom.is_empty:
            return out
        idx = np.unique(tree.query(geom, predicate="intersects"))
        if len(idx):
            shapely.prepare(geom)
            out[idx] = shapely.area(shapely.intersection(ppa.geometry.values[idx], geom)) / M2_AC * ppa.w.values[idx]
        return out

    ppa["in_pj"] = inter(PJ_G)
    clip = lambda g: shapely.intersection(g, PJ_G)
    cols = {"in_approved_2022plus": clip(G22), "in_approved_2020_2021_only": clip(shapely.difference(G2021, G22)), "in_pending_only": clip(shapely.difference(GP, shapely.union(G22, G2021))),
            "in_any_case": clip(shapely.union_all([G22, G2021, GP])), "in_clearing_since_mid2020": clip(GC), "in_case_or_clearing": clip(shapely.union_all([G22, G2021, GP, GC])),
            "in_any_case_with_23CZ13": clip(shapely.union_all([cgeom[c] for c in a22 + a20 + pend]))}
    for k, g in cols.items():
        ppa[k] = inter(g)
    P = ppa.groupby("CompositePri")[["in_pj"] + list(cols)].sum().reindex(PRI)
    P.loc["All classes"] = P.sum()
    P.loc["Very High + High"] = P.loc[["Very High", "High"]].sum()
    P = P.rename(columns={"in_pj": "planting_area_acres_in_jurisdiction"}).round(1)
    P["share_in_case_or_clearing"] = (P.in_case_or_clearing / P.planting_area_acres_in_jurisdiction).round(3)
    P.index.name = "composite_priority"
    P.to_csv(os.path.join(OUT, "ppa_priority_overlay.csv"))
    crows = []
    for c in a22 + a20 + pend:
        x = inter(clip(cgeom[c]))
        g = pd.Series(x).groupby(ppa.CompositePri.values).sum().reindex(PRI).fillna(0)
        if g.sum() < 0.05:
            continue
        crows.append(dict(case=c, name=CASES.name[c], status=CASES.status[c], approved_era=CASES.approved_era[c], case_acres=CASES.case_acres[c], **{f"ppa_{p.lower().replace(' ', '_')}_acres": round(g[p], 2) for p in PRI},
                          ppa_very_high_plus_high_acres=round(g["Very High"] + g["High"], 2), ppa_all_acres=round(g.sum(), 2), note=CASES.note[c], conflict_flag=CASES.conflict_flag[c]))
    PC = pd.DataFrame(crows).sort_values("ppa_very_high_plus_high_acres", ascending=False)
    PC.to_csv(os.path.join(OUT, "ppa_by_case.csv"), index=False)
    CASES["acres_in_jurisdiction_grid"] = [r1(cmask[c].sum() * PX) for c in CASES.index]
    CASES["forest_standing_now_acres"] = [r1((cmask[c] & standing).sum() * PX) for c in CASES.index]
    CASES["canopy_2020_acres"] = [r1(float(can20[cmask[c]].sum()) * PX) for c in CASES.index]
    CASES["canopy_cleared_since_mid2020_acres"] = [r1(float(can20[cmask[c] & since].sum()) * PX) for c in CASES.index]
    CASES.to_csv(os.path.join(OUT, "cases_used.csv"), index=False)

    say()
    say("3. Potential Planting Areas (County layer, composite priority) against cases and clearings (ppa_priority_overlay.csv, ppa_by_case.csv)")
    say(f"   Cases: {len(hl(a22))} approved and numbered 2022 or later, {len(hl(a20))} approved and numbered 2020-2021, {len(hl(pend))} pending (cases_used.csv). Clearings: {len(cl_shapes)} outlines since mid-2020.")
    say("   Acres inside the planning jurisdiction. Planting areas exist on the Wake County side only.")
    say("   priority            mapped | approved 2022+ | approved 2020-21 only | pending only | any case | in a clearing | case or clearing (once)")
    for p in PRI + ["Very High + High", "All classes"]:
        r = P.loc[p]
        say(f"   {p:<17} {r.planting_area_acres_in_jurisdiction:>8,.1f} | {r.in_approved_2022plus:>14,.1f} | {r.in_approved_2020_2021_only:>21,.1f} | {r.in_pending_only:>12,.1f} | {r.in_any_case:>8,.1f} | {r.in_clearing_since_mid2020:>13,.1f} | {r.in_case_or_clearing:>8,.1f} ({100 * r.share_in_case_or_clearing:.1f}%)")
    say(f"   With 23CZ13: any case {P.loc['Very High + High'].in_any_case_with_23CZ13:,.1f} acres of Very High + High, {P.loc['All classes'].in_any_case_with_23CZ13:,.1f} of all classes.")
    say("   Cases holding the most Very High + High planting area:")
    for _, r in PC[PC.conflict_flag == ""].head(12).iterrows():
        say(f"     {r.case} {str(r['name'])[:42]:<42} {r.status:<14} {r.ppa_very_high_plus_high_acres:>6.1f} ac (all classes {r.ppa_all_acres:.1f})")

    # ---------------------------------------------------------------- 4. canopy now, three geographies
    def geo_row(label, m, basis):
        s = stats(m)
        mm = m & inb
        c20 = float(can20[mm].sum()) * PX
        a = mm.sum() * PX
        alt = lambda mask: r1(c20 - float(can20[mm & mask].sum()) * PX)
        to25 = float(can20[mm & since & (fe <= i25)].sum()) * PX
        nn = mm & np.isfinite(n20) & np.isfinite(n25)
        c = mm & since & (fe <= i25) & np.isfinite(n20) & np.isfinite(n25)
        return dict(geography=label, boundary=basis, **s,
                    canopy_2020_acres_outside_county_study_area_naip=r1(float(can20[mm & ~proj].sum()) * PX), acres_outside_county_study_area=r1((mm & ~proj).sum() * PX),
                    change_points_2020_to_now=round(s["est_canopy_now_pct"] - s["canopy_2020_pct"], 1),
                    est_now_pct_release_rule=pct(alt(since_strict), a), est_now_pct_with_patches_under_an_acre=pct(alt(since | since_small), a),
                    est_now_pct_all_signals=pct(alt(since | since_small | changed), a), canopy_on_changed_no_event_cells_acres=r1(float(can20[mm & changed].sum()) * PX),
                    est_canopy_mid2025_pct=pct(c20 - to25, a), canopy_cleared_mid2020_to_mid2025_acres=r1(to25),
                    naip_recipe_canopy_2020_acres=r1(np.nansum(n20[nn]) * PX), naip_recipe_canopy_2025_acres=r1(np.nansum(n25[nn]) * PX),
                    naip_recipe_canopy_2020_pct=pct(np.nansum(n20[nn]) * PX, nn.sum() * PX), naip_recipe_canopy_2025_pct=pct(np.nansum(n25[nn]) * PX, nn.sum() * PX),
                    naip_recipe_change_2020_2025_acres=r1(np.nansum(n25[nn] - n20[nn]) * PX),
                    naip_recipe_change_on_cleared_cells_acres=r1(np.nansum(n25[c] - n20[c]) * PX), naip_recipe_change_elsewhere_acres=r1(np.nansum((n25 - n20)[nn & ~c]) * PX),
                    naip_canopy_2020_on_cleared_cells=round(float(np.nanmean(n20[c])), 2) if c.any() else "", naip_canopy_2025_on_cleared_cells=round(float(np.nanmean(n25[c])), 2) if c.any() else "")

    wk = {k: burn(load(n).query(q).geometry).astype(bool) for k, n, q in (("corp", "wake_corporate_limits", "LONG_NAME == 'APEX'"), ("etj", "wake_planning_excl_city", "JURISDICTION == 'APEX'"), ("pj", "wake_planning_jurisdiction", "JURISDICTION == 'APEX'"))}
    GEO = pd.DataFrame([geo_row("Corporate limits", corp, "Town layer, pulled " + TODAY), geo_row("ETJ outside corporate limits", etj, "Town layer, pulled " + TODAY), geo_row("Planning jurisdiction", pj, "Town layers, pulled " + TODAY),
                        geo_row("Corporate limits", wk["corp"], "as in the County report, Wake side"), geo_row("ETJ outside corporate limits", wk["etj"], "as in the County report, Wake side"),
                        geo_row("Planning jurisdiction", wk["pj"], "as in the County report, Wake side")])
    GEO.to_csv(os.path.join(OUT, "canopy_estimate_by_geography.csv"), index=False)
    say()
    say("4. Canopy now: the County's 2020 canopy minus clearing since (canopy_estimate_by_geography.csv). ESTIMATE: it subtracts clearings and adds no growth.")
    say("   geography (boundary)                                           acres   2010 est  2020     cleared since      now est   | release rule  +small  +unrecorded")
    for _, r in GEO.iterrows():
        say(f"   {r.geography + ' (' + r.boundary + ')':<62} {r.acres:>8,.0f}  {r.est_canopy_2010_pct:>5}%  {r.canopy_2020_pct:>5}%  {r.canopy_cleared_since_mid2020_acres:>7,.0f} ac ({r.pct_of_2020_canopy_cleared}%)  {r.est_canopy_now_pct:>5}%   | "
            f"{r.est_now_pct_release_rule:>5}%  {r.est_now_pct_with_patches_under_an_acre:>5}%  {r.est_now_pct_all_signals:>5}%")
    g = GEO.iloc[2]
    say(f"   Planning jurisdiction: {g.canopy_2020_acres:,.0f} acres of canopy in 2020, {g.canopy_cleared_since_mid2020_acres:,.0f} cleared since, {g.est_canopy_now_acres:,.0f} now. "
        f"{g.acres_outside_county_study_area:,.0f} acres on the Chatham side are outside the County's study area; their 2020 canopy ({g.canopy_2020_acres_outside_county_study_area_naip:,.0f} acres) is from NAIP 2020 by the release's recipe.")
    say(f"   Columns after the bar: the same estimate with the release's stricter rule; with event patches under an acre added; and with those plus {g.forest_cells_changed_no_event_acres:,.0f} acres of cells "
        f"that were forest by both sources in summer 2020, are not forest-like in Jul-Sep 2026, and have no event on record ({g.canopy_on_changed_no_event_cells_acres:,.0f} acres of canopy). "
        f"Most of those cells were never in the 2017 forest baseline, so the detection could not see them.")
    say(f"   2020 forest cells in the planning jurisdiction ({g.forest_cells_2020_acres:,.0f} acres): standing now {g.forest_standing_now_acres:,.0f}; cleared in patches of an acre or more {g.forest_cells_cleared_since_acres:,.0f}; "
        f"event under an acre {g.forest_cells_event_under_an_acre_acres:,.0f}; changed with no event {g.forest_cells_changed_no_event_acres:,.0f}; tree cover the satellite cannot read as forest in either year {g.canopy_cells_satellite_cannot_read_acres:,.0f}.")
    # NAIP cross-check: the same recipe on the 2020 and 2025 flights, by what the detection says happened to each cell
    okn = pj & np.isfinite(n20) & np.isfinite(n25)
    parts = [("cleared, patches of an acre or more, first seen by " + NAIP25_LAST_Q, since & (fe <= i25)), ("event in a patch under an acre, by " + NAIP25_LAST_Q, since_small & (fe <= i25)),
             ("first seen after the 2025 flight (2025Q3 on)", ev_since & (fe > i25)), ("forest in 2020, not forest-like in 2026, no event", changed),
             ("cleared before mid-2020", (fe >= 0) & (fe < i0)), ("forest in 2020 and forest-like in 2026, no event", standing)]
    used, nrows = np.zeros(SHAPE, bool), []
    for k, m in parts + [("everything else (yards, fields, roofs, partial tree cover)", np.ones(SHAPE, bool))]:
        m = m & okn & ~used
        used |= m
        nrows.append(dict(cells=k, acres=r1(m.sum() * PX), county_2020_canopy_share=round(float(can20[m].mean()), 2), naip_2020_canopy_share=round(float(n20[m].mean()), 2), naip_2025_canopy_share=round(float(n25[m].mean()), 2),
                          naip_change_acres=r1(float((n25[m] - n20[m]).sum()) * PX)))
    nrows.append(dict(cells="Planning jurisdiction", acres=r1(okn.sum() * PX), county_2020_canopy_share=round(float(can20[okn].mean()), 2), naip_2020_canopy_share=round(float(n20[okn].mean()), 2),
                      naip_2025_canopy_share=round(float(n25[okn].mean()), 2), naip_change_acres=r1(float((n25[okn] - n20[okn]).sum()) * PX)))
    NA = pd.DataFrame(nrows)
    NA.to_csv(os.path.join(OUT, "naip_crosscheck.csv"), index=False)
    say(f"   NAIP cross-check (naip_crosscheck.csv): the release's canopy recipe on the July 2020 flight and on the July 25, 2025 flight, the latest. Share of each cell that is canopy:")
    say("     cells, by what the detection says                                   acres   County 2020   NAIP 2020 -> NAIP 2025   NAIP change")
    for _, r in NA.iterrows():
        say(f"     {r.cells:<66} {r.acres:>8,.0f}   {r.county_2020_canopy_share:>6.2f}        {r.naip_2020_canopy_share:.2f} -> {r.naip_2025_canopy_share:.2f}           {r.naip_change_acres:>+8,.0f} ac")
    say(f"     Read it row by row, not as a total. The recipe is not steady between flights: forest that stood the whole time reads {NA.naip_2020_canopy_share[5]:.2f} in 2020 and {NA.naip_2025_canopy_share[5]:.2f} in 2025, "
        f"and it counts less canopy than the County's map throughout. So the NAIP totals ({g.naip_recipe_canopy_2020_pct}% and {g.naip_recipe_canopy_2025_pct}%) are not a second estimate of the level.")
    say(f"     What it does show: the cells the detection calls cleared went from {NA.naip_2020_canopy_share[0]:.2f} canopy to {NA.naip_2025_canopy_share[0]:.2f}; cells first seen cleared after the flight were still mostly canopy on it; "
        f"and the cells with no event that changed between two dates lost about half their canopy. Estimate for mid-2025, the flight date: {g.canopy_2020_pct}% -> {g.est_canopy_mid2025_pct}% ({-g.canopy_cleared_mid2020_to_mid2025_acres:+,.0f} acres).")

    # ---------------------------------------------------------------- 5. Peak Plan 2055
    ca = load("apex_context_areas_2055")
    calab = features.rasterize([(g, i + 1) for i, g in enumerate(ca.geometry)], out_shape=SHAPE, transform=T10, fill=0, dtype="int32")

    def plan_row(label, m, total_acres=None):
        s = stats(m & pj)
        d = dict(area=label, total_acres=r1(total_acres) if total_acres is not None else "", **{("acres_in_jurisdiction" if k == "acres" else k): v for k, v in s.items()},
                 forest_standing_now_in_approved_2022plus_acres=r1((m & pj & standing & M22).sum() * PX), forest_standing_now_in_approved_2020plus_acres=r1((m & pj & standing & M20).sum() * PX),
                 forest_standing_now_in_pending_acres=r1((m & pj & standing & MP & ~M20).sum() * PX),
                 forest_standing_now_in_approved_2022plus_with_23CZ13_acres=r1((m & pj & standing & M22c).sum() * PX))
        o = m & ~pj & proj
        d |= dict(outside_jurisdiction_on_grid_acres=r1((m & ~pj).sum() * PX), outside_jurisdiction_canopy_2020_acres=r1(float(f20[o].sum()) * PX),
                  outside_jurisdiction_canopy_2020_pct=pct(float(f20[o].sum()) * PX, o.sum() * PX), outside_jurisdiction_forest_2020_not_forestlike_now_acres=r1((o & (f20 >= FOREST_FRAC) & (s20 == 0) & (now == 1)).sum() * PX))
        return d

    CA = pd.DataFrame([plan_row(r.Name, calab == i + 1, r.geometry.area / M2_AC) for i, r in ca.iterrows()] + [plan_row("All four", calab > 0, ca.area.sum() / M2_AC)])
    CA.to_csv(os.path.join(OUT, "context_areas.csv"), index=False)
    pt = gpd.read_file(latest("apex_place_types_2055")).to_crs(32617)
    pt["geometry"] = shapely.make_valid(pt.geometry.values)
    codes = sorted(pt.PT_RD6.fillna("").str.strip().unique())
    ptlab = features.rasterize([(g, codes.index((c or "").strip()) + 1) for g, c in zip(pt.geometry, pt.PT_RD6.fillna("")) if not g.is_empty], out_shape=SHAPE, transform=T10, fill=0, dtype="int32")
    PT = pd.DataFrame([plan_row(f"{c or '(blank)'}: {PT_LABELS.get(c, 'no place type assigned')}", ptlab == i + 1, pt.geometry[pt.PT_RD6.fillna('').str.strip() == c].area.sum() / M2_AC) for i, c in enumerate(codes)]
                      + [plan_row("not in a parcel of the layer (roads, right-of-way, gaps)", (ptlab == 0) & pj)]).sort_values("forest_standing_now_acres", ascending=False)
    PT.to_csv(os.path.join(OUT, "place_types.csv"), index=False)
    S = json.load(open(os.path.join(LAYERS, "SOURCES.json")))
    say()
    say("5. Peak Plan 2055 (context_areas.csv, place_types.csv)")
    say(f"   The Town has published both layers on its public map server: Context Areas (\"STAFF DRAFT\", last edited {S['apex_context_areas_2055']['layer_last_edit']}) "
        f"and Place Types (\"Public Forum 3\", last edited {S['apex_place_types_2055']['layer_last_edit']}). No georeferencing of the slide was needed.")
    say("   Inside the planning jurisdiction (clearing detection exists nowhere else):")
    say("   context area                     acres  | canopy 2020        | cleared since    | canopy now est | forest standing now | of it in approved 2022+ / 2020+ / pending")
    for _, r in CA.iterrows():
        say(f"   {r.area:<30} {r.acres_in_jurisdiction:>8,.0f} | {r.canopy_2020_acres:>7,.0f} ac {r.canopy_2020_pct:>5}% | {r.canopy_cleared_since_mid2020_acres:>6,.0f} ac {r.pct_of_2020_canopy_cleared:>5}% | {r.est_canopy_now_pct:>5}%         | "
            f"{r.forest_standing_now_acres:>8,.0f} ac         | {r.forest_standing_now_in_approved_2022plus_acres:,.0f} / {r.forest_standing_now_in_approved_2020plus_acres:,.0f} / {r.forest_standing_now_in_pending_acres:,.0f} ac")
    for _, r in CA.iloc[:4].iterrows():
        if r.total_acres - r.acres_in_jurisdiction > 5:
            say(f"   {r.area}: {r.total_acres:,.0f} acres in all; {r.total_acres - r.acres_in_jurisdiction:,.0f} lie outside the jurisdiction, {r.outside_jurisdiction_on_grid_acres:,.0f} of them on the analysis grid "
                f"with {r.outside_jurisdiction_canopy_2020_acres:,.0f} acres of 2020 canopy ({r.outside_jurisdiction_canopy_2020_pct}%). No clearing detection there; "
                f"{r.outside_jurisdiction_forest_2020_not_forestlike_now_acres:,.0f} acres of its 2020 forest cells are not forest-like in Jul-Sep 2026 (two dates only, unverified).")
    say(f"   With 23CZ13: forest standing in approved 2022+ cases, all four areas, {CA.iloc[-1].forest_standing_now_in_approved_2022plus_with_23CZ13_acres:,.0f} acres.")
    say("   Place types holding the most standing forest:")
    for _, r in PT.head(8).iterrows():
        say(f"     {r.area[:52]:<52} {r.acres_in_jurisdiction:>7,.0f} ac, canopy 2020 {r.canopy_2020_pct}%, cleared since {r.canopy_cleared_since_mid2020_acres:,.0f} ac, standing {r.forest_standing_now_acres:,.0f} ac, "
            f"in approved 2022+ cases {r.forest_standing_now_in_approved_2022plus_acres:,.0f} ac")
    open(os.path.join(OUT, "summary.txt"), "w").write("\n".join(L) + "\n")


if __name__ == "__main__":
    steps = sys.argv[1:] or ["pull", "rasters", "naip", "report"]
    if "pull" in steps:
        pull()
    if "rasters" in steps:
        rasters()
    if "naip" in steps:
        naip_2025()
    if "report" in steps:
        report()
