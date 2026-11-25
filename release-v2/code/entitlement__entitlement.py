#!/usr/bin/env python
"""entitlement.py: when each clearing happened relative to its zoning case, and how much forest
sits inside cases approved since 2022.

    ../apex-canopy/df-venv/bin/python entitlement.py

Inputs
  ../apex-canopy/release-v1/   clearings.geojson, case_join.csv, baseline_forest_10m.tif (release v1.1)
  ../apex-canopy/s2/cache/detect.npz   per-quarter forest-like / cleared-like state from the release's detection
                                       step (04_detect.py); state_2026Q3 is the latest leaf-on composite
  inputs/town_*.geojson        three Town of Apex public layers, pulled 2026-11-24:
      Rezoning            69 cases with a filing date (Submitted), status and action date. NOT a full list.
      Zoning_Conditions   the zoning map: 763 districts, each with its current case number, an approval
                          date, and BACK1..BACK14, the earlier cases on the same ground, newest first.
      Development         site and subdivision plan records, with submittal and action dates.
  inputs/public_parcels_*.geojson   parcels owned by public bodies (pull_public_parcels.py)
Outputs (out/)
  clearings_entitlement.csv, summary_entitlement_x_timing.csv, pipeline_2022plus.csv,
  cleared_before_filing.csv, case_ground_history.csv, chain_varies_by_polygon.csv, chain_audit.txt, summary.txt,
  parent_projects.csv, review_list.csv, freshness_25CZ_26CZ.csv, plan_check/ (plan_records.csv, plan_coverage_by_clearing.csv, plan_check.kml)
Method and caveats: NOTES.md.
"""
import glob, os, re
from xml.sax.saxutils import escape
import numpy as np, pandas as pd, geopandas as gpd, rasterio, shapely
from rasterio import features

HERE = os.path.dirname(os.path.abspath(__file__))
REL = os.path.join(HERE, "..", "apex-canopy", "release-v1")
S2 = os.path.join(HERE, "..", "apex-canopy", "s2", "cache", "detect.npz")
OUT = os.path.join(HERE, "out"); os.makedirs(OUT, exist_ok=True)
M2_AC = 4046.8564
MIN_OVERLAP_AC = 0.05          # same rule as the release's case join
FRAC, TPA = 0.84, 163.9        # share of an outline truly bare; trees 5"+ per forest acre (Wake County, FIA)
CUR_Q = "2026Q3"               # latest leaf-on composite: "current forest" is measured here
PUBLIC_SHARE = 0.5             # a case is a public-owner case if public bodies own at least this share of its area
COI = {"23CZ13": "Seymour Mixed Use PUD is next to the author's home: left out of totals and disclosed"}
AMEND = re.compile(r"amend|expan|text", re.I)
PULLED = "2026-11-24"          # date of the Town layer pull in inputs/
# Dates and statuses Adam supplied on 2026-11-24, to be used in place of what the Town layers carry.
MANUAL = {"22CZ21": dict(approved="2023-03-28"),
          "26CZ05": dict(approved="2026-08-25", status="Approved"),
          "25CZ13": dict(approved="2026-01-12", status="Approved")}
BEFORE_FILED = "cleared_before_case_filed"                     # internal: the first-detection quarter ended before the case was filed. Reported as one of:
UNDER_EARLIER = "cleared_under_earlier_approval"               #   a conditional case from an earlier year was already on the ground
BEFORE_ANY = "cleared_before_any_approval"                     #   no conditional case was on the ground before the clearing
SAME_YEAR = "cleared_before_case_filed_earlier_case_same_year"  #   the only earlier conditional case is numbered the same year as the clearing: order not known
REVIEW_MIN_AC = 2.0
EXPANSION_SHARE = 0.5           # an amendment with at least this share of its petition outside the parent project adds ground
# Amendment labels (Adam, 2026-11-24). Nothing is called a text change unless the petition says so; size is not used.
EXPAND, CARVE, SAME = "expansion onto new ground", "carve-out to a different district", "same district, conditions or phase"
PARENT_NAMES = {"09CZ07": "Veridea", "18CZ04": "Horton Park", "22CZ26": "Apex Gateway Phase 2"}      # project names given by hand; the rest are labelled by their case numbers
NEW, A22, APRE, OLD = "new_rezoning_2022plus", "amendment_of_2022plus_original", "amendment_of_pre2022_original", "pre2022_or_none"


def fix(g):
    """Repair invalid shapes. Several Town polygons carry a part nested inside another part ("nested shells"); every one checked
    is ground that belongs to a different district or record, so the nested part is a hole. make_valid reads it that way.
    buffer(0), used in the first version, merged it into the surrounding shape and so counted that ground twice."""
    out = gpd.GeoSeries(shapely.make_valid(g.geometry.values), index=g.index, crs=g.crs)
    assert out.geom_type.isin(["Polygon", "MultiPolygon"]).all()
    return out


def ms(s):
    return pd.to_datetime(s, unit="ms", errors="coerce") if "datetime" not in str(s.dtype) else s.dt.tz_localize(None)


def parse_case(c):
    """'25CZ18' -> (2025, 'CZ'). Tokens that are not case numbers (WC, CC, 1963, GS ...) -> (None, None)."""
    m = re.match(r"^0?(\d{2})([A-Z]{2,3})\d", str(c).strip().upper())
    if not m:
        return None, None
    y = int(m.group(1))
    return (2000 + y if y <= 30 else 1900 + y), m.group(2)


# ------------------------------------------------------------------ load
cl = gpd.read_file(os.path.join(REL, "clearings.geojson")).to_crs(32617)
cl["q"] = pd.PeriodIndex(cl.first_quarter, freq="Q")
cl["q_start"], cl["q_end"] = cl.q.dt.start_time, cl.q.dt.end_time.dt.normalize()
cl["leaf_off"] = cl.q.dt.quarter.isin([1, 4])
cj = pd.read_csv(os.path.join(REL, "case_join.csv"), dtype=str).fillna("").set_index("id")

rz = gpd.read_file(os.path.join(HERE, "inputs", "town_rezoning_2026-11-24.geojson")).to_crs(32617)
rz["geometry"] = fix(rz)
rz["case"] = rz.Petition.str.strip().str.upper()
rz["filed"], rz["action"] = ms(rz.Submitted), ms(rz.Action_Date)
rz = rz.set_index("case", drop=False)

zn = gpd.read_file(os.path.join(HERE, "inputs", "town_zoning_2026-11-24.geojson")).to_crs(32617)
zn["geometry"] = fix(zn)
zn["case"] = zn.CASE_NUMBE.fillna("").str.strip().str.upper()
zn["approved"] = ms(zn["DATE_"])
zn["ac"] = zn.area / M2_AC
BACK = sorted([c for c in zn.columns if c.startswith("BACK")], key=lambda c: int(c[4:]))
zn["chain"] = zn[BACK].fillna("").apply(lambda r: [x.strip().upper() for x in r if x and x.strip()], axis=1)
CURRENT, IN_CHAIN = {}, {}                       # case -> zoning rows now under it / rows that list it as an earlier case
for z in zn.itertuples():
    if z.case:
        CURRENT.setdefault(z.case, []).append(z.Index)
    for c in dict.fromkeys(z.chain):
        if c != z.case:
            IN_CHAIN.setdefault(c, []).append(z.Index)

dv = gpd.read_file(os.path.join(HERE, "inputs", "town_development_2026-11-24.geojson")).to_crs(32617)
dv["geometry"] = fix(dv)
dv["submitted"], dv["action"] = ms(dv.Submittal_Date), ms(dv.Action_Date)

pp = gpd.read_file(sorted(glob.glob(os.path.join(HERE, "inputs", "public_parcels_*.geojson")))[-1]).to_crs(32617)
pp["geometry"] = fix(pp)
PUB = {k: v.geometry.union_all() for k, v in pp.groupby("owner_class")}
PUB_ALL = pp.geometry.union_all()


def public_share(geom):
    """Share of a shape inside parcels owned by public bodies, and who owns it."""
    if geom is None or geom.is_empty or geom.area == 0:
        return 0.0, ""
    tot = geom.intersection(PUB_ALL).area / geom.area
    by = sorted(((geom.intersection(g).area / geom.area, k) for k, g in PUB.items()), reverse=True)
    return tot, "; ".join(f"{k} {s:.0%}" for s, k in by if s >= 0.005)


# ------------------------------------------------------------------ case history, one answer per case
def history(earlier):
    """From the cases listed before a case on one piece of ground (newest first):
    prior     the conditional (CZ/CU) case immediately before it
    original  the conditional case in force at the start of 2022 (the newest one numbered before 2022);
              where there is none, the earliest conditional case numbered 2022 or later
    earliest  the oldest conditional case year anywhere in the list. On districts merged from many old
              ones this can belong to a corner of the ground, so it is reported but not used to classify."""
    cond = [(c, parse_case(c)[0]) for c in earlier if parse_case(c)[1] in ("CZ", "CU")]
    if not cond:
        return ("", None), ("", None), None
    pre = [x for x in cond if x[1] < 2022]
    return cond[0], (pre[0] if pre else min(reversed(cond), key=lambda x: x[1])), min(y for _, y in cond)


def classify(case_year, by_name, original_year):
    """entitlement type and how it was reached."""
    if not case_year or case_year < 2022:
        return OLD, "", ""
    by_chain = bool(original_year and original_year < 2022)
    if not (by_name or by_chain):
        return NEW, "", ""
    basis = "+".join(b for b, on in (("name", by_name), ("earlier case on the ground", by_chain)) if on)
    if original_year:
        return (APRE if original_year < 2022 else A22), basis, "earlier conditional case on the ground"
    return A22, basis, "name only: no earlier conditional case on this ground, so the case itself is the ground's first"


