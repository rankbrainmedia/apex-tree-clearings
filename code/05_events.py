#!/usr/bin/env python
"""Step 5: split >=1-ac clearings into per-quarter clearing events, write GeoJSON + CSV,
run validation (control parks, NAIP 2020-22 loss overlap), render top-5 before/after chips.

Event splitting: each contiguous cleared patch (>= 1 ac, 8-connected) is split into
same-first-quarter connected pieces; pieces < 1 ac (timing noise / phased edges) are merged
into the neighbouring piece they share the longest border with, repeatedly, until every
piece is >= 1 ac. Each feature in the GeoJSON is one such event (>= 1 ac) with its own
first_quarter, so feature acres sum exactly to the patch total and to the CSV.
"""
import os, json, csv, warnings
import numpy as np, geopandas as gpd, rasterio
from rasterio.features import shapes, rasterize
from affine import Affine
from scipy import ndimage
from shapely.geometry import shape, Point
from shapely.ops import unary_union
from pyproj import Transformer
warnings.simplefilter("ignore")
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

import config as Cfg
X0, X1, Y0, Y1 = Cfg.X0, Cfg.X1, Cfg.Y0, Cfg.Y1
W, O = Cfg.WORK, Cfg.OUT
T10 = Affine(10, 0, X0, 0, -10, Y1)
M2_PER_AC = Cfg.M2_PER_AC
MIN_PX = Cfg.MIN_PX
D = np.load(f"{W}/detect.npz")
J = json.load(open(f"{W}/detect.json"))
det_q = J["det_quarters"]; cal = J["calibration"]
first, confirmed, lab, kept = D["first"], D["confirmed"], D["lab"], D["kept"]
B = np.load(f"{W}/baseline.npz")
forest_naip, inb = B["forest"], B["inb"]

# ---------- event splitting ----------
ev = np.zeros(lab.shape, np.int32)
ev_q = {}
next_id = 1
objs = ndimage.find_objects(np.where(kept, lab, 0))
s8 = np.ones((3, 3), int)
for pid, sl in enumerate(objs, start=1):
    if sl is None:
        continue
    pm = (lab[sl] == pid) & kept[sl]
    if not pm.any():
        continue
    fq = first[sl]
    sub = np.zeros(pm.shape, np.int32); subq = {}
    nid = 1
    for k in np.unique(fq[pm]):
        l, n = ndimage.label(pm & (fq == k), structure=s8)
        for j in range(1, n + 1):
            sub[l == j] = nid; subq[nid] = int(k); nid += 1
    while True:
        ids, cnt = np.unique(sub[pm], return_counts=True)
        if len(ids) <= 1:
            break
        small = ids[cnt < MIN_PX]
        if len(small) == 0:
            break
        sid = small[np.argmin(cnt[cnt < MIN_PX])]
        m = sub == sid
        ring = ndimage.binary_dilation(m, structure=s8) & ~m & pm
        nb, nc = np.unique(sub[ring], return_counts=True)
        if len(nb) == 0:
            break
        tgt = nb[np.argmax(nc)]
        sub[m] = tgt
    for sid in np.unique(sub[pm]):
        ev[sl][sub == sid] = next_id; ev_q[next_id] = det_q[subq[sid]]; next_id += 1

# ---------- polygons ----------
geoms = {}
for g, v in shapes(ev, mask=ev > 0, transform=T10, connectivity=8):
    geoms.setdefault(int(v), []).append(shape(g))
to4326 = Transformer.from_crs(32617, 4326, always_xy=True)
rows = []
for eid, gs in geoms.items():
    g = unary_union(gs).buffer(0)  # fix 8-connected corner-touch self-intersections
    m = ev == eid
    c = g.centroid
    lon, lat = to4326.transform(c.x, c.y)
    rows.append(dict(eid=eid, acres=g.area / M2_PER_AC, npx=int(m.sum()), first_quarter=ev_q[eid],
                     confirmed_frac=float(confirmed[m].mean()), cent_lon=round(lon, 6), cent_lat=round(lat, 6),
                     patch_id=int(np.bincount(lab[m]).argmax()), geometry=g))
gdf = gpd.GeoDataFrame(rows, crs=32617).sort_values("acres", ascending=False).reset_index(drop=True)
gdf["clear_id"] = [f"C{i+1:03d}" for i in range(len(gdf))]
gdf["provisional"] = gdf["confirmed_frac"] < 0.5
gdf["acres"] = gdf["acres"].round(2)
out = gdf[["clear_id", "acres", "first_quarter", "cent_lon", "cent_lat", "provisional", "geometry"]].to_crs(4326)
gj = f"{O}/events_full_geometry.geojson"
if os.path.exists(gj):
    os.remove(gj)
