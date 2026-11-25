#!/usr/bin/env python
"""office_period.py: the same clearings and cases, cut at OFFICE_START.

    ../apex-canopy/df-venv/bin/python office_period.py

Run after entitlement.py, ../prerezoning/detect_2017.py and (for the RCA columns) rca/build_office.py.
1. Every governing case by approval date, on or after OFFICE_START or before, and the release's 929 acres split that way,
   with amendments also counted at their parent project's original approval.
2. Acres cleared per calendar year from the 2017-2026 detection, and period totals.
3. Every conditional zoning case approved on or after OFFICE_START with 2 acres or more of 2017 forest: forest at
   approval, cleared since, standing now.
Writes out/office_governing_cases.csv, out/office_clearings_by_year.csv, out/office_period_cases.csv (forest columns; the
RCA columns are added by rca/build_office.py), out/office_period_summary.txt.
"""
import json, os, re
import numpy as np, pandas as pd, geopandas as gpd, shapely
from affine import Affine
from rasterio import features

HERE = os.path.dirname(os.path.abspath(__file__))
AC = os.path.join(HERE, "..", "apex-canopy"); OUT = os.path.join(HERE, "out"); PRE = os.path.join(AC, "prerezoning_cache")
OFFICE_START = pd.Timestamp("2019-12-03")
WAKE_ASSESSMENT = "2020Q3"       # first quarter after the NAIP 2020 flight used by Wake County's canopy assessment (July 11-12, 2020 over most of Apex)
MIN_FOREST_AC = 2.0
M2_AC = 4046.8564
X0, Y1, W, H = 683800, 3961460, 1504, 1272
T10 = Affine(10, 0, X0, 0, -10, Y1); SHAPE = (H, W); PX = 100 / M2_AC
MANUAL = {"22CZ21": "2023-03-28", "26CZ05": "2026-08-25", "25CZ13": "2026-01-12"}        # Adam, 2026-11-24
MANUAL_STATUS = {"26CZ05": "Approved", "25CZ13": "Approved"}
COI = {"23CZ13": "Seymour Mixed Use PUD is next to the author's home: left out of totals and disclosed",
       "24CZ19": "applicant is Barnett Properties, LLC: disclosed (the applicant is named in Barnett v. Seymour)",
       "24CZ20": "its PUD text names the Seymour PUD as the adjacent neighbourhood and ties a signal payment to it: held, not read",
       "24CZ08": "its application lists the proposed Seymour Mixed Use PUD as adjacent: disclosed (connected to the Seymour PUD)"}
HEADLINE_OUT = {"23CZ13"}        # left out of headline totals, as in entitlement.py

ms = lambda s: pd.to_datetime(s, unit="ms", errors="coerce") if "datetime" not in str(s.dtype) else s.dt.tz_localize(None)
fix = lambda g: gpd.GeoSeries(shapely.make_valid(g.geometry.values), index=g.index, crs=g.crs)


def parse_case(c):
    m = re.match(r"^0?(\d{2})([A-Z]{2,3})\d", str(c).strip().upper())
    if not m:
        return None, None
    y = int(m.group(1))
    return (2000 + y if y <= 30 else 1900 + y), m.group(2)


rz = gpd.read_file(os.path.join(HERE, "inputs", "town_rezoning_2026-11-24.geojson")).to_crs(32617); rz["geometry"] = fix(rz)
rz["case"] = rz.Petition.str.strip().str.upper(); rz["filed"], rz["action"] = ms(rz.Submitted), ms(rz.Action_Date); rz = rz.set_index("case", drop=False)
zn = gpd.read_file(os.path.join(HERE, "inputs", "town_zoning_2026-11-24.geojson")).to_crs(32617); zn["geometry"] = fix(zn)
zn["case"] = zn.CASE_NUMBE.fillna("").str.strip().str.upper(); zn["approved"] = ms(zn["DATE_"]); zn["ac"] = zn.area / M2_AC


