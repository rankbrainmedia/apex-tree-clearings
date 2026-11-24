#!/usr/bin/env python
"""Step 4: detect NEW persistent forest clearings (>= 1 ac) in Apex from S2 quarterly composites.

Inputs: WORK/baseline.npz (02_baseline.py), WORK/composite_<Q>.npz (03_composites.py).

Seasonal normalisation (per quarter Q, per index k in {NDVI, NBR}):
    s_k,Q = (x - bare_med_Q) / (stableforest_med_Q - bare_med_Q)
  1 = typical stable forest that quarter, 0 = typical bare/impervious that quarter.
  stable-forest reference = NAIP-2022 interior forest (canopy >= 90%, eroded 20 m) that is
      still dense (NBR > 0.6) in the 2022Q3 baseline and in the last two Q3 composites, and
      NDVI > 0.6 in the final composite (forest at both ends of the period).
  bare reference = NAIP-2022 zero-canopy cells with 2022Q3 NDVI < 0.25 (roofs, pavement, soil).
Per-quarter "cleared-like" state:
    NDVI:  s_ndvi < T_ndvi_Q,  T_ndvi_Q = min(T_NDVI, stable-forest 1st percentile of s_ndvi in Q)
    NBR (leaf-on quarters only): s_nbr < T_nbr_Q, same rule with T_NBR.
    leaf-on cleared-like = NDVI-test OR NBR-test; leaf-off/transition = NDVI-test only.
  (NBR keeps graded-then-sodded lawns from looking like 'recovered' forest in summer; it is
   useless in leaf-off, where deciduous forest NBR collapses, so it is not used then.)
  A composite pixel is valid if it has >= MIN_OBS clear observations.
Candidates: NAIP forest (>= 50 % canopy at 10 m) inside the boundary AND forest-like in the
  2022Q3 baseline composite by the same test (otherwise 'baseline-ambiguous', excluded).
Persistent clearing: first quarter Q (2022Q4 onward) such that the pixel is cleared-like in Q
  AND cleared-like in every later valid LEAF-ON composite (Q2/Q3; plus 2026Q4 if it passes the
  leaf-on test). Leaf-off/transition quarters (Q1, Q4) may be the first quarter but are not
  used to test persistence (winter lawns/deciduous forest are not separable).
  'confirmed' = the drop is seen again in at least one later valid composite (any season);
  otherwise the pixel is provisional (only the latest quarters can be in this state).
Patches: 8-connected cleared pixels; keep patches >= 1 acre (>= 4046.86 m2, i.e. >= 41 px).
  The patch-level first_quarter printed here is a summary only; per-event quarters are
  assigned in 05_events.py.
"""
import glob, os, sys, json, argparse, warnings
import numpy as np
from scipy import ndimage
warnings.simplefilter("ignore")
import config as Cfg
X0, Y1 = Cfg.X0, Cfg.Y1
M2_PER_AC = Cfg.M2_PER_AC
MIN_PX = Cfg.MIN_PX  # 41 px = 1 acre

ap = argparse.ArgumentParser()
ap.add_argument("--t-ndvi", type=float, default=Cfg.T_NDVI)
ap.add_argument("--t-nbr", type=float, default=Cfg.T_NBR)
ap.add_argument("--min-obs", type=int, default=Cfg.MIN_OBS)
ap.add_argument("--tag", default="")
ap.add_argument("--write", action="store_true")
ap.add_argument("--alt-baseline", action="store_true",
                help="sensitivity only: also allow cells the NAIP mask calls non-forest (<50%% canopy) "
                     "if S2 2022Q3 is clearly forest (NDVI-s and NBR-s >= 0.8)")
args = ap.parse_args()
os.makedirs(Cfg.WORK, exist_ok=True)

b = np.load(f"{Cfg.WORK}/baseline.npz")
frac, forest_naip, inb = b["frac"], b["forest"], b["inb"]
C = {}
for f in sorted(glob.glob(f"{Cfg.WORK}/composite_*.npz")):
    z = dict(np.load(f))
    if "ndvi" in z:
        C[f.split("_")[-1][:6]] = z
Q = sorted(C)
assert Q[0] == "2022Q3"
last_q3 = [q for q in Q if q.endswith("Q3")][-2:]

interior = ndimage.binary_erosion(forest_naip & (frac >= 0.9), iterations=2)
stable = interior & (C["2022Q3"]["nbr"] > 0.6)
for q in last_q3:
    stable &= C[q]["nbr"] > 0.6
stable &= C[Q[-1]]["ndvi"] > 0.6   # still vegetated in the final (partial) composite = forest at the end
nf0 = inb & (np.nan_to_num(frac) == 0)
bare = nf0 & (C["2022Q3"]["ndvi"] < 0.25)

