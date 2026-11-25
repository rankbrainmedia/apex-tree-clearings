#!/usr/bin/env python
"""lag_buildout.py: how long after approval clearing starts, and how fast the forest goes.

    ../apex-canopy/df-venv/bin/python lag_buildout.py

Uses the 2017-2026 detection (../prerezoning/detect_2017.py), not the 2022 release. For every conditional zoning case
approved on or after OFFICE_START with 2 acres or more of forest at approval:
  forest at approval   2017 forest cells not first-detected as cleared in a quarter that ended before the approval date
  lag                  months from the approval date to the middle of the first quarter in which clearing since approval
                       reaches an acre (quarters are three months long, so the lag is good to about +/- 1.5 months)
  build-out            share of forest at approval cleared by 1, 2, ... 6 years after approval, for cases old enough
Cases are split three ways, from the zoning map's history of the ground the case mostly sits on:
  first approval       no earlier conditional case on the ground. These make the lag and the curve.
  amendment            an earlier conditional case is on the ground, or the name says amendment, expansion or text. Measured on
                       the parent project's boundary from the original approval date, one row per parent, reported separately.
  excluded             a manually corrected date, or an original whose date is in neither layer (case-number year only).
23CZ13 is computed and flagged, and left out of every total, median and list.
Writes out/lag_cases.csv, out/lag_amendments.csv, out/lag_buildout_curve.csv, out/lag_summary.txt.
"""
import glob, json, os, re
import numpy as np, pandas as pd, geopandas as gpd, shapely
from affine import Affine
from rasterio import features

HERE = os.path.dirname(os.path.abspath(__file__))
AC = os.path.join(HERE, "..", "apex-canopy"); OUT = os.path.join(HERE, "out"); PRE = os.path.join(AC, "prerezoning_cache")
OFFICE_START = pd.Timestamp("2019-12-03")
DATA_END = pd.Timestamp("2026-10-24")          # last image in the detection
MARK_END = pd.Timestamp("2026-09-30")          # end of the last complete quarter: a year mark must fall on or before this
PUBLIC_SHARE = 0.5                             # as in entitlement.py
BASELINE_END = pd.Timestamp("2017-09-30")      # the 2017 forest baseline is May-September 2017
MIN_FOREST_AC = 2.0
YEARS = [1, 2, 3, 4, 5, 6]
M2_AC = 4046.8564
X0, Y1, W, H = 683800, 3961460, 1504, 1272
T10 = Affine(10, 0, X0, 0, -10, Y1); SHAPE = (H, W); PX = 100 / M2_AC; ACRE_PX = 41
MANUAL = {"22CZ21": "2023-03-28", "26CZ05": "2026-08-25", "25CZ13": "2026-01-12"}
MANUAL_STATUS = {"26CZ05": "Approved", "25CZ13": "Approved"}
OUT_OF_TOTALS = {"23CZ13"}
COI = {"23CZ13": "Seymour Mixed Use PUD is next to the author's home: left out of totals", "24CZ20": "held: its PUD text names the Seymour PUD as adjacent",
       "24CZ19": "disclosed (Barnett Properties, LLC)", "24CZ08": "disclosed (lists the Seymour PUD as adjacent)"}
AMEND = re.compile(r"amend|expan|text", re.I)

ms = lambda s: pd.to_datetime(s, unit="ms", errors="coerce") if "datetime" not in str(s.dtype) else s.dt.tz_localize(None)
fix = lambda g: gpd.GeoSeries(shapely.make_valid(g.geometry.values), index=g.index, crs=g.crs)


def parse_case(c):
    m = re.match(r"^0?(\d{2})([A-Z]{2,3})\d", str(c).strip().upper())
    if not m:
        return None, None
    y = int(m.group(1))
    return (2000 + y if y <= 30 else 1900 + y), m.group(2)


