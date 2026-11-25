#!/usr/bin/env python
"""detect_2017.py: the release's clearing detection, run from a 2017 baseline instead of a 2022 one.

    ../apex-canopy/df-venv/bin/python detect_2017.py

Same per-quarter test and thresholds as the release's 04_detect.py (T_NDVI 0.50, T_NBR 0.65, at least 2 clear
observations, NBR used in leaf-on quarters only, each threshold capped at the stable-forest 1st percentile).
What has to differ, and why:

  Baseline     May-Sep 2017 pooled ("2017MS") instead of 2022Q3. In 2017 one orbit covers Apex and Sentinel-2B only
               started in July, so the Jul-Sep quarter alone leaves 41% of the area with fewer than two clear looks.
               The pooled season covers 97% with one clear look and 88% with two; one look is accepted for the
               baseline only (a bad single look makes a cell look less like forest, so it can drop forest, not invent it).
               A cell is 2017 forest if it is forest-like in that composite AND tree canopy is confirmed by NAIP: at
               least half canopy in NAIP 2016, or forest in the release's 2022 mask (a cell that is forest in 2022 and
               forest-like in 2017 was forest in 2017).
  References   The stable-forest and bare cells must hold for the whole period, so the release's sets are narrowed:
               stable forest also has NBR > 0.6 in 2017MS, 2019Q3 and 2021Q3; bare also has NDVI < 0.25 in 2017MS.
  Two rules    STRICT is the release's rule: cleared-like in quarter Q and in every later valid leaf-on composite.
               Over nine years that drops land that was logged and then greened up before it was built on, which is
               the pattern this analysis looks for. EVENT is added for that: cleared-like in Q and in the next two
               valid leaf-on composites (about a year), whatever happens later. The event rule is new and is
               Claude's; both are written out.

Writes ../apex-canopy/prerezoning_cache/detect_2017.npz and detect_2017.json.
"""
import glob, json, os, sys
import numpy as np
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
AC = os.path.join(HERE, "..", "apex-canopy")
CACHE = os.path.join(AC, "prerezoning_cache")
sys.path.insert(0, os.path.join(AC, "release-v1", "code"))
os.environ.setdefault("APEX_WORK", CACHE); os.environ.setdefault("APEX_OUT", CACHE)
import config as C  # noqa: E402

BASE_Q = "2017MS"
BASE_MIN_OBS = 1
EVENT_CONFIRM = 2              # later valid leaf-on composites that must also be cleared-like
PX_AC = 100 / C.M2_PER_AC

b = np.load(os.path.join(AC, "s2", "cache", "baseline.npz"))
frac22, forest22, inb = b["frac"], b["forest"], b["inb"]
rel = np.load(os.path.join(AC, "s2", "cache", "detect.npz"))
naip16 = np.load(os.path.join(CACHE, "naip", "canopy_2016.npz"))["frac"]

files = {os.path.basename(f)[10:16]: f for d in (os.path.join(CACHE, "s2"), os.path.join(AC, "s2", "cache")) for f in sorted(glob.glob(os.path.join(d, "composite_*.npz")))}
Q = sorted(q for q in files if q >= "2017Q4" or q == BASE_Q)             # the 2017Q1-Q3 quarterly composites are not used
Cq = {}
for q in Q:
    z = np.load(files[q])
    if "ndvi" in z:
        Cq[q] = {k: z[k] for k in ("ndvi", "nbr", "count")} | {"n_scenes_total": int(z["n_scenes_total"]), "n_scenes_used": int(z["n_scenes_used"])}
Q = sorted(Cq)
Q = [BASE_Q] + [q for q in Q if q != BASE_Q]
assert BASE_Q in Cq and Q[-1] >= "2026Q3", Q

stable = rel["stable"].copy()
for q in (BASE_Q, "2019Q3", "2021Q3"):
    stable &= Cq[q]["nbr"] > 0.6
bare = rel["bare"] & (Cq[BASE_Q]["ndvi"] < 0.25)

