#!/usr/bin/env python3
"""projection.py: forest cleared, and a labelled PROJECTION of forest still to be cleared, inside conditional zoning cases approved
on or after 2019-12-03. Every figure this writes beyond "cleared so far" is an estimate resting on the stated assumption.

    ../apex-canopy/df-venv/bin/python projection.py

Ground is counted once. A cell covered by more than one of the cases starts its clock at the EARLIEST of their approval dates
(so clearing under a 2020 approval is not lost when the ground is re-approved in 2025) and takes its tree-save terms from the
LATEST one. 23CZ13 is left out. Uses the 2017-2026 detection (patches of an acre or more).

  cleared so far      2017 forest standing at that first approval and cleared since
  remaining           the rest of it
Two ways to turn "remaining" into an end number:
  A. experience       what share of the forest at approval older projects ended up clearing. Measured on conditional zoning cases
                      approved between 2017-10-01 and 2019-12-02 (seven to nine years ago, after the 2017 baseline) with 2 acres or
                      more of forest: share cleared by October 2026. Each case approved since is projected to end at that share, or
                      at what it has already cleared if that is more.
  B. the approvals    every acre of forest outside the required conservation area (RCA) is cleared. RCA acres = the case's stated
                      percent x its acres (stated acres for Veridea's flat 100 and the cases that differ by part; none for the exempt
                      ones; the average stated percent for cases whose documents give no figure). Given twice: with the RCA all
                      forest (the most the rule can save) and with it 53% forest (what the Town's mapped RCA averages).
Writes out/projection_cases.csv and out/projection.txt.
"""
import json, os, re
import numpy as np, pandas as pd, geopandas as gpd, shapely
from affine import Affine
from rasterio import features

HERE = os.path.dirname(os.path.abspath(__file__))
T = os.path.normpath(os.path.join(HERE, ".."))
AC = os.path.join(T, "apex-canopy"); OUT = os.path.join(HERE, "out")
OFFICE_START = pd.Timestamp("2019-12-03"); MATURE_FROM = pd.Timestamp("2017-10-01")
PX = 100 / 4046.8564
T10 = Affine(10, 0, 683800, 0, -10, 3961460); SHAPE = (1272, 1504)
RCA_TREE_SHARE = 0.53
VERIDEA = ["25CZ18", "25CZ15", "26CZ03", "26CZ10"]          # 24CZ23 (Greenway) left Veridea's SD district for LI-CZ, so the 100 acres is not its term
STATED_AC = {"24CZ19": 6.459, "22CZ23": 14.79, "21CZ31": 7.54}          # cases whose RCA differs by part of the site: the acres their plan states
OTHER_PCT = {"20CZ05": 27, "21CZ03": 2, "21CZ27": 10, "20CZ14": 34}      # the "other" group, from rca_percent_basis

D = np.load(os.path.join(AC, "prerezoning_cache", "detect_2017.npz")); J = json.load(open(os.path.join(AC, "prerezoning_cache", "detect_2017.json")))
QP = pd.PeriodIndex(J["det_quarters"], freq="Q"); Q_END = QP.end_time.normalize()
cand = D["cand"]; ev = np.where(D["kept_event"], D["first_event"], -1)
inb = np.load(os.path.join(AC, "s2", "cache", "baseline.npz"))["inb"]
a0 = lambda d: int(np.searchsorted(Q_END.values, np.datetime64(pd.Timestamp(d).normalize())))

O = pd.read_csv(os.path.join(T, "entitlement", "out", "office_period_cases.csv")).fillna("")
O = O[O.case != "23CZ13"].copy()
O["approved"] = pd.to_datetime(O.approved)
MASK = np.load(os.path.join(AC, "prerezoning_cache", "office_masks.npz"))
LOOK = {r["case"]: r for r in json.load(open(os.path.join(OUT, "lookup_rows.json")))}

# ---------------------------------------------------------------- each cell: its first approval and its governing (latest) case
start = np.full(SHAPE, 9999, np.int32); gov_date = np.zeros(SHAPE, "int64"); gov = np.full(SHAPE, -1, np.int32)
cases = list(O.sort_values("approved").case)
for i, c in enumerate(cases):
    m = MASK[c]; d = O.approved[O.case == c].iloc[0]
    start[m] = np.minimum(start[m], a0(d))
    later = m & (d.value >= gov_date)
    gov[later] = i; gov_date[later] = d.value
inside = gov >= 0
before = cand & inside & (ev >= 0) & (ev < start)
fa = cand & inside & ~before                         # forest standing at the first approval in the period
cl = fa & (ev >= start)                              # cleared since
rem = fa & ~cl

