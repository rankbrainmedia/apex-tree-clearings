#!/usr/bin/env python
"""build_sets.py: the two verification sets and the blank log. Writes only into ../out_verify/.

    ../apex-canopy/df-venv/bin/python build_sets.py

Set "release": all 238 clearings of the public release (apex-canopy/release-v1/clearings.geojson).
Set "sample":  100 clearings drawn at random from the 2017-2026 detection (prerezoning/detect_2017.py, event rule),
               stratified by year of first detection and by size.

The 2017-2026 detection is a raster, so it is first cut into clearings the way the release was (release code 05_events.py):
each connected cleared patch of an acre or more is split into pieces that share a first-detection quarter, and pieces under
an acre are merged into the neighbour they share the longest border with. Each piece is one clearing, numbered D0001... by size.

The draw: 15 each from 2025 and 2026; the other 70 spread over 2017-2024 in proportion to the number of clearings in each
year (at least 4 a year); within a year, across the size classes (under 3 ac, 3 to 10, over 10) in proportion to their counts,
at least one from every class that has any. Within a stratum the draw is simple random, without replacement, from
numpy.random.default_rng(SEED), taking the strata by year and then by size (under 3, 3 to 10, over 10) and the ids in sorted order.

Set "large" (optional): the clearings over 10 acres that the draw did not pick. Those few clearings hold 44% of the detection's
acres, and the draw takes only one from most year-by-size strata, so the acres-weighted result leans on them. Reviewing them too
turns that size class into a full count. They get their own log, verify_log_large_optional.csv; verify_log.csv is unchanged.

Outputs (out_verify/):
  sample_frame.csv     every clearing in the 2017-2026 detection with its stratum, whether it was drawn, and its weight
  sample_draw.json     the seed, the allocation and the software versions
  items.csv            one row per clearing to review, both sets, with governing case and stratum weights
  outlines.geojson     the outlines, both sets
  verify_log.csv       the blank log: release and sample (never overwritten once any verdict has been entered)
  verify_log_large_optional.csv   the same columns for the optional large set
"""
import json, os, sys
import numpy as np, pandas as pd, geopandas as gpd, shapely, scipy
from affine import Affine
from rasterio.features import shapes
from scipy import ndimage
from shapely.geometry import shape
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
AC = os.path.join(ROOT, "apex-canopy")
OUT = os.path.join(ROOT, "out_verify"); os.makedirs(OUT, exist_ok=True)
SEED = 20261124
N_SAMPLE = 100
FIXED = {2025: 15, 2026: 15}          # at least this many from these years
MIN_PER_YEAR = 4
SIZES = [("under 3 ac", 0, 3), ("3 to 10 ac", 3, 10), ("over 10 ac", 10, 1e9)]
M2_AC = 4046.8564
X0, Y1 = 683800, 3961460
T10 = Affine(10, 0, X0, 0, -10, Y1)
MIN_PX = 41                           # one acre of 10 m cells, as in the release
COI = {"23CZ13": "conflict rule: Seymour Mixed Use PUD", "24CZ20": "conflict rule: held (names the Seymour PUD as adjacent)",
       "24CZ19": "disclosed (Barnett Properties, LLC)", "24CZ08": "disclosed (lists the Seymour PUD as adjacent)"}


def size_class(ac):
    return next(n for n, lo, hi in SIZES if (lo <= ac < hi) or (n == SIZES[1][0] and ac == 10))


def largest_remainder(shares, total, floor, cap):
    """Whole numbers adding to total, close to shares, each between its floor and its cap."""
    keys = list(shares)
    n = {k: min(floor[k], cap[k]) for k in keys}
    left = total - sum(n.values())
    assert left >= 0, "the floors already exceed the total"
    tot = sum(shares.values())
    while left > 0:
        room = [k for k in keys if n[k] < cap[k]]
        if not room:
            break
        want = {k: shares[k] / tot * total - n[k] for k in room}       # how far below its proportional share
        k = max(room, key=lambda k: (want[k], shares[k], str(k)))
        n[k] += 1; left -= 1
    return n


