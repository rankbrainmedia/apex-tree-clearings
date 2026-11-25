#!/usr/bin/env python
"""naip2022_bands.py: NAIP 2022 (the latest NAIP flight over Apex) read at 1.25 m on the release grid, for the RCA overlay.

    ../../apex-canopy/df-venv/bin/python naip2022_bands.py

Writes ../../apex-canopy/rca_cache/naip2022.npz: ndvi and ndwi (float16, NaN = no image) on a 1.25 m grid (8 x 8 per 10 m
release cell), and tile dates. NDWI = (green - NIR) / (green + NIR), used only to find open water.
"""
import os, sys
from concurrent.futures import ThreadPoolExecutor
import numpy as np, rasterio, pystac_client
import planetary_computer as pc
from rasterio.enums import Resampling
from rasterio.windows import from_bounds

HERE = os.path.dirname(os.path.abspath(__file__))
AC = os.path.join(HERE, "..", "..", "apex-canopy")
sys.path.insert(0, os.path.join(AC, "release-v1", "code"))
os.environ.setdefault("APEX_WORK", os.path.join(AC, "rca_cache")); os.environ.setdefault("APEX_OUT", os.path.join(AC, "rca_cache"))
import config as C  # noqa: E402
for k, v in dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MULTIRANGE="YES", GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES", VSI_CACHE="TRUE", GDAL_HTTP_MAX_RETRY="5", GDAL_HTTP_RETRY_DELAY="2").items():
    os.environ.setdefault(k, v)
SUB = 8
BBOX = [-78.969003, 35.664933, -78.802403, 35.778735]


def tile(item):
    with rasterio.open(pc.sign(item.assets["image"].href)) as src:
        b = src.bounds
        c0, c1 = int(np.ceil((max(b.left, C.X0) - C.X0) / 10)), int(np.floor((min(b.right, C.X1) - C.X0) / 10))
        r0, r1 = int(np.ceil((C.Y1 - min(b.top, C.Y1)) / 10)), int(np.floor((C.Y1 - max(b.bottom, C.Y0)) / 10))
        if c1 <= c0 or r1 <= r0:
            return None
        win = from_bounds(C.X0 + 10 * c0, C.Y1 - 10 * r1, C.X0 + 10 * c1, C.Y1 - 10 * r0, transform=src.transform)
        r, g, n = src.read([1, 2, 4], window=win, out_shape=(3, (r1 - r0) * SUB, (c1 - c0) * SUB), resampling=Resampling.average).astype(np.float32)
    ok = (r + n) > 0
    nd = np.where(ok, (n - r) / np.maximum(n + r, 1e-6), np.nan).astype(np.float16)
    nw = np.where(ok, (g - n) / np.maximum(g + n, 1e-6), np.nan).astype(np.float16)
    return item.id, item.datetime.date().isoformat(), r0, r1, c0, c1, nd, nw


cat = pystac_client.Client.open(C.STAC_URL)
items = sorted(cat.search(collections=["naip"], bbox=BBOX, datetime="2022-01-01/2022-12-31").items(), key=lambda i: i.id)
ndvi = np.full((C.H * SUB, C.W * SUB), np.nan, np.float16); ndwi = ndvi.copy(); dates = {}
with ThreadPoolExecutor(4) as ex:
    for out in ex.map(tile, items):
        if out is None:
            continue
        tid, d, r0, r1, c0, c1, nd, nw = out
        sl = (slice(r0 * SUB, r1 * SUB), slice(c0 * SUB, c1 * SUB))
        fill = np.isnan(ndvi[sl]) & np.isfinite(nd)
        ndvi[sl][fill] = nd[fill]; ndwi[sl][fill] = nw[fill]; dates[tid] = d
        print(tid, d, flush=True)
np.savez_compressed(os.path.join(AC, "rca_cache", "naip2022.npz"), ndvi=ndvi, ndwi=ndwi, tiles=np.array(sorted(dates.items())))
print("coverage", float(np.isfinite(ndvi).mean()))