def ground(case):
    """The pieces of zoning-map ground a case covers, each with the cases that came before it there."""
    geom = rz.geometry[case] if case in rz.index else None
    segs = []
    for i in CURRENT.get(case, []):
        z = zn.loc[i]
        segs.append(dict(zrow=i, acres=z.ac, earlier=list(z.chain), how="current district"))
    for i in IN_CHAIN.get(case, []):                 # the case was later replaced here: what came before it is what follows it in the list
        z = zn.loc[i]
        a = z.geometry.intersection(geom).area / M2_AC if geom is not None else z.ac
        if a >= MIN_OVERLAP_AC:
            segs.append(dict(zrow=i, acres=a, earlier=z.chain[z.chain.index(case) + 1:], how=f"replaced by {z.case}"))
    if not segs and geom is not None:                # not on the zoning map (pending or denied): the ground's history is whatever is there now
        for i in zn.index[zn.intersects(geom)]:
            z = zn.loc[i]
            a = z.geometry.intersection(geom).area / M2_AC
            if a >= MIN_OVERLAP_AC:
                segs.append(dict(zrow=i, acres=a, earlier=([z.case] if z.case else []) + list(z.chain), how=f"not on map, over {z.case or 'unnumbered district'}"))
    return segs


_CI = {}


def case_info(case):
    """Everything known about one case number, from both layers. One answer per case: where its polygons carry
    different histories, the history covering the most acres is the case's."""
    if case in _CI:
        return _CI[case]
    yr, kind = parse_case(case)
    r = rz.loc[case] if case in rz.index else None
    segs = ground(case)
    cur = sorted((s for s in segs if s["how"] == "current district"), key=lambda s: -s["acres"])
    z = zn.loc[cur[0]["zrow"]] if cur else None
    name = (r.Name if r is not None else "") or (z.NAME if z is not None else "") or ""
    zname = "; ".join(sorted({str(zn.NAME[s["zrow"]] or "").strip() for s in cur} - {""}))
    by_name = bool(AMEND.search(str(name)) or AMEND.search(zname))
    groups = {}
    for s in segs:
        s["prior"], s["original"], s["earliest"] = history(s["earlier"])
        s["type_by_ground"] = classify(yr, by_name, s["original"][1])[0]
        groups[(s["prior"], s["original"])] = groups.get((s["prior"], s["original"]), 0) + s["acres"]
    tot = sum(s["acres"] for s in segs)
    (prior, orig), dom = max(groups.items(), key=lambda kv: kv[1]) if groups else ((("", None), ("", None)), 0)
    main = max((s for s in segs if (s["prior"], s["original"]) == (prior, orig)), key=lambda s: s["acres"]) if segs else None
    et, basis, obasis = classify(yr, by_name, orig[1])
    by_type = {}
    for s in segs:
        by_type[s["type_by_ground"]] = by_type.get(s["type_by_ground"], 0) + s["acres"]
    from_rz = r is not None and pd.notna(r.action)
    approved = r.action if from_rz else (z.approved if z is not None else pd.NaT)
    appr_basis = "" if pd.isna(approved) else "Rezoning layer action date" if from_rz else "zoning map date"
    status = r.Status if r is not None else "on zoning map"
    man = MANUAL.get(case, {})
    if "approved" in man:
        appr_basis = f"manual, Adam 2026-11-24 (Town layers: {approved.date() if pd.notna(approved) else 'no date'})"
        approved = pd.Timestamp(man["approved"])
    if "status" in man:
        status = f"{man['status']} (manual; Rezoning layer: {status})"
    info = dict(case=case, case_year=yr, kind=kind or "", name=str(name).strip(), zoning_name=zname,
                filed=(r.filed if r is not None else pd.NaT), filed_basis=("Rezoning layer" if r is not None and pd.notna(r.filed) else "case-number year only"),
                approved=approved, approved_basis=appr_basis, layer_status=status, on_zoning_map=z is not None,
                more_info=str((r.More_Info if r is not None else None) or (z.More_Info if z is not None else None) or "").replace("nan", ""),
                chain=" < ".join(main["earlier"]) if main else "", prior_case=prior[0], prior_case_year=prior[1],
                original_case=orig[0], original_year=orig[1], earliest_year=main["earliest"] if main else None,
                history_share=(dom / tot if tot else None), amend_by_name=by_name, etype=et, basis=basis, original_basis=obasis,
                segments=segs, n_pieces=len(segs), n_chains=len({" < ".join(s["earlier"]) for s in segs}),
                prior_varies=len({s["prior"] for s in segs}) > 1, original_varies=len({s["original"] for s in segs}) > 1,
                type_varies=len(by_type) > 1, ground_by_type="; ".join(f"{k} {v:.1f} ac" for k, v in sorted(by_type.items(), key=lambda kv: -kv[1])),
                approval_dates=sorted({str(zn.approved[s["zrow"]].date()) for s in cur if pd.notna(zn.approved[s["zrow"]])}))
    _CI[case] = info
    return info


BLANK = dict(case="", case_year=None, kind="", name="", zoning_name="", filed=pd.NaT, filed_basis="", approved=pd.NaT, approved_basis="", more_info="", layer_status="", on_zoning_map=False,
             chain="", prior_case="", prior_case_year=None, original_case="", original_year=None, earliest_year=None, history_share=None, amend_by_name=False,
             etype=OLD, basis="", original_basis="", segments=[], n_pieces=0, n_chains=0, prior_varies=False, original_varies=False, type_varies=False, ground_by_type="", approval_dates=[])

_CG = {}


def case_geom(case):
    """A case's boundary: the petition area where the Rezoning layer has the case, otherwise the districts the zoning map now labels with it."""
    if case not in _CG:
        if case in rz.index:
            _CG[case] = (rz.geometry[case], "Rezoning layer (petition area)")
        elif case in CURRENT:
            _CG[case] = (zn.geometry[CURRENT[case]].union_all(), "zoning map (districts now under this case)")
        else:
            _CG[case] = (None, "")
    return _CG[case]


_CP = {}


def case_public(case):
    if case not in _CP:
        share, who = public_share(case_geom(case)[0]) if case else (0.0, "")
        _CP[case] = (share >= PUBLIC_SHARE, share, who)
    return _CP[case]


def timing(q_start, q_end, info):
    """Where the first-detection quarter falls against the case's filing and approval dates."""
    yr, filed, appr = info["case_year"], info["filed"], info["approved"]
    if not yr:
        return "undated"
    filed_floor = filed if pd.notna(filed) else pd.Timestamp(yr, 1, 1)      # a case numbered 25xx was filed in 2025 at the earliest
    if q_end < filed_floor:
        return BEFORE_FILED
    if pd.notna(appr) and q_start > appr:
        return "cleared_after_approval"
    if pd.isna(appr) and pd.isna(filed):
        return "undated"
    return "cleared_between_filing_and_approval"                              # includes the same quarter as either date


# ------------------------------------------------------------------ parent projects of the amendment cases
CASES_2022 = sorted(set(zn.case[zn.case.map(lambda c: (parse_case(c)[0] or 0) >= 2022)]) | set(rz.case[((rz.Status == "Approved") | rz.case.map(lambda c: MANUAL.get(c, {}).get("status") == "Approved")) & (rz.filed >= "2022-01-01")]))


def main_district(rows):
    d = zn.loc[rows].groupby("DISTRICT").ac.sum()
    return d.idxmax() if len(d) else ""


def find_parent(case):
    """(original case, how it was found) for an amendment. The original is the plan being amended: the conditional case in force on the
    amendment's ground at the start of 2022, or the first 2022+ one. An amendment by name alone, on ground with no earlier conditional
    case, takes the parent of an adjoining district whose name starts with the same word (Veridea Expansion V -> Veridea)."""
    ci = case_info(case)
    if ci["original_case"]:
        return ci["original_case"], "earlier conditional case on the amendment's ground"
    geom, word = case_geom(case)[0], (ci["name"] or ci["zoning_name"]).upper().split(" ")[0]
    nb = zn[(zn.case != case) & (zn.case != "") & zn.NAME.fillna("").str.upper().str.startswith(word) & zn.intersects(geom.buffer(30))] if geom is not None and word else zn.iloc[:0]
    if not len(nb):
        return "", ""
    c = nb.loc[nb.ac.idxmax()].case
    return (case_info(c)["original_case"] or c), "adjoining district of the same name"