out.to_file(gj, driver="GeoJSON")
np.savez_compressed(f"{W}/events.npz", ev=ev)
gdf.drop(columns="geometry").to_csv(f"{W}/events_table.csv", index=False)
eid_to_cid = dict(zip(gdf.eid, gdf.clear_id))

# ---------- CSV ----------
crow = []
for q in det_q:
    sub = gdf[gdf.first_quarter == q]
    c = cal[q]
    note = []
    if not c["leaf_on"]:
        note.append("leaf-off/transition composite: can be first-detection quarter only; timing may lead true clearing by <=1 quarter")
    if q == det_q[-1]:
        note.append("PARTIAL quarter (Oct 1-24 2026 scenes only); detections unconfirmed")
    if sub.provisional.any():
        note.append("contains provisional (unconfirmed) events")
    crow.append(dict(quarter=q, n_patches=len(sub), acres=round(sub.acres.sum(), 1),
                     clear_coverage_pct=c["clear_coverage_pct"], n_scenes=c["n_scenes"], n_scenes_used=c["n_used"],
                     median_clear_obs=c["median_clear_obs"], leaf_on=c["leaf_on"],
                     provisional_acres=round(sub[sub.provisional].acres.sum(), 1), note="; ".join(note)))
with open(f"{O}/clearings_by_quarter.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(crow[0])); w.writeheader(); w.writerows(crow)
base = cal["2022Q3"]
summary = dict(n_events=len(gdf), total_acres=round(gdf.acres.sum(), 1),
               confirmed_acres=round(gdf[~gdf.provisional].acres.sum(), 1),
               provisional_acres=round(gdf[gdf.provisional].acres.sum(), 1),
               n_contiguous_patches=int(gdf.patch_id.nunique()),
               baseline_2022Q3=dict(clear_coverage_pct=base["clear_coverage_pct"], n_scenes=base["n_scenes"],
                                    n_used=base["n_used"], median_clear_obs=base["median_clear_obs"]),
               cand_ac=round(J["cand_ac"], 1), ambig_ac=round(J["ambig_ac"], 1),
               forest_naip_ac=round(forest_naip.sum() * 100 / M2_PER_AC, 1))

# ---------- validation (a): control sites ----------
fromll = Transformer.from_crs(4326, 32617, always_xy=True)
yy, xx = np.mgrid[0:lab.shape[0], 0:lab.shape[1]]
cx = X0 + 10 * xx + 5; cy = Y1 - 10 * yy - 5
controls = {name: (lon, lat) for name, lon, lat, _src in Cfg.CONTROLS}
ctrl_src = {name: src for name, _lon, _lat, src in Cfg.CONTROLS}
ctrl = {}
cleared_any = first >= 0
for name, (lon, lat) in controls.items():
    x, y = fromll.transform(lon, lat)
    m = ((cx - x) ** 2 + (cy - y) ** 2 <= Cfg.CONTROL_RADIUS_M ** 2) & inb
    ctrl[name] = dict(lon=lon, lat=lat, source=ctrl_src[name], radius_m=Cfg.CONTROL_RADIUS_M, window_ac=round(m.sum() * 100 / M2_PER_AC, 1),
                      baseline_forest_ac=round((m & forest_naip).sum() * 100 / M2_PER_AC, 1),
                      cleared_pixels_any_size_ac=round((m & cleared_any).sum() * 100 / M2_PER_AC, 2),
                      cleared_in_ge1ac_events_ac=round((m & (ev > 0)).sum() * 100 / M2_PER_AC, 2),
                      events=sorted({eid_to_cid[e] for e in np.unique(ev[m]) if e > 0}))
stable = D["stable"]
ctrl["stable-forest reference pixels (all quarters)"] = dict(
    n_px=int(stable.sum()), ac=round(stable.sum() * 100 / M2_PER_AC, 1),
    cleared_px_ac=round((stable & cleared_any).sum() * 100 / M2_PER_AC, 2),
    note="circular check only: reference was selected as dense at both ends of the period")
summary["controls"] = ctrl

# ---------- validation (c): NAIP 2020-2022 loss polygons ----------
loss = gpd.read_file(Cfg.NAIP_LOSS_2020_2022).to_crs(32617)
lm = rasterize([(g, 1) for g in loss.geometry], out_shape=lab.shape, transform=T10).astype(bool) & inb
summary["naip_2020_2022_loss_check"] = dict(
    loss_polygons=len(loss), loss_ac_poly=round(loss.acres.sum(), 1), loss_ac_10m=round(lm.sum() * 100 / M2_PER_AC, 1),
    of_which_baseline_forest_ac=round((lm & forest_naip).sum() * 100 / M2_PER_AC, 1),
    of_which_candidates_ac=round((lm & D["cand"]).sum() * 100 / M2_PER_AC, 1),
    of_which_detected_new_any_ac=round((lm & cleared_any).sum() * 100 / M2_PER_AC, 2),
    of_which_in_ge1ac_events_ac=round((lm & (ev > 0)).sum() * 100 / M2_PER_AC, 2),
    events_touching=sorted({eid_to_cid[e] for e in np.unique(ev[lm]) if e > 0}))

# ---------- validation (b): chips ----------
def rgb(q):
    z = np.load(f"{W}/composite_{q}.npz")
    a = np.dstack([z["B04"], z["B03"], z["B02"]])
    return np.clip(np.nan_to_num(a) / 0.16, 0, 1) ** (1 / 1.6)
last_on = [q for q in det_q if cal[q]["leaf_on"]][-1]
R0 = rgb("2022Q3"); R1 = rgb(last_on)
os.makedirs(f"{O}/chips", exist_ok=True)
chips = []
for _, r in gdf.head(5).iterrows():
    m = ev == r.eid
    rr, cc = np.where(m)
    pad = 25
    r0, r1 = max(rr.min() - pad, 0), min(rr.max() + pad, lab.shape[0])
    c0, c1 = max(cc.min() - pad, 0), min(cc.max() + pad, lab.shape[1])
    side = max(r1 - r0, c1 - c0)
    r1 = min(r0 + side, lab.shape[0]); c1 = min(c0 + side, lab.shape[1])
    qmid = r.first_quarter
    # 'during' = the quarter of first detection composite
    Rq = rgb(qmid)
    fig, ax = plt.subplots(1, 3, figsize=(15, 5.3))
    for a, img, t in zip(ax, (R0, Rq, R1), ("before: 2022Q3 median", f"first-detect: {qmid} median", f"after: {last_on} median")):
        a.imshow(img[r0:r1, c0:c1], interpolation="nearest")
        a.contour(m[r0:r1, c0:c1].astype(float), levels=[0.5], colors="yellow", linewidths=1.0)
        a.contour((ev[r0:r1, c0:c1] > 0) & ~m[r0:r1, c0:c1], levels=[0.5], colors="cyan", linewidths=0.6)
        a.contour(forest_naip[r0:r1, c0:c1].astype(float), levels=[0.5], colors="lime", linewidths=0.3, alpha=0.5)
        a.set_title(t, fontsize=10); a.set_xticks([]); a.set_yticks([])
    fig.suptitle(f"{r.clear_id}: {r.acres:.1f} ac, first quarter {qmid}, centroid {r.cent_lat:.5f}, {r.cent_lon:.5f}  "
                 f"(yellow=this event, cyan=other events, green=NAIP-2022 forest edge)", fontsize=10)
    plt.tight_layout()
    fn = f"{O}/chips/{r.clear_id}_{r.first_quarter}_{r.acres:.0f}ac.png"
    fig.savefig(fn, dpi=110); plt.close(fig)
    chips.append(fn)
# control chips
for name, (lon, lat) in controls.items():
    x, y = fromll.transform(lon, lat)
    c = int((x - X0) // 10); rr_ = int((Y1 - y) // 10); h = 45
    sl = (slice(rr_ - h, rr_ + h), slice(c - h, c + h))
    fig, ax = plt.subplots(1, 2, figsize=(10, 5.3))
    for a, img, t in zip(ax, (R0, R1), ("2022Q3", last_on)):
        a.imshow(img[sl], interpolation="nearest")
        a.contour((ev[sl] > 0).astype(float), levels=[0.5], colors="yellow", linewidths=1)
        a.contour(forest_naip[sl].astype(float), levels=[0.5], colors="lime", linewidths=0.3)
        a.add_patch(plt.Circle((h, h), 30, fill=False, color="white", ls="--"))
        a.set_title(t); a.set_xticks([]); a.set_yticks([])
    fig.suptitle(f"CONTROL {name} (300 m radius dashed; yellow = detected clearings)", fontsize=10)
    plt.tight_layout()
    slug = "".join(ch if ch.isalnum() else "_" for ch in name.split("(")[0].strip())[:40].strip("_")
    fig.savefig(f"{O}/chips/control_{slug}.png", dpi=100); plt.close(fig)
summary["chips"] = chips
summary["top5"] = gdf.head(5)[["clear_id", "acres", "first_quarter", "cent_lon", "cent_lat", "provisional"]].to_dict("records")
json.dump(summary, open(f"{O}/validation_summary.json", "w"), indent=1, default=str)
print(json.dumps(summary, indent=1, default=str))
print(open(f"{O}/clearings_by_quarter.csv").read())
