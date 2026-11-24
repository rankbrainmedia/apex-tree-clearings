#!/usr/bin/env python
"""Step 3: per-quarter clear-pixel median composites of Sentinel-2 L2A over Apex, NC.

Usage: python 03_composites.py [QUARTER ...]      (default: every quarter in items.json)

- De-duplication: items sharing (acquisition datetime, relative orbit) are reprocessings of one
  datatake; the newest product id is kept (802 items -> 663 scenes for v1.0).
- Mask: keep SCL 4/5/6 only. SCL 3/8/9/10 (shadow, cloud medium/high, cirrus) are dilated by
  2 SCL pixels (40 m) and removed. 20 m bands (SCL, B11, B12) are nearest-neighbour upsampled to 10 m.
- Scene skip rule: skip if <1% of the AOI window is clear, or if <20% of the data-covered part of
  the AOI is clear (cloud-edge leakage). Partial-swath scenes that are clear where they have data are kept.
- Reflectance = (DN - 1000) / 10000 (every scene is processing baseline >= 04.00).
- Per quarter, per pixel median of NDVI(B08,B04), NBR(B08,B12), NDMI(B08,B11), B02/B03/B04,
  plus the clear-observation count.
Writes WORK/composite_<Q>.npz and WORK/scenes.csv (quarter, scene id, ok/skip, AOI clear fraction).
"""
import json, os, sys, warnings
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import rasterio
from rasterio.windows import from_bounds
from scipy import ndimage
import pystac
import planetary_computer as pc
import config as C

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("GDAL_HTTP_MULTIRANGE", "YES")
os.environ.setdefault("GDAL_HTTP_MERGE_CONSECUTIVE_RANGES", "YES")
os.environ.setdefault("VSI_CACHE", "TRUE")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "5")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "2")


def quarter_of(d):
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


def load_items():
    raw = json.load(open(os.path.join(C.WORK, "items.json")))
    best = {}
    for d in raw:
        p = d["properties"]
        key = (p["datetime"][:19], p["sat:relative_orbit"])
        if key not in best or d["id"] > best[key]["id"]:
            best[key] = d
    items = [pystac.Item.from_dict(d) for d in best.values()]
    items.sort(key=lambda i: i.datetime)
    return items


def read_window(href):
    with rasterio.open(href) as src:
        win = from_bounds(C.X0, C.Y0, C.X1, C.Y1, transform=src.transform).round_offsets().round_lengths()
        return src.read(1, window=win, boundless=True, fill_value=0)


def read_band(href, res):
    a = read_window(href)
    if res == 20:
        a = np.repeat(np.repeat(a, 2, axis=0), 2, axis=1)
    assert a.shape == (C.H, C.W), (a.shape, href)
    return a


def process_scene(item):
    item = pc.sign(item)
    a = item.assets
    scl20, err = None, None
    for _ in range(3):
        try:
            scl20 = read_window(a["SCL"].href)
            break
        except Exception as e:  # transient HTTP errors
            err = e
    if scl20 is None:
        return item.id, None, f"error SCL {err}"
    cloud = ndimage.binary_dilation(np.isin(scl20, C.CLOUD_SCL), iterations=C.CLOUD_DILATE)
    clear20 = np.isin(scl20, C.KEEP_SCL) & ~cloud
    clear = np.repeat(np.repeat(clear20, 2, 0), 2, 1)
    frac = clear.mean()
    covered = max(float((scl20 > 0).mean()), 1e-6)
    if frac < C.MIN_SCENE_CLEAR or clear20.mean() / covered < C.MIN_CLEAR_OF_COVERED:
        return item.id, {"frac": float(frac)}, "skip"
    out = {}
    try:
        bands = {b: (read_band(a[b].href, r).astype(np.float32) + C.BOA_OFFSET) / 10000.0
                 for b, r in (("B02", 10), ("B03", 10), ("B04", 10), ("B08", 10), ("B11", 20), ("B12", 20))}
    except Exception as e:
        return item.id, None, f"error bands {e}"
    valid = clear & (bands["B04"] > -0.05) & (bands["B08"] > 0)   # DN 0 = nodata

    def nd(p, q):
        with np.errstate(divide="ignore", invalid="ignore"):
            v = (p - q) / (p + q)
        v[~valid] = np.nan
        return v.astype(np.float32)
    out["ndvi"] = nd(bands["B08"], bands["B04"])
    out["nbr"] = nd(bands["B08"], bands["B12"])
    out["ndmi"] = nd(bands["B08"], bands["B11"])
    for b in ("B02", "B03", "B04"):
        v = bands[b].copy(); v[~valid] = np.nan
        out[b] = v.astype(np.float32)
    out["frac"] = float(valid.mean())
    return item.id, out, "ok"


def main(quarters=None):
    items = load_items()
    byq = {}
    for it in items:
        byq.setdefault(quarter_of(it.datetime), []).append(it)
    qs = [q for q in sorted(byq) if not quarters or q in quarters]
    print(f"{len(items)} unique scenes in {len(byq)} quarters")
    log_fn = os.path.join(C.WORK, "scenes.csv")
    done = set()
    if os.path.exists(log_fn):
        done = {l.split(",")[1] for l in open(log_fn) if l.strip()}
    log = open(log_fn, "a")
    for q in qs:
        fn = os.path.join(C.WORK, f"composite_{q}.npz")
        if os.path.exists(fn):
            print(q, "cached"); continue
        stacks = {k: [] for k in ("ndvi", "nbr", "ndmi", "B02", "B03", "B04")}
        n_used, failed = 0, []
        with ThreadPoolExecutor(12) as ex:
            for iid, out, status in ex.map(process_scene, byq[q]):
                if status.startswith("error"):
                    failed.append((iid, status)); continue
                if iid not in done:
                    log.write(f"{q},{iid},{status},{out['frac']:.4f}\n"); log.flush()
                if status == "ok":
                    n_used += 1
                    for k in stacks:
                        stacks[k].append(out[k])
        if failed:  # never write a composite with silently missing scenes
            for f in failed:
                print("FAILED", *f)
            sys.exit(f"{q}: {len(failed)} scene(s) failed to download; re-run to retry")
        res = {"n_scenes_total": len(byq[q]), "n_scenes_used": n_used}
        if n_used:
            res["count"] = np.isfinite(np.stack(stacks["ndvi"])).sum(0).astype(np.int16)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                for k, v in stacks.items():
                    res[k] = np.nanmedian(np.stack(v), axis=0).astype(np.float32)
        np.savez_compressed(fn, **res)
        print(q, "scenes", len(byq[q]), "used", n_used, flush=True)


if __name__ == "__main__":
    main(sys.argv[1:] or None)