cal, state = {}, {}        # state: 1 cleared-like, 0 forest-like, -1 no valid observation
for q in Q:
    z = Cq[q]
    ok = z["count"] >= (BASE_MIN_OBS if q == BASE_Q else C.MIN_OBS)
    rec = {"n_scenes": z["n_scenes_total"], "n_used": z["n_scenes_used"]}
    s = {}
    for k, Tn in (("ndvi", C.T_NDVI), ("nbr", C.T_NBR)):
        fm = float(np.nanmedian(z[k][stable & ok])); bm = float(np.nanmedian(z[k][bare & ok]))
        s[k] = (z[k] - bm) / (fm - bm)
        p1 = float(np.nanpercentile(s[k][stable & ok], 1))
        rec[k] = dict(forest_med=round(fm, 4), bare_med=round(bm, 4), stable_p1_s=round(p1, 3), T_s=round(min(Tn, p1), 3))
    leafon = (q[-1] in "23" or q == BASE_Q) and rec["nbr"]["stable_p1_s"] >= C.LEAFON_NBR_P1
    rec["leaf_on"] = bool(leafon)
    clr = s["ndvi"] < rec["ndvi"]["T_s"]
    if leafon:
        clr |= s["nbr"] < rec["nbr"]["T_s"]
    st = np.where(clr, 1, 0).astype(np.int8)
    st[~ok | ~np.isfinite(s["ndvi"]) | (leafon & ~np.isfinite(s["nbr"]))] = -1
    state[q] = st
    rec["clear_coverage_pct"] = round(100 * float((ok & inb).sum()) / inb.sum(), 1)
    rec["median_clear_obs"] = float(np.median(z["count"][inb]))
    rec["stable_fp_pct"] = round(100 * float(((st == 1) & stable).sum()) / max(1, ((st >= 0) & stable).sum()), 2)
    cal[q] = rec

base = state[BASE_Q]
tree = (np.nan_to_num(naip16, nan=-1) >= 0.5) | forest22
cand = inb & (base == 0) & tree
det_q = [q for q in Q if q != BASE_Q]
n = len(det_q)
shape = base.shape

# strict: the release's rule
first_strict = np.full(shape, -1, np.int16); later_ok = np.ones(shape, bool)
# event: cleared-like in Q and in the next EVENT_CONFIRM valid leaf-on composites
first_event = np.full(shape, -1, np.int16); confirmed = np.zeros(shape, bool)
nxt = [np.full(shape, -1, np.int8) for _ in range(EVENT_CONFIRM)]      # states of the next valid leaf-on composites, nearest first (-1 = none yet)
regrew = np.zeros(shape, bool)                                         # forest-like in some later valid leaf-on composite
later_forest = np.zeros(shape, bool)
for i in range(n - 1, -1, -1):
    q = det_q[i]; st = state[q]
    hit = cand & (st == 1) & later_ok
    first_strict[hit] = i
    ev = cand & (st == 1) & np.all([x != 0 for x in nxt], axis=0)
    first_event[ev] = i
    confirmed[ev] = np.all([x == 1 for x in nxt], axis=0)[ev]
    regrew[ev] = later_forest[ev]
    if cal[q]["leaf_on"]:
        later_ok &= (st != 0)
        v = st >= 0
        for k in range(EVENT_CONFIRM - 1, 0, -1):
            nxt[k][v] = nxt[k - 1][v]
        nxt[0][v] = st[v]
        later_forest |= (st == 0)


def patches(mask, min_px=C.MIN_PX):
    lab, m = ndimage.label(mask, structure=np.ones((3, 3), int))
    sizes = ndimage.sum(np.ones_like(lab), lab, index=np.arange(1, m + 1))
    return np.isin(lab, np.where(sizes >= min_px)[0] + 1)