def approval(case):
    """(date, basis, note). Rezoning layer action date first, else the date on the largest zoning-map district; manual dates override both."""
    yr, kind = parse_case(case)
    r = rz.loc[case] if case in rz.index else None
    z = zn[zn.case == case].sort_values("ac", ascending=False)
    zd = sorted({d.date() for d in z.approved.dropna()})
    if case in MANUAL:
        d, basis = pd.Timestamp(MANUAL[case]), "manual (Adam, 2026-11-24)"
    elif r is not None and pd.notna(r.action) and (r.Status == "Approved" or len(z)):
        d, basis = r.action, "Rezoning layer action date"
    elif len(z) and pd.notna(z.approved.iloc[0]):
        d, basis = z.approved.iloc[0], "zoning map date"
    else:
        d, basis = pd.NaT, "no date"
    notes = []
    if pd.isna(d):
        notes.append("no approval date in either layer")
    elif yr and d.year < yr:
        notes.append(f"date is before the case number's year ({yr})")
    elif yr and d.year > yr + 2:
        notes.append(f"date is more than two years after the case number's year ({yr})")
    if len(zd) > 1:
        notes.append("districts carry different dates: " + ", ".join(map(str, zd)))
    if r is not None and pd.notna(r.action) and zd and r.action.date() not in zd and case not in MANUAL:
        notes.append(f"Rezoning layer {r.action.date()} against zoning map {', '.join(map(str, zd))}")
    if pd.notna(d) and abs((d - OFFICE_START).days) <= 60:
        notes.append("within 60 days of the cut")
    return d, basis, "; ".join(notes)


def period(d):
    return "no date" if pd.isna(d) else "on or after 2019-12-03" if d >= OFFICE_START else "before 2019-12-03"


# ------------------------------------------------------------------ 1. governing cases and the release's clearings
T = pd.read_csv(os.path.join(OUT, "clearings_entitlement.csv")).fillna("")
PT = pd.read_csv(os.path.join(OUT, "parent_projects.csv")).fillna("")
ORIG = dict(zip(PT.parent_project, PT.original_case))
G = []
T.loc[T.governing_case == "1963", "governing_case"] = ""          # "1963" is the map's label for the original base zoning, not a case
for case, t in T.groupby("governing_case"):
    if not case:
        continue
    d, basis, note = approval(case)
    yr, kind = parse_case(case)
    par = t.parent_project.iloc[0]
    oc = ORIG.get(par, "")
    od, ob, on = approval(oc) if oc else (pd.NaT, "", "")
    if oc and pd.isna(od):                      # an original that is no longer a district of its own: its number still places it
        oy = parse_case(oc)[0]
        od = pd.Timestamp(oy, 12, 31) if oy and oy < OFFICE_START.year else pd.Timestamp(oy, 1, 1) if oy and oy > OFFICE_START.year else pd.NaT
        ob = "case-number year only"
    G.append(dict(governing_case=case, case_name=t.case_name.iloc[0], kind=kind or "", entitlement_type=t.entitlement_type.iloc[0], approved=d.date() if pd.notna(d) else "", approved_basis=basis, period=period(d), date_note=note,
                  parent_project=par, original_case=oc, original_approved=(od.date() if pd.notna(od) else ""), original_approved_basis=ob, period_at_parent=(period(od) if oc else period(d)),
                  clearings=len(t), acres=round(t.acres.sum(), 1)))
G = pd.DataFrame(G).sort_values("acres", ascending=False)
G.to_csv(os.path.join(OUT, "office_governing_cases.csv"), index=False)
gi = G.set_index("governing_case")
T["period"] = T.governing_case.map(gi.period).fillna("no case on the ground")
T["period_at_parent"] = T.governing_case.map(gi.period_at_parent).fillna("no case on the ground")
T["cut"] = np.where((T.period == "on or after 2019-12-03") & (T.period_at_parent == "before 2019-12-03"), "amendment approved in the period, original project approved before",
                    np.where(T.period == "on or after 2019-12-03", "case approved on or after 2019-12-03", np.where(T.period == "before 2019-12-03", "case approved before 2019-12-03", T.period)))

# ------------------------------------------------------------------ 2. acres per year, 2017 to 2026
J = json.load(open(os.path.join(PRE, "detect_2017.json")))
Q = pd.DataFrame([dict(quarter=q, **v) for q, v in J["acres_by_first_quarter"].items()])
Q["year"] = Q.quarter.str[:4].astype(int)
Y = Q.groupby("year").agg(quarters=("quarter", "size"), event_acres=("event_ac", "sum"), still_bare_acres=("strict_ac", "sum")).reset_index()
Y.to_csv(os.path.join(OUT, "office_clearings_by_year.csv"), index=False)
before = Q[Q.quarter < "2019Q4"]; straddle = Q[Q.quarter == "2019Q4"]; after = Q[Q.quarter > "2019Q4"]; wake = Q[Q.quarter >= WAKE_ASSESSMENT]

