#!/usr/bin/env python
"""render.py: one PNG per clearing in ../out_verify/items.csv, with the outline drawn on every panel.

    ../apex-canopy/df-venv/bin/python render.py [--only C001,D0106] [--workers 6] [--redo]

Panels, left to right (a panel is left out where it would repeat another or has nothing to show):
  NAIP before            the latest NAIP flight whose every tile over the frame was flown before the first-detection quarter began
  NAIP during            a NAIP flight flown inside the first-detection quarter, if there was one (it may show either state)
  NAIP first after       the first NAIP flight flown wholly after that quarter ended, where that is not also the latest one
  NAIP after             the latest NAIP flight flown wholly after that quarter ended. The latest flight over Apex is July 25, 2025
                         (30 cm), so clearings first detected from July 2025 on have no NAIP "after": the panel says so.
  State aerial photo     NC OneMap "Orthoimagery_Latest" (the State's 6-inch leaf-off photography; February 14, 2025 here).
                         Not NAIP. Its title says whether it was flown before or after first detection.
  Sentinel-2 before      true colour, median of the last July-September before the first-detection quarter (10 m)
  Sentinel-2 latest      true colour, median of October 1-24, 2026, the most recent images in the detection (10 m)
Sources are all public: USDA NAIP on Microsoft Planetary Computer (2012-2022 through its search catalogue; the 2025 flight is
in the same public storage but not yet in the catalogue, so its tiles are listed from the storage itself, as
entitlement/wake_tca.py does); the NC OneMap image service; Copernicus Sentinel-2 composites already built for the detection.
Already-rendered PNGs are skipped unless --redo. The frames fetched are kept in apex-canopy/verify_cache/. Dates of every
image used go to ../out_verify/_meta/<id>.json, which make_index.py collects.
"""
import argparse, io, json, os, re, time, urllib.parse, urllib.request, warnings
from multiprocessing import Pool
import numpy as np, pandas as pd, geopandas as gpd
warnings.simplefilter("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
AC = os.path.join(ROOT, "apex-canopy")
OUT = os.path.join(ROOT, "out_verify")
META = os.path.join(OUT, "_meta")
CHIPS = os.path.join(AC, "verify_cache")           # the NAIP and State photo frames as fetched, so a re-render does not fetch them again
X0, Y1 = 683800, 3961460
PANEL_PX = 720                                   # pixels read per panel side
NAIP_STORE = "https://naipeuwest.blob.core.windows.net/naip"
NAIP_2025_PREFIX = "v002/nc/2025/nc_030cm_2025/35078/"          # in Planetary Computer's public storage, not yet in its search catalogue
STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
BBOX = [-78.969003, 35.664933, -78.802403, 35.778735]
ORTHO = "https://services.nconemap.gov/secure/rest/services/Imagery/Orthoimagery_Latest/ImageServer"
UA = {"User-Agent": "Mozilla/5.0 (verification image set)"}
S2_LATEST = "2026Q4"
for k, v in dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MULTIRANGE="YES", GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES", VSI_CACHE="TRUE", GDAL_HTTP_MAX_RETRY="5", GDAL_HTTP_RETRY_DELAY="2",
                 CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif").items():
    os.environ.setdefault(k, v)


def naip_catalogue():
    """Every NAIP tile over the study area: id, date, address and footprint. Cached for the run."""
    fn = os.path.join(META, "naip_items_v2.json")
    if os.path.exists(fn):
        return json.load(open(fn))
    import pystac_client, rasterio, planetary_computer as pc
    from shapely.geometry import shape
    from pyproj import Transformer
    from shapely.ops import transform
    tr = Transformer.from_crs(4326, 32617, always_xy=True).transform
    items = []
    for it in pystac_client.Client.open(STAC).search(collections=["naip"], bbox=BBOX).items():
        items.append(dict(id=it.id, year=it.datetime.year, date=it.datetime.date().isoformat(), href=it.assets["image"].href, bounds=list(transform(tr, shape(it.geometry)).bounds)))
    # the 2025 flight: list the tiles from the public storage container, then read each one's footprint from its header
    tok = get("https://planetarycomputer.microsoft.com/api/sas/v1/token/naipeuwest/naip", {})["token"]
    xml = urllib.request.urlopen(urllib.request.Request(f"{NAIP_STORE}?restype=container&comp=list&prefix={NAIP_2025_PREFIX}&{tok}", headers=UA), timeout=90).read().decode()
    x0, y0 = tr(BBOX[0], BBOX[1]); x1, y1 = tr(BBOX[2], BBOX[3])
    for n in sorted(re.findall(r"<Name>([^<]+\.tif)</Name>", xml)):
        if not re.search(r"m_35078(09|10|17|18)_", n):
            continue
        d = re.search(r"_(\d{4})(\d{2})(\d{2})\.tif$", n)
        href = f"{NAIP_STORE}/{n}"
        with rasterio.open(pc.sign(href)) as src:
            b = src.bounds                      # NAD83 UTM 17N, read as WGS84 UTM 17N (about a metre apart), as elsewhere in this project
        if b.left < x1 and b.right > x0 and b.bottom < y1 and b.top > y0:
            items.append(dict(id="nc_" + os.path.basename(n)[:-4], year=int(d.group(1)), date="-".join(d.groups()), href=href, bounds=[b.left, b.bottom, b.right, b.top]))
    json.dump(items, open(fn, "w"))
    return items


_S2 = {}


def s2_rgb(q):
    if q not in _S2:
        fn = os.path.join(AC, "s2", "cache", f"composite_{q}.npz")
        if not os.path.exists(fn):
            fn = os.path.join(AC, "prerezoning_cache", "s2", f"composite_{q}.npz")
        z = np.load(fn)
        a = np.dstack([z["B04"], z["B03"], z["B02"]]).astype(np.float32)
        ok = np.isfinite(a).all(-1)
        _S2[q] = (np.clip(np.nan_to_num(a) / 0.32, 0, 1) ** (1 / 2.2), ok)      # soft enough that bare ground keeps its detail; both Sentinel-2 panels use it
    return _S2[q]


def s2_before_quarter(q):
    """The last July-September composite before quarter q. The 2017 baseline is the pooled May-September 2017 composite."""
    y, n = int(q[:4]), int(q[5])
    y = y if n == 4 else y - 1
    return "2017MS" if y <= 2017 else f"{y}Q3"


def read_naip(tiles, bb):
    """Mosaic of the given tiles on the frame bb (EPSG:32617), newest tile on top. Returns (array or None, dates used)."""
    import rasterio, planetary_computer as pc
    from rasterio.vrt import WarpedVRT
    from rasterio.enums import Resampling
    from affine import Affine
    x0, y0, x1, y1 = bb
    px = (x1 - x0) / PANEL_PX
    out = np.zeros((PANEL_PX, PANEL_PX, 3), np.uint8); dates = set()
    for t in sorted(tiles, key=lambda t: t["date"], reverse=True):
        for attempt in range(4):
            try:
                with rasterio.open(pc.sign(t["href"])) as src, WarpedVRT(src, crs="EPSG:32617", transform=Affine(px, 0, x0, 0, -px, y1), width=PANEL_PX, height=PANEL_PX, nodata=0,
                                                                        resampling=Resampling.bilinear) as v:
                    a = np.moveaxis(v.read([1, 2, 3]), 0, -1)
                break
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(3 * (attempt + 1))
        fill = (out.sum(-1) == 0) & (a.sum(-1) > 0)
        if fill.any():
            out[fill] = a[fill]; dates.add(t["date"])
    return (out if out.any() else None), sorted(dates)


def get(url, params, binary=False):
    u = url + "?" + urllib.parse.urlencode(params)
    for attempt in range(5):
        try:
            b = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=90).read()
            return b if binary else json.loads(b)
        except Exception:
            if attempt == 4:
                raise
            time.sleep(4 * (attempt + 1))


