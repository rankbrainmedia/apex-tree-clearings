#!/usr/bin/env python
"""Step 8 (optional): before/after panels for the 30-event validation sample, using only
public-domain Sentinel-2 composites (this pipeline) and USDA NAIP (Planetary Computer).

Usage: python 08_sample_panels.py [--sample reference/sample30.csv] [--dest OUT/sample30]

Six panels per event:
  NAIP 2020 (Jul 2020, 0.6 m) | NAIP 2022 (Sep-Oct 2022, 0.6 m) | S2 2022Q3 median (baseline)
  S2 first-detection quarter median | S2 2026Q3 median (latest leaf-on) | S2 2026Q4 median (Oct 1-24, partial)
Yellow outline = the event polygon. No Esri, Google or county basemap imagery is used.
NAIP has no flight after Sept-Oct 2022 over Apex, so every "after" view is Sentinel-2 (10 m).
"""
import argparse, os, warnings
import numpy as np, pandas as pd, geopandas as gpd
import rasterio
from rasterio.vrt import WarpedVRT
from rasterio.enums import Resampling
from affine import Affine
import pystac_client, planetary_computer as pc
from pyproj import Transformer
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import config as C
warnings.simplefilter("ignore")

ap = argparse.ArgumentParser()
ap.add_argument("--sample", default=os.path.join(C.CODE, "reference", "sample30.csv"))
ap.add_argument("--dest", default=os.path.join(C.OUT, "sample30"))
args = ap.parse_args()
os.makedirs(args.dest, exist_ok=True)

S = pd.read_csv(args.sample)
ev = gpd.read_file(os.path.join(C.OUT, "events_full_geometry.geojson"))
ev = ev[ev.clear_id.isin(S.clear_id)].to_crs(C.EPSG).set_index("clear_id")
to_ll = Transformer.from_crs(C.EPSG, 4326, always_xy=True)
cat = pystac_client.Client.open(C.STAC_URL, modifier=pc.sign_inplace)
_rgb = {}


def s2_rgb(q):
    if q not in _rgb:
        z = np.load(os.path.join(C.WORK, f"composite_{q}.npz"))
        a = np.dstack([z["B04"], z["B03"], z["B02"]])
        _rgb[q] = np.clip(np.nan_to_num(a) / 0.16, 0, 1) ** (1 / 1.6)
    return _rgb[q]


def naip(year, bb, px=0.6):
    """Mosaic NAIP RGB for bbox bb (EPSG:32617) from every item of that year touching it."""
    x0, y0, x1, y1 = bb
    lo0, la0 = to_ll.transform(x0, y0); lo1, la1 = to_ll.transform(x1, y1)
    items = list(cat.search(collections=["naip"], bbox=[lo0, la0, lo1, la1],
                            datetime=f"{year}-01-01/{year}-12-31").items())
    w = int(round((x1 - x0) / px)); h = int(round((y1 - y0) / px))
    out = np.zeros((h, w, 3), np.uint8); dates = set()
    for it in sorted(items, key=lambda i: i.datetime, reverse=True):
        # warp each NAIP tile straight onto the chip grid (EPSG:32617, px metres)
        with rasterio.open(it.assets["image"].href) as src, \
                WarpedVRT(src, crs=f"EPSG:{C.EPSG}", transform=Affine(px, 0, x0, 0, -px, y1),
                          width=w, height=h, nodata=0, resampling=Resampling.bilinear) as v:
            a = v.read([1, 2, 3])
        a = np.moveaxis(a, 0, -1)
        fill = (out.sum(-1) == 0) & (a.sum(-1) > 0)
        if fill.any():
            out[fill] = a[fill]; dates.add(it.datetime.strftime("%Y-%m-%d"))
    return (out if out.any() else None), sorted(dates)


for r in S.itertuples():
    g = ev.loc[r.clear_id].geometry
    x0, y0, x1, y1 = g.bounds
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    h = max(max(x1 - x0, y1 - y0) / 2 + 80, 150)
    cx, cy = round(cx / 10) * 10, round(cy / 10) * 10      # snap the chip to the 10 m grid
    h = int(np.ceil(h / 10) * 10)
    bb = (cx - h, cy - h, cx + h, cy + h)
    c0, c1 = int((bb[0] - C.X0) / 10), int((bb[2] - C.X0) / 10)
    r0, r1 = int((C.Y1 - bb[3]) / 10), int((C.Y1 - bb[1]) / 10)
    n20, d20 = naip(2020, bb); n22, d22 = naip(2022, bb)
    q = r.first_quarter
    panels = [(f"NAIP 2020 ({', '.join(d20) or 'n/a'})", n20, "naip"),
              (f"NAIP 2022 ({', '.join(d22) or 'n/a'})", n22, "naip"),
              ("S2 2022Q3 median (baseline)", s2_rgb("2022Q3")[r0:r1, c0:c1], "s2"),
              (f"S2 {q} median (first detection)", s2_rgb(q)[r0:r1, c0:c1], "s2"),
              ("S2 2026Q3 median (latest leaf-on)", s2_rgb("2026Q3")[r0:r1, c0:c1], "s2"),
              ("S2 2026Q4 median (Oct 1-24, partial)", s2_rgb("2026Q4")[r0:r1, c0:c1], "s2")]
    fig, ax = plt.subplots(2, 3, figsize=(15, 10.6))
    for a, (t, im, k) in zip(ax.flat, panels):
        if im is not None:
            a.imshow(im, extent=(bb[0], bb[2], bb[1], bb[3]), interpolation="nearest" if k == "s2" else "antialiased")
        else:
            a.text(0.5, 0.5, "no imagery", ha="center", va="center", transform=a.transAxes)
        gpd.GeoSeries([g]).boundary.plot(ax=a, color="yellow", lw=1.2)
        a.set_xlim(bb[0], bb[2]); a.set_ylim(bb[1], bb[3]); a.set_title(t, fontsize=10)
        a.set_xticks([]); a.set_yticks([])
    lon, lat = to_ll.transform(g.centroid.x, g.centroid.y)
    fig.suptitle(f"{r.clear_id}: {r.acres:.2f} ac, first quarter {q}"
                 f"{' (PROVISIONAL)' if str(r.provisional) == 'True' else ''}, {lat:.5f}, {lon:.5f}. "
                 f"Imagery: USDA NAIP; Copernicus Sentinel-2 (ESA), quarterly medians", fontsize=11)
    plt.tight_layout()
    fig.savefig(os.path.join(args.dest, f"{r.clear_id}.png"), dpi=72); plt.close(fig)
    print(r.clear_id, "NAIP2020", d20, "NAIP2022", d22, flush=True)
