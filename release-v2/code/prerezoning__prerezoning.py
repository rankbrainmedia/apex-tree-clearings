#!/usr/bin/env python
"""prerezoning.py: forest cleared on a case's ground before the case was filed, 2017 to 2026.

    ../apex-canopy/df-venv/bin/python prerezoning.py

Run after s2_composites_2017.py, naip_canopy.py and detect_2017.py. Reads their cache, the Town layers and public
parcels in ../entitlement/inputs/, and ../entitlement/out/pipeline_2022plus.csv (types, approval dates, public flag).
Writes out/prerezoning_clearing.csv (one row per case), out/no_case_clearings.csv (clearings of 2 acres or more on
ground with no conditional case), out/summary.txt. Method and caveats: NOTES.md.
"""
import glob, json, os, re, sys, time
import numpy as np, pandas as pd, geopandas as gpd, requests, shapely
from affine import Affine
from rasterio import features
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
AC = os.path.join(HERE, "..", "apex-canopy")
CACHE = os.path.join(AC, "prerezoning_cache")
ENT = os.path.join(HERE, "..", "entitlement")
OUT = os.path.join(HERE, "out"); os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, os.path.join(AC, "release-v1", "code"))
os.environ.setdefault("APEX_WORK", CACHE); os.environ.setdefault("APEX_OUT", CACHE)
import config as C  # noqa: E402

M2_AC = C.M2_PER_AC
PX_AC = 100 / M2_AC
T10 = Affine(10, 0, C.X0, 0, -10, C.Y1)
SHAPE = (C.H, C.W)
TPA = 163.9
CANDIDATE_SHARE = 0.20        # Adam's rule: 20% or more of 2017 forest cleared before filing with no prior conditional case
MIN_NO_CASE_AC = 2.0
HOMESTEAD_MAX_AC = 10.0       # a single-family parcel under this size, owned by individuals, is treated as a homestead
PUBLIC_SHARE = 0.5
COI = {"23CZ13": "Seymour Mixed Use PUD is next to the author's home: left out of totals and disclosed"}
MANUAL_STATUS = {"26CZ05": "Approved", "25CZ13": "Approved"}       # Adam, 2026-11-24 (the Rezoning layer says Proposed)
UA = {"User-Agent": "parcel-lookup/1.0"}
ORG = re.compile(r"\b(LLC|L L C|INC|LP|LLP|LTD|CORP|CORPORATION|COMPANY|ASSOCIATION|ASSN|ASSOC|HOA|TOWN OF|COUNTY|CNTY|BOARD OF EDUCATION|CHURCH|PROPERTY SERVICES|"
                 r"PARTNERSHIP|PARTNERS|BANK|STATE OF|DEPARTMENT|DEPT|TRANSPORTATION|AUTHORITY|UNIVERSITY|UNITED STATES?|CONSERVANCY|HOMES|PROPERTIES|DEVELOPMENT|"
                 r"INVESTMENTS|HOLDINGS|VENTURES|GROUP|MINISTRIES|FOUNDATION|ENERGY|UTILITIES)\b")
PUBLIC = re.compile(r"TOWN OF|COUNTY|CNTY|BOARD OF EDUCATION|STATE OF|TRANSPORTATION|TURNPIKE|TRNPK|UNITED STATES? OF AMERICA|POSTAL SERVICE")


def ms(s):
    return pd.to_datetime(s, unit="ms", errors="coerce") if "datetime" not in str(s.dtype) else s.dt.tz_localize(None)


def fix(g):
    return gpd.GeoSeries(shapely.make_valid(g.geometry.values), index=g.index, crs=g.crs)


def parse_case(c):
    m = re.match(r"^0?(\d{2})([A-Z]{2,3})\d", str(c).strip().upper())
    if not m:
        return None, None
    y = int(m.group(1))
    return (2000 + y if y <= 30 else 1900 + y), m.group(2)


def burn(geoms, value=1, dtype="uint8"):
    return features.rasterize([(g, value) for g in geoms], out_shape=SHAPE, transform=T10, fill=0, dtype=dtype)