# ---------------------------------------------------------------- A. what older projects ended up clearing
ms = lambda s: pd.to_datetime(s, unit="ms", errors="coerce") if "datetime" not in str(s.dtype) else s.dt.tz_localize(None)
fix = lambda g: gpd.GeoSeries(shapely.make_valid(g.geometry.values), index=g.index, crs=g.crs)
rz = gpd.read_file(os.path.join(T, "entitlement", "inputs", "town_rezoning_2026-11-24.geojson")).to_crs(32617); rz["geometry"] = fix(rz)
rz["case"] = rz.Petition.str.strip().str.upper(); rz["action"] = ms(rz.Action_Date)
zn = gpd.read_file(os.path.join(T, "entitlement", "inputs", "town_zoning_2026-11-24.geojson")).to_crs(32617); zn["geometry"] = fix(zn)
zn["case"] = zn.CASE_NUMBE.fillna("").str.strip().str.upper(); zn["approved"] = ms(zn["DATE_"]); zn["ac"] = zn.area / 4046.8564
mature = []
for c in sorted(set(zn.case[zn.case.str.contains(r"^\d{2}CZ\d", regex=True)]) | set(rz.case[rz.case.str.contains(r"^\d{2}CZ\d", regex=True)])):
    r = rz[rz.case == c]; z = zn[zn.case == c].sort_values("ac", ascending=False)
    d = r.action.iloc[0] if len(r) and pd.notna(r.action.iloc[0]) and (r.Status.iloc[0] == "Approved" or len(z)) else (z.approved.iloc[0] if len(z) else pd.NaT)
    if pd.isna(d) or not (MATURE_FROM <= d < OFFICE_START):
        continue
    geom = r.geometry.iloc[0] if len(r) else z.geometry.union_all()
    m = features.rasterize([(geom, 1)], out_shape=SHAPE, transform=T10, fill=0, dtype="uint8").astype(bool) & inb
    q = a0(d); f = m & cand & ~((ev >= 0) & (ev < q)); c2 = f & (ev >= q)
    if f.sum() * PX >= 2:
        mature.append(dict(case=c, approved=d.date(), forest_at_approval=round(f.sum() * PX, 1), cleared=round(c2.sum() * PX, 1), share=round(c2.sum() / f.sum(), 3)))
MT = pd.DataFrame(mature)
f_pooled = MT.cleared.sum() / MT.forest_at_approval.sum(); f_median = MT.share.median()
started = MT[MT.cleared >= 1]
f_started = started.cleared.sum() / started.forest_at_approval.sum()

# ---------------------------------------------------------------- per governing case
rows = []
pct_known = []
for i, c in enumerate(cases):
    g = gov == i
    r = O[O.case == c].iloc[0]
    F, C, S = fa[g].sum() * PX, cl[g].sum() * PX, rem[g].sum() * PX
    share_gov = g.sum() / max(MASK[c].sum(), 1)                         # the part of this case's ground it still governs
    grp = r.rca_percent_group
    rca = None
    if c in VERIDEA: rca = None                                           # handled together below
    elif c in STATED_AC: rca = STATED_AC[c] * share_gov
    elif c in OTHER_PCT: rca = OTHER_PCT[c] / 100 * float(r.case_acres) * share_gov
    elif grp in ("5", "15", "20", "25", "30", "35", "40"): rca = int(grp) / 100 * float(r.case_acres) * share_gov; pct_known.append((int(grp), float(r.case_acres)))
    elif grp == "none/exempt": rca = 0.0
    elif grp == "mixed by district": rca = 0.30 * float(r.case_acres) * share_gov          # 24CZ10: 30% and 35% by part; the lower is used
    rows.append(dict(case=c, name=LOOK[c]["name"], approved=r.approved.date(), entitlement_type=r.entitlement_type, veridea=c in VERIDEA, governed_acres=round(g.sum() * PX, 1), forest_at_first_approval=round(F, 1),
                     cleared_so_far=round(C, 1), remaining=round(S, 1), rca_group=grp, rca_acres_assumed=rca))
P = pd.DataFrame(rows)
mean_pct = sum(p * a for p, a in pct_known) / sum(a for _, a in pct_known)
nofig = P.rca_acres_assumed.isna() & ~P.veridea
P.loc[nofig, "rca_acres_assumed"] = [mean_pct / 100 * float(O.case_acres[O.case == c].iloc[0]) * ((gov == cases.index(c)).sum() / max(MASK[c].sum(), 1)) for c in P.case[nofig]]
P["rca_basis"] = np.where(P.veridea, "Veridea: 100 acres for the whole development, shared across its rows", np.where(nofig, f"no figure in the documents: the average stated percent ({mean_pct:.0f}%) assumed", "stated"))
# Veridea: one 100-acre requirement against all its forest
V = P[P.veridea]; vF = V.forest_at_first_approval.sum(); vC = V.cleared_so_far.sum()


def final_A(f):
    nonv = P[~P.veridea]
    return float(np.maximum(nonv.cleared_so_far, f * nonv.forest_at_first_approval).sum()), float(max(vC, f * vF))


def final_B(k):
    nonv = P[~P.veridea]
    kept = np.minimum(nonv.forest_at_first_approval, k * nonv.rca_acres_assumed.astype(float))
    return float(np.maximum(nonv.cleared_so_far, nonv.forest_at_first_approval - kept).sum()), float(max(vC, vF - min(vF, k * 100)))