PARENT, CASE_PARENT, ZPARENT = {}, {}, {}        # original case -> project; amendment -> its parent and scope; zoning row -> project label
for case in CASES_2022:
    ci = case_info(case)
    if ci["etype"] not in (A22, APRE):
        continue
    orig, how = find_parent(case)
    if not orig:
        continue
    if orig not in PARENT:
        prow = sorted(set(CURRENT.get(orig, []) + IN_CHAIN.get(orig, [])))            # every district that carries the original case, now or earlier
        lineage, cur = [orig], orig
        while AMEND.search(case_info(cur)["name"] or case_info(cur)["zoning_name"] or "") and case_info(cur)["prior_case"] and case_info(cur)["prior_case"] not in lineage:
            cur = case_info(cur)["prior_case"]; lineage.append(cur)                   # the original is itself an amendment: go back to what it amended
        oname = (case_info(orig)["name"] or case_info(orig)["zoning_name"]).split(";")[0].strip()
        label = f"{PARENT_NAMES[orig]} ({' + '.join(reversed(lineage))})" if orig in PARENT_NAMES else " + ".join(reversed(lineage))
        PARENT[orig] = dict(label=label, lineage=" + ".join(reversed(lineage)), rows=prow, geom=zn.geometry[prow].union_all(), amendments=[], town_name=oname)
        for i in prow:
            ZPARENT.setdefault(i, label)
    par = PARENT[orig]
    pet = case_geom(case)[0]
    share = pet.area / par["geom"].area
    outside = pet.difference(par["geom"]).area / pet.area
    own = main_district(CURRENT.get(case, []))
    rest = main_district(CURRENT.get(orig, [])) or main_district([i for i in par["rows"] if zn.case[i] != case])       # the original's own district where it still has one
    district = "no other district of the parent to compare" if not own or not rest else "same" if own == rest else f"differs: {own} against {rest}"
    scope = EXPAND if outside >= EXPANSION_SHARE else CARVE if district.startswith("differs") else SAME
    CASE_PARENT[case] = dict(orig=orig, label=par["label"], how=how, share=share, outside_ac=pet.difference(par["geom"]).area / M2_AC, scope=scope, district=district)
    par["amendments"].append(case)


def report_timing(tm, cond_before):
    """Split 'before the case was filed' by whether a conditional case was already on the ground (conditional_case_year_before_clearing)."""
    if tm != BEFORE_FILED:
        return tm
    return {"yes": UNDER_EARLIER, "same year": SAME_YEAR}.get(cond_before, BEFORE_ANY)


# ------------------------------------------------------------------ 1. one governing case per clearing
zi = gpd.overlay(cl[["id", "geometry"]], zn[["case", "NAME", "DISTRICT", "geometry"]].reset_index(names="zrow"), how="intersection", keep_geom_type=True)
zi["ov"] = zi.area / M2_AC
zi = zi[zi.ov >= MIN_OVERLAP_AC]
ri = gpd.overlay(cl[["id", "geometry"]], rz[["case", "geometry"]].reset_index(drop=True), how="intersection", keep_geom_type=True)
ri["ov"] = ri.area / M2_AC
ri = ri[ri.ov >= MIN_OVERLAP_AC]
di = gpd.overlay(cl[["id", "geometry"]], dv[["Name", "Status", "submitted", "action", "geometry"]].reset_index(names="drow"), how="intersection", keep_geom_type=True)
di["ov"] = di.area / M2_AC
di = di[di.ov >= MIN_OVERLAP_AC]
KIND = {"CZ": "conditional zoning", "CU": "conditional use", "RZ": "general rezoning", "TRZ": "general rezoning", "ETJ": "ETJ zoning"}

rows, pairs = [], []
for c in cl.itertuples():
    z = zi[zi.id == c.id].sort_values("ov", ascending=False)
    rr = ri[ri.id == c.id].sort_values("ov", ascending=False)
    d = di[di.id == c.id]
    info, district, share, zname, here = BLANK, "", 0.0, "", []
    if len(z):
        top = z.iloc[0]
        district, share, zname, here = top.DISTRICT, top.ov / c.acres, str(top.NAME or "").strip(), list(zn.chain[top.zrow])
        if top.case:
            info = case_info(top.case)
    et = info["etype"]
    raw_tm = timing(c.q_start, c.q_end, info)
    kind = KIND.get(info["kind"], "none or base zoning")
    # the ground under this clearing: the history of the one district it sits in, which can differ from the case's main history
    g_prior, g_orig, _ = history(here)
    type_by_ground = classify(info["case_year"], info["amend_by_name"], g_orig[1])[0]
    # the first conditional approval known on this ground: the governing case itself, or the original one under it
    cond_years = [y for y in ([info["case_year"]] if info["kind"] in ("CZ", "CU") else []) + [g_orig[1]] if y]
    first_cond = min(cond_years) if cond_years else None
    prior_note = "" if not first_cond else ("yes" if first_cond < c.q_start.year else "same year" if first_cond == c.q_start.year else "no")
    tm = report_timing(raw_tm, prior_note)
    # development plan records, for context: the earliest approved plan on this ground
    ok = d[d.Status.isin(["Approved", "Under Construction"])]
    plan_first = ok.action.min() if len(ok) else pd.NaT
    plan_timing = "no approved plan record" if not len(ok) else "plan record undated" if pd.isna(plan_first) else "cleared_after_plan_approval" if c.q_start > plan_first else "plan approved in the same quarter" if c.q_end >= plan_first else "cleared_before_plan_approval"
    owners = "; ".join(p.strip() for p in cj.owners_by_share.get(c.id, "").split(";") if p.strip() and not p.strip().startswith("["))
    pub_case, pub_case_share, pub_case_who = case_public(info["case"])
    parent_label = ZPARENT.get(int(z.iloc[0].zrow), "") if len(z) else ""
    pub_share, pub_who = public_share(c.geometry)
    rows.append(dict(id=c.id, acres=round(c.acres, 2), first_quarter=c.first_quarter, status=c.status, est_trees=round(c.acres * FRAC * TPA),
                     entitlement_type=et, amendment_basis=info["basis"], timing=tm, governing_case_kind=kind, parent_project=parent_label,
                     first_conditional_case_year=first_cond or "", conditional_case_year_before_clearing=prior_note,
                     governing_case=info["case"], case_name=info["name"] or info["zoning_name"] or zname, district=district, share_of_clearing_in_case=round(min(share, 1.0), 2),
                     case_filed=info["filed"].date() if pd.notna(info["filed"]) else "", case_filed_basis=info["filed_basis"], case_approved=info["approved"].date() if pd.notna(info["approved"]) else "", case_approved_basis=info["approved_basis"],
                     prior_conditional_case=info["prior_case"], prior_conditional_case_year=info["prior_case_year"] or "",
                     original_conditional_case=info["original_case"], original_conditional_year=info["original_year"] or "", original_basis=info["original_basis"],
                     earliest_conditional_year_in_chain=info["earliest_year"] or "", case_chain_varies_by_polygon=info["n_chains"] > 1, earlier_cases_on_ground=" < ".join(here), type_by_ground=type_by_ground, ground_differs_from_case=type_by_ground != et,
                     public_owner_case=pub_case, public_share_of_case=round(pub_case_share, 2), public_owners_of_case=pub_case_who,
                     public_share_of_clearing=round(pub_share, 2), public_owners_of_clearing=pub_who,
                     other_zoning_cases="; ".join(f"{r.case} ({r.ov:.1f} ac)" for r in z.iloc[1:].itertuples() if r.case),
                     rezoning_layer_cases="; ".join(f"{r.case} {rz.Status[r.case]} ({r.ov:.1f} ac)" for r in rr.itertuples()),
                     plan_timing=plan_timing, first_approved_plan=plan_first.date() if pd.notna(plan_first) else "", plan_records="; ".join(sorted(set(d.Name.str.strip()))),
                     owners_orgs_only=owners, manual_identification=cj.manual_identification.get(c.id, ""), detected_in_leaf_off_quarter=bool(c.leaf_off),
                     conflict_flag=COI.get(info["case"], "")))
    # every (clearing, case) pair, for the before-filing list: zoning-map cases and Rezoning-layer cases
    seen = {}
    for r in z.itertuples():
        if r.case: seen[r.case] = max(seen.get(r.case, 0), r.ov)
    for r in rr.itertuples():
        seen[r.case] = max(seen.get(r.case, 0), r.ov)
    for case, ov in seen.items():
        ci = case_info(case)
        if not ci["case_year"]:
            continue
        pairs.append(dict(c=c, case=case, ov=ov, info=ci, tm=timing(c.q_start, c.q_end, ci), owners=owners))

T = pd.DataFrame(rows)
T.to_csv(os.path.join(OUT, "clearings_entitlement.csv"), index=False)
TH = T[T.conflict_flag == ""]                 # headline tables leave out clearings governed by a conflict-flagged case

# ------------------------------------------------------------------ 2. summary
ORDER_E = [NEW, A22, APRE, OLD]
ORDER_T = [BEFORE_ANY, SAME_YEAR, UNDER_EARLIER, "cleared_between_filing_and_approval", "cleared_after_approval", "undated"]


def tally(df, keys):
    g = df.groupby(keys).agg(clearings=("id", "size"), acres=("acres", "sum"))
    p = df[~df.public_owner_case].groupby(keys).agg(clearings_excl_public_owner_cases=("id", "size"), acres_excl_public_owner_cases=("acres", "sum"))
    g = g.join(p).fillna(0)
    g["est_trees"] = (g.acres * FRAC * TPA).round(-2).astype(int)
    g["clearings_excl_public_owner_cases"] = g.clearings_excl_public_owner_cases.astype(int)
    return g[["clearings", "acres", "est_trees", "clearings_excl_public_owner_cases", "acres_excl_public_owner_cases"]].round(1)


S = tally(TH, ["entitlement_type", "timing"]).reset_index()
S["entitlement_type"] = pd.Categorical(S.entitlement_type, ORDER_E, ordered=True); S["timing"] = pd.Categorical(S.timing, ORDER_T, ordered=True)
S = S.sort_values(["entitlement_type", "timing"])
S.to_csv(os.path.join(OUT, "summary_entitlement_x_timing.csv"), index=False)