# ------------------------------------------------------------------ 1. the 2017-2026 detection cut into clearings
D = np.load(os.path.join(AC, "prerezoning_cache", "detect_2017.npz"))
J = json.load(open(os.path.join(AC, "prerezoning_cache", "detect_2017.json")))
DET_Q = J["det_quarters"]
kept, first, regrew = D["kept_event"], D["first_event"], D["regrew"]
s8 = np.ones((3, 3), int)
lab, npatch = ndimage.label(kept, structure=s8)
ev = np.zeros(lab.shape, np.int32); ev_q = {}; next_id = 1
for pid, sl in enumerate(ndimage.find_objects(lab), start=1):
    pm = lab[sl] == pid
    fq = first[sl]
    sub = np.zeros(pm.shape, np.int32); subq = {}; nid = 1
    for k in np.unique(fq[pm]):
        l, n = ndimage.label(pm & (fq == k), structure=s8)
        for j in range(1, n + 1):
            sub[l == j] = nid; subq[nid] = int(k); nid += 1
    while True:
        ids, cnt = np.unique(sub[pm], return_counts=True)
        small = ids[cnt < MIN_PX]
        if len(ids) <= 1 or len(small) == 0:
            break
        sid = small[np.argmin(cnt[cnt < MIN_PX])]
        m = sub == sid
        ring = ndimage.binary_dilation(m, structure=s8) & ~m & pm
        nb, nc = np.unique(sub[ring], return_counts=True)
        if len(nb) == 0:
            break
        sub[m] = nb[np.argmax(nc)]
    for sid in np.unique(sub[pm]):
        ev[sl][sub == sid] = next_id; ev_q[next_id] = DET_Q[subq[sid]]; next_id += 1
geoms = {}
for g, v in shapes(ev, mask=ev > 0, transform=T10, connectivity=8):
    geoms.setdefault(int(v), []).append(shape(g))
rows = []
for eid, gs in geoms.items():
    m = ev == eid
    rr, cc = np.where(m)
    rows.append(dict(eid=eid, npx=int(m.sum()), acres=round(m.sum() * 100 / M2_AC, 2), first_quarter=ev_q[eid], regrown_share=round(float(regrew[m].mean()), 2),
                     row0=int(rr.min()), col0=int(cc.min()), geometry=shapely.make_valid(unary_union(gs))))
F = gpd.GeoDataFrame(rows, crs=32617).sort_values(["npx", "row0", "col0"], ascending=[False, True, True]).reset_index(drop=True)
F["id"] = [f"D{i + 1:04d}" for i in range(len(F))]
F["year"] = F.first_quarter.str[:4].astype(int)
F["size_class"] = F.acres.map(size_class)
assert abs(F.npx.sum() - kept.sum()) == 0

# overlap with the release, for reference only
rel = gpd.read_file(os.path.join(AC, "release-v1", "clearings.geojson")).to_crs(32617)
rel["geometry"] = shapely.make_valid(rel.geometry.values)
ov = gpd.overlay(F[["id", "geometry"]], rel[["id", "geometry"]].rename(columns={"id": "rid"}), how="intersection", keep_geom_type=True)
ov["a"] = ov.area
top = ov.sort_values("a", ascending=False).drop_duplicates("id").set_index("id")
F["overlaps_release_id"] = F.id.map(top.rid).fillna("")
F["share_inside_release_outlines"] = (F.id.map(ov.groupby("id").a.sum()).fillna(0) / F.area).round(2)

# ------------------------------------------------------------------ 2. the stratified draw
years = sorted(F.year.unique())
cnt_y = F.groupby("year").size().to_dict()
n_year = {y: min(FIXED[y], cnt_y.get(y, 0)) for y in FIXED}
rest = [y for y in years if y not in FIXED]
alloc = largest_remainder({y: cnt_y[y] for y in rest}, N_SAMPLE - sum(n_year.values()), {y: MIN_PER_YEAR for y in rest}, {y: cnt_y[y] for y in rest})
n_year.update(alloc)
n_h = {}
for y in years:
    c = F[F.year == y].groupby("size_class").size().to_dict()
    a = largest_remainder(c, n_year[y], {k: 1 for k in c}, c)
    n_h.update({(y, k): v for k, v in a.items()})
rng = np.random.default_rng(SEED)
F["stratum"] = F.year.astype(str) + " | " + F.size_class
F["stratum_N"] = F.groupby("stratum").id.transform("size")
F["stratum_n"] = [n_h[(y, s)] for y, s in zip(F.year, F.size_class)]
F["drawn"] = False; F["draw_order"] = 0
order = [n for n, _, _ in SIZES]
for y in years:
    for s in order:
        if (y, s) not in n_h:
            continue
        ids = sorted(F.id[(F.year == y) & (F.size_class == s)])
        pick = rng.choice(ids, size=n_h[(y, s)], replace=False)
        for i, p in enumerate(pick, start=1):
            F.loc[F.id == p, "drawn"] = True
            F.loc[F.id == p, "draw_order"] = i