# ------------------------------------------------------------------ load
D = np.load(os.path.join(CACHE, "detect_2017.npz"))
J = json.load(open(os.path.join(CACHE, "detect_2017.json")))
DET_Q = J["det_quarters"]
QP = pd.PeriodIndex(DET_Q, freq="Q")
Q_END = QP.end_time.normalize().values.astype("datetime64[D]")
Q_YEAR = np.array([p.year for p in QP])
cand, first_event, first_strict, regrew, kept_event, kept_strict = (D[k] for k in ("cand", "first_event", "first_strict", "regrew", "kept_event", "kept_strict"))
now_forest = D["state_now"] == 0
b = np.load(os.path.join(AC, "s2", "cache", "baseline.npz"))
frac22, inb = b["frac"], b["inb"]
NAIP = {y: np.load(os.path.join(CACHE, "naip", f"canopy_{y}.npz"))["frac"] for y in (2016, 2018, 2020)} | {2022: frac22}
NAIP_META = {y: json.load(open(os.path.join(CACHE, "naip", f"canopy_{y}.json"))) for y in (2016, 2018, 2020)}

rz = gpd.read_file(os.path.join(ENT, "inputs", "town_rezoning_2026-11-24.geojson")).to_crs(32617)
rz["geometry"] = fix(rz)
rz["case"] = rz.Petition.str.strip().str.upper()
rz["filed"], rz["action"] = ms(rz.Submitted), ms(rz.Action_Date)
rz = rz.set_index("case", drop=False)
zn = gpd.read_file(os.path.join(ENT, "inputs", "town_zoning_2026-11-24.geojson")).to_crs(32617)
zn["geometry"] = fix(zn)
zn["case"] = zn.CASE_NUMBE.fillna("").str.strip().str.upper()
BACK = sorted([c for c in zn.columns if c.startswith("BACK")], key=lambda c: int(c[4:]))
zn["chain"] = zn[BACK].fillna("").apply(lambda r: [x.strip().upper() for x in r if x and x.strip()], axis=1)
# the first conditional (CZ or CU) case year the zoning map knows on each district: its current case or any earlier one
zn["cond_year"] = [min((parse_case(c)[0] for c in [z.case] + z.chain if parse_case(c)[1] in ("CZ", "CU")), default=0) for z in zn.itertuples()]
zn["cond_cases"] = [" < ".join(c for c in [z.case] + z.chain if parse_case(c)[1] in ("CZ", "CU")) for z in zn.itertuples()]
zrow = features.rasterize([(g, i + 1) for i, g in enumerate(zn.geometry)], out_shape=SHAPE, transform=T10, fill=0, dtype="int32") - 1
cond_year = np.where(zrow >= 0, zn.cond_year.values[np.maximum(zrow, 0)], 0)

pp = gpd.read_file(sorted(glob.glob(os.path.join(ENT, "inputs", "public_parcels_*.geojson")))[-1]).to_crs(32617)
pp["geometry"] = fix(pp)
PUB_ALL = pp.geometry.union_all()
pub_px = burn([PUB_ALL]).astype(bool)
PIPE = pd.read_csv(os.path.join(ENT, "out", "pipeline_2022plus.csv")).fillna("").set_index("case")

# ------------------------------------------------------------------ 1-3. every conditional zoning case numbered 2022 or later, any status
cases = sorted({c for c in list(zn.case) + list(rz.index) if parse_case(c) == (parse_case(c)[0], "CZ") and (parse_case(c)[0] or 0) >= 2022})
ev_year = np.where(first_event >= 0, Q_YEAR[np.maximum(first_event, 0)], 0)
ev_end = np.where(first_event >= 0, Q_END[np.maximum(first_event, 0)], np.datetime64("2100-01-01"))
prior = (cond_year > 0) & (cond_year < ev_year)             # a conditional case numbered in an earlier year than the clearing
same = (cond_year > 0) & (cond_year == ev_year)             # numbered the same year: order not known
none = ~prior & ~same


