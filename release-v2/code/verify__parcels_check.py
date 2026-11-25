#!/usr/bin/env python
"""parcels_check.py: which clearings in the sample and the optional large set sit on a single residential parcel.

    ../apex-canopy/df-venv/bin/python parcels_check.py

For each outline, the current parcels under it (Wake County's public parcel service, Chatham County's where Wake has none),
as prerezoning/prerezoning.py pulls them. Parcels are as they stand today, not at the time of the clearing: ground cleared in
2018 and since platted into lots shows as many parcels.

"Single residential parcel" here means: one parcel holds 90% or more of the outline's acres, AND that parcel is residential
by the County's own coding (Wake TYPE_USE "SINGL FAM RES" or the like, or LAND_CLASS beginning "Residential"; Chatham land_use
naming a residence or dwelling). Rows between 75% and 90% on one residential parcel are listed as near misses. The parcel's deed
acres and whether the owner is an individual or an organisation are given beside it, because a 60-acre tract coded residential and
owned by a builder is not a house lot.

Writes ../out_verify/single_parcel_check.csv (no private owner names: organisations are named, individuals are not).
The raw pull, with owner names, stays in the git-ignored cache: apex-canopy/verify_cache/parcels_raw.csv.
"""
import os, re, time
import numpy as np, pandas as pd, geopandas as gpd, requests, shapely

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
OUT = os.path.join(ROOT, "out_verify")
CACHE = os.path.join(ROOT, "apex-canopy", "verify_cache"); os.makedirs(CACHE, exist_ok=True)
M2_AC = 4046.8564
SINGLE, NEAR = 0.90, 0.75
UA = {"User-Agent": "parcel-lookup/1.0"}
ORG = re.compile(r"\b(LLC|L L C|INC|LP|LLP|LTD|CORP|CORPORATION|COMPANY|ASSOCIATION|ASSN|ASSOC|HOA|TOWN OF|COUNTY|CNTY|BOARD OF EDUCATION|CHURCH|PROPERTY SERVICES|"
                 r"PARTNERSHIP|PARTNERS|BANK|STATE OF|DEPARTMENT|DEPT|TRANSPORTATION|AUTHORITY|UNIVERSITY|UNITED STATES?|CONSERVANCY|HOMES|PROPERTIES|DEVELOPMENT|"
                 r"INVESTMENTS|HOLDINGS|VENTURES|GROUP|MINISTRIES|FOUNDATION|ENERGY|UTILITIES|TRUST|TRUSTEE|ESTATE)\b")
ENTITY = re.compile(r"\b(TRUST|TRUSTEE|ESTATE)\b")           # a family trust or an estate is not a company: named as a kind, not by name
WAKE = ("https://maps.wakegov.com/arcgis/rest/services/Property/Parcels/MapServer/0/query",
        "PIN_NUM,OWNER,DEED_ACRES,YEAR_BUILT,TYPE_USE_DECODE,LAND_CLASS_DECODE,BILLING_CLASS_DECODE,PLANNING_JURISDICTION")
CHATHAM = ("https://gisservices.chathamcountync.gov/opendataagol/rest/services/Cadastral/Chatham_CamaParcels/MapServer/0/query", "parcel_number,current_owners,gross_current_acres,land_use")
RES_USE = re.compile(r"SINGL|RESID|DWELL|MOBILE HOME|MFG HOME|TOWNHOUSE|DUPLEX|CONDO", re.I)
RES_CLASS = re.compile(r"^\s*RESIDENTIAL", re.I)


def fetch(url, fields, g84):
    p = {"where": "1=1", "outFields": fields, "f": "geojson", "outSR": 4326, "inSR": 4326, "geometry": ",".join(f"{v:.6f}" for v in g84.bounds), "geometryType": "esriGeometryEnvelope", "spatialRel": "esriSpatialRelIntersects"}
    for _ in range(4):
        try:
            return requests.get(url, params=p, timeout=120, headers=UA).json().get("features", [])
        except Exception:
            time.sleep(2)
    raise SystemExit("parcel query failed")


def parcels_for(geom):
    g84 = gpd.GeoSeries([geom], crs=32617).to_crs(4326).iloc[0]
    out = []
    for county, (url, fields) in (("Wake", WAKE), ("Chatham", CHATHAM)):
        feats = fetch(url, fields, g84)
        if not feats:
            continue
        p = gpd.GeoDataFrame.from_features(feats, crs=4326).to_crs(32617)
        p["geometry"] = shapely.make_valid(p.geometry.values)
        p["ov"] = p.geometry.intersection(geom).area / M2_AC
        p = p[p.ov >= 0.02].copy()
        if not len(p):
            continue
        if county == "Wake":
            p = p.rename(columns={"PIN_NUM": "pin", "OWNER": "owner", "DEED_ACRES": "deed_acres", "TYPE_USE_DECODE": "use", "LAND_CLASS_DECODE": "land_class", "YEAR_BUILT": "year_built", "BILLING_CLASS_DECODE": "billing_class"})
        else:
            p = p.rename(columns={"parcel_number": "pin", "current_owners": "owner", "gross_current_acres": "deed_acres", "land_use": "use"}).assign(land_class="", year_built=np.nan, billing_class="")
        p["county"] = county
        out.append(p[["pin", "owner", "deed_acres", "use", "land_class", "billing_class", "year_built", "ov", "county"]])
        if sum(q.ov.sum() for q in out) >= 0.9 * geom.area / M2_AC:
            break
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=["pin", "owner", "deed_acres", "use", "land_class", "billing_class", "year_built", "ov", "county"])