rz = gpd.read_file(os.path.join(HERE, "inputs", "town_rezoning_2026-11-24.geojson")).to_crs(32617); rz["geometry"] = fix(rz)
rz["case"] = rz.Petition.str.strip().str.upper(); rz["action"] = ms(rz.Action_Date); rz = rz.set_index("case", drop=False)
zn = gpd.read_file(os.path.join(HERE, "inputs", "town_zoning_2026-11-24.geojson")).to_crs(32617); zn["geometry"] = fix(zn)
zn["case"] = zn.CASE_NUMBE.fillna("").str.strip().str.upper(); zn["approved"] = ms(zn["DATE_"]); zn["ac"] = zn.area / M2_AC
BACK = sorted([c for c in zn.columns if c.startswith("BACK")], key=lambda c: int(c[4:]))
zn["chain"] = zn[BACK].fillna("").apply(lambda r: [x.strip().upper() for x in r if x and x.strip()], axis=1)
HIST = pd.read_csv(os.path.join(OUT, "case_ground_history.csv")).fillna("")
PIPE = pd.read_csv(os.path.join(OUT, "pipeline_2022plus.csv")).fillna("").set_index("case")
PARENTS = pd.read_csv(os.path.join(OUT, "parent_projects.csv")).fillna("")
PNAME = {r.original_case: r.parent_project for r in PARENTS.itertuples()}

J = json.load(open(os.path.join(PRE, "detect_2017.json")))
D = np.load(os.path.join(PRE, "detect_2017.npz"))
DET_Q = J["det_quarters"]
QP = pd.PeriodIndex(DET_Q, freq="Q")
Q_START, Q_END = QP.start_time.normalize(), QP.end_time.normalize()
Q_SEEN = pd.DatetimeIndex([min(e, DATA_END) for e in Q_END])            # the last quarter stops at the last image
Q_MID = Q_START + (Q_SEEN - Q_START) / 2
cand, first_event, kept_event = D["cand"], D["first_event"], D["kept_event"]
now_forest = D["state_now"] == 0
inb = np.load(os.path.join(AC, "s2", "cache", "baseline.npz"))["inb"]
event_q = np.where(kept_event, first_event, -1)                    # quarter index of the first clearing, in patches of an acre or more
pp = gpd.read_file(sorted(glob.glob(os.path.join(HERE, "inputs", "public_parcels_*.geojson")))[-1]).to_crs(32617)
PUBMASK = features.rasterize([(g, 1) for g in shapely.make_valid(pp.geometry.values)], out_shape=SHAPE, transform=T10, fill=0, dtype="uint8").astype(bool)


def public(mask):
    sh = (mask & PUBMASK).sum() / mask.sum() if mask.sum() else 0.0
    return dict(public_owner_case=bool(sh >= PUBLIC_SHARE), public_share=round(float(sh), 2))


def eff_date(case):
    """The date used: Adam's manual date where he gave one, else the layers'."""
    return pd.Timestamp(MANUAL[case]) if case in MANUAL else layer_date(case)[0]


def layer_date(case):
    """(date, basis) from the layers only: Rezoning layer action date, else the largest zoning-map district's date."""
    r = rz.loc[case] if case in rz.index else None
    z = zn[zn.case == case].sort_values("ac", ascending=False)
    if r is not None and pd.notna(r.action) and (r.Status == "Approved" or len(z) or case in MANUAL_STATUS):
        return r.action, "Rezoning layer action date"
    if len(z) and pd.notna(z.approved.iloc[0]):
        return z.approved.iloc[0], "zoning map date"
    return pd.NaT, "not in either layer"


def name_of(case):
    r = rz.loc[case] if case in rz.index else None
    z = zn[zn.case == case].sort_values("ac", ascending=False)
    return str((r.Name if r is not None else "") or (z.NAME.iloc[0] if len(z) else "") or "").strip()


def boundary(case):
    """The ground the case was approved on: the petition boundary from the Rezoning layer; else every district that carries the case
    now or lists it in its history (so ground later moved to an amendment's case number is still counted)."""
    if case in rz.index:
        return rz.geometry[case], "Rezoning layer petition boundary"
    rows = [i for i in zn.index if zn.case[i] == case or case in zn.chain[i]]
    later = sorted({zn.case[i] for i in rows} - {case})
    return zn.geometry[rows].union_all(), "zoning map districts" + (f", with ground now under {', '.join(later)}" if later else "")