def read_ortho(bb):
    """The State's latest aerial photo over the frame, and its flight date from the tile name (e.g. OF6i0_37_000_20073102_20250214_0226R0)."""
    from PIL import Image
    x0, y0, x1, y1 = bb
    img = get(ORTHO + "/exportImage", dict(bbox=f"{x0},{y0},{x1},{y1}", bboxSR=32617, imageSR=32617, size=f"{PANEL_PX},{PANEL_PX}", format="jpg", f="image"), binary=True)
    a = np.asarray(Image.open(io.BytesIO(img)).convert("RGB"))
    dates = set()
    for fx, fy in ((0.5, 0.5), (0.2, 0.2), (0.8, 0.8), (0.2, 0.8), (0.8, 0.2)):
        r = get(ORTHO + "/identify", dict(geometry=json.dumps({"x": x0 + fx * (x1 - x0), "y": y0 + fy * (y1 - y0), "spatialReference": {"wkid": 32617}}), geometryType="esriGeometryPoint",
                                          returnCatalogItems="true", returnGeometry="false", f="json"))
        for f in r.get("catalogItems", {}).get("features", []):
            at = f.get("attributes", {})
            if float(at.get("lowps") or 99) > 1:                      # overview rows, not the photo itself
                continue
            for d in re.findall(r"(?<=_)(20[1-3]\d)(0[1-9]|1[0-2])([0-3]\d)(?=_)", str(at.get("name", ""))):      # the tile number also has 8 digits; only a real date passes
                dates.add("-".join(d))
    return (a if a.max() > 0 else None), sorted(dates)