I = pd.read_csv(os.path.join(OUT, "items.csv"), dtype=str).fillna("")
I = I[I.set.isin(["sample", "large"])]
G = gpd.read_file(os.path.join(OUT, "outlines.geojson")).to_crs(32617)
G = G[G.set.isin(["sample", "large"])].set_index("id")
raw_fn = os.path.join(CACHE, "parcels_raw.csv")
RAW = pd.read_csv(raw_fn, dtype={"pin": str}).fillna("") if os.path.exists(raw_fn) else None
rows, raws = [], []
for r in I.itertuples():
    geom = G.geometry[r.id]; acres = geom.area / M2_AC
    if RAW is not None and (RAW.clearing_id == r.id).any():
        p = RAW[RAW.clearing_id == r.id].copy()
    else:
        p = parcels_for(geom).assign(clearing_id=r.id)
    raws.append(p)
    base = dict(id=r.id, set=r.set, acres=r.acres, first_quarter=r.first_quarter, governing_case=r.governing_case, case_name=r.case_name)
    if not len(p):
        rows.append(dict(base, parcels_under_outline=0, single_residential_parcel="no", why="no parcel under the outline (likely right-of-way)"))
        continue
    p["owner"] = p.owner.fillna("").astype(str).str.upper()
    p["use"] = p.use.fillna("").astype(str); p["land_class"] = p.land_class.fillna("").astype(str)
    p = p.sort_values("ov", ascending=False)
    top = p.iloc[0]
    share = min(float(top.ov) / acres, 1.0)
    res = bool(RES_USE.search(top.use) or RES_CLASS.search(top.land_class))
    is_org = bool(ORG.search(top.owner))
    owner = "individual(s)" if not is_org else ("a trust or estate" if ENTITY.search(top.owner) and not re.search(r"\b(LLC|INC|CORP|LP|LLP|LTD|COMPANY|BANK)\b", top.owner) else top.owner.title())
    flag = "yes" if (share >= SINGLE and res) else "near miss" if (share >= NEAR and res) else "no"
    why = "" if flag != "no" else ("one parcel, but not coded residential" if share >= SINGLE else "spread over several parcels" if share < NEAR else "mostly one parcel, not coded residential")
    rows.append(dict(base, parcels_under_outline=int((p.ov >= 0.05 * acres).sum()), share_on_largest_parcel=round(share, 2), largest_parcel_county=top.county, largest_parcel_use=top.use, largest_parcel_land_class=top.land_class,
                     largest_parcel_deed_acres=top.deed_acres, largest_parcel_year_built=("" if str(top.year_built) in ("", "nan", "0", "0.0") else str(top.year_built).split(".")[0]), largest_parcel_owner=owner,
                     share_on_all_parcels=round(min(float(p.ov.sum()) / acres, 1.0), 2), single_residential_parcel=flag, why=why))
pd.concat(raws, ignore_index=True).to_csv(raw_fn, index=False)          # has private owner names: stays in the ignored cache
R = pd.DataFrame(rows).fillna("")
L = [pd.read_csv(f, dtype=str, keep_default_na=False) for f in (os.path.join(OUT, "verify_log.csv"), os.path.join(OUT, "verify_log_large_optional.csv")) if os.path.exists(f)]
V = pd.concat(L)[["id", "set", "verdict", "share_of_outline_cleared"]]
R = R.merge(V, on=["id", "set"], how="left").fillna("")
R = R.sort_values(["single_residential_parcel", "set", "first_quarter"], key=lambda s: s.map({"yes": 0, "near miss": 1, "no": 2}) if s.name == "single_residential_parcel" else s)
R.to_csv(os.path.join(OUT, "single_parcel_check.csv"), index=False)
pd.set_option("display.width", 320, "display.max_rows", 200, "display.max_colwidth", 40)
print(R.single_residential_parcel.value_counts().to_dict(), "| by set:", R.groupby(["set", "single_residential_parcel"]).size().to_dict())
c = ["id", "set", "acres", "first_quarter", "verdict", "governing_case", "share_on_largest_parcel", "largest_parcel_use", "largest_parcel_land_class", "largest_parcel_deed_acres", "largest_parcel_year_built", "largest_parcel_owner", "parcels_under_outline"]
print(R[R.single_residential_parcel != "no"][["single_residential_parcel"] + c].rename(columns={"single_residential_parcel": "flag", "share_on_largest_parcel": "share", "largest_parcel_use": "use", "largest_parcel_land_class": "land_class",
      "largest_parcel_deed_acres": "deed_ac", "largest_parcel_year_built": "built", "largest_parcel_owner": "owner", "parcels_under_outline": "parcels"}).to_string(index=False))
print("\nuse and land-class values seen on the largest parcel:", R.groupby(["largest_parcel_use", "largest_parcel_land_class"]).size().sort_values(ascending=False).head(25).to_dict())
print("one parcel but not residential:", R[R.why == "one parcel, but not coded residential"][["id", "acres", "largest_parcel_use", "largest_parcel_land_class", "largest_parcel_owner"]].to_dict("records"))
