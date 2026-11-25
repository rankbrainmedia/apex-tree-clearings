#!/usr/bin/env python
"""s2_composites_2017.py: quarterly Sentinel-2 composites for 2017Q1..2022Q2, to extend the release's
detection back to 2017. Same masking and compositing as the release's 03_composites.py, with one change:

  Reflectance offset by processing baseline. The release used (DN - 1000) / 10000 for every scene because
  all of its scenes were baseline 04.00 or later. Before 04.00 (almost everything before 2022) there is no
  offset, so here the offset is -1000 only where s2:processing_baseline >= 04.00.

    ../apex-canopy/df-venv/bin/python s2_composites_2017.py            # every quarter
    ../apex-canopy/df-venv/bin/python s2_composites_2017.py 2019Q3     # one quarter
    ../apex-canopy/df-venv/bin/python s2_composites_2017.py 2017MS     # the pooled May-Sep 2017 baseline composite

Writes ../apex-canopy/prerezoning_cache/s2/items.json, composite_<Q>.npz, scenes.csv  (not in git: ~700 MB).
"""
import json, os, sys, warnings
from concurrent.futures import ThreadPoolExecutor
import numpy as np, rasterio, pystac, pystac_client
import planetary_computer as pc
from rasterio.windows import from_bounds
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "apex-canopy", "release-v1", "code"))
os.environ.setdefault("APEX_WORK", os.path.join(HERE, "..", "apex-canopy", "prerezoning_cache", "s2"))
os.environ.setdefault("APEX_OUT", os.path.join(HERE, "..", "apex-canopy", "prerezoning_cache", "s2"))
import config as C  # noqa: E402  (grid, masking rules and thresholds: unchanged from the release)

DATE_START, DATE_END = "2017-01-01T00:00:00Z", "2022-06-30T23:59:59Z"
BBOX = [-78.969003, 35.664933, -78.802403, 35.778735]          # bounds of the Apex boundary, as in the release
for k, v in dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MULTIRANGE="YES", GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES",
                 VSI_CACHE="TRUE", GDAL_HTTP_MAX_RETRY="5", GDAL_HTTP_RETRY_DELAY="2").items():
    os.environ.setdefault(k, v)


def quarter_of(d):
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


def load_items():
    fn = os.path.join(C.WORK, "items.json")
    if not os.path.exists(fn):
        cat = pystac_client.Client.open(C.STAC_URL)
        it = cat.search(collections=[C.COLLECTION], bbox=BBOX, datetime=f"{DATE_START}/{DATE_END}").items()
        json.dump([i.to_dict() for i in it if i.properties.get("s2:mgrs_tile") == C.MGRS_TILE], open(fn, "w"))
    raw = json.load(open(fn))
    best = {}
    for d in raw:                                   # reprocessed duplicates of one datatake: keep the newest product
        p = d["properties"]
        key = (p["datetime"][:19], p["sat:relative_orbit"])
        if key not in best or d["id"] > best[key]["id"]:
            best[key] = d
    items = [pystac.Item.from_dict(d) for d in best.values()]
    items.sort(key=lambda i: i.datetime)
    return items, len(raw)


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
    offset = C.BOA_OFFSET if float(item.properties.get("s2:processing_baseline", "0")) >= 4.0 else 0.0
    item = pc.sign(item)
    a = item.assets
    scl20, err = None, None
    for _ in range(3):
        try:
            scl20 = read_window(a["SCL"].href)
            break
        except Exception as e:
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
    try:
        bands = {b: (read_band(a[b].href, r).astype(np.float32) + offset) / 10000.0
                 for b, r in (("B02", 10), ("B03", 10), ("B04", 10), ("B08", 10), ("B11", 20), ("B12", 20))}
    except Exception as e:
        return item.id, None, f"error bands {e}"
    valid = clear & (bands["B04"] > -0.05) & (bands["B08"] > 0)

    def nd(p, q):
        with np.errstate(divide="ignore", invalid="ignore"):
            v = (p - q) / (p + q)
        v[~valid] = np.nan
        return v.astype(np.float32)
    out = {"ndvi": nd(bands["B08"], bands["B04"]), "nbr": nd(bands["B08"], bands["B12"]), "ndmi": nd(bands["B08"], bands["B11"])}
    for b in ("B02", "B03", "B04"):
        v = bands[b].copy(); v[~valid] = np.nan
        out[b] = v.astype(np.float32)
    out["frac"] = float(valid.mean())
    return item.id, out, "ok"


def main(quarters=None):
    items, n_raw = load_items()
    byq = {}
    for it in items:
        byq.setdefault(quarter_of(it.datetime), []).append(it)
    # 2017MS: May 1 to Sep 30, 2017 pooled. In 2017 only one orbit (97) covers Apex and Sentinel-2B started in July, so a
    # single quarter leaves 40% of the area with fewer than two clear looks. The pooled season is the 2017 baseline.
    byq["2017MS"] = [it for it in items if "2017-05-01" <= it.datetime.date().isoformat() <= "2017-09-30"]
    qs = [q for q in sorted(byq) if (not quarters and q != "2017MS") or (quarters and q in quarters)]
    print(f"{n_raw} STAC items, {len(items)} unique scenes in {len(byq)} quarters", flush=True)
    log_fn = os.path.join(C.WORK, "scenes.csv")
    done = {l.split(",")[1] for l in open(log_fn) if l.strip()} if os.path.exists(log_fn) else set()
    log = open(log_fn, "a")
    for q in qs:
        fn = os.path.join(C.WORK, f"composite_{q}.npz")
        if os.path.exists(fn):
            print(q, "cached", flush=True); continue
        stacks = {k: [] for k in ("ndvi", "nbr", "ndmi", "B02", "B03", "B04")}
        n_used, failed = 0, []
        with ThreadPoolExecutor(12) as ex:
            for iid, out, status in ex.map(process_scene, byq[q]):
                if status.startswith("error"):
                    failed.append((iid, status)); continue
                if iid not in done and q != "2017MS":
                    log.write(f"{q},{iid},{status},{out['frac']:.4f}\n"); log.flush()
                if status == "ok":
                    n_used += 1
                    for k in stacks:
                        stacks[k].append(out[k])
        if failed:                                  # never write a composite with silently missing scenes
            for f in failed:
                print("FAILED", *f, flush=True)
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
