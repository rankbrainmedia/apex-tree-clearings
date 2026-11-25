#!/usr/bin/env python
"""naip_canopy.py: tree canopy fraction per 10 m cell from NAIP 2016, 2018 and 2020, on the release's grid.

    ../apex-canopy/df-venv/bin/python naip_canopy.py [2016 2018 2020]

Recipe: the same as the 2022 canopy mask behind the release (canopy_update.py): a pixel is canopy if its NDVI is
above a threshold AND its local NDVI texture (5-pixel standard deviation) is at least 0.012, then a 1-step opening
and a 2-step closing. Two things differ, both because the vintages are not on one radiometric scale:
  - Each tile is read at 1.25 m (2016 is 1 m imagery, 2018 and 2020 are 0.6 m).
  - The NDVI threshold is set per flight date from the stable forest under that date's tiles: the NDVI_Q quantile of
    NDVI over cells that the Sentinel-2 run holds as interior forest through 2026. No fixed number is carried across years.
A 10 m cell's canopy fraction is the share of its 64 pixels that are canopy.

NAIP tiles are in NAD83 UTM 17N and are read as if WGS84 UTM 17N (about 1 m apart), as the 2022 mask was.
Writes ../apex-canopy/prerezoning_cache/naip/canopy_<year>.npz: frac (float32, NaN = no image), tile (int8 index),
and a json of tile ids, dates, thresholds and checks.
"""
import json, os, sys
from concurrent.futures import ThreadPoolExecutor
import numpy as np, rasterio, pystac_client
import planetary_computer as pc
from rasterio.enums import Resampling
from rasterio.windows import from_bounds
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "apex-canopy", "release-v1", "code"))
CACHE = os.path.join(HERE, "..", "apex-canopy", "prerezoning_cache", "naip")
os.makedirs(CACHE, exist_ok=True)
os.environ.setdefault("APEX_WORK", CACHE); os.environ.setdefault("APEX_OUT", CACHE)
import config as C  # noqa: E402

for k, v in dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MULTIRANGE="YES", GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES",
                 VSI_CACHE="TRUE", GDAL_HTTP_MAX_RETRY="5", GDAL_HTTP_RETRY_DELAY="2", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif").items():
    os.environ.setdefault(k, v)
SUB = 8                       # 1.25 m pixels per 10 m cell side
TEXTURE_T = 0.012             # from canopy_update.py
NDVI_Q = float(os.environ.get("NDVI_Q", 0.25))
BBOX = [-78.969003, 35.664933, -78.802403, 35.778735]
S2 = np.load(os.path.join(HERE, "..", "apex-canopy", "s2", "cache", "detect.npz"))
STABLE, BARE = S2["stable"], S2["bare"]            # 10 m reference cells from the release's detection step


def texture(ndvi, win=5):
    m = ndimage.uniform_filter(ndvi, win); m2 = ndimage.uniform_filter(ndvi * ndvi, win)
    return np.sqrt(np.maximum(m2 - m * m, 0))


def up(a):
    return np.repeat(np.repeat(a, SUB, 0), SUB, 1)


def read_tile(item):
    """NDVI at 1.25 m on the 10 m cells this tile covers, cached to disk. Returns (id, date, row slice, col slice) or None."""
    fn = os.path.join(CACHE, "tiles", item.id + ".npz")
    if os.path.exists(fn):
        z = np.load(fn)
        return (item.id, item.datetime.date().isoformat(), *[int(v) for v in z["cells"]]) if z["cells"].size else None
    with rasterio.open(pc.sign(item.assets["image"].href)) as src:
        b = src.bounds
        c0, c1 = int(np.ceil((max(b.left, C.X0) - C.X0) / 10)), int(np.floor((min(b.right, C.X1) - C.X0) / 10))
        r0, r1 = int(np.ceil((C.Y1 - min(b.top, C.Y1)) / 10)), int(np.floor((C.Y1 - max(b.bottom, C.Y0)) / 10))
        if c1 <= c0 or r1 <= r0:
            np.savez_compressed(fn, cells=np.array([]))
            return None
        win = from_bounds(C.X0 + 10 * c0, C.Y1 - 10 * r1, C.X0 + 10 * c1, C.Y1 - 10 * r0, transform=src.transform)
        a = src.read([1, 4], window=win, out_shape=(2, (r1 - r0) * SUB, (c1 - c0) * SUB), resampling=Resampling.average).astype(np.float32)
    red, nir = a
    valid = (red + nir) > 0
    ndvi = np.where(valid, (nir - red) / np.maximum(nir + red, 1e-6), np.nan).astype(np.float16)       # NaN = no image
    np.savez_compressed(fn, ndvi=ndvi, cells=np.array([r0, r1, c0, c1]))
    return item.id, item.datetime.date().isoformat(), r0, r1, c0, c1