cal = {}
state = {}   # 1 cleared-like, 0 forest-like, -1 invalid
for q in Q:
    z = C[q]
    ok = z["count"] >= args.min_obs
    rec = {"n_scenes": int(z["n_scenes_total"]), "n_used": int(z["n_scenes_used"])}
    s = {}
    for k, Tn in (("ndvi", args.t_ndvi), ("nbr", args.t_nbr)):
        fm = float(np.nanmedian(z[k][stable & ok])); bm = float(np.nanmedian(z[k][bare & ok]))
        s[k] = (z[k] - bm) / (fm - bm)
        p1 = float(np.nanpercentile(s[k][stable & ok], 1))
        rec[k] = dict(forest_med=round(fm, 4), bare_med=round(bm, 4), stable_p1_s=round(p1, 3),
                      T_s=round(min(Tn, p1), 3), T_raw=round(bm + min(Tn, p1) * (fm - bm), 4))
    # leaf-on = Apr-Sep quarter AND stable-forest NBR lower tail stays high (p1 >= 0.75 in s units).
    # Q4 (Oct-Dec, incl. the partial Oct-2026 quarter) is always treated as transition/leaf-off.
    leafon = q[-1] in "23" and rec["nbr"]["stable_p1_s"] >= Cfg.LEAFON_NBR_P1
    rec["leaf_on"] = bool(leafon)
    cl = s["ndvi"] < rec["ndvi"]["T_s"]
    if leafon:
        cl |= s["nbr"] < rec["nbr"]["T_s"]
    st = np.where(cl, 1, 0).astype(np.int8)
    st[~ok | ~np.isfinite(s["ndvi"]) | (leafon & ~np.isfinite(s["nbr"]))] = -1
    state[q] = st
    rec["clear_coverage_pct"] = round(100 * float((ok & inb).sum()) / inb.sum(), 1)
    rec["forest_valid_pct"] = round(100 * float((ok & forest_naip).sum()) / forest_naip.sum(), 1)
    rec["median_clear_obs"] = float(np.median(z["count"][inb]))
    rec["stable_fp_pct"] = round(100 * float(((st == 1) & stable).sum()) / max(1, ((st >= 0) & stable).sum()), 2)
    cal[q] = rec

base = state["2022Q3"]
cand = forest_naip & (base == 0)
ambig = forest_naip & (base != 0)
if args.alt_baseline:
    z = C["2022Q3"]; c = cal["2022Q3"]
    sn = (z["ndvi"] - c["ndvi"]["bare_med"]) / (c["ndvi"]["forest_med"] - c["ndvi"]["bare_med"])
    sb = (z["nbr"] - c["nbr"]["bare_med"]) / (c["nbr"]["forest_med"] - c["nbr"]["bare_med"])
    extra = inb & ~forest_naip & (base == 0) & (sn >= 0.8) & (sb >= 0.8)
    print(f"alt-baseline: adding {extra.sum()*100/M2_PER_AC:.0f} ac of S2-forest cells the NAIP mask calls non-forest")
    cand = cand | extra
det_q = Q[1:]
first = np.full(frac.shape, -1, np.int16)    # index into det_q
confirmed = np.zeros(frac.shape, bool)
# iterate from latest to earliest: track "all later valid leaf-on composites cleared-like"
later_ok = np.ones(frac.shape, bool)      # vacuous truth
later_has = np.zeros(frac.shape, bool)    # drop re-observed in any later valid composite
for i in range(len(det_q) - 1, -1, -1):
    q = det_q[i]; st = state[q]
    hit = cand & (st == 1) & later_ok
    first[hit] = i                          # overwritten by earlier quarters that also qualify
    confirmed[hit] = later_has[hit]
    later_has |= (st == 1)
    if cal[q]["leaf_on"]:
        later_ok &= (st != 0)               # a valid forest-like leaf-on composite breaks it
cleared = first >= 0

lab, n = ndimage.label(cleared, structure=np.ones((3, 3), int))
sizes = ndimage.sum(np.ones_like(lab), lab, index=np.arange(1, n + 1))
keep_ids = np.where(sizes >= MIN_PX)[0] + 1
patches = []
for pid in keep_ids:
    m = lab == pid
    fq = np.sort(first[m])
    q50 = fq[(len(fq) - 1) // 2]
    patches.append(dict(pid=int(pid), npx=int(m.sum()), acres=m.sum() * 100 / M2_PER_AC,
                        first_quarter=det_q[q50], confirmed_frac=float(confirmed[m].mean()),
                        q_counts={det_q[k]: int((fq == k).sum()) for k in np.unique(fq)}))
kept = np.isin(lab, keep_ids)
tot = sum(p["acres"] for p in patches)
print(f"T_ndvi={args.t_ndvi} T_nbr={args.t_nbr} min_obs={args.min_obs}: candidates {cand.sum()*100/M2_PER_AC:.0f} ac, "
      f"baseline-ambiguous {ambig.sum()*100/M2_PER_AC:.0f} ac, cleared px {cleared.sum()*100/M2_PER_AC:.0f} ac, "
      f"patches>=1ac {len(patches)} = {tot:.1f} ac")
for q in det_q:
    ps = [p for p in patches if p["first_quarter"] == q]
    print(f"  {q} {'ON ' if cal[q]['leaf_on'] else 'off'} n={len(ps):3d} ac={sum(p['acres'] for p in ps):7.1f}  "
          f"pix-timing ac={((first==det_q.index(q))&kept).sum()*100/M2_PER_AC:7.1f}  cov={cal[q]['clear_coverage_pct']}% "
          f"T_ndvi_s={cal[q]['ndvi']['T_s']} T_nbr_s={cal[q]['nbr']['T_s']} stableFP={cal[q]['stable_fp_pct']}%")

if args.write:
    np.savez_compressed(f"{Cfg.WORK}/detect{args.tag}.npz", first=first, confirmed=confirmed, lab=lab,
                        kept=kept, cand=cand, ambig=ambig, stable=stable, bare=bare,
                        **{f"state_{q}": state[q] for q in Q})
    json.dump(dict(args=vars(args), quarters=Q, det_quarters=det_q, calibration=cal, patches=patches,
                   stable_px=int(stable.sum()), bare_px=int(bare.sum()),
                   cand_ac=float(cand.sum() * 100 / M2_PER_AC), ambig_ac=float(ambig.sum() * 100 / M2_PER_AC)),
              open(f"{Cfg.WORK}/detect{args.tag}.json", "w"), indent=1)