# ------------------------------------------------------------------ 3. conditional zoning cases approved on or after OFFICE_START
D = np.load(os.path.join(PRE, "detect_2017.npz"))
DET_Q = J["det_quarters"]
Q_END = pd.PeriodIndex(DET_Q, freq="Q").end_time.normalize().values.astype("datetime64[D]")
cand, first_event, kept_event = D["cand"], D["first_event"], D["kept_event"]
now_forest = D["state_now"] == 0
ev_end = np.where(first_event >= 0, Q_END[np.maximum(first_event, 0)], np.datetime64("2100-01-01"))
inb = np.load(os.path.join(AC, "s2", "cache", "baseline.npz"))["inb"]
PIPE = pd.read_csv(os.path.join(OUT, "pipeline_2022plus.csv")).fillna("").set_index("case")
R, masks = [], {}
for case in sorted(set(zn.case[zn.case != ""]) | set(rz.index)):
    yr, kind = parse_case(case)
    if kind != "CZ":
        continue
    r = rz.loc[case] if case in rz.index else None
    cur = zn[zn.case == case]
    status = MANUAL_STATUS.get(case) or (r.Status if r is not None else "on zoning map")
    if status not in ("Approved", "on zoning map") and not len(cur):
        continue
    d, basis, note = approval(case)
    if pd.isna(d) or d < OFFICE_START:
        continue
    geom, src = (r.geometry, "Rezoning layer (petition area)") if r is not None else (cur.geometry.union_all(), "zoning map (districts now under this case)")
    m = features.rasterize([(geom, 1)], out_shape=SHAPE, transform=T10, fill=0, dtype="uint8").astype(bool) & inb
    f17 = m & cand
    ev = m & kept_event
    pre = ev & (ev_end < np.datetime64(d.date()))
    info = PIPE.loc[case] if case in PIPE.index else None
    masks[case] = m
    R.append(dict(case=case, name=((r.Name if r is not None else "") or (cur.NAME.iloc[0] if len(cur) else "")), status=status, approved=d.date(), approved_basis=basis, date_note=note,
                  entitlement_type=(info.entitlement_type if info is not None else ""), parent_project=(info.parent_project if info is not None else ""), amendment_scope=(info.amendment_scope if info is not None else ""),
                  case_acres=round(m.sum() * PX, 1), forest_2017_acres=round(f17.sum() * PX, 1), cleared_before_approval_acres=round(pre.sum() * PX, 1),
                  forest_at_approval_acres=round((f17 & ~pre).sum() * PX, 1), cleared_since_approval_acres=round((ev & ~pre).sum() * PX, 1), standing_now_acres=round((f17 & now_forest).sum() * PX, 1),
                  share_of_forest_at_approval_cleared=(round((ev & ~pre).sum() / max((f17 & ~pre).sum(), 1), 2)), public_owner_case=(bool(info.public_owner_case) if info is not None else ""),
                  town_case_file_url=str(((r.More_Info if r is not None else None) or (cur.More_Info.dropna().iloc[0] if len(cur.More_Info.dropna()) else "")) or "").replace("nan", ""),
                  boundary_from=src, conflict_flag=COI.get(case, "")))
R = pd.DataFrame(R)
ALL = R.copy()
R = R[R.forest_2017_acres >= MIN_FOREST_AC].sort_values("forest_at_approval_acres", ascending=False)
R.to_csv(os.path.join(OUT, "office_period_cases.csv"), index=False)
np.savez_compressed(os.path.join(PRE, "office_masks.npz"), **{k: v for k, v in masks.items() if k in set(R.case)})

# ------------------------------------------------------------------ summary (the RCA part is appended by rca/build_office.py)
pd.set_option("display.width", 300, "display.max_columns", 40, "display.max_rows", 300, "display.max_colwidth", 60)
L = []
say = L.append
say(f"Re-cut at {OFFICE_START.date()}. Approval date: the Rezoning layer's action date, else the date on the zoning map; three manual dates from Adam.")
say(f"\n1. Governing cases of the release's {len(T)} clearings ({T.acres.sum():.1f} ac): {len(G)} cases plus {int((T.governing_case == '').sum())} clearings with no case (base zoning).")
say(G.groupby("period").agg(cases=("governing_case", "size"), clearings=("clearings", "sum"), acres=("acres", "sum")).round(1).to_string())
say("\n   The 929 acres by the governing case's approval date:")
say(T.groupby("period").agg(clearings=("id", "size"), acres=("acres", "sum")).round(1).to_string())
say("\n   With amendments counted at the parent project's original approval:")
say(T.groupby("cut").agg(clearings=("id", "size"), acres=("acres", "sum")).round(1).to_string())
am = G[(G.period == "on or after 2019-12-03") & (G.period_at_parent == "before 2019-12-03")]
say("   amendments approved in the period on projects first approved before it:")
say(am[["governing_case", "case_name", "approved", "parent_project", "original_case", "original_approved", "original_approved_basis", "clearings", "acres"]].to_string(index=False))
odd = G[G.date_note != ""]
say(f"\n   Governing cases whose date is missing or looks wrong, or sits close to the cut: {len(odd)}")
say(odd[["governing_case", "case_name", "approved", "approved_basis", "period", "date_note", "clearings", "acres"]].to_string(index=False) if len(odd) else "   none")
say("\n   Largest governing cases on each side:")
for p, g in G.groupby("period"):
    say(f"   -- {p}")
    say(g[["governing_case", "case_name", "approved", "clearings", "acres", "parent_project"]].head(8).to_string(index=False))