def lineage(case):
    """Conditional cases the zoning map lists before this one on most of its ground, newest first."""
    h = HIST[HIST.case == case]
    if not len(h):
        return []
    chain = h.groupby("earlier_cases_on_this_piece").acres.sum().idxmax()
    return [c for c in chain.split(" < ") if parse_case(c)[1] in ("CZ", "CU")]


def measure(mask, approved):
    """Forest at approval, first clearing and the build-out marks for one boundary and one approval date."""
    f17 = mask & cand
    out = dict(area_acres=round(mask.sum() * PX, 1), forest_2017_acres=round(f17.sum() * PX, 1))
    if approved < BASELINE_END:
        out.update(measurable=False, forest_at_approval_acres="", note="approved before the 2017 forest baseline: forest at approval cannot be measured")
        ev = f17 & (event_q >= 0)
        q = np.sort(event_q[ev])
        out.update(cleared_since_2017_acres=round(ev.sum() * PX, 1), first_clearing_quarter_since_2017=(DET_Q[q[ACRE_PX - 1]] if len(q) >= ACRE_PX else ""), standing_now_acres=round((f17 & now_forest).sum() * PX, 1))
        return out
    a0 = int(np.searchsorted(Q_END.values, np.datetime64(approved.normalize())))          # first quarter that ends on or after the approval date
    before = f17 & (event_q >= 0) & (event_q < a0)
    fa = f17 & ~before
    post = fa & (event_q >= a0)
    n = fa.sum()
    out.update(measurable=True, forest_at_approval_acres=round(n * PX, 1), cleared_before_approval_acres=round(before.sum() * PX, 1), approval_quarter=(DET_Q[a0] if a0 < len(DET_Q) else "after the data"),
               cleared_since_approval_acres=round(post.sum() * PX, 1), standing_now_acres=round((fa & now_forest).sum() * PX, 1), share_cleared_to_date=round(post.sum() / n, 3) if n else "",
               age_years=round((DATA_END - approved).days / 365.25, 2))
    q = np.sort(event_q[post])
    if len(q) >= ACRE_PX:
        fq = int(q[ACRE_PX - 1])
        out.update(first_clearing_quarter=DET_Q[fq], lag_months=round(max((Q_MID[fq] - approved).days / 30.44, 0), 1), first_clearing_in_approval_quarter=bool(fq == a0), cleared=True)
    else:
        out.update(first_clearing_quarter="", lag_months="", first_clearing_in_approval_quarter=False, cleared=False, months_waited=round((DATA_END - approved).days / 30.44, 1))
    for k in YEARS:
        mark = approved + pd.DateOffset(years=k)
        if mark <= MARK_END and n:
            last = int(np.searchsorted(Q_END.values, np.datetime64(mark.normalize()), side="right")) - 1        # last quarter that ended by the mark
            out[f"share_cleared_year_{k}"] = round(((post & (event_q <= last)).sum()) / n, 3)
        else:
            out[f"share_cleared_year_{k}"] = ""
    return out


def burn(geom):
    return features.rasterize([(geom, 1)], out_shape=SHAPE, transform=T10, fill=0, dtype="uint8").astype(bool) & inb