kept_event, kept_strict = patches(first_event >= 0), patches(first_strict >= 0)
out = dict(quarters=Q, det_quarters=det_q, base_quarter=BASE_Q, calibration=cal, stable_px=int(stable.sum()), bare_px=int(bare.sum()),
           forest_2017_ac=float(cand.sum() * PX_AC), forestlike_2017_no_naip_tree_ac=float((inb & (base == 0) & ~tree).sum() * PX_AC),
           naip16_forest_ac=float((inb & (np.nan_to_num(naip16, nan=-1) >= 0.5)).sum() * PX_AC),
           event_ac=float(kept_event.sum() * PX_AC), strict_ac=float(kept_strict.sum() * PX_AC),
           event_px_any_size_ac=float((first_event >= 0).sum() * PX_AC), strict_px_any_size_ac=float((first_strict >= 0).sum() * PX_AC),
           stable_event_fp_pct=round(100 * float(((first_event >= 0) & stable).sum()) / stable.sum(), 3))
# check against the release where the two overlap: its outlines, and this run's clearings from 2022Q4 on
i22 = det_q.index("2022Q4")
relk = rel["kept"]
out["check_vs_release"] = dict(release_ac=float(relk.sum() * PX_AC), release_cells_that_were_2017_forest_ac=float((relk & cand).sum() * PX_AC),
                               release_cells_strict_here_ac=float((relk & kept_strict).sum() * PX_AC), release_cells_event_here_ac=float((relk & kept_event).sum() * PX_AC),
                               strict_2022Q4_on_ac=float((kept_strict & (first_strict >= i22)).sum() * PX_AC), strict_2022Q4_on_outside_release_ac=float((kept_strict & (first_strict >= i22) & ~relk).sum() * PX_AC))
by = {}
for i, q in enumerate(det_q):
    by[q] = dict(event_ac=round(float((kept_event & (first_event == i)).sum() * PX_AC), 1), strict_ac=round(float((kept_strict & (first_strict == i)).sum() * PX_AC), 1))
out["acres_by_first_quarter"] = by
json.dump(out, open(os.path.join(CACHE, "detect_2017.json"), "w"), indent=1)
np.savez_compressed(os.path.join(CACHE, "detect_2017.npz"), cand=cand, first_event=first_event, first_strict=first_strict, confirmed=confirmed, regrew=regrew,
                    kept_event=kept_event, kept_strict=kept_strict, stable=stable, bare=bare, state_base=base, state_now=state["2026Q3"],
                    **{f"state_{q}": state[q] for q in ("2018Q3", "2020Q3", "2022Q3")})

out["baseline_coverage_pct"] = {f"at least {k} clear look(s)": round(100 * float((Cq[BASE_Q]["count"][inb] >= k).mean()), 1) for k in (1, 2)}
json.dump(out, open(os.path.join(CACHE, "detect_2017.json"), "w"), indent=1)
print("baseline coverage:", out["baseline_coverage_pct"], "; baseline leaf-on:", cal[BASE_Q]["leaf_on"])
print(f"2017 forest {out['forest_2017_ac']:,.0f} ac (forest-like in {BASE_Q} but no NAIP tree canopy: {out['forestlike_2017_no_naip_tree_ac']:,.0f} ac left out); stable {stable.sum()} px, bare {bare.sum()} px")
print(f"clearings in patches of an acre or more: event rule {out['event_ac']:,.0f} ac, strict rule {out['strict_ac']:,.0f} ac; stable-forest cells with an event: {out['stable_event_fp_pct']}%")
print("check vs release:", json.dumps({k: round(v, 1) for k, v in out["check_vs_release"].items()}))
print("quarter  leaf  used/total  cov%  NDVI f/b      T     NBR f/b       T    stableFP%   event_ac strict_ac")
for q in Q:
    r = cal[q]; a = by.get(q, {})
    print(f"{q}  {'on ' if r['leaf_on'] else 'off'}  {r['n_used']:3d}/{r['n_scenes']:<3d}  {r['clear_coverage_pct']:5.1f}  {r['ndvi']['forest_med']:.3f}/{r['ndvi']['bare_med']:.3f}  {r['ndvi']['T_s']:.2f}  "
          f"{r['nbr']['forest_med']:.3f}/{r['nbr']['bare_med']:.3f}  {r['nbr']['T_s']:.2f}  {r['stable_fp_pct']:6.2f}   {a.get('event_ac', ''):>8} {a.get('strict_ac', ''):>8}")