# ------------------------------------------------------------------ 3. forest inside cases approved since 2022
with rasterio.open(os.path.join(REL, "baseline_forest_10m.tif")) as src:
    base = src.read(1); tf = src.transform; shape = base.shape
PX_AC = abs(tf.a * tf.e) / M2_AC
forest = base == 1; inside = base != 255
D = np.load(S2)
st_now, st_2022 = D[f"state_{CUR_Q}"], D["state_2022Q3"]          # 0 forest-like, 1 cleared-like, -1 no valid observation
assert st_now.shape == shape and (D["cand"] == (forest & (st_2022 == 0))).all(), "detect.npz does not match the release baseline grid"
cleared_px = features.rasterize([(g, 1) for g in cl.geometry], out_shape=shape, transform=tf, fill=0, dtype="uint8").astype(bool)
assert (cleared_px == D["kept"]).all(), "clearing outlines do not match the detection run in detect.npz"
late = cl[cl.q > pd.Period(CUR_Q, freq="Q")]
late_px = features.rasterize([(g, 1) for g in late.geometry], out_shape=shape, transform=tf, fill=0, dtype="uint8").astype(bool) if len(late) else np.zeros(shape, bool)
now_forest = forest & (st_now == 0)                              # baseline forest cells that pass the detection step's forest-like test in the latest leaf-on composite
PX = dict(baseline=forest, forestlike_2022=forest & (st_2022 == 0), cleared=forest & cleared_px, remaining=forest & ~cleared_px, current=now_forest,
          d_never=forest & ~cleared_px & (st_now == 1) & (st_2022 != 0),      # not forest-like in 2022Q3 either: partial-canopy and edge cells, not a loss
          d_lost=forest & ~cleared_px & (st_now == 1) & (st_2022 == 0),       # forest-like in 2022Q3, not now, outside the 1-acre outlines: small clearings, edges, thinning
          d_noobs=forest & ~cleared_px & (st_now == -1),                      # no valid observation in the composite
          d_standing=now_forest & cleared_px,                                 # inside an outline but still forest-like in the composite
          d_standing_late=now_forest & late_px)                               # ... of which inside an outline first detected after the composite


def measure(m):
    v = {k: (m & a).sum() * PX_AC for k, a in PX.items()}
    v["acres"] = (m & inside).sum() * PX_AC
    v["diff"] = v["remaining"] - v["current"]
    return v


def mask(geom):
    return features.rasterize([(geom, 1)], out_shape=shape, transform=tf, fill=0, dtype="uint8").astype(bool)


cases = {}
for case in CASES_2022:
    cases[case] = (case_info(case),) + case_geom(case)

for orig, par in PARENT.items():
    par["mask"] = mask(par["geom"]); par["v"] = measure(par["mask"])
P, masks = [], {}
for case, (info, geom, src_g) in cases.items():
    m = mask(geom); masks[case] = m
    v = measure(m)
    f, c = v["baseline"], v["cleared"]
    inter = cl[cl.intersects(geom)]
    outlined = inter.geometry.intersection(geom).area.sum() / M2_AC
    pub, pub_share, pub_who = case_public(case)
    cp = CASE_PARENT.get(case)
    pv = PARENT[cp["orig"]]["v"] if cp else None
    P.append(dict(case=case, name=info["name"] or info["zoning_name"], entitlement_type=info["etype"], amendment_basis=info["basis"],
                  parent_project=cp["label"] if cp else "", amendment_scope=cp["scope"] if cp else "", petition_share_of_parent=round(cp["share"], 2) if cp else "",
                  petition_acres_outside_parent=round(cp["outside_ac"], 1) if cp else "", district_against_parent=cp["district"] if cp else "", parent_found_by=cp["how"] if cp else "",
                  parent_acres=round(PARENT[cp["orig"]]["geom"].area / M2_AC, 1) if cp else "", parent_forest_acres_2022=round(pv["baseline"], 1) if cp else "", parent_forest_cleared_acres=round(pv["cleared"], 1) if cp else "",
                  parent_forest_remaining_acres=round(pv["remaining"], 1) if cp else "", parent_current_forest_acres=round(pv["current"], 1) if cp else "", layer_status=info["layer_status"], on_zoning_map=info["on_zoning_map"],
                  filed=info["filed"].date() if pd.notna(info["filed"]) else "", approved=info["approved"].date() if pd.notna(info["approved"]) else "", approved_basis=info["approved_basis"],
                  total_acres=round(geom.area / M2_AC, 1), acres_in_study_area=round(v["acres"], 1), baseline_forest_acres_2022=round(f, 1),
                  cleared_acres_outlined=round(outlined, 1), forest_cleared_acres=round(c, 1), forest_remaining_acres=round(v["remaining"], 1),
                  current_forest_acres=round(v["current"], 1), remaining_minus_current_acres=round(v["diff"], 1),
                  forestlike_2022Q3_acres=round(v["forestlike_2022"], 1), diff_not_forestlike_in_2022_either_acres=round(v["d_never"], 1), diff_lost_outside_outlines_acres=round(v["d_lost"], 1),
                  diff_no_observation_acres=round(v["d_noobs"], 1), diff_standing_inside_outlines_acres=round(v["d_standing"], 1), of_which_outlines_detected_after_composite_acres=round(v["d_standing_late"], 1),
                  share_of_forest_cleared=round(c / f, 2) if f > 0 else "", est_trees_remaining=int(round(v["remaining"] * TPA, -1)), est_trees_current=int(round(v["current"] * TPA, -1)),
                  clearings=len(inter[inter.geometry.intersection(geom).area / M2_AC >= MIN_OVERLAP_AC]),
                  prior_conditional_case=info["prior_case"], prior_conditional_case_year=info["prior_case_year"] or "", original_conditional_case=info["original_case"], original_conditional_year=info["original_year"] or "",
                  original_basis=info["original_basis"], earliest_conditional_year_in_chain=info["earliest_year"] or "", earlier_cases_on_ground=info["chain"],
                  share_of_case_ground_with_this_history=round(info["history_share"], 2) if info["history_share"] else "", chain_varies_by_polygon=info["n_chains"] > 1, type_varies_by_polygon=info["type_varies"], ground_by_type=info["ground_by_type"],
                  public_owner_case=pub, public_share_of_case=round(pub_share, 2), public_owners=pub_who,
                  boundary_from=src_g, town_case_file_url=info["more_info"], conflict_flag=COI.get(case, "")))
P = pd.DataFrame(P).sort_values("current_forest_acres", ascending=False)
P.to_csv(os.path.join(OUT, "pipeline_2022plus.csv"), index=False)


for orig, par in PARENT.items():
    masks["parent:" + orig] = par["mask"]
Tpar = T[T.conflict_flag == ""].groupby("parent_project").agg(n=("id", "size"), ac=("acres", "sum"))
PT = []
for orig, par in PARENT.items():
    v, am = par["v"], P[P.case.isin(par["amendments"])]
    pshare, pwho = public_share(par["geom"])
    PT.append(dict(parent_project=par["label"], original_case=orig, lineage=par["lineage"], town_name_for_original_case=par["town_name"], districts=len(par["rows"]), acres=round(par["geom"].area / M2_AC, 1), acres_in_study_area=round(v["acres"], 1),
                   baseline_forest_acres_2022=round(v["baseline"], 1), forest_cleared_acres=round(v["cleared"], 1), forest_remaining_acres=round(v["remaining"], 1), current_forest_acres=round(v["current"], 1),
                   remaining_minus_current_acres=round(v["diff"], 1), share_of_forest_cleared=round(v["cleared"] / v["baseline"], 2) if v["baseline"] > 0 else "", est_trees_current=int(round(v["current"] * TPA, -1)),
                   clearings_on_parent_ground=int(Tpar.n.get(par["label"], 0)), clearing_acres_on_parent_ground=round(float(Tpar.ac.get(par["label"], 0)), 1),
                   amendments_2022plus="; ".join(f"{r.case} {r.name} ({r.total_acres} ac, {r.petition_share_of_parent:.0%} of parent" + f", {r.amendment_scope})" for r in am.sort_values("case").itertuples()),
                   amendment_types="; ".join(sorted(set(am.entitlement_type))), sum_of_amendment_petition_forest_2022=round(am.baseline_forest_acres_2022.sum(), 1), sum_of_amendment_petition_current_forest=round(am.current_forest_acres.sum(), 1),
                   public_share_of_parent=round(pshare, 2), public_owners=pwho))
PT = pd.DataFrame(PT).sort_values("current_forest_acres", ascending=False)
PT.to_csv(os.path.join(OUT, "parent_projects.csv"), index=False)


def union_mask(keys):
    m = np.zeros(shape, bool)
    for k in keys: m |= masks[k]
    return m