# ------------------------------------------------------------------ classify every case approved in the period
cases, parents = [], {}
for case in sorted(set(zn.case[zn.case != ""]) | set(rz.index)):
    if parse_case(case)[1] != "CZ":
        continue
    status = MANUAL_STATUS.get(case) or (rz.Status[case] if case in rz.index else "on zoning map")
    if status not in ("Approved", "on zoning map") and not (zn.case == case).any():
        continue
    d, basis = layer_date(case)
    eff = pd.Timestamp(MANUAL[case]) if case in MANUAL else d
    if pd.isna(eff) or eff < OFFICE_START:
        continue
    name = name_of(case)
    line = lineage(case)
    pre = [c for c in line if (eff_date(c) < OFFICE_START if pd.notna(eff_date(c)) else (parse_case(c)[0] or 9999) < OFFICE_START.year)]
    by_name = bool(AMEND.search(name))
    if not line and not by_name:
        kind, anchor = "first approval", ""
    elif not line and by_name:
        anchor = PARENTS.original_case[PARENTS.parent_project == PIPE.parent_project.get(case, "__")].iloc[0] if PIPE.parent_project.get(case, "") else ""
        kind = "amendment" if anchor else "first approval"
    else:
        anchor = pre[0] if pre else line[-1]            # the plan in force at the cut; else the first conditional case on this ground within the period
        kind = "amendment"
    row = dict(case=case, name=name, status=status, approved=eff.date(), approved_basis=("manual (Adam, 2026-11-24); layers say " + (str(d.date()) if pd.notna(d) else "nothing")) if case in MANUAL else basis,
               kind=kind, earlier_conditional_cases=" < ".join(line), amendment_by_name=by_name, parent_anchor=anchor, conflict_flag=COI.get(case, ""))
    if kind == "amendment":
        parents.setdefault(anchor, []).append(case)
    cases.append(row)
C = pd.DataFrame(cases)

# ------------------------------------------------------------------ first approvals: one row per case
rows = []
for r in C[C.kind == "first approval"].itertuples():
    geom, gb = boundary(r.case)
    mk = burn(geom)
    rows.append(dict(r._asdict(), boundary_basis=gb, **public(mk), **measure(mk, pd.Timestamp(r.approved))))
A = pd.DataFrame(rows).drop(columns=["Index", "parent_anchor"]).fillna("")
A["date_ok"] = ~A.case.isin(MANUAL)
A["in_scope"] = pd.to_numeric(A.forest_at_approval_acres, errors="coerce").fillna(0) >= MIN_FOREST_AC
A["in_lag_calculation"] = A.in_scope & A.date_ok & ~A.case.isin(OUT_OF_TOTALS)
A = A.sort_values(["in_lag_calculation", "approved"], ascending=[False, True])
A.to_csv(os.path.join(OUT, "lag_cases.csv"), index=False)

# ------------------------------------------------------------------ amendments: one row per parent project
groups = {}
for anchor, kids in parents.items():
    root, seen = anchor, {anchor}
    while AMEND.search(name_of(root)) and lineage(root) and lineage(root)[0] not in seen:        # the plan in force is itself an amendment: go back to what it amended
        root = lineage(root)[0]; seen.add(root)
    g = groups.setdefault(root, dict(keys=set(), kids=[]))
    g["keys"].add(anchor); g["kids"] += kids        # the boundary is the plan in force (the anchor), which is what the amendments changed; the date is the root's
P = []
for root, g in groups.items():
    keys, kids = g["keys"], sorted(set(g["kids"]))
    d, basis = layer_date(root)
    manual = root in MANUAL
    rowsz = [i for i in zn.index if zn.case[i] in keys or keys & set(zn.chain[i])]
    geom = zn.geometry[rowsz].union_all() if rowsz else None
    named = [PNAME[k] for k in keys if k in PNAME]
    base = dict(parent=named[0] if named else " + ".join([root] + sorted(keys - {root})), original_case=root, boundary_from="districts that carry or list " + ", ".join(sorted(keys)), original_name=name_of(root), original_approved=(d.date() if pd.notna(d) and not manual else ""),
                original_approved_basis=(f"manual date {MANUAL[root]} (Adam); the layers say {d.date() if pd.notna(d) else 'nothing'}" if manual else basis if pd.notna(d) else f"case-number year only ({parse_case(root)[0]})"),
                amendments_in_period="; ".join(f"{k} {name_of(k)} ({C.approved[C.case == k].iloc[0]})" for k in kids),
                n_amendments=len(kids), conflict_flag="; ".join(sorted({COI[k] for k in kids + list(keys) if k in COI})), out_of_totals=bool((set(kids) | keys) & OUT_OF_TOTALS))
    mk = burn(geom) if geom is not None else None
    if mk is None or pd.isna(d) or manual:
        m = dict(measurable=False, note="no boundary on the map for the original" if mk is None else "the original's date was corrected by hand" if manual else "the original's approval date is in neither layer")
        if mk is not None:
            ev = mk & cand & (event_q >= 0); q = np.sort(event_q[ev])
            m.update(area_acres=round(mk.sum() * PX, 1), forest_2017_acres=round((mk & cand).sum() * PX, 1), cleared_since_2017_acres=round(ev.sum() * PX, 1),
                     first_clearing_quarter_since_2017=(DET_Q[q[ACRE_PX - 1]] if len(q) >= ACRE_PX else ""), standing_now_acres=round((mk & cand & now_forest).sum() * PX, 1))
    else:
        m = measure(mk, d)
    P.append(dict(base, **(public(mk) if mk is not None else {}), **m))