say(f"\n2. Acres cleared per calendar year, 2017-2026 detection (2017 forest baseline, patches of an acre or more). 'event' = bare for about a year or more; 'still bare' = the release's rule.")
say("   2017 is October-December only; 2026 runs to October 24. A clearing's quarter is when it was first seen, which can be a quarter early in winter.")
say(Y.round(1).to_string(index=False))
f = lambda q: f"{q.event_ac.sum():,.1f} ac (still bare {q.strict_ac.sum():,.1f})"
say(f"\n   2017Q4 through 2019Q3 (before {OFFICE_START.date()}): {f(before)}")
say(f"   2019Q4, the quarter the cut falls in (Oct 1 to Dec 31, 2019): {f(straddle)}")
say(f"   2020Q1 to 2026Q4 (after): {f(after)}")
say(f"   since July 2020 ({WAKE_ASSESSMENT} on): {f(wake)}")
say("   Wake County's Land Cover Analysis & Tree Canopy Assessment used leaf-on NAIP imagery of vintage 2020 and compares 2010 with 2020. NAIP 2020 over Apex was flown July 11-12, 2020")
say("   (ten tiles) and September 21, 2020 (two tiles on the east side), so 'since July 2020' is right for most of Apex. The report gives Apex 2,180 acres of canopy lost 2010-2020 (15.2%).")

H = R[~R.case.isin(HEADLINE_OUT)]
say(f"\n3. Conditional zoning cases approved on or after {OFFICE_START.date()}: {len(ALL)} with a date and a boundary; {len(R)} have {MIN_FOREST_AC:g} ac or more of 2017 forest ({len(H)} without {', '.join(HEADLINE_OUT)}).")
say(f"   Sum of rows, without {', '.join(HEADLINE_OUT)} (cases overlap, so this double-counts shared ground): forest in 2017 {H.forest_2017_acres.sum():,.0f} ac, at approval {H.forest_at_approval_acres.sum():,.0f}, "
    f"cleared since approval {H.cleared_since_approval_acres.sum():,.0f}, standing now {H.standing_now_acres.sum():,.0f}.")
um = np.zeros(SHAPE, bool)
for c in H.case: um |= masks[c]
say(f"   Counted once on the ground: {(um & cand).sum() * PX:,.0f} ac of 2017 forest, {(um & kept_event).sum() * PX:,.0f} ac cleared since mid-2017, {(um & cand & now_forest).sum() * PX:,.0f} ac standing now.")
say(R[["case", "name", "approved", "case_acres", "forest_2017_acres", "forest_at_approval_acres", "cleared_since_approval_acres", "standing_now_acres", "conflict_flag"]].rename(
    columns={"case_acres": "acres", "forest_2017_acres": "forest17", "forest_at_approval_acres": "at_approval", "cleared_since_approval_acres": "cleared_since", "standing_now_acres": "standing", "conflict_flag": "conflict"})
    .assign(name=lambda d: d.name.str[:30], conflict=lambda d: d.conflict.str[:10]).to_string(index=False))
odd3 = ALL[ALL.date_note != ""]
say(f"\n   Date notes among these cases: {len(odd3)}")
say(odd3[["case", "name", "approved", "approved_basis", "date_note"]].to_string(index=False) if len(odd3) else "   none")
say("   Not in this list: cases that are no longer a district of their own and are not in the Rezoning layer (for example 22CZ26, 23CZ21): the map keeps no boundary or date for them.")
open(os.path.join(OUT, "office_period_summary.txt"), "w").write("\n".join(L) + "\n")
print("\n".join(L))