def quarters_of(mask):
    """(first quarter in which the running total reaches an acre, area-weighted median quarter) of the cells in mask."""
    idx = np.sort(first_event[mask])
    if len(idx) < C.MIN_PX:
        return ("", "") if not len(idx) else (DET_Q[idx[min(len(idx) - 1, C.MIN_PX - 1)]], DET_Q[idx[(len(idx) - 1) // 2]])
    return DET_Q[idx[C.MIN_PX - 1]], DET_Q[idx[(len(idx) - 1) // 2]]


def months(q, floor):
    return "" if not q else round((floor - pd.Period(q, freq="Q").end_time.normalize()).days / 30.44, 1)


rows, masks, cleared_px = [], {}, {}
for case in cases:
    yr = parse_case(case)[0]
    r = rz.loc[case] if case in rz.index else None
    cur = zn[zn.case == case]
    geom, src = (r.geometry, "Rezoning layer (petition area)") if r is not None else (cur.geometry.union_all(), "zoning map (districts now under this case)")
    m = burn([geom]).astype(bool) & inb; masks[case] = m
    filed = r.filed if r is not None and pd.notna(r.filed) else pd.NaT
    floor = filed if pd.notna(filed) else pd.Timestamp(yr, 1, 1)
    status = MANUAL_STATUS.get(case) or (r.Status if r is not None else "on zoning map")
    f17 = m & cand
    ev = m & kept_event
    pre = ev & (ev_end < np.datetime64(floor.date()))
    f = f17.sum() * PX_AC
    a = {k: (pre & v).sum() * PX_AC for k, v in (("all", np.ones(SHAPE, bool)), ("prior", prior), ("same", same), ("none", none))}
    fq, mq = quarters_of(pre)
    cleared_px[case] = pre & none
    nfq, nmq = quarters_of(pre & none)
    big = pd.Series(first_event[pre]).value_counts()
    here = "no clearing before filing" if a["all"] < 0.05 else "yes" if a["none"] + a["same"] < 0.05 else "no" if a["prior"] + a["same"] < 0.05 else "partly"
    pub_share = (m & pub_px).sum() / max(m.sum(), 1)
    info = PIPE.loc[case] if case in PIPE.index else None
    naip_f = {y: (m & (np.nan_to_num(NAIP[y], nan=-1) >= 0.5)).sum() * PX_AC for y in NAIP}
    s2_by = {q: (ev & (first_event < DET_Q.index(q))).sum() * PX_AC for q in ("2018Q3", "2020Q3", "2022Q3")}
    early = pre & (ev_end < np.datetime64("2020-07-01"))                   # cleared before the 2020 NAIP flight
    gap = m & (np.nan_to_num(NAIP[2016], nan=-1) >= 0.5) & (D["state_base"] == 1) & (np.nan_to_num(NAIP[2020], nan=1) < 0.5) & (np.nan_to_num(frac22, nan=1) < 0.5)
    rows.append(dict(
        case=case, name=(r.Name if r is not None else "") or (cur.NAME.iloc[0] if len(cur) else ""), status=status,
        entitlement_type=info.entitlement_type if info is not None else "", filed=filed.date() if pd.notna(filed) else "", filing_date_basis="Rezoning layer" if pd.notna(filed) else f"year only: Jan 1 {yr} used",
        approved=info.approved if info is not None else (r.action.date() if r is not None and pd.notna(r.action) and status == "Approved" else ""),
        case_acres=round(m.sum() * PX_AC, 1), forest_2017_acres=round(f, 1),
        cleared_2017_to_filing_acres=round(a["all"], 1), share_of_2017_forest_cleared_before_filing=round(a["all"] / f, 2) if f >= 1 else "",
        first_detection_quarter=fq, median_clearing_quarter=mq, months_first_detection_to_filing=months(fq, floor), months_median_clearing_to_filing=months(mq, floor),
        largest_quarter=(DET_Q[big.index[0]] if len(big) else ""), largest_quarter_acres=(round(big.iloc[0] * PX_AC, 1) if len(big) else ""),
        conditional_case_on_ground_at_clearing=here, cleared_with_prior_conditional_acres=round(a["prior"], 1), cleared_conditional_same_year_acres=round(a["same"], 1),
        cleared_no_prior_conditional_acres=round(a["none"], 1), share_of_2017_forest_cleared_no_prior_conditional=round(a["none"] / f, 2) if f >= 1 else "",
        no_prior_first_detection_quarter=nfq, no_prior_median_clearing_quarter=nmq, no_prior_months_median_clearing_to_filing=months(nmq, floor),
        prerezoning_candidate=bool(f >= 1 and a["none"] / f >= CANDIDATE_SHARE and case not in COI),
        would_be_candidate_but_conflict_flagged=bool(f >= 1 and a["none"] / f >= CANDIDATE_SHARE and case in COI),
        regrew_before_2026_acres=round((pre & regrew).sum() * PX_AC, 1), still_cleared_by_release_rule_acres=round((pre & (first_strict >= 0) & (first_strict <= first_event)).sum() * PX_AC, 1),
        cleared_after_filing_acres=round((ev & ~pre).sum() * PX_AC, 1), forest_2017_still_forestlike_2026Q3_acres=round((f17 & now_forest).sum() * PX_AC, 1),
        est_trees_cleared_before_filing=int(round(a["all"] * TPA, -1)),
        conditional_cases_on_ground="; ".join(sorted(set(zn.cond_cases.values[np.unique(zrow[m & (zrow >= 0)])]) - {""}))[:400],
        naip_forest_acres_2016=round(naip_f[2016], 1), naip_forest_acres_2018=round(naip_f[2018], 1), naip_forest_acres_2020=round(naip_f[2020], 1), naip_forest_acres_2022=round(naip_f[2022], 1),
        s2_cleared_by_2018Q3_acres=round(s2_by["2018Q3"], 1), s2_cleared_by_2020Q3_acres=round(s2_by["2020Q3"], 1), s2_cleared_by_2022Q3_acres=round(s2_by["2022Q3"], 1),
        naip_canopy_2016_on_cells_cleared_before_filing=round(float(np.nanmean(NAIP[2016][pre])), 2) if pre.any() else "",
        naip_canopy_2020_on_cells_cleared_before_mid2020=round(float(np.nanmean(NAIP[2020][early])), 2) if early.any() else "",
        naip_share_under_half_canopy_2020_on_cells_cleared_before_mid2020=round(float((NAIP[2020][early] < 0.5).mean()), 2) if early.any() else "",
        naip_canopy_2022_on_cells_cleared_before_filing_and_2022Q3=round(float(np.nanmean(frac22[pre & (first_event < DET_Q.index("2022Q3"))])), 2) if (pre & (first_event < DET_Q.index("2022Q3"))).any() else "",
        naip_only_possible_clearing_2016_to_mid2017_acres=round(gap.sum() * PX_AC, 1),
        public_share_of_case=round(pub_share, 2), public_owner_case=bool(pub_share >= PUBLIC_SHARE), boundary_from=src, conflict_flag=COI.get(case, "")))
R = pd.DataFrame(rows).sort_values(["prerezoning_candidate", "cleared_no_prior_conditional_acres"], ascending=False)
# where the candidates' pre-filing clearing is, for the parcel and tax-record step and for looking at on a map
G = []
near = (~R.prerezoning_candidate) & (R.conflict_flag == "") & (R.cleared_no_prior_conditional_acres >= 2)
for r in R[R.prerezoning_candidate | near].itertuples():
    pm = cleared_px[r.case]
    geom = shapely.union_all([shapely.geometry.shape(s) for s, v in features.shapes(pm.astype("uint8"), mask=pm, transform=T10)])
    G.append(dict(case=r.case, tier="candidate" if r.prerezoning_candidate else "below the 20% line", name=r.name, filed=str(r.filed), acres=r.cleared_no_prior_conditional_acres, first_quarter=r.no_prior_first_detection_quarter, median_quarter=r.no_prior_median_clearing_quarter, geometry=geom))
if G:
    fn = os.path.join(OUT, "candidate_cleared_areas.geojson")
    if os.path.exists(fn):
        os.remove(fn)
    gpd.GeoDataFrame(G, crs=32617).to_crs(4326).to_file(fn, driver="GeoJSON")

# ------------------------------------------------------------------ 4. clearings on ground with no conditional case
petitions = burn(list(rz.geometry[rz.Status.isin(["Proposed", "Approved"])])).astype(bool)
no_case = inb & (cond_year == 0) & ~petitions
lab, n = ndimage.label(kept_event & no_case, structure=np.ones((3, 3), int))
bare_now = D["state_now"] == 1
sizes = ndimage.sum(np.ones(SHAPE), lab, index=np.arange(1, n + 1))
keep = [i + 1 for i in np.argsort(-sizes) if sizes[i] * PX_AC >= MIN_NO_CASE_AC]


def fetch(url, fields, geom84):
    p = {"where": "1=1", "outFields": fields, "f": "geojson", "outSR": 4326, "inSR": 4326, "geometry": ",".join(f"{v:.6f}" for v in geom84.bounds),
         "geometryType": "esriGeometryEnvelope", "spatialRel": "esriSpatialRelIntersects"}
    for _ in range(4):
        try:
            return requests.get(url, params=p, timeout=120, headers=UA).json().get("features", [])
        except Exception:
            time.sleep(2)
    raise SystemExit("parcel query failed")


WAKE = ("https://maps.wakegov.com/arcgis/rest/services/Property/Parcels/MapServer/0/query",
        "PIN_NUM,REID,OWNER,DEED_ACRES,DEED_DATE,SALE_DATE,TOTSALPRICE,YEAR_BUILT,TYPE_USE_DECODE,LAND_CLASS_DECODE,BILLING_CLASS_DECODE,EXEMPTDESC,SITE_ADDRESS,PLANNING_JURISDICTION")
CHATHAM = ("https://gisservices.chathamcountync.gov/opendataagol/rest/services/Cadastral/Chatham_CamaParcels/MapServer/0/query",
           "parcel_number,current_owners,gross_current_acres,land_use,physical_street_address")


def parcels_for(geom):
    """Current parcels under a shape: Wake first, Chatham where Wake has none. Cached raw pulls stay in the git-ignored cache."""
    g84 = gpd.GeoSeries([geom], crs=32617).to_crs(4326).iloc[0]
    out = []
    for county, (url, fields) in (("Wake", WAKE), ("Chatham", CHATHAM)):
        feats = fetch(url, fields, g84)
        if not feats:
            continue
        p = gpd.GeoDataFrame.from_features(feats, crs=4326).to_crs(32617)
        p["geometry"] = fix(p)
        p["ov"] = p.geometry.intersection(geom).area / M2_AC
        p = p[p.ov >= 0.05].copy()
        if not len(p):
            continue
        if county == "Wake":
            p = p.rename(columns={"PIN_NUM": "pin", "OWNER": "owner", "DEED_ACRES": "deed_acres", "TYPE_USE_DECODE": "use", "LAND_CLASS_DECODE": "land_class", "YEAR_BUILT": "year_built", "REID": "reid"})
        else:
            p = p.rename(columns={"parcel_number": "pin", "current_owners": "owner", "gross_current_acres": "deed_acres", "land_use": "use"}).assign(land_class="", year_built=np.nan, reid="")
        p["county"] = county
        p["owner"] = p.owner.fillna("").map(lambda s: re.sub(r"[\s,]+$", "", re.sub(r"\s+", " ", str(s))).strip())
        p["owner"] = p.owner.map(lambda s: s.split(" DBA ")[1] + " (DBA)" if " DBA " in s else s)          # a trade name, without the person's name in front of it
        out.append(p)
        break
    return pd.concat(out) if out else None


def owners_redacted(p, total):
    """Organisations by name, private individuals as a count: the release's rule."""
    org = p[p.is_org].groupby("owner").ov.sum().sort_values(ascending=False)
    ind = p[~p.is_org]
    s = [f"{k} ({v / total:.0%})" for k, v in org.items()]
    if len(ind):
        s.append(f"[{ind.owner.nunique()} private individual owner(s), names withheld] ({ind.ov.sum() / total:.0%})")
    return "; ".join(s)


N, parcel_cache = [], []
for k, pid in enumerate(keep, 1):
    pm = lab == pid
    geom = shapely.union_all([shapely.geometry.shape(s) for s, v in features.shapes(pm.astype("uint8"), mask=pm, transform=T10)])
    idx = np.sort(first_event[pm])
    zr = pd.Series(zrow[pm]).value_counts()
    z = zn.iloc[zr.index[0]] if zr.index[0] >= 0 else None
    cen = gpd.GeoSeries([geom.centroid], crs=32617).to_crs(4326).iloc[0]
    p = parcels_for(geom)
    acres = pm.sum() * PX_AC
    row = dict(id=f"N{k:03d}", acres=round(acres, 2), still_bare_2026Q3_acres=round((pm & bare_now).sum() * PX_AC, 2), current_clearing=bool((pm & bare_now).sum() / pm.sum() >= 0.5), first_quarter=DET_Q[idx[0]], median_quarter=DET_Q[idx[(len(idx) - 1) // 2]], last_quarter=DET_Q[idx[-1]],
               centroid_lat=round(cen.y, 6), centroid_lon=round(cen.x, 6), zoning_district=(z.DISTRICT if z is not None else "no district"), zoning_case=(z.case if z is not None else ""),
               in_2022_release=bool((pm & np.load(os.path.join(AC, "s2", "cache", "detect.npz"))["kept"]).sum() / pm.sum() >= 0.5),
               in_denied_or_withdrawn_petition="; ".join(c for c in rz.index[rz.Status.isin(["Denied", "Withdrawn"])] if rz.geometry[c].intersection(geom).area / M2_AC >= 0.05),
               public_parcel_share=round((pm & pub_px).sum() / pm.sum(), 2))
    if p is None:
        row.update(parcels=0, parcel_share=0.0, parcel_county="", owners_orgs_only="", largest_parcel_use="", land_classes="", single_family_homestead=False, likely_public_or_right_of_way=True,
                   note="no parcel under it in either county: road right-of-way or unparcelled land")
    else:
        p["is_org"] = p.owner.str.upper().str.contains(ORG)
        p["is_public"] = p.owner.str.upper().str.contains(PUBLIC)
        p["homestead"] = (~p.is_org) & p.use.fillna("").str.upper().str.contains("SINGL") & (pd.to_numeric(p.deed_acres, errors="coerce").fillna(0) < HOMESTEAD_MAX_AC)
        tot = p.ov.sum()
        top = p.sort_values("ov", ascending=False).iloc[0]
        row.update(parcels=len(p), parcel_share=round(min(tot / acres, 1), 2), parcel_county=top.county, owners_orgs_only=owners_redacted(p, acres), largest_parcel_use=str(top.use or ""),
                   largest_parcel_deed_acres=top.deed_acres, land_classes="; ".join(f"{k} {v / tot:.0%}" for k, v in p.groupby("land_class").ov.sum().sort_values(ascending=False).items() if k),
                   share_on_homestead_parcels=round(p.ov[p.homestead].sum() / acres, 2), single_family_homestead=bool(p.ov[p.homestead].sum() / acres >= 0.5),
                   share_on_individually_owned_parcels=round(p.ov[~p.is_org].sum() / acres, 2),
                   likely_public_or_right_of_way=bool((p.ov[p.is_public].sum() / acres >= 0.5) or (tot / acres < 0.5)), note="")
        parcel_cache.append(p.drop(columns="geometry").assign(clearing_id=row["id"]))
    N.append(row)
N = pd.DataFrame(N)
if parcel_cache:
    pd.concat(parcel_cache).to_csv(os.path.join(CACHE, "no_case_clearing_parcels_raw.csv"), index=False)       # has private owner names: stays out of git
N.to_csv(os.path.join(OUT, "no_case_clearings_all.csv"), index=False)
NL = N[~N.single_family_homestead]
NL.to_csv(os.path.join(OUT, "no_case_clearings.csv"), index=False)
np.savez_compressed(os.path.join(CACHE, "prerezoning_masks.npz"), no_case_lab=np.where(np.isin(lab, keep), lab, 0), zrow=zrow, cond_year=cond_year)
R.to_csv(os.path.join(OUT, "prerezoning_clearing.csv"), index=False)

# ------------------------------------------------------------------ summary
pd.set_option("display.width", 320, "display.max_columns", 60, "display.max_colwidth", 60, "display.max_rows", 400)
L = []
say = L.append
say(f"Pre-rezoning clearing, 2017 to 2026. Baseline May-Sep 2017 (pooled); detection {DET_Q[0]} to {DET_Q[-1]}; Town layers pulled 2026-11-24.")
say(f"2017 forest in the jurisdiction: {J['forest_2017_ac']:,.0f} ac. Cleared since, in patches of an acre or more: {J['event_ac']:,.0f} ac by the event rule "
    f"(bare for about a year or more), {J['strict_ac']:,.0f} ac still bare today by the release's rule.")
say(f"Conflict flag: {', '.join(COI)} is in the table, flagged, and left out of the candidate list and the totals below.")
H = R[R.conflict_flag == ""]
say(f"\n1-3. Conditional zoning cases numbered 2022 or later, any status: {len(R)} ({", ".join(f"{k} {v}" for k, v in R.status.value_counts().items())})")
say(f"   2017 forest inside them (rows overlap, so this is a sum of rows): {H.forest_2017_acres.sum():,.0f} ac. Cleared between mid-2017 and the filing date: {H.cleared_2017_to_filing_acres.sum():,.0f} ac, of which "
    f"{H.cleared_with_prior_conditional_acres.sum():,.0f} with an earlier conditional case on the ground, {H.cleared_conditional_same_year_acres.sum():,.0f} same year, {H.cleared_no_prior_conditional_acres.sum():,.0f} with none.")
um = np.zeros(SHAPE, bool)
for c in H.case: um |= masks[c]
say(f"   counted once on the ground: {(um & cand).sum() * PX_AC:,.0f} ac of 2017 forest in {um.sum() * PX_AC:,.0f} ac of case ground")
cols = ["case", "name", "status", "filed", "forest_2017_acres", "cleared_2017_to_filing_acres", "cleared_no_prior_conditional_acres", "share_of_2017_forest_cleared_no_prior_conditional",
        "no_prior_first_detection_quarter", "no_prior_median_clearing_quarter", "no_prior_months_median_clearing_to_filing", "regrew_before_2026_acres", "public_owner_case"]
short = {"forest_2017_acres": "forest17", "cleared_2017_to_filing_acres": "pre_filing", "cleared_no_prior_conditional_acres": "no_prior", "share_of_2017_forest_cleared_no_prior_conditional": "share",
         "no_prior_first_detection_quarter": "first_q", "no_prior_median_clearing_quarter": "median_q", "no_prior_months_median_clearing_to_filing": "months", "regrew_before_2026_acres": "regrew", "public_owner_case": "public"}
K = H[H.prerezoning_candidate]
say(f"   cases with an acre or more cleared before filing: {int((H.cleared_2017_to_filing_acres >= 1).sum())}; with an acre or more and no earlier conditional case: {int((H.cleared_no_prior_conditional_acres >= 1).sum())}. "
    f"At a 10% line instead of 20%: {int(((pd.to_numeric(H.share_of_2017_forest_cleared_no_prior_conditional, errors='coerce') >= 0.10)).sum())} cases.")
say(f"\n   CANDIDATES: {CANDIDATE_SHARE:.0%} or more of 2017 forest cleared before filing with no earlier conditional case on the ground: {len(K)} cases, {K.cleared_no_prior_conditional_acres.sum():,.1f} ac "
    f"(about {K.cleared_no_prior_conditional_acres.sum() * TPA:,.0f} trees at the county average)")
say(K[cols].rename(columns=short).assign(name=lambda d: d.name.str[:30]).to_string(index=False))
say("\n   below the 20% line but with 2 ac or more cleared before filing and no earlier conditional case:")
say(H[~H.prerezoning_candidate & (H.cleared_no_prior_conditional_acres >= 2)][cols].rename(columns=short).assign(name=lambda d: d.name.str[:30]).to_string(index=False))
say("\n   cleared before filing, but with an earlier conditional case already on the ground (5 ac or more):")
c2 = ["case", "name", "filed", "forest_2017_acres", "cleared_2017_to_filing_acres", "cleared_with_prior_conditional_acres", "cleared_conditional_same_year_acres", "first_detection_quarter", "median_clearing_quarter", "conditional_cases_on_ground"]
say(H[H.cleared_with_prior_conditional_acres + H.cleared_conditional_same_year_acres >= 5][c2].sort_values("cleared_with_prior_conditional_acres", ascending=False)
    .rename(columns={"forest_2017_acres": "forest17", "cleared_2017_to_filing_acres": "pre_filing", "cleared_with_prior_conditional_acres": "prior", "cleared_conditional_same_year_acres": "same_yr", "first_detection_quarter": "first_q", "median_clearing_quarter": "median_q"})
    .assign(name=lambda d: d.name.str[:28], conditional_cases_on_ground=lambda d: d.conditional_cases_on_ground.str[:60]).to_string(index=False))
if R.would_be_candidate_but_conflict_flagged.any():
    say(f"   {', '.join(R.case[R.would_be_candidate_but_conflict_flagged])} meets the 20% line and is held out by the conflict flag.")

say("\n   NAIP cross-check (cells at least half canopy, by NAIP year) against Sentinel-2, candidates:")
c3 = ["case", "forest_2017_acres", "naip_forest_acres_2016", "naip_forest_acres_2018", "naip_forest_acres_2020", "naip_forest_acres_2022", "s2_cleared_by_2018Q3_acres", "s2_cleared_by_2020Q3_acres", "s2_cleared_by_2022Q3_acres",
      "naip_canopy_2016_on_cells_cleared_before_filing", "naip_share_under_half_canopy_2020_on_cells_cleared_before_mid2020", "naip_only_possible_clearing_2016_to_mid2017_acres"]
say(K[c3].rename(columns={"forest_2017_acres": "s2_forest17", "naip_forest_acres_2016": "naip16", "naip_forest_acres_2018": "naip18", "naip_forest_acres_2020": "naip20", "naip_forest_acres_2022": "naip22", "s2_cleared_by_2018Q3_acres": "s2_by18Q3",
                          "s2_cleared_by_2020Q3_acres": "s2_by20Q3", "s2_cleared_by_2022Q3_acres": "s2_by22Q3", "naip_canopy_2016_on_cells_cleared_before_filing": "canopy16_on_cleared",
                          "naip_share_under_half_canopy_2020_on_cells_cleared_before_mid2020": "gone_in_naip20", "naip_only_possible_clearing_2016_to_mid2017_acres": "naip_only_2016_17"}).to_string(index=False))
early = kept_event & (ev_end < np.datetime64("2020-07-01"))
say(f"   jurisdiction-wide: of {early.sum() * PX_AC:,.0f} ac Sentinel-2 calls cleared before mid-2020, NAIP 2016 had {np.nanmean(NAIP[2016][early] >= 0.5):.0%} at least half canopy and NAIP 2020 has {np.nanmean(NAIP[2020][early] < 0.5):.0%} under half.")
say("   NAIP tile dates: " + "; ".join(f"{y}: " + ", ".join(sorted({t['date'] for t in NAIP_META[y]['tiles']})) for y in NAIP_META))

say(f"\n4. Clearings of {MIN_NO_CASE_AC:g} ac or more since mid-2017 on ground with no conditional case, outside every pending or approved petition: {len(N)} ({N.acres.sum():,.1f} ac)")
say(f"   single-family homesteads (most of the clearing on individually owned single-family parcels under {HOMESTEAD_MAX_AC:g} ac): {int(N.single_family_homestead.sum())} ({N.acres[N.single_family_homestead].sum():,.1f} ac), left out of no_case_clearings.csv")
say(f"   public land or right-of-way: {int((NL.likely_public_or_right_of_way).sum())} ({NL.acres[NL.likely_public_or_right_of_way].sum():,.1f} ac), kept in the file and marked")
PF = NL[~NL.likely_public_or_right_of_way]
c4 = ["id", "acres", "still_bare_2026Q3_acres", "first_quarter", "median_quarter", "centroid_lat", "centroid_lon", "zoning_district", "zoning_case", "parcels", "largest_parcel_use", "largest_parcel_deed_acres", "share_on_individually_owned_parcels", "owners_orgs_only"]
for label, sel in (("still bare today (current clearings)", PF.current_clearing), ("cut and since greened over (bare for a year or more, forest-like again by 2026)", ~PF.current_clearing)):
    say(f"   the rest, {label}: {int(sel.sum())} ({PF.acres[sel].sum():,.1f} ac)")
    if sel.any():
        say(PF[sel][[c for c in c4 if c in PF]].rename(columns={"still_bare_2026Q3_acres": "bare_now", "largest_parcel_use": "use", "largest_parcel_deed_acres": "parcel_ac", "share_on_individually_owned_parcels": "indiv_share"})
            .assign(owners_orgs_only=lambda d: d.owners_orgs_only.str[:80]).to_string(index=False))
open(os.path.join(OUT, "summary.txt"), "w").write("\n".join(L) + "\n")
print("\n".join(L))