P["final_A_pooled"] = np.maximum(P.cleared_so_far, f_pooled * P.forest_at_first_approval).round(1)
P["final_B_rca_all_forest"] = np.where(P.veridea, np.nan, np.maximum(P.cleared_so_far, P.forest_at_first_approval - np.minimum(P.forest_at_first_approval, P.rca_acres_assumed.astype(float)))).round(1)
P.sort_values("forest_at_first_approval", ascending=False).to_csv(os.path.join(OUT, "projection_cases.csv"), index=False)

F_all, C_all, S_all = fa.sum() * PX, cl.sum() * PX, rem.sum() * PX
nv = P[~P.veridea]
S = []
say = S.append
say("PROJECTION: forest cleared and still to be cleared inside conditional zoning cases approved on or after 2019-12-03")
say("Everything below the first block is an estimate. 23CZ13 is left out. Ground counted once; 2017-2026 detection, patches of an acre or more.")
say(f"\nMEASURED ({len(cases)} cases, {inside.sum() * PX:,.0f} acres of ground):")
say(f"  forest standing at the first approval in the period: {F_all:,.0f} ac")
say(f"  cleared since: {C_all:,.0f} ac        remaining: {S_all:,.0f} ac")
say(f"  of which Veridea's four cases: forest {vF:,.0f}, cleared {vC:,.0f}, remaining {vF - vC:,.0f}; everything else: forest {nv.forest_at_first_approval.sum():,.0f}, cleared {nv.cleared_so_far.sum():,.0f}, remaining {nv.remaining.sum():,.0f}")
say(f"\nA. EXPERIENCE. {len(MT)} conditional zoning cases approved {MATURE_FROM.date()} to 2019-12-02 with 2 ac or more of forest at approval:")
say(f"   forest at approval {MT.forest_at_approval.sum():,.0f} ac, cleared by October 2026 {MT.cleared.sum():,.0f} ac. Share cleared: {f_pooled:.0%} of all their acres; {f_median:.0%} for the median case; {f_started:.0%} among the {len(started)} that cleared an acre or more.")
for lab, f in (("all acres pooled", f_pooled), ("median case", f_median), ("cases that started", f_started)):
    a, v = final_A(f)
    say(f"   at {f:.0%} ({lab}): cleared or to be cleared {a + v:,.0f} ac  (other cases {a:,.0f} + Veridea {v:,.0f}); that is {a + v - C_all:,.0f} more than so far")
say(f"\nB. THE APPROVALS. Every acre of forest outside the required conservation area is cleared. Stated RCA for {int((P.rca_basis == 'stated').sum())} cases; average stated percent ({mean_pct:.0f}%) assumed for {int(nofig.sum())} with no figure; Veridea 100 acres in all.")
for lab, k in (("RCA entirely forest (the most the rule can save)", 1.0), (f"RCA {RCA_TREE_SHARE:.0%} forest (the mapped average)", RCA_TREE_SHARE)):
    a, v = final_B(k)
    say(f"   {lab}: cleared or to be cleared {a + v:,.0f} ac  (other cases {a:,.0f} + Veridea {v:,.0f}); {a + v - C_all:,.0f} more than so far")
say(f"\nCEILING: if all remaining forest inside these cases went, {F_all:,.0f} ac.")
say("\nRead with care. A is what happened elsewhere, applied here; projects differ, and Veridea is not a subdivision. B assumes nothing outside the RCA survives and that the RCA is where the trees are; neither is required.")
say("An approval date and a clearing date show order, not cause. The case list includes amendments to projects first approved before the period (Veridea above all).")
say("\nThe older cases behind A:")
say(MT.sort_values("forest_at_approval", ascending=False).to_string(index=False))
aA = [sum(final_A(f)) for f in (f_pooled, f_median)]; aB = [sum(final_B(k)) for k in (1.0, RCA_TREE_SHARE)]
json.dump(dict(cases=len(cases), forest_at_first_approval=F_all, cleared=C_all, remaining=S_all, veridea_forest=vF, veridea_cleared=vC, veridea_remaining=vF - vC,
               mature_cases=len(MT), mature_forest=float(MT.forest_at_approval.sum()), mature_cleared=float(MT.cleared.sum()), share_pooled=f_pooled, share_median=float(f_median),
               A_low=min(aA), A_high=max(aA), B_low=min(aB), B_high=max(aB), mean_stated_pct=mean_pct, no_figure_cases=int(nofig.sum()), stated_cases=int((P.rca_basis == "stated").sum()),
               nonveridea_A_low=min(final_A(f_pooled)[0], final_A(f_median)[0]), nonveridea_A_high=max(final_A(f_pooled)[0], final_A(f_median)[0]), nonveridea_B_low=final_B(1.0)[0], nonveridea_B_high=final_B(RCA_TREE_SHARE)[0]),
          open(os.path.join(OUT, "projection.json"), "w"), indent=1)
open(os.path.join(OUT, "projection.txt"), "w").write("\n".join(S) + "\n")
print("\n".join(S))