P = pd.DataFrame(P).fillna("")
od = pd.to_datetime(P.original_approved, errors="coerce")
P["group"] = np.where(P.original_approved_basis.str.startswith("manual"), "3 excluded: original date corrected by hand",
             np.where(od.isna(), "4 excluded: original date is the case-number year only",
             np.where(od < BASELINE_END, "2 original approved before the 2017 baseline: no forest-at-approval figure",
             np.where(od < OFFICE_START, "1a original approved between the 2017 baseline and 2019-12-03", "1b first approved within the period, later amended (also in the first-approval table)"))))
P = P.sort_values(["group", "forest_2017_acres"], ascending=[True, False])
P.to_csv(os.path.join(OUT, "lag_amendments.csv"), index=False)

# ------------------------------------------------------------------ lag and build-out, first approvals only
L = A[A.in_lag_calculation].copy()
L["lag"] = pd.to_numeric(L.lag_months, errors="coerce")
done, wait = L[L.cleared == True], L[L.cleared != True]


def km_median(times, events):
    """Kaplan-Meier median: the lag by which half of all cases, counting those still waiting, have started clearing."""
    o = np.argsort(times); t, e = np.asarray(times)[o], np.asarray(events)[o]
    s, n = 1.0, len(t)
    for i in range(n):
        if e[i]:
            s *= 1 - 1 / (n - i)
            if s <= 0.5:
                return float(t[i])
    return None


km = km_median(list(done.lag) + list(pd.to_numeric(wait.months_waited)), [1] * len(done) + [0] * len(wait))
med = float(done.lag.median()) if len(done) else float("nan")
curve = []
for k in YEARS:
    v = pd.to_numeric(L[f"share_cleared_year_{k}"], errors="coerce").dropna()
    el = L[pd.to_numeric(L[f"share_cleared_year_{k}"], errors="coerce").notna()]
    fa = pd.to_numeric(el.forest_at_approval_acres)
    curve.append(dict(years_after_approval=k, cases_old_enough=len(v), median_share_cleared=round(v.median(), 3) if len(v) else "", lowest=round(v.min(), 3) if len(v) else "", highest=round(v.max(), 3) if len(v) else "",
                      quarter_25=round(v.quantile(0.25), 3) if len(v) else "", quarter_75=round(v.quantile(0.75), 3) if len(v) else "", cases_with_any_clearing=int((v > 0).sum()),
                      forest_at_approval_acres=round(fa.sum(), 1), acres_cleared_by_then=round((fa * pd.to_numeric(el[f"share_cleared_year_{k}"])).sum(), 1),
                      pooled_share=round((fa * pd.to_numeric(el[f"share_cleared_year_{k}"])).sum() / fa.sum(), 3) if fa.sum() else ""))
CV = pd.DataFrame(curve); CV.to_csv(os.path.join(OUT, "lag_buildout_curve.csv"), index=False)