# ------------------------------------------------------------------ 4. clearings first detected before an overlapping case was filed
Ti = T.set_index("id")
B = []
for p in pairs:
    if p["tm"] != BEFORE_FILED:
        continue
    c, ci = p["c"], p["info"]
    floor = ci["filed"] if pd.notna(ci["filed"]) else pd.Timestamp(ci["case_year"], 1, 1)
    nxt_end = (c.q + 1).end_time.normalize()
    B.append(dict(id=c.id, acres=round(c.acres, 2), overlap_acres=round(p["ov"], 2), first_quarter=c.first_quarter, timing=report_timing(BEFORE_FILED, Ti.conditional_case_year_before_clearing[c.id]), case=p["case"], case_name=ci["name"] or ci["zoning_name"], case_status=ci["layer_status"],
                  filing_date=ci["filed"].date() if pd.notna(ci["filed"]) else f'{ci["case_year"]} (year only)', approval_date=ci["approved"].date() if pd.notna(ci["approved"]) else "",
                  months_before_filing=round((floor - c.q_end).days / 30.44, 1), holds_if_detection_ran_a_quarter_early=bool((not c.leaf_off) or nxt_end < floor),
                  case_type=ci["etype"], amendment_basis=ci["basis"], prior_conditional_case=ci["prior_case"], prior_conditional_case_year=ci["prior_case_year"] or "",
                  original_conditional_case=ci["original_case"], original_conditional_year=ci["original_year"] or "", public_owner_case=case_public(p["case"])[0],
                  governing_case_of_clearing=Ti.governing_case[c.id], first_conditional_case_year_on_ground=Ti.first_conditional_case_year[c.id],
                  conditional_case_year_before_clearing=Ti.conditional_case_year_before_clearing[c.id], plan_timing=Ti.plan_timing[c.id], first_approved_plan=Ti.first_approved_plan[c.id],
                  current_owner_orgs_only=p["owners"], manual_identification=cj.manual_identification.get(c.id, ""), conflict_flag=COI.get(p["case"], "")))
B = pd.DataFrame(B).sort_values(["case", "first_quarter", "id"])
B.to_csv(os.path.join(OUT, "cleared_before_filing.csv"), index=False)

# ------------------------------------------------------------------ 5. chain audit: every case, every piece of ground
G, V = [], []
for case in sorted(set(CURRENT) | set(rz.index)):
    ci = case_info(case)
    for s in sorted(ci["segments"], key=lambda s: -s["acres"]):
        z = zn.loc[s["zrow"]]
        G.append(dict(case=case, case_name=ci["name"] or ci["zoning_name"], zoning_objectid=int(z.OBJECTID_1), district_name=str(z.NAME or "").strip(), district=z.DISTRICT, acres=round(s["acres"], 1), how=s["how"],
                      earlier_cases_on_this_piece=" < ".join(s["earlier"]), prior_conditional_case=s["prior"][0], original_conditional_case=s["original"][0], original_conditional_year=s["original"][1] or "",
                      earliest_conditional_year_in_chain=s["earliest"] or "", type_by_ground=s["type_by_ground"], case_type=ci["etype"]))
    if ci["n_chains"] > 1:
        tot = sum(s["acres"] for s in ci["segments"])
        V.append(dict(case=case, case_name=ci["name"] or ci["zoning_name"], case_year=ci["case_year"] or "", pieces=ci["n_pieces"], acres=round(tot, 1), distinct_chains=ci["n_chains"],
                      prior_case_varies=ci["prior_varies"], original_case_varies=ci["original_varies"], type_varies=ci["type_varies"], case_type=ci["etype"],
                      prior_conditional_case=ci["prior_case"], original_conditional_case=ci["original_case"], original_conditional_year=ci["original_year"] or "", share_of_ground_with_this_history=round(ci["history_share"], 2),
                      ground_by_type=ci["ground_by_type"], governs_clearings=int((T.governing_case == case).sum()), in_2022plus_table=case in cases))
G = pd.DataFrame(G); G.to_csv(os.path.join(OUT, "case_ground_history.csv"), index=False)
V = pd.DataFrame(V).sort_values(["type_varies", "original_case_varies", "prior_case_varies", "acres"], ascending=False); V.to_csv(os.path.join(OUT, "chain_varies_by_polygon.csv"), index=False)

A = []
asay = A.append
asay("Chain audit. For each case: every piece of zoning-map ground it covers, the cases the map lists before it there (BACK1.., newest first),")
asay("and what each piece alone would give. 'current district' = a district now labelled with the case; 'replaced by X' = ground where a later case X now sits.")
asay("The first version read these two ways. The clearing table took the district under each clearing: prior = the first conditional case in its list,")
asay("original = the OLDEST conditional case number anywhere in its list. The 2022+ table took the first polygon of the case in file order, whatever its size.")
asay("Now: one answer per case, from the history covering the most acres. original = the conditional case in force at the start of 2022")
asay("(the newest one numbered before 2022), or the earliest 2022+ conditional case where there is none.\n")
for case in ["25CZ18", "26CZ03", "26CZ10", "23CZ03", "09CZ07"]:
    ci = case_info(case)
    asay(f"{case}  {ci['name'] or ci['zoning_name'] or '(no name: not a current district, not in the Rezoning layer)'}")
    for s in sorted(ci["segments"], key=lambda s: -s["acres"]):
        z = zn.loc[s["zrow"]]
        asay(f"   OBJECTID {int(z.OBJECTID_1)}  {s['acres']:7.1f} ac  {s['how']:19s} {str(z.NAME or '').strip():17s} BACK: {' < '.join(s['earlier']) or '(none)'}")
        asay(f"   {'':45s}-> prior {s['prior'][0] or 'none'}, original {s['original'][0] or 'none'} ({s['original'][1] or '-'}), earliest in list {s['earliest'] or '-'}, type by this piece: {s['type_by_ground']}")
    if case in CURRENT:
        f0 = zn.loc[CURRENT[case][0]]
        p0, o0, e0 = history(f0.chain)
        asay(f"   first polygon in file order (what the old pipeline table read): OBJECTID {int(f0.OBJECTID_1)}, {f0.ac:.1f} ac -> prior {p0[0] or 'none'} ({p0[1] or '-'}), earliest {e0 or '-'}")
    asay(f"   PER CASE NOW: prior {ci['prior_case'] or 'none'} ({ci['prior_case_year'] or '-'}), original {ci['original_case'] or 'none'} ({ci['original_year'] or '-'}), "
         f"on {ci['history_share']:.0%} of its ground; earliest conditional year in that list {ci['earliest_year'] or '-'}; type {ci['etype']}" + (f" ({ci['original_basis']})" if ci["original_basis"].startswith("name only") else "") + "\n")
asay(f"Cases whose pieces carry different chains: {len(V)} of {len(set(CURRENT) | set(rz.index))} cases ({int(V.prior_case_varies.sum())} where the prior conditional case differs, "
     f"{int(V.original_case_varies.sum())} where the original differs, {int(V.type_varies.sum())} where the type would differ). Full list: chain_varies_by_polygon.csv.")
asay("\nThose numbered 2022 or later, or governing a clearing:")
asay(V[(V.case_year.map(lambda y: (y or 0) >= 2022)) | (V.governs_clearings > 0)][["case", "case_name", "pieces", "acres", "distinct_chains", "prior_case_varies", "original_case_varies", "type_varies", "prior_conditional_case", "original_conditional_case", "share_of_ground_with_this_history", "governs_clearings", "ground_by_type"]].to_string(index=False))
multi_date = [(c, case_info(c)["approval_dates"]) for c in sorted(CURRENT) if len(case_info(c)["approval_dates"]) > 1]
asay(f"\nCases whose districts carry more than one approval date on the zoning map: {len(multi_date)}" + ("" if not multi_date else " (the largest district's date is used unless the Rezoning layer has an action date): " + "; ".join(f"{c} {d}" for c, d in multi_date)))
open(os.path.join(OUT, "chain_audit.txt"), "w").write("\n".join(A) + "\n")

# ------------------------------------------------------------------ 6. plan records under C014 and the Veridea clearings detected before plan approval
PC = os.path.join(OUT, "plan_check"); os.makedirs(PC, exist_ok=True)
pick = T[(T.id == "C014") | (T.case_name.str.contains("veridea", case=False) & (T.plan_timing == "cleared_before_plan_approval"))].id.tolist()
APPROVED = ["Approved", "Under Construction"]
R, CV = [], []
for cid in pick:
    c = cl[cl.id == cid].iloc[0]
    d = di[di.id == cid].sort_values("ov", ascending=False)
    for r in d.itertuples():
        v = dv.loc[r.drow]
        when = "undated" if pd.isna(v.action) else "before the quarter" if v.action < c.q_start else "in the quarter" if v.action <= c.q_end else "after the quarter"
        R.append(dict(clearing_id=cid, clearing_acres=round(c.acres, 2), first_quarter=c.first_quarter, governing_case=Ti.governing_case[cid], plan_timing=Ti.plan_timing[cid],
                      plan_layer_fid=int(v.FID), plan_document_id=("" if pd.isna(v.Id) or not v.Id else int(v.Id)), plan_name=str(v.Name).strip(), plan_type=v.Type, plan_status=v.Status,
                      counts_as_approved=v.Status in APPROVED, plan_submitted=v.submitted.date() if pd.notna(v.submitted) else "", plan_action_date=v.action.date() if pd.notna(v.action) else "",
                      plan_action_taken=v.Action_Taken if isinstance(v.Action_Taken, str) else "", action_date_vs_clearing_quarter=when, plan_total_acres=round(v.geometry.area / M2_AC, 1),
                      overlap_acres=round(r.ov, 2), share_of_clearing_inside_plan=round(min(r.ov / c.acres, 1), 2), plan_url=v.More_Info if isinstance(v.More_Info, str) else ""))

    def cover(rows):
        return shapely.union_all(rows.geometry.values).area / c.geometry.area if len(rows) else 0.0

    ok = d[d.Status.isin(APPROVED)]
    CV.append(dict(clearing_id=cid, acres=round(c.acres, 2), first_quarter=c.first_quarter, governing_case=Ti.governing_case[cid], plan_timing=Ti.plan_timing[cid],
                   plan_records=len(d), approved_or_under_construction=len(ok), share_inside_any_record=round(cover(d), 2), share_inside_approved_record=round(cover(ok), 2),
                   share_inside_record_approved_before_quarter=round(cover(ok[ok.action < c.q_start]), 2), share_inside_record_approved_by_quarter_end=round(cover(ok[ok.action <= c.q_end]), 2),
                   share_inside_approved_record_with_no_date=round(cover(ok[ok.action.isna()]), 2), acres_outside_every_approved_record=round(c.acres * (1 - min(cover(ok), 1)), 2)))