def load_ndvi(tid):
    nd = np.load(os.path.join(CACHE, "tiles", tid + ".npz"))["ndvi"].astype(np.float32)
    valid = np.isfinite(nd)
    return np.where(valid, nd, 0), valid


def run(year):
    os.makedirs(os.path.join(CACHE, "tiles"), exist_ok=True)
    cat = pystac_client.Client.open(C.STAC_URL)
    items = sorted(cat.search(collections=["naip"], bbox=BBOX, datetime=f"{year}-01-01/{year}-12-31").items(), key=lambda i: i.id)
    with ThreadPoolExecutor(4) as ex:
        tiles = [t for t in ex.map(read_tile, items) if t]
    # one NDVI threshold per flight date, from the stable forest under all of that date's tiles
    pool = {}
    for tid, date, r0, r1, c0, c1 in tiles:
        nd, valid = load_ndvi(tid)
        pool.setdefault(date, []).append(nd[up(STABLE[r0:r1, c0:c1]) & valid])
    thr = {d: float(np.quantile(np.concatenate(v), NDVI_Q)) for d, v in pool.items()}
    npx = {d: int(sum(len(x) for x in v)) for d, v in pool.items()}
    frac = np.full((C.H, C.W), np.nan, np.float32); tile = np.full((C.H, C.W), -1, np.int8); infos = []
    for tid, date, r0, r1, c0, c1 in tiles:
        nd, valid = load_ndvi(tid)
        sl = (slice(r0, r1), slice(c0, c1))
        can = (nd >= thr[date]) & (texture(nd) >= TEXTURE_T) & valid
        can = ndimage.binary_closing(ndimage.binary_opening(can, iterations=1), iterations=2)
        st, br = up(STABLE[sl]) & valid, up(BARE[sl]) & valid
        h, w = r1 - r0, c1 - c0
        nval = valid.reshape(h, SUB, w, SUB).sum((1, 3))
        f = np.where(nval >= SUB * SUB // 2, can.reshape(h, SUB, w, SUB).sum((1, 3)) / np.maximum(nval, 1), np.nan).astype(np.float32)
        info = dict(id=tid, date=date, ndvi_t=round(thr[date], 4), stable_px_on_date=npx[date], stable_px=int(st.sum()),
                    stable_ndvi_median=round(float(np.median(nd[st])), 4) if st.sum() else None, stable_canopy_share=round(float(can[st].mean()), 4) if st.sum() else None,
                    bare_in_2022_canopy_share=round(float(can[br].mean()), 4) if br.sum() else None)
        infos.append(info)
        print(year, json.dumps(info), flush=True)
        fill = np.isnan(frac[sl]) & np.isfinite(f)          # first tile wins where tiles overlap
        frac[sl][fill] = f[fill]; tile[sl][fill] = len(infos) - 1
    np.savez_compressed(os.path.join(CACHE, f"canopy_{year}.npz"), frac=frac, tile=tile)
    json.dump(dict(year=year, ndvi_q=NDVI_Q, texture_t=TEXTURE_T, tiles=infos), open(os.path.join(CACHE, f"canopy_{year}.json"), "w"), indent=1)
    b = np.load(os.path.join(HERE, "..", "apex-canopy", "s2", "cache", "baseline.npz"))
    inb = b["inb"]
    print(f"{year}: coverage {np.isfinite(frac[inb]).mean():.1%} of the jurisdiction, cells at least half canopy {(frac[inb] >= 0.5).sum() * 100 / C.M2_PER_AC:,.0f} ac "
          f"(the 2022 mask: {b['forest'].sum() * 100 / C.M2_PER_AC:,.0f} ac); stable forest scored canopy {np.nanmean(frac[STABLE]):.1%}", flush=True)


if __name__ == "__main__":
    for y in [int(a) for a in sys.argv[1:]] or [2016, 2018, 2020]:
        run(y)