pd.set_option("display.width", 320, "display.max_columns", 40, "display.max_rows", 300, "display.max_colwidth", 70)
S = []
say = S.append
allA = A[~A.case.isin(OUT_OF_TOTALS)]
say(f"Lag from approval to clearing, and build-out. 2017-2026 detection; approvals on or after {OFFICE_START.date()}; data through {DATA_END.date()}.")
say(f"Conditional zoning cases approved in the period: {len(C)}. First approvals (no earlier conditional case on the ground): {int((C.kind == 'first approval').sum())}. Amendments or re-approvals: {int((C.kind == 'amendment').sum())}, on {len(P)} parent projects.")
say(f"First approvals with {MIN_FOREST_AC:g} ac or more of forest at approval: {int(allA.in_scope.sum())} (without {', '.join(OUT_OF_TOTALS)}). In the lag calculation: {len(L)}. Left out for a manually corrected date: {', '.join(allA.case[allA.in_scope & ~allA.date_ok]) or 'none'}.")
say(f"\n1. LAG. {len(done)} of the {len(L)} cases have had an acre or more cleared since approval; {len(wait)} have not.")
say(f"   Median lag among the {len(done)} that have started: {med:.1f} months (middle half {done.lag.quantile(0.25):.1f} to {done.lag.quantile(0.75):.1f}; shortest {done.lag.min():.1f}, longest {done.lag.max():.1f}).")
say(f"   Counting the {len(wait)} still waiting (Kaplan-Meier): half of all cases have started by " + (f"{km:.1f} months." if km is not None else "a point not yet reached in the data."))
say(f"   {int(done.first_clearing_in_approval_quarter.sum())} cases were first detected in the same quarter as their approval, where the order within the quarter is not known: " + ", ".join(done.case[done.first_clearing_in_approval_quarter == True]))
say(f"   Started within 6 months: {int((done.lag <= 6).sum())}; 6 to 12: {int(((done.lag > 6) & (done.lag <= 12)).sum())}; 12 to 24: {int(((done.lag > 12) & (done.lag <= 24)).sum())}; over 24: {int((done.lag > 24).sum())}.")
big = L[pd.to_numeric(L.forest_at_approval_acres) >= 10]; bd = big[big.cleared == True]
say(f"   Cases with 10 ac or more of forest at approval: {len(big)}, {len(bd)} started, median lag {pd.to_numeric(bd.lag_months).median():.1f} months.")
say("\n2. BUILD-OUT: share of forest at approval cleared, by years since approval (only cases old enough to have reached each mark).")
say(CV.rename(columns={"years_after_approval": "year", "cases_old_enough": "cases", "median_share_cleared": "median", "quarter_25": "q25", "quarter_75": "q75", "cases_with_any_clearing": "started", "forest_at_approval_acres": "forest_ac",
                       "acres_cleared_by_then": "cleared_ac", "pooled_share": "pooled"}).to_string(index=False))
say("   'pooled' is all acres cleared by the mark over all forest at approval, so large cases weigh more; 'median' gives every case one vote.")
cols = ["case", "name", "approved", "forest_at_approval_acres", "first_clearing_quarter", "lag_months", "cleared_since_approval_acres", "share_cleared_to_date"] + [f"share_cleared_year_{k}" for k in YEARS]
ren = {"forest_at_approval_acres": "forest", "first_clearing_quarter": "first_q", "lag_months": "lag", "cleared_since_approval_acres": "cleared", "share_cleared_to_date": "to_date", **{f"share_cleared_year_{k}": f"y{k}" for k in YEARS}}
say("\n   The cases, oldest first:")
say(L.sort_values("approved")[cols + ["public_owner_case", "conflict_flag"]].rename(columns=dict(ren, public_owner_case="public", conflict_flag="flag")).assign(name=lambda d: d.name.str[:24], flag=lambda d: d.flag.str[:8]).to_string(index=False))
old = wait[pd.to_numeric(wait.months_waited) > med].sort_values("approved")
say(f"\n3. APPROVED LONGER AGO THAN THE MEDIAN LAG ({med:.1f} months) WITH NO CLEARING OF AN ACRE YET: {len(old)} cases, {pd.to_numeric(old.forest_at_approval_acres).sum():,.1f} ac of forest at approval.")
say(old[["case", "name", "approved", "months_waited", "forest_at_approval_acres", "cleared_since_approval_acres", "standing_now_acres", "public_owner_case", "conflict_flag"]].assign(name=lambda d: d.name.str[:30]).to_string(index=False) if len(old) else "   none")
young = wait[pd.to_numeric(wait.months_waited) <= med]
say(f"   Not yet cleared and younger than the median lag: {len(young)} ({', '.join(young.case)}).")
if km is not None:
    old2 = wait[pd.to_numeric(wait.months_waited) > km]
    say(f"   Against the {km:.1f}-month figure that counts the cases still waiting: {len(old2)} cases, {pd.to_numeric(old2.forest_at_approval_acres).sum():,.1f} ac ({', '.join(old2.sort_values('approved').case)}).")