R = pd.DataFrame(R); R.to_csv(os.path.join(PC, "plan_records.csv"), index=False)
CV = pd.DataFrame(CV); CV.to_csv(os.path.join(PC, "plan_coverage_by_clearing.csv"), index=False)


def kml_geom(g):
    ring = lambda r: " ".join(f"{x:.6f},{y:.6f},0" for x, y in r.coords)
    polys = list(g.geoms) if g.geom_type == "MultiPolygon" else [g]
    return "<MultiGeometry>" + "".join(
        f"<Polygon><outerBoundaryIs><LinearRing><coordinates>{ring(q.exterior)}</coordinates></LinearRing></outerBoundaryIs>"
        + "".join(f"<innerBoundaryIs><LinearRing><coordinates>{ring(i)}</coordinates></LinearRing></innerBoundaryIs>" for i in q.interiors) + "</Polygon>" for q in polys) + "</MultiGeometry>"


def placemark(name, desc, style, g):
    return f"<Placemark><name>{escape(name)}</name><description><![CDATA[{desc}]]></description><styleUrl>#{style}</styleUrl>{kml_geom(g)}</Placemark>"


COLORS = ["ffff9900", "ff00aa00", "ffff00ff", "ff00ccff", "ffaa5500", "ff9900ff", "ff66ff00", "ffffcc66", "ff0066ff", "ff999999"]     # aabbggrr
cl84, dv84 = cl.set_index("id").geometry.to_crs(4326), dv.geometry.to_crs(4326)
K = ['<?xml version="1.0" encoding="UTF-8"?>', '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>', f"<name>Plan check: C014 and Veridea clearings detected before plan approval ({PULLED} Town layers)</name>",
     '<Style id="clearing"><LineStyle><color>ff0000ff</color><width>2</width></LineStyle><PolyStyle><color>660000ff</color></PolyStyle></Style>']
K += [f'<Style id="plan{i}"><LineStyle><color>{col}</color><width>3</width></LineStyle><PolyStyle><fill>0</fill></PolyStyle></Style>' for i, col in enumerate(COLORS)]
K.append(f"<Folder><name>Clearings ({len(pick)})</name>")
for cid in pick:
    v = CV[CV.clearing_id == cid].iloc[0]
    K.append(placemark(f"{cid} {v.acres} ac, first detected {v.first_quarter}", f"Governing case {v.governing_case}. {v.plan_timing}.<br>Share inside an approved or under-construction plan record: {v.share_inside_approved_record:.0%}; "
                       f"inside one approved before the quarter began: {v.share_inside_record_approved_before_quarter:.0%}.", "clearing", cl84[cid]))
K.append("</Folder>")
for title, sel in (("Approved or under-construction plan records", R.counts_as_approved), ("Other plan records on the same ground (proposed or under study)", ~R.counts_as_approved)):
    recs = R[sel].drop_duplicates("plan_layer_fid").sort_values("plan_name")
    K.append(f"<Folder><name>{title} ({len(recs)})</name>")
    for n, r in enumerate(recs.itertuples()):
        on = R[R.plan_layer_fid == r.plan_layer_fid]
        K.append(placemark(f"{r.plan_name} ({r.plan_status}, {r.plan_action_date or 'no action date'})",
                           f"Layer FID {r.plan_layer_fid}; DocumentCenter id {r.plan_document_id or 'none'}; {r.plan_type}; {r.plan_status}; submitted {r.plan_submitted or 'not given'}; action {r.plan_action_taken or 'not given'} {r.plan_action_date or ''}; "
                           f"{r.plan_total_acres} ac.<br>Clearings on it: " + ", ".join(f"{x.clearing_id} ({x.overlap_acres} ac)" for x in on.itertuples()) + (f'<br><a href="{r.plan_url}">{r.plan_url}</a>' if r.plan_url else ""),
                           f"plan{n % len(COLORS)}", dv84[dv.index[dv.FID == r.plan_layer_fid][0]]))
    K.append("</Folder>")
K.append("</Document></kml>")
open(os.path.join(PC, "plan_check.kml"), "w").write("\n".join(K) + "\n")

# ------------------------------------------------------------------ 7. review list
RV = P[(P.conflict_flag == "") & (~P.public_owner_case) & (P.current_forest_acres >= REVIEW_MIN_AC)].sort_values("current_forest_acres", ascending=False)
shared = {a: "; ".join(f"{b} ({ac:.1f} ac)" for ac, b in sorted((((masks[a] & masks[b]).sum() * PX_AC, b) for b in masks if b != a), reverse=True) if ac >= 1) for a in RV.case}
RV = RV.assign(ground_shared_with=RV.case.map(shared))[["case", "name", "entitlement_type", "parent_project", "amendment_scope", "parent_acres", "parent_current_forest_acres", "layer_status", "filed", "approved", "approved_basis", "total_acres", "baseline_forest_acres_2022", "forest_cleared_acres",
                                                         "current_forest_acres", "est_trees_current", "public_share_of_case", "ground_shared_with", "boundary_from", "town_case_file_url"]]
for col in ["rca_required_ac", "buffer_floodplain_ac", "limits_of_disturbance_ac", "source_doc_url", "reviewer", "notes"]:
    RV[col] = ""
RV.to_csv(os.path.join(OUT, "review_list.csv"), index=False)

# ------------------------------------------------------------------ 8. freshness: every 25CZ and 26CZ case in either layer
is_recent = lambda c: bool(re.match(r"^2[56]CZ\d", c))
recent = sorted({c for c in list(rz.index) + list(CURRENT) + list(IN_CHAIN) if is_recent(c)})
F = []
for case in recent:
    ci = case_info(case)
    r = rz.loc[case] if case in rz.index else None
    cur, old = CURRENT.get(case, []), IN_CHAIN.get(case, [])
    zdates = sorted({str(zn.approved[i].date()) for i in cur if pd.notna(zn.approved[i])})
    src = " and ".join(x for x, on in (("Rezoning layer", r is not None), ("zoning map", bool(cur)), ("zoning map, only as an earlier case", bool(old) and not cur)) if on)
    notes = []
    if r is not None and r.Status == "Proposed" and cur:
        notes.append("Rezoning layer says Proposed but the zoning map shows it adopted")
    if r is not None and r.Status == "Approved" and not cur and not old:
        notes.append("Approved in the Rezoning layer but not on the zoning map")
    if r is None:
        notes.append("not in the Rezoning layer: no filing date")
    if r is not None and pd.notna(r.action) and zdates and str(r.action.date()) not in zdates:
        notes.append(f"dates differ: Rezoning layer {r.action.date()}, zoning map {', '.join(zdates)}")
    if case in MANUAL:
        notes.append("manual value from Adam 2026-11-24: " + ", ".join(f"{k} {v}" for k, v in MANUAL[case].items()))
    if case in COI:
        notes.append("conflict flag")
    F.append(dict(case=case, name=ci["name"] or ci["zoning_name"], source=src, rezoning_layer_status=(r.Status if r is not None else ""), filed=(r.filed.date() if r is not None and pd.notna(r.filed) else ""),
                  rezoning_layer_action=(r.Action_Taken if r is not None and isinstance(r.Action_Taken, str) else ""), rezoning_layer_action_date=(r.action.date() if r is not None and pd.notna(r.action) else ""),
                  zoning_map_date="; ".join(zdates), zoning_map_acres=(round(sum(zn.ac[i] for i in cur), 1) if cur else ""), replaced_on_map_by="; ".join(sorted({zn.case[i] for i in old})),
                  status_used=ci["layer_status"], approval_date_used=(ci["approved"].date() if pd.notna(ci["approved"]) else ""), approval_date_basis=ci["approved_basis"], check=". ".join(notes), layers_pulled=PULLED, town_case_file_url=ci["more_info"]))
for yy in ("25", "26"):
    nums = [int(re.match(r"^\d\dCZ(\d+)", c).group(1)) for c in recent if c.startswith(yy)]
    for n in range(1, max(nums) + 1):
        if n not in nums:
            F.append(dict(case=f"{yy}CZ{n:02d}", source="in neither layer", check="number skipped in both layers: withdrawn, denied before mapping, or never posted", layers_pulled=PULLED))
F = pd.DataFrame(F).fillna("").sort_values("case"); F.to_csv(os.path.join(OUT, "freshness_25CZ_26CZ.csv"), index=False)