F["weight"] = np.where(F.drawn, F.stratum_N / F.stratum_n, np.nan)
assert int(F.drawn.sum()) == N_SAMPLE, F.drawn.sum()

# ------------------------------------------------------------------ 3. governing case, both sets
zn = gpd.read_file(os.path.join(ROOT, "entitlement", "inputs", "town_zoning_2026-11-24.geojson")).to_crs(32617)
zn["geometry"] = shapely.make_valid(zn.geometry.values)
zn["case"] = zn.CASE_NUMBE.fillna("").str.strip().str.upper()


def governing(g):
    """The zoning district covering most of each clearing: its case number (blank if the district has none), name and share of the clearing."""
    z = gpd.overlay(g[["id", "geometry"]], zn[["case", "NAME", "DISTRICT", "geometry"]], how="intersection", keep_geom_type=True)
    z["a"] = z.area
    z = z.sort_values("a", ascending=False).drop_duplicates("id").set_index("id")
    return z


S = F[F.drawn | (F.size_class == SIZES[2][0])].copy()        # the sample, plus the undrawn clearings over 10 acres (optional set "large")
zs = governing(S)
S["governing_case"] = S.id.map(zs.case).fillna("").replace("", "no case")
S["case_name"] = S.id.map(zs.NAME).fillna("")
S["share_of_clearing_in_case"] = (S.id.map(zs.a).fillna(0) / S.area).round(2)
E = pd.read_csv(os.path.join(ROOT, "entitlement", "out", "clearings_entitlement.csv")).fillna("").set_index("id")
R = rel.copy()
R["year"] = R.first_quarter.str[:4].astype(int); R["size_class"] = R.acres.map(size_class)
R["governing_case"] = R.id.map(E.governing_case).replace("", "no case"); R["case_name"] = R.id.map(E.case_name)
R["share_of_clearing_in_case"] = R.id.map(E.share_of_clearing_in_case)


def items(g, set_name, extra):
    c = g.geometry.centroid.to_crs(4326)
    d = pd.DataFrame(dict(id=g.id, set=set_name, acres=g.acres.round(2), first_quarter=g.first_quarter, year=g.year, size_class=g.size_class, governing_case=g.governing_case, case_name=g.case_name,
                          share_of_clearing_in_case=g.share_of_clearing_in_case, conflict_flag=g.governing_case.map(COI).fillna(""), centroid_lat=c.y.round(6).values, centroid_lon=c.x.round(6).values,
                          image=[f"{set_name}/{i}.png" for i in g.id]))
    for k, v in extra.items():
        d[k] = v
    return d


IR = items(R, "release", dict(stratum="", stratum_N="", stratum_n="", weight=1.0, release_status=R.status.values, regrown_share="", overlaps_release_id=""))
parts = []
for nm, sel in (("sample", S.drawn), ("large", ~S.drawn)):
    Ss = S[sel].sort_values(["year", "size_class", "draw_order", "id"])
    d = items(Ss, nm, {})
    for k in ("stratum", "stratum_N", "stratum_n", "weight", "regrown_share", "overlaps_release_id"):
        d[k] = Ss[k].values
    d["release_status"] = ""
    parts.append(d)
IS, IL = parts
IL["weight"] = ""                                             # not part of the random draw
I = pd.concat([IR.sort_values("id"), IS, IL], ignore_index=True)
I.to_csv(os.path.join(OUT, "items.csv"), index=False)

G = pd.concat([R[["id", "acres", "first_quarter", "geometry"]].assign(set="release"), S[S.drawn][["id", "acres", "first_quarter", "geometry"]].assign(set="sample"),
               S[~S.drawn][["id", "acres", "first_quarter", "geometry"]].assign(set="large")], ignore_index=True)
fn = os.path.join(OUT, "outlines.geojson")
if os.path.exists(fn):
    os.remove(fn)
gpd.GeoDataFrame(G, crs=32617).to_crs(4326).to_file(fn, driver="GeoJSON")