def cached(key, fetch):
    """fetch() -> (uint8 image or None, dates). Kept as a JPEG and a small json under CHIPS."""
    from PIL import Image
    fj, fi = os.path.join(CHIPS, key + ".json"), os.path.join(CHIPS, key + ".jpg")
    if os.path.exists(fj):
        d = json.load(open(fj))
        return (np.asarray(Image.open(fi).convert("RGB")) if d["has_image"] else None), d["dates"]
    im, dates = fetch()
    if im is not None:
        Image.fromarray(im).save(fi, quality=93)
    json.dump(dict(has_image=im is not None, dates=dates), open(fj, "w"))
    return im, dates


def render(job):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patheffects as pe
    from shapely import wkb
    r, tiles_all, redo = job
    dest = os.path.join(OUT, r["image"])
    mfn = os.path.join(META, r["id"] + ".json")
    if os.path.exists(dest) and os.path.exists(mfn) and not redo:
        return r["id"], "skipped"
    try:
        g = wkb.loads(bytes.fromhex(r["wkb"]))
        x0, y0, x1, y1 = g.bounds
        cx, cy = round((x0 + x1) / 20) * 10, round((y0 + y1) / 20) * 10          # frame snapped to the 10 m grid
        h = int(np.ceil(max(max(x1 - x0, y1 - y0) / 2 + 80, 150) / 10) * 10)
        bb = (cx - h, cy - h, cx + h, cy + h)
        q = pd.Period(r["first_quarter"], freq="Q")
        q_start, q_end = q.start_time.date().isoformat(), q.end_time.date().isoformat()
        # NAIP: which tiles of each year touch the frame, and when they were flown
        by_year = {}
        for t in tiles_all:
            b = t["bounds"]
            if b[0] < bb[2] and b[2] > bb[0] and b[1] < bb[3] and b[3] > bb[1]:
                by_year.setdefault(t["year"], []).append(t)
        before = max([y for y, ts in by_year.items() if max(t["date"] for t in ts) < q_start], default=None)
        afters = sorted(y for y, ts in by_year.items() if min(t["date"] for t in ts) > q_end)
        after = afters[-1] if afters else None                                  # the latest flight wholly after the quarter
        first_after = afters[0] if len(afters) > 1 else None                    # the first one, where it is a different flight
        during = max([y for y, ts in by_year.items() if any(q_start <= t["date"] <= q_end for t in ts)], default=None)
        key = f"{r['set']}_{r['id']}_{2 * h}"
        nb, db = cached(f"{key}_naip{before}", lambda: read_naip(by_year[before], bb)) if before else (None, [])
        na, da = cached(f"{key}_naip{after}", lambda: read_naip(by_year[after], bb)) if after else (None, [])
        nf, df = cached(f"{key}_naip{first_after}", lambda: read_naip(by_year[first_after], bb)) if first_after else (None, [])
        nd, dd = cached(f"{key}_naip{during}", lambda: read_naip(by_year[during], bb)) if during else (None, [])
        try:
            orth, do = cached(f"{key}_state", lambda: read_ortho(bb))
        except Exception as e:                                           # the State service is the one outside source that can fail: keep going
            orth, do = None, [f"service error: {type(e).__name__}"]
        c0, c1, r0, r1 = int((bb[0] - X0) / 10), int((bb[2] - X0) / 10), int((Y1 - bb[3]) / 10), int((Y1 - bb[1]) / 10)
        qb = s2_before_quarter(r["first_quarter"])
        sb, okb = s2_rgb(qb); sl, okl = s2_rgb(S2_LATEST)
        sb, sl = sb[max(r0, 0):r1, max(c0, 0):c1], sl[max(r0, 0):r1, max(c0, 0):c1]
        ext10 = (X0 + 10 * max(c0, 0), X0 + 10 * min(c1, okb.shape[1]), Y1 - 10 * min(r1, okb.shape[0]), Y1 - 10 * max(r0, 0))
        s2b_gap = round(float(1 - okb[max(r0, 0):r1, max(c0, 0):c1].mean()), 2)
        real_dates = [d for d in do if d[:2] == "20"]
        rel = "" if not real_dates else "AFTER first detection" if min(real_dates) > q_end else "BEFORE first detection" if max(real_dates) < q_start else "DURING the first-detection quarter"
        last_naip = max(t["date"] for ts in by_year.values() for t in ts) if by_year else "none"
        AMBER = "#9a5b00"
        panels = [(f"NAIP before: {', '.join(db) or 'none'}", nb, "No NAIP flight before\nthe first-detection quarter", "k", "air")]
        if during:
            panels.append((f"NAIP DURING the first-detection quarter: {', '.join(dd)}\nmay show the ground before or after the clearing", nd, "", AMBER, "air"))
        if first_after:
            panels.append((f"NAIP first after: {', '.join(df)}", nf, "", "k", "air"))
        panels.append((f"NAIP after{' (latest)' if first_after else ''}: {', '.join(da)}" if after else "NAIP after: none", na, f"No NAIP flight after first detection.\nLatest NAIP here: {last_naip}", "k", "air"))
        panels += [(f"State aerial photo (not NAIP): {', '.join(do) or 'date unknown'}\n{rel}", orth, "State aerial photo not available", "#1b7837" if rel.startswith("AFTER") else "#b2182b", "air"),
                   (f"Sentinel-2 before: {'May-Sep 2017' if qb == '2017MS' else 'Jul-Sep ' + qb[:4]} median (10 m)" + (f"\n{s2b_gap:.0%} of frame has no clear image" if s2b_gap >= 0.05 else ""), sb, "", "k", "s2"),
                   ("Sentinel-2 latest: Oct 1-24, 2026 median (10 m)", sl, "", "k", "s2")]
        n = len(panels)
        fig, ax = plt.subplots(1, n, figsize=(5 * n, 5.75))
        for i, (a, (title, im, missing, colour, kind)) in enumerate(zip(ax, panels)):
            if im is not None:
                a.imshow(im, extent=ext10 if kind == "s2" else (bb[0], bb[2], bb[1], bb[3]), interpolation="nearest" if kind == "s2" else "antialiased")
            else:
                a.set_facecolor("#dddddd"); a.text(0.5, 0.5, missing, ha="center", va="center", transform=a.transAxes, fontsize=13)
            ln = gpd.GeoSeries([g]).boundary.plot(ax=a, color="#ffe600", lw=1.4)
            for coll in ln.collections:
                coll.set_path_effects([pe.Stroke(linewidth=3.4, foreground="black", alpha=0.85), pe.Normal()])
            a.set_xlim(bb[0], bb[2]); a.set_ylim(bb[1], bb[3]); a.set_xticks([]); a.set_yticks([])
            a.set_title(f"{i + 1}. {title}", fontsize=10.5, color=colour)
        case = r["governing_case"] + (f" ({r['case_name']})" if r["case_name"] else "")
        fig.suptitle(f"{r['id']}   {r['acres']:.2f} ac   first detected {r['first_quarter']}   governing case: {case}   {r['centroid_lat']:.5f}, {r['centroid_lon']:.5f}   frame {2 * h} m across   yellow = detected outline",
                     fontsize=12.5, x=0.01, ha="left")
        fig.subplots_adjust(left=0.02 / n, right=1 - 0.02 / n, bottom=0.01, top=0.87, wspace=0.02)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        fig.savefig(dest, dpi=96); plt.close(fig)
        json.dump(dict(id=r["id"], set=r["set"], frame_m=2 * h, panels=n, naip_before_year=before, naip_before_dates=db, naip_first_after_year=first_after, naip_first_after_dates=df, naip_during_year=during, naip_during_dates=dd,
                       naip_after_year=after, naip_after_dates=da, state_photo_dates=do, state_photo_vs_first_detection=rel,
                       s2_before=qb, s2_before_gap_share=s2b_gap, s2_latest=S2_LATEST), open(mfn, "w"))
        return r["id"], "ok"
    except Exception as e:
        return r["id"], f"FAILED {type(e).__name__}: {e}"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=""); ap.add_argument("--workers", type=int, default=6); ap.add_argument("--redo", action="store_true")
    args = ap.parse_args()
    os.makedirs(META, exist_ok=True); os.makedirs(CHIPS, exist_ok=True)
    I = pd.read_csv(os.path.join(OUT, "items.csv")).fillna("")
    G = gpd.read_file(os.path.join(OUT, "outlines.geojson")).to_crs(32617)
    G["key"] = G["set"] + "/" + G["id"]
    wk = dict(zip(G.key, G.geometry.apply(lambda g: g.wkb_hex)))
    if args.only:
        I = I[I.id.isin(args.only.split(","))]
    tiles = naip_catalogue()
    jobs = [(dict(r._asdict(), wkb=wk[r.set + "/" + r.id]), tiles, args.redo) for r in I.itertuples(index=False)]
    t0 = time.time(); done = 0; bad = []
    with Pool(args.workers) as pool:
        for cid, status in pool.imap_unordered(render, jobs):
            done += 1
            if status.startswith("FAILED"):
                bad.append((cid, status))
            if done % 20 == 0 or status.startswith("FAILED"):
                print(f"{done}/{len(jobs)} {cid} {status} ({time.time() - t0:.0f}s)", flush=True)
    print(f"done: {done} items, {len(bad)} failed, {time.time() - t0:.0f}s", flush=True)
    for b in bad:
        print(b)