# ------------------------------------------------------------------ report
L = []
say = L.append
say(f"Clearings: {len(T)}, {T.acres.sum():.1f} acres, est. {T.acres.sum() * FRAC * TPA:,.0f} trees (acres x {FRAC} x {TPA}).")
say(f"Conflict flag: {', '.join(COI)} stays in every table, flagged. Headline tables and totals below leave it out: {len(T) - len(TH)} clearings ({T.acres.sum() - TH.acres.sum():.1f} ac) are governed by it.")
say(f"Public-owner case: public bodies own at least {PUBLIC_SHARE:.0%} of the case area (current county parcel records).")
say("\n1-2. Entitlement type x timing (each clearing counted once, under the zoning-map case covering most of it)")
say(S.to_string(index=False))
say("\n   by entitlement type:")
say(tally(TH, "entitlement_type").reindex(ORDER_E).to_string())
since = TH[TH.entitlement_type.isin([NEW, A22])]; np_ = since[~since.public_owner_case]
say(f"\n   entitled since 2022 (new + amendment of a 2022+ original): {len(since)} clearings, {since.acres.sum():.1f} ac; without public-owner cases {len(np_)}, {np_.acres.sum():.1f} ac")
say(f"   all clearings: {len(TH)}, {TH.acres.sum():.1f} ac; without public-owner cases {(~TH.public_owner_case).sum()}, {TH.acres[~TH.public_owner_case].sum():.1f} ac")
priv = TH[~TH.public_owner_case & (TH.public_share_of_clearing < PUBLIC_SHARE)]
say(f"   also leaving out clearings that are themselves at least {PUBLIC_SHARE:.0%} on public parcels: {len(priv)}, {priv.acres.sum():.1f} ac")
say("\n   clearings under public-owner cases:")
say(TH[TH.public_owner_case].groupby(["governing_case", "case_name", "entitlement_type", "public_owners_of_case"]).agg(clearings=("id", "size"), acres=("acres", "sum")).round(1).sort_values("acres", ascending=False).to_string())
onpub = TH[TH.public_share_of_clearing >= PUBLIC_SHARE]
say(f"   clearings at least {PUBLIC_SHARE:.0%} on public parcels, whatever the case: {len(onpub)} ({onpub.acres.sum():.1f} ac); {len(onpub[~onpub.public_owner_case])} of them ({onpub.acres[~onpub.public_owner_case].sum():.1f} ac) are under a case that is not public-owner: " + "; ".join(f"{r.id} {r.acres} ac, {r.governing_case} {r.case_name}, {r.public_owners_of_clearing}" for r in onpub[~onpub.public_owner_case].itertuples()))
re22 = TH[(TH.entitlement_type == NEW) & (TH.prior_conditional_case != "")]
say(f"\n   new_rezoning_2022plus clearings whose case sits on ground with an earlier conditional case also numbered 2022+ (name does not say amendment, so they stay 'new'): {len(re22)} ({re22.acres.sum():.1f} ac)")
say("   " + "; ".join(f"{k[0]} over {k[1]}: {len(v)} ({v.acres.sum():.1f} ac)" for k, v in re22.groupby(["governing_case", "prior_conditional_case"])))
dif = TH[TH.ground_differs_from_case]
say(f"   clearings on a district whose own chain would give a different type than the case's: {len(dif)} ({dif.acres.sum():.1f} ac)" + ("" if not len(dif) else ": " + "; ".join(f"{r.id} {r.governing_case} {r.entitlement_type} vs {r.type_by_ground}" for r in dif.itertuples())))
say("\n   pre2022_or_none, by the kind of case governing the ground:")
say(TH[TH.entitlement_type == OLD].groupby("governing_case_kind").agg(clearings=("id", "size"), acres=("acres", "sum")).round(1).to_string())
cond = TH[TH.governing_case_kind.isin(["conditional zoning", "conditional use"])]
say(f"\n   clearings whose ground is under a conditional zoning or conditional use case of any year: {len(cond)} of {len(TH)}, {cond.acres.sum():.1f} of {TH.acres.sum():.1f} acres ({cond.acres.sum() / TH.acres.sum():.1%})")
rel_none = TH[TH.id.isin(cj.index[(cj.rezoning_cases == "") & (cj.development_cases == "") & (cj.residential_phases == "")])]
say(f"   of the release's {len(rel_none)} 'no case' clearings ({rel_none.acres.sum():.1f} ac): " + "; ".join(f"{k}: {len(v)} ({v.acres.sum():.1f} ac)" for k, v in rel_none.groupby("governing_case_kind")))
say("\n   amendments x timing, split by whether a conditional approval already existed before the clearing year:")
say(TH[TH.entitlement_type.isin([A22, APRE])].groupby(["entitlement_type", "timing", "conditional_case_year_before_clearing"]).agg(clearings=("id", "size"), acres=("acres", "sum")).round(1).to_string())
low = TH[TH.share_of_clearing_in_case < 0.5]
say(f"\n   clearings where the governing case covers under half the clearing: {len(low)} ({low.acres.sum():.1f} ac)")
say("\n   amendments, by how they were identified:")
say(TH[TH.entitlement_type.isin([A22, APRE])].groupby(["entitlement_type", "amendment_basis"]).agg(clearings=("id", "size"), acres=("acres", "sum")).round(1).to_string())
say("\n   same table, against development plan records instead of the zoning case:")
say(TH.groupby(["entitlement_type", "plan_timing"]).agg(clearings=("id", "size"), acres=("acres", "sum")).round(1).reindex(ORDER_E, level=0).to_string())
say("\n   largest governing cases:")
say(TH.groupby(["governing_case", "case_name", "entitlement_type", "original_conditional_case"]).agg(clearings=("id", "size"), acres=("acres", "sum")).round(1).sort_values("acres", ascending=False).head(14).to_string())

say(f"\n3. Cases approved and numbered 2022 or later: {len(P)} ({(P.boundary_from.str.startswith('Rez')).sum()} with a petition boundary and filing date in the Rezoning layer, {(~P.boundary_from.str.startswith('Rez')).sum()} from the zoning map only)")
say(f"   current_forest = 2022 baseline forest cells that are still forest-like in the {CUR_Q} composite (the detection step's own test).")
say("   forest_remaining = the earlier measure: 2022 baseline forest outside clearing outlines of an acre or more. diff = remaining - current.")
say(P[["case", "name", "entitlement_type", "original_conditional_case", "approved", "total_acres", "baseline_forest_acres_2022", "forest_cleared_acres", "forest_remaining_acres", "current_forest_acres", "remaining_minus_current_acres", "est_trees_current", "public_owner_case", "conflict_flag"]]
    .rename(columns={"entitlement_type": "type", "original_conditional_case": "original", "baseline_forest_acres_2022": "forest_2022", "forest_cleared_acres": "cleared", "forest_remaining_acres": "remaining", "current_forest_acres": "current", "remaining_minus_current_acres": "diff", "est_trees_current": "trees_current", "public_owner_case": "public", "conflict_flag": "conflict"})
    .head(30).assign(conflict=lambda d: d.conflict.str[:7]).to_string(index=False))
head = P[P.conflict_flag == ""]
nopub = head[~head.public_owner_case]
pub_ground = union_mask(list(head.case[head.public_owner_case]))      # another case can sit on a public-owner case's ground (24CZ20 over 24CZ08), so the ground comes out too


def uline(label, keys, drop=None):
    v = measure(union_mask(keys) if drop is None else union_mask(keys) & ~drop)
    return (f"   {label:58s} {len(keys):3d} cases {v['acres']:6,.0f} ac | forest 2022 {v['baseline']:6,.0f} | cleared {v['cleared']:4,.0f} | remaining {v['remaining']:6,.0f} | "
            f"current {v['current']:6,.0f} | diff {v['diff']:4,.0f} | est. {v['current'] * TPA:8,.0f} trees"), v


say(f"\n   Union totals: each piece of ground counted once within a line. Headline lines leave out {', '.join(COI)}.")
GROUPS = [("all cases", None), ("new_rezoning_2022plus", [NEW]), ("amendment_of_2022plus_original", [A22]), ("amendment_of_pre2022_original", [APRE]), ("entitled since 2022 (new + amendment of 2022+ original)", [NEW, A22])]
for tag, df, drop in (("with public-owner cases", head, None), ("without public-owner cases, and without the ground they cover", nopub, pub_ground)):
    say(f"   -- {tag}")
    for label, types in GROUPS:
        say(uline(label, list(df.case if types is None else df.case[df.entitlement_type.isin(types)]), drop)[0])
say("\n   Amendments at their parent project's full boundary instead of the petition area (parent_projects.csv):")
for tag, df, drop in (("with public-owner cases", head, None), ("without public-owner cases, and without the ground they cover", nopub, pub_ground)):
    say(f"   -- {tag}")
    am = df[df.parent_project != ""]
    origs = sorted({CASE_PARENT[c]["orig"] for c in am.case})
    for label, sel in (("parent projects whose original is pre-2022", lambda o: parse_case(o)[0] < 2022), ("parent projects whose original is 2022 or later", lambda o: parse_case(o)[0] >= 2022)):
        say(uline(label, ["parent:" + o for o in origs if sel(o)], drop)[0].replace(" cases ", " parents"))
    grow = list(am.case[am.amendment_scope == EXPAND])                     # an expansion's own ground is outside its parent, so it stays in
    say(uline("expansions onto new ground (their petition areas)", grow, drop)[0])
    keys = list(df.case[df.parent_project == ""]) + ["parent:" + o for o in origs] + grow
    say(uline("all cases, amendments counted at the parent boundary", keys, drop)[0].replace(" cases ", " areas "))
say("\n   Parent projects (forest measured on the whole original boundary):")
say(PT[["parent_project", "acres", "baseline_forest_acres_2022", "forest_cleared_acres", "forest_remaining_acres", "current_forest_acres", "clearings_on_parent_ground", "clearing_acres_on_parent_ground", "sum_of_amendment_petition_current_forest"]]
    .rename(columns={"baseline_forest_acres_2022": "forest_2022", "forest_cleared_acres": "cleared", "forest_remaining_acres": "remaining", "current_forest_acres": "current", "clearings_on_parent_ground": "clearings",
                     "clearing_acres_on_parent_ground": "clearing_ac", "sum_of_amendment_petition_current_forest": "current_by_petitions"}).to_string(index=False))