F.drop(columns=["geometry", "eid", "row0", "col0"]).assign(centroid_lat=F.geometry.centroid.to_crs(4326).y.round(6), centroid_lon=F.geometry.centroid.to_crs(4326).x.round(6))[
    ["id", "acres", "npx", "first_quarter", "year", "size_class", "stratum", "stratum_N", "stratum_n", "drawn", "draw_order", "weight", "regrown_share", "overlaps_release_id", "share_inside_release_outlines",
     "centroid_lat", "centroid_lon"]].to_csv(os.path.join(OUT, "sample_frame.csv"), index=False)
fn = os.path.join(OUT, "sample_frame_outlines.geojson")
if os.path.exists(fn):
    os.remove(fn)
F[["id", "acres", "first_quarter", "stratum", "drawn", "geometry"]].to_crs(4326).to_file(fn, driver="GeoJSON")
tab = F.groupby(["year", "size_class"]).agg(clearings=("id", "size"), acres=("acres", "sum"), drawn=("drawn", "sum")).reset_index()
json.dump(dict(seed=SEED, generator="numpy.random.default_rng(seed); rng.choice(sorted ids of the stratum, n, replace=False), strata taken by year then size class (under 3, 3 to 10, over 10)",
               n_sample=N_SAMPLE, fixed_years=FIXED, min_per_other_year=MIN_PER_YEAR, size_classes=[s[0] for s in SIZES],
               frame=dict(source="apex-canopy/prerezoning_cache/detect_2017.npz (kept_event, first_event)", clearings=len(F), acres=round(float(F.acres.sum()), 1), connected_patches=int(npatch)),
               per_year={int(y): int(n) for y, n in n_year.items()}, allocation=[dict(year=int(r.year), size_class=r.size_class, clearings=int(r.clearings), acres=round(float(r.acres), 1), drawn=int(r.drawn)) for r in tab.itertuples()],
               versions=dict(python=sys.version.split()[0], numpy=np.__version__, scipy=scipy.__version__, pandas=pd.__version__, geopandas=gpd.__version__, shapely=shapely.__version__)),
          open(os.path.join(OUT, "sample_draw.json"), "w"), indent=1)

# ------------------------------------------------------------------ 4. the blank log
fn = os.path.join(OUT, "verify_log.csv")
ALL = I[["id", "set", "acres", "first_quarter"]].assign(reviewer="", verdict="", share_of_outline_cleared="", notes="")
LOG = ALL[ALL.set != "large"]
fl = os.path.join(OUT, "verify_log_large_optional.csv")
if not (os.path.exists(fl) and pd.read_csv(fl, dtype=str).fillna("")[["reviewer", "verdict", "share_of_outline_cleared", "notes"]].ne("").any().any()):
    ALL[ALL.set == "large"].to_csv(fl, index=False)
if os.path.exists(fn) and pd.read_csv(fn, dtype=str).fillna("")[["reviewer", "verdict", "share_of_outline_cleared", "notes"]].ne("").any().any():
    old = pd.read_csv(fn, dtype=str).fillna("")
    same = list(old.id + old.set) == list(LOG.id + LOG.set)
    print("verify_log.csv already has entries: left as it is." + ("" if same else "  WARNING: its rows no longer match items.csv."))
else:
    LOG.to_csv(fn, index=False)

pd.set_option("display.width", 200)
print(f"2017-2026 detection: {len(F)} clearings, {F.acres.sum():,.1f} ac, in {npatch} connected patches. Seed {SEED}.")
print(tab.pivot(index="year", columns="size_class", values="clearings").reindex(columns=[s[0] for s in SIZES]).fillna(0).astype(int).assign(total=lambda d: d.sum(axis=1)).to_string())
print("drawn:")
print(tab.pivot(index="year", columns="size_class", values="drawn").reindex(columns=[s[0] for s in SIZES]).fillna(0).astype(int).assign(total=lambda d: d.sum(axis=1)).to_string())
print(f"optional large set: {len(IL)} clearings over 10 ac not drawn, {IL.acres.sum():,.1f} ac")
print(f"items: {len(IR)} release + {len(IS)} sample = {len(IR) + len(IS)}; sample acres {IS.acres.sum():,.1f}; sample clearings that overlap a release clearing: {int((IS.overlaps_release_id != '').sum())}")
print("conflict-flagged items:", I[I.conflict_flag != ""][["id", "set", "governing_case"]].to_dict("records"))
