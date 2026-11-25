#!/usr/bin/env python3
"""build_panel.py: one neighbourhood, three aerial photos, with the Town's Plant the Peak points marked on the latest.

    ../apex-canopy/df-venv/bin/python build_panel.py [--refetch]

Site rule (fixed before looking at any picture): the clearing in the 2017-2026 series with the most Plant the Peak points
CLEARLY inside its outline, meaning at least 10 metres from the outline's edge (one satellite cell), measured in EPSG:32617.
The count at 20 metres is reported too, to show the ranking does not hang on the threshold. A site on or beside the Seymour Mixed Use PUD ground (23CZ13),
which is next to the author's home, would be skipped; the check is in the code.

Inputs
  inputs/PRIVATE_plant_the_peak_points_*.geojson   the Town's public layer (PRIVATE: it carries home addresses; none is used here)
  ../out_verify/sample_frame_outlines.geojson      the 497 clearings of the 2017-2026 series (the frame the verification sample was drawn from)
  ../entitlement/inputs/town_hoa_os_rca_*.geojson  the Town's HOA / open space / RCA layer, for the subdivision name on the recorded plats
  ../entitlement/inputs/town_rezoning_*.geojson    to locate 23CZ13 for the conflict check
Pictures: USDA NAIP aerial photos from Microsoft Planetary Computer's public storage, the same source and tile list as
  verify/render.py (out_verify/_meta/naip_items_v2.json). Frames are kept in out/panel_cache/.
Outputs
  ../article/out/img/plant-panel.png           three panels side by side, about 3000 px wide
  ../article/out/img/plant-panel-stacked.png   the same three stacked, 1200 px wide, for phones
  out/panel_site_ranking.csv                   every clearing with at least one point: counts only, no addresses
  out/panel_caption.json                       site, acres, photo dates, counts, draft caption
"""
import glob, json, os, sys, time, warnings
import numpy as np, pandas as pd, geopandas as gpd
warnings.simplefilter("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
T = os.path.normpath(os.path.join(HERE, ".."))
OUT = os.path.join(HERE, "out")
CACHE = os.path.join(OUT, "panel_cache")
IMG = os.path.join(T, "article", "out", "img")
ACCENT = "#a42528"                       # the site's red; the only colour in the graphic
INK, MUTED = "#1c1c1c", "#5f5f5f"
EDGE_M = (10, 20)
YEARS = (2016, 2022, 2025)               # before the clearing; the first flight in which the whole outline is built on (in 2020 the north half was still graded dirt); the latest flight
for k, v in dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MULTIRANGE="YES", GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES", VSI_CACHE="TRUE", GDAL_HTTP_MAX_RETRY="5", GDAL_HTTP_RETRY_DELAY="2",
                 CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif").items():
    os.environ.setdefault(k, v)


def newest(pattern):
    return sorted(glob.glob(pattern))[-1]


# ------------------------------------------------------------------------------------------------ counts and ranking
pts = gpd.read_file(newest(os.path.join(HERE, "inputs", "PRIVATE_plant_the_peak_points_*.geojson"))).to_crs(32617)[["FID", "YearMarker", "geometry"]]
outl = gpd.read_file(os.path.join(T, "out_verify", "sample_frame_outlines.geojson")).to_crs(32617)
assert len(outl) == 497, len(outl)
hoa = gpd.read_file(newest(os.path.join(T, "entitlement", "inputs", "town_hoa_os_rca_*.geojson"))).to_crs(32617)
rez = gpd.read_file(newest(os.path.join(T, "entitlement", "inputs", "town_rezoning_*.geojson"))).to_crs(32617)
j = gpd.sjoin(pts, outl[["id", "geometry"]], predicate="within")
assert j.FID.is_unique                                                   # outlines do not overlap, so a point is in one at most
geom = outl.set_index("id").geometry
j["edge_m"] = [geom[i].boundary.distance(g) for i, g in zip(j.id, j.geometry)]

# the subdivision named on the recorded plats that overlap the clearing most (Town layer; public names only)
SUBS = ["JORDAN POINTE", "LAKE CASTLEBERRY", "WILLIAMS GROVE", "SMITH FARM", "RETREAT AT CEDAR CROSSING", "RETREAT @ CEDAR CROSSING", "OLIVE RIDGE", "BUCKHORN PRESERVE", "WEST VILLAGE", "FRIENDSHIP STATION"]


def plat_name(g):
    near = hoa[hoa.intersects(g.buffer(30))]
    if not len(near): return ""
    ov = near.intersection(g.buffer(30)).area
    best = {}
    for desc, a in zip(near.PROPDESC.astype(str).str.upper(), ov):
        for s in SUBS:
            if s in desc: best[s.replace(" @ ", " AT ")] = best.get(s.replace(" @ ", " AT "), 0) + a
    return max(best, key=best.get).title().replace(" At ", " at ") if best else ""


rank = j.groupby("id").agg(points_inside=("FID", "size"), **{f"clearly_inside_{m}m": ("edge_m", lambda s, m=m: int((s >= m).sum())) for m in EDGE_M}).reset_index()
rank = rank.merge(outl[["id", "acres", "first_quarter"]], on="id")
rank["first_detected"] = rank.first_quarter
rank["subdivision_on_recorded_plats"] = [plat_name(geom[i]) for i in rank.id]
rank = rank.sort_values([f"clearly_inside_{EDGE_M[0]}m", f"clearly_inside_{EDGE_M[1]}m", "points_inside"], ascending=False)[
    ["id", "subdivision_on_recorded_plats", "acres", "first_detected", "points_inside", f"clearly_inside_{EDGE_M[0]}m", f"clearly_inside_{EDGE_M[1]}m"]]
os.makedirs(OUT, exist_ok=True)
rank.to_csv(os.path.join(OUT, "panel_site_ranking.csv"), index=False)
TOTAL_INSIDE, CLEARLY = len(j), {m: int((j.edge_m >= m).sum()) for m in EDGE_M}
print(f"{TOTAL_INSIDE} of {len(pts)} points are inside an outline of the 2017-2026 series ({len(rank)} clearings); clearly inside: " + ", ".join(f"{CLEARLY[m]} at {m} m" for m in EDGE_M))
print(rank.head(8).to_string(index=False))

# the Seymour Mixed Use PUD ground is next to the author's home and is left out of this work: skip a site on or beside it
seymour = rez[rez.Petition.astype(str) == "23CZ13"].geometry.union_all()
site = None
for cid in rank.id:
    d_sey = geom[cid].distance(seymour)
    if d_sey < 500:
        print(f"SKIPPED: {cid} ({d_sey:.0f} m from the 23CZ13 ground)"); continue
    site = cid; print(f"site: {cid}; {d_sey / 1000:.1f} km from the 23CZ13 ground"); break
S = rank[rank.id == site].iloc[0]
G = geom[site]

# ------------------------------------------------------------------------------------------------ the three photos
x0, y0, x1, y1 = G.bounds
MARGIN = 90
W = max(x1 - x0, y1 - y0) + 2 * MARGIN
ASPECT = 1.0                                                              # square panels: they stack and sit side by side equally well
cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
BB = (cx - W / 2, cy - W / (2 * ASPECT), cx + W / 2, cy + W / (2 * ASPECT))
PX = 1500                                                                 # pixels across a frame as fetched (NAIP is 0.3 to 0.6 m; the frame is under 700 m)
tiles_all = json.load(open(os.path.join(T, "out_verify", "_meta", "naip_items_v2.json")))


def fetch(year):
    """The NAIP flight of that year over the frame, and the dates of the tiles used (newest on top), kept in out/panel_cache/."""
    from PIL import Image
    fi, fj = os.path.join(CACHE, f"{site}_{round(W)}_{PX}_naip{year}.jpg"), os.path.join(CACHE, f"{site}_{round(W)}_{PX}_naip{year}.json")
    if os.path.exists(fj) and "--refetch" not in sys.argv:
        return np.asarray(Image.open(fi).convert("RGB")), json.load(open(fj))["dates"]
    import rasterio, planetary_computer as pc
    from rasterio.vrt import WarpedVRT
    from rasterio.enums import Resampling
    from affine import Affine
    h = round(PX / ASPECT); px = W / PX
    out = np.zeros((h, PX, 3), np.uint8); dates = set()
    tiles = [t for t in tiles_all if t["year"] == year and t["bounds"][0] < BB[2] and t["bounds"][2] > BB[0] and t["bounds"][1] < BB[3] and t["bounds"][3] > BB[1]]
    for t in sorted(tiles, key=lambda t: t["date"], reverse=True):
        for attempt in range(4):
            try:
                with rasterio.open(pc.sign(t["href"])) as src, WarpedVRT(src, crs="EPSG:32617", transform=Affine(px, 0, BB[0], 0, -px, BB[3]), width=PX, height=h, nodata=0, resampling=Resampling.bilinear) as v:
                    a = np.moveaxis(v.read([1, 2, 3]), 0, -1)
                break
            except Exception:
                if attempt == 3: raise
                time.sleep(3 * (attempt + 1))
        fill = (out.sum(-1) == 0) & (a.sum(-1) > 0)
        if fill.any():
            out[fill] = a[fill]; dates.add(t["date"])
    os.makedirs(CACHE, exist_ok=True)
    Image.fromarray(out).save(fi, quality=94); json.dump(dict(dates=sorted(dates)), open(fj, "w"))
    return out, sorted(dates)


photos = {y: fetch(y) for y in YEARS}
in_frame = pts[pts.geometry.x.between(BB[0], BB[2]) & pts.geometry.y.between(BB[1], BB[3])]
in_site = j[j.id == site]
N_FRAME, N_SITE, N_CLEAR = len(in_frame), len(in_site), int((in_site.edge_m >= EDGE_M[0]).sum())
N_SPOTS = len(set(zip(in_frame.geometry.x.round(1), in_frame.geometry.y.round(1))))          # some points share a position, so there are fewer rings than trees
print(f"frame {W:.0f} m across; points in the frame {N_FRAME}; inside the outline {N_SITE}; clearly inside {N_CLEAR}; photo dates " + "; ".join(f"{y}: {', '.join(d)}" for y, (_, d) in photos.items()))


def nice(d):
    y, m, dd = d.split("-"); return f"{['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'][int(m) - 1]} {int(dd)}, {y}"


def dates_text(ds):
    return nice(ds[0]) if len(ds) == 1 else " and ".join(nice(d) for d in ds)


TITLES = [(f"{YEARS[0]}: before", dates_text(photos[YEARS[0]][1]), "Outline: the ground later cleared"),
          (f"{YEARS[1]}: homes built", dates_text(photos[YEARS[1]][1]), "Outline: the same ground"),
          (f"{YEARS[2]}: latest photo", dates_text(photos[YEARS[2]][1]), f"Rings: {N_FRAME} Plant the Peak trees")]


def draw(layout, dest, width_px):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patheffects as pe
    side = layout == "side"
    dpi = 200
    if side:
        fw = width_px / dpi; pw = fw * 0.3187; fh = pw / ASPECT + 1.05
        fig = plt.figure(figsize=(fw, fh), dpi=dpi, facecolor="white")
        axes = [fig.add_axes([0.012 + i * (0.3187 + 0.0102), 0.02 * (fw / fh) * 0.6, 0.3187, (pw / ASPECT) / fh]) for i in range(3)]
        fs_t, fs_s = 19, 12.5
    else:
        fw = width_px / dpi; pw = fw * 0.94; ph = pw / ASPECT; head = 0.62; fh = 3 * (ph + head) + 0.12
        fig = plt.figure(figsize=(fw, fh), dpi=dpi, facecolor="white")
        axes = [fig.add_axes([0.03, 1 - ((i + 1) * (ph + head)) / fh, 0.94, ph / fh]) for i in range(3)]
        fs_t, fs_s = 15, 10
    for a, y, (title, date, key) in zip(axes, YEARS, TITLES):
        a.imshow(photos[y][0], extent=(BB[0], BB[2], BB[1], BB[3]), interpolation="antialiased")
        ln = gpd.GeoSeries([G]).boundary.plot(ax=a, color="white", lw=1.5 if side else 1.2, alpha=0.95)
        for coll in ln.collections:
            coll.set_path_effects([pe.Stroke(linewidth=3.2 if side else 2.6, foreground="#222222", alpha=0.75), pe.Normal()])
        if y == YEARS[2]:
            a.scatter(in_frame.geometry.x, in_frame.geometry.y, s=260 if side else 150, facecolors="none", edgecolors="white", linewidths=5.2 if side else 4.2, zorder=5)
            a.scatter(in_frame.geometry.x, in_frame.geometry.y, s=260 if side else 150, facecolors="none", edgecolors=ACCENT, linewidths=3.0 if side else 2.4, zorder=6)
        a.set_xlim(BB[0], BB[2]); a.set_ylim(BB[1], BB[3]); a.set_xticks([]); a.set_yticks([]); a.set_xlabel(""); a.set_ylabel("")
        for s in a.spines.values(): s.set_edgecolor("#bdbdbd"); s.set_linewidth(0.8)
        b = a.get_position()
        fig.text(b.x0, b.y1 + (0.50 if side else 0.33) / fh, title, fontsize=fs_t, fontweight="bold", color=ACCENT if y == YEARS[2] else INK, ha="left", va="bottom", family="Helvetica")
        fig.text(b.x0, b.y1 + (0.12 if side else 0.09) / fh, f"{date}   ·   {key}", fontsize=fs_s, color=MUTED, ha="left", va="bottom", family="Helvetica")
    fig.savefig(dest, dpi=dpi, facecolor="white"); plt.close(fig)


draw("side", os.path.join(IMG, "plant-panel.png"), 3000)
draw("stacked", os.path.join(IMG, "plant-panel-stacked.png"), 1200)
name = S.subdivision_on_recorded_plats
cap = dict(site=name, clearing_id=site, acres_cleared=round(float(S.acres), 1), first_detected=S.first_detected, frame_metres=round(W),
           photo_dates={str(y): d for y, (_, d) in photos.items()}, trees_marked_in_frame=N_FRAME, ring_positions_in_frame=N_SPOTS, points_inside_the_outline=N_SITE, points_clearly_inside_10m=N_CLEAR,
           all_points_inside_any_series_outline=TOTAL_INSIDE, all_points_clearly_inside_10m=CLEARLY[10], all_points_clearly_inside_20m=CLEARLY[20],
           accent_colour=ACCENT, imagery="USDA National Agriculture Imagery Program (NAIP) aerial photos, from Microsoft Planetary Computer's public storage",
           points="Town of Apex, Plant the Peak public map layer, pulled November 25, 2026",
           caption=(f"{name}, southwest Apex. The outline is {float(S.acres):.1f} acres of forest the satellite count shows cleared, first detected in late 2017. Aerial photos of {dates_text(photos[YEARS[0]][1])}, "
                    f"{dates_text(photos[YEARS[1]][1])} and {dates_text(photos[YEARS[2]][1])}. The red rings on the last photo mark the {N_FRAME} Plant the Peak trees on the Town's map inside this frame, at {N_SPOTS} spots (some trees share a spot on the map); {N_SITE} are inside the outline and {N_CLEAR} are at least 10 metres inside it. "
                    "Other planting visible in the photo, such as street trees and yard trees planted by builders or owners, is not marked."))
json.dump(cap, open(os.path.join(OUT, "panel_caption.json"), "w"), indent=1)
print(json.dumps(cap, indent=1))