say("\n   Each amendment against its parent:")
say(P[P.parent_project != ""].sort_values(["parent_project", "case"])[["case", "name", "parent_project", "total_acres", "parent_acres", "petition_share_of_parent", "petition_acres_outside_parent", "amendment_scope", "district_against_parent", "parent_found_by"]]
    .rename(columns={"total_acres": "petition_ac", "parent_acres": "parent_ac", "petition_share_of_parent": "share", "petition_acres_outside_parent": "outside_ac", "amendment_scope": "scope", "district_against_parent": "district", "parent_found_by": "found_by"})
    .assign(name=lambda d: d.name.str[:30], found_by=lambda d: d.found_by.str[:24]).to_string(index=False))
for lab in (CARVE, EXPAND, SAME):
    g = P[P.amendment_scope == lab]
    say(f"   {lab}: {len(g)}: " + ", ".join(f"{r.case} ({r.petition_share_of_parent:.0%} of parent)" for r in g.itertuples()))
say("   'same district' with nothing to compare against (the amendment covers every district of its parent): " + (", ".join(P.case[P.district_against_parent.str.startswith("no other")]) or "none"))
noparent = P[P.entitlement_type.isin([A22, APRE]) & (P.parent_project == "")]
say("   amendments with no parent found: " + (", ".join(noparent.case) if len(noparent) else "none"))
say("   -- for reference")
say(uline(f"all cases including {', '.join(COI)}", list(P.case))[0])
say(uline("public-owner cases only", list(head.case[head.public_owner_case]))[0])
v = measure(union_mask(list(head.case)) & features.rasterize([(PUB_ALL, 1)], out_shape=shape, transform=tf, fill=0, dtype="uint8").astype(bool))
say(f"   {'ground on public parcels inside any case (parcel-based)':58s}           {v['acres']:6,.0f} ac | forest 2022 {v['baseline']:6,.0f} | cleared {v['cleared']:4,.0f} | remaining {v['remaining']:6,.0f} | current {v['current']:6,.0f}")
say("\n   The three types overlap on the ground (a later case can sit on top of an earlier one), so their lines add up to more than 'all cases'.")
say("   Counted once, giving shared ground to the first type in this order: new, amendment of 2022+ original, amendment of pre-2022 original:")
for tag, df, drop in (("with public-owner cases", head, None), ("without public-owner cases", nopub, pub_ground)):
    taken = np.zeros(shape, bool) if drop is None else drop.copy(); parts = []
    for label, types in GROUPS[1:4]:
        m = union_mask(list(df.case[df.entitlement_type.isin(types)])) & ~taken
        taken |= m; v = measure(m)
        parts.append(f"{label}: forest 2022 {v['baseline']:,.0f}, cleared {v['cleared']:,.0f}, remaining {v['remaining']:,.0f}, current {v['current']:,.0f}")
    say(f"   -- {tag}: " + " | ".join(parts))
_, v = uline("", list(head.case))
say(f"\n   Why remaining and current differ (all cases, without {', '.join(COI)}): remaining {v['remaining']:,.0f} - current {v['current']:,.0f} = {v['diff']:,.0f} ac")
say(f"      + {v['d_never']:6,.0f} ac  baseline cells outside outlines that fail the forest-like test now and also failed it in 2022Q3 (partial-canopy and edge cells: not a loss, the test never counted them)")
say(f"      + {v['d_lost']:6,.0f} ac  forest-like in 2022Q3, not now, outside the 1-acre outlines (clearings under an acre, edges, thinning)")
say(f"      + {v['d_noobs']:6,.0f} ac  no valid observation in the {CUR_Q} composite")
say(f"      - {v['d_standing']:6,.0f} ac  inside an outline but still forest-like in {CUR_Q}; {v['d_standing_late']:,.0f} ac of it is in outlines first detected after {CUR_Q} (provisional), so that much of 'current' has since been cut")
say(f"      like for like under the same test: forest-like in 2022Q3 {v['forestlike_2022']:,.0f} ac -> forest-like in {CUR_Q} {v['current']:,.0f} ac")
say(f"      current forest less the outlines first detected after {CUR_Q}: {v['current'] - v['d_standing_late']:,.0f} ac (est. {(v['current'] - v['d_standing_late']) * TPA:,.0f} trees)")
say(f"   sum of rows (double-counts overlapping cases): {P.current_forest_acres.sum():,.0f} ac current, {P.forest_remaining_acres.sum():,.0f} ac remaining")
say("\n   public-owner cases in this table:")
say(P[P.public_owner_case][["case", "name", "entitlement_type", "total_acres", "current_forest_acres", "public_share_of_case", "public_owners"]].to_string(index=False))
part = P[(~P.public_owner_case) & (P.public_share_of_case >= 0.1)]
say(f"   not flagged, but 10% to {PUBLIC_SHARE:.0%} public: " + ("none" if not len(part) else "; ".join(f"{r.case} {r.name} ({r.public_owners})" for r in part.itertuples())))

say("\n   Timing names: 'before the case was filed' is reported as cleared_under_earlier_approval where a conditional case from an earlier year was already on the ground,")
say("   cleared_before_any_approval where none was, and cleared_before_case_filed_earlier_case_same_year where the only earlier case is numbered the same year as the clearing.")
say(f"\n4. Clearing-case pairs where the first-detection quarter ended before the case was filed: {len(B)} pairs, {B.id.nunique()} clearings, {T[T.id.isin(B.id)].acres.sum():.1f} acres ({(B.conflict_flag != '').sum()} pairs involve {', '.join(COI)})")
say(B.groupby(["case", "case_name", "case_status", "case_type"]).agg(clearings=("id", "nunique"), overlap_acres=("overlap_acres", "sum"), filing=("filing_date", "first"), robust=("holds_if_detection_ran_a_quarter_early", "sum")).round(1).sort_values("overlap_acres", ascending=False).to_string())
say("\n   the same pairs by timing class:")
say(B.groupby("timing").agg(pairs=("id", "size"), clearings=("id", "nunique"), overlap_acres=("overlap_acres", "sum")).round(1).to_string())
notunder = B[B.timing != UNDER_EARLIER]
say("   pairs not under an earlier approval:")
say(notunder[["id", "acres", "overlap_acres", "first_quarter", "timing", "case", "case_name", "filing_date", "governing_case_of_clearing", "plan_timing", "first_approved_plan"]].to_string(index=False))
new_before = TH[TH.timing.isin([BEFORE_ANY, SAME_YEAR])]
say(f"\n   clearings detected before their governing case was filed and not under an earlier-year conditional case: {len(new_before)}, {new_before.acres.sum():.1f} acres")
say(new_before[["id", "acres", "first_quarter", "timing", "governing_case", "case_name", "case_filed", "case_filed_basis", "prior_conditional_case", "plan_timing", "owners_orgs_only"]].assign(owners_orgs_only=lambda d: d.owners_orgs_only.str[:60]).to_string(index=False))

say("\n5. Case history audit (full text: chain_audit.txt)")
L += ["   " + a.replace("\n", "\n   ") for a in A]

say(f"\n6. Plan records under C014 and the Veridea clearings detected before plan approval: {len(pick)} clearings, {R.plan_layer_fid.nunique()} plan records ({R[R.counts_as_approved].plan_layer_fid.nunique()} approved or under construction). Files: plan_check/")
say("   The Development layer has no plan number. plan_layer_fid is the layer's own id; plan_document_id is the Town DocumentCenter id in the record's link.")
say(CV.drop(columns=["plan_timing"]).rename(columns={"approved_or_under_construction": "approved", "share_inside_any_record": "in_any", "share_inside_approved_record": "in_approved", "share_inside_record_approved_before_quarter": "in_appr_before_qtr",
                                                      "share_inside_record_approved_by_quarter_end": "in_appr_by_qtr_end", "share_inside_approved_record_with_no_date": "in_appr_undated", "acres_outside_every_approved_record": "ac_outside_approved"}).to_string(index=False))
say("\n   the records:")
say(R.drop_duplicates("plan_layer_fid").sort_values("plan_action_date", key=lambda x: x.astype(str))[["plan_layer_fid", "plan_document_id", "plan_name", "plan_type", "plan_status", "plan_action_taken", "plan_action_date", "plan_total_acres"]].to_string(index=False))

say(f"\n7. Review list (review_list.csv): {len(RV)} cases numbered 2022 or later with at least {REVIEW_MIN_AC:g} ac of current forest, without {', '.join(COI)} and public-owner cases. Rows overlap, so the column does not add up to a total.")
say(RV[["case", "name", "entitlement_type", "approved", "total_acres", "current_forest_acres", "ground_shared_with"]].to_string(index=False))

say(f"\n8. Freshness (freshness_25CZ_26CZ.csv): every case numbered 25CZ or 26CZ in the Rezoning layer or on the zoning map, layers pulled {PULLED}")
say(F[["case", "name", "source", "rezoning_layer_status", "filed", "rezoning_layer_action_date", "zoning_map_date", "replaced_on_map_by", "approval_date_used", "check"]].assign(name=lambda d: d.name.str[:34], check=lambda d: d.check.str[:95]).to_string(index=False))
open(os.path.join(OUT, "summary.txt"), "w").write("\n".join(L) + "\n")
print("\n".join(L))