part = wait[pd.to_numeric(wait.cleared_since_approval_acres) >= 0.1]
say("   Some clearing but under an acre since approval: " + (", ".join(f"{r.case} {r.cleared_since_approval_acres} ac" for r in part.itertuples()) or "none"))
say("\n4. LISTED SEPARATELY")
ex = allA[allA.in_scope & ~allA.date_ok]
say("   Manually corrected dates (left out of the lag): " + ("none" if not len(ex) else ""))
if len(ex):
    say(ex[["case", "name", "approved", "approved_basis", "forest_at_approval_acres", "first_clearing_quarter", "lag_months", "share_cleared_to_date"]].to_string(index=False))
small = allA[~allA.in_scope]
say(f"   First approvals with under {MIN_FOREST_AC:g} ac of forest at approval (out of scope): {len(small)}.")
say("\n   AMENDMENTS AND RE-APPROVALS, on the parent project's boundary from the original approval date:")
short = {"forest_2017_acres": "forest17", "forest_at_approval_acres": "at_approval", "first_clearing_quarter": "first_q", "lag_months": "lag", "cleared_since_approval_acres": "cleared", "share_cleared_to_date": "to_date",
         "cleared_since_2017_acres": "cleared_since_2017", "first_clearing_quarter_since_2017": "first_q_since_2017", "standing_now_acres": "standing", "amendments_in_period": "cases in the period", "public_owner_case": "public"}
for grp, g in P[~P.out_of_totals].groupby("group"):
    say(f"   -- {grp[2:].strip()}: {len(g)} parent projects, {int(g.n_amendments.sum())} cases")
    c5 = ["parent", "original_case", "original_approved", "area_acres", "forest_2017_acres"] + (["forest_at_approval_acres", "first_clearing_quarter", "lag_months", "cleared_since_approval_acres", "share_cleared_to_date"] + [f"share_cleared_year_{k}" for k in YEARS]
          if grp.startswith("1") else ["cleared_since_2017_acres", "first_clearing_quarter_since_2017"]) + ["standing_now_acres", "public_owner_case", "amendments_in_period"]
    say(g[[c for c in c5 if c in g.columns]].rename(columns=dict(short, **{f"share_cleared_year_{k}": f"y{k}" for k in YEARS})).assign(**{"cases in the period": lambda d: d["cases in the period"].str[:70]}).to_string(index=False))
held = P[P.out_of_totals]
say("   Parent rows left out of the tables above because they include 23CZ13: " + (", ".join(held.parent) or "none"))
say(f"\n   {', '.join(OUT_OF_TOTALS)} is in " + ("lag_cases.csv" if set(A.case) & OUT_OF_TOTALS else "lag_amendments.csv" if len(held) else "neither table") + " with its flag and is in none of the figures above.")
say("\nRead with care: a quarter is when clearing was first seen, and winter quarters can run a quarter early. Clearing means bare for about a year or more in a patch of an acre or more;")
say("thinning and cuts under an acre do not count. The newest cases have had the least time, so the later year marks rest on the older cases only.")
open(os.path.join(OUT, "lag_summary.txt"), "w").write("\n".join(S) + "\n")
print("\n".join(S))
