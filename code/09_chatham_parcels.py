#!/usr/bin/env python
"""Step 9 (added in v1.1): join Chatham County parcels for events with no Wake parcel overlap,
and export case_join.csv / case_join.xlsx with every PIN stored as text.

Wake County parcels don't cover the Chatham side of the Apex ETJ (Apex Gateway / New Hope township),
so v1.0 left 14 events with n_parcels = 0. This step queries Chatham County's CAMA parcel layer for
those events and fills the same parcel columns, applying the same overlap threshold and the same
organisation / private-individual redaction rule as the Wake join.

Usage: python 09_chatham_parcels.py <case_join.csv in> <clearings.geojson> <out dir>
Needs network access. Chatham's layer is live, so a later rerun can differ if parcels are re-platted.
"""
import re, sys, os, warnings
warnings.filterwarnings("ignore")
import geopandas as gpd, pandas as pd, requests

URL = ("https://gisservices.chathamcountync.gov/opendataagol/rest/services/"
       "Cadastral/Chatham_CamaParcels/MapServer/0/query")
FIELDS = "parcel_number,current_owners,physical_street_address,zoning,township_name"
MIN_OVERLAP_AC = 0.05          # same as the Wake join
ORG = re.compile(r"\b(LLC|INC|LP|CORPORATION|COMPANY|ASSOCIATION|ASSN|HOA|TOWN OF|COUNTY|"
                 r"BOARD OF EDUCATION|CHURCH|PROPERTY SERVICES)\b")
PIN_COLS = ["org_parcel_pins"]

def clean_owner(s):
    return re.sub(r"[\s,]+$", "", str(s or "")).strip()

def fetch(bounds):
    p = {"where": "1=1", "outFields": FIELDS, "f": "geojson", "outSR": 4326, "inSR": 4326,
         "geometry": ",".join(map(str, bounds)), "geometryType": "esriGeometryEnvelope",
         "spatialRel": "esriSpatialRelIntersects"}
    for _ in range(4):
        try:
            return requests.get(URL, params=p, timeout=120).json().get("features", [])
        except Exception:
            pass
    raise SystemExit("Chatham parcel query failed")

def main(cj_path, ev_path, out_dir):
    cj = pd.read_csv(cj_path, dtype=str, keep_default_na=False)
    ev = gpd.read_file(ev_path)
    todo = cj.loc[cj.n_parcels == "0", "id"].tolist()
    feats = [f for i in todo for f in fetch(ev.loc[ev.id == i].total_bounds)]
    par = gpd.GeoDataFrame.from_features(feats, crs=4326).drop_duplicates("parcel_number").to_crs(2264)
    par["geometry"] = par.buffer(0)
    par["owner"] = par.current_owners.map(clean_owner)
    E = ev[ev.id.isin(todo)].to_crs(2264)[["id", "acres", "geometry"]]
    x = gpd.overlay(E, par[["parcel_number", "owner", "geometry"]], how="intersection", keep_geom_type=True)
    x["overlap_ac"] = x.area / 43560
    x = x[x.overlap_ac >= MIN_OVERLAP_AC].copy()
    x["is_org"] = x.owner.str.upper().str.contains(ORG)
    print("Chatham owners, organisations:", sorted(x[x.is_org].owner.unique()))
    print("Chatham owners, individuals (withheld):", x[~x.is_org].owner.nunique())

    if "parcel_county" not in cj.columns:
        cj["parcel_county"] = cj.n_parcels.map(lambda n: "Wake" if n != "0" else "")
    for i, g in x.groupby("id"):
        k = cj.index[cj.id == i][0]
        acres = float(cj.at[k, "acres"])
        org, ind = g[g.is_org], g[~g.is_org]
        own = org.groupby("owner").overlap_ac.sum().sort_values(ascending=False)
        parts = [f"{o} ({a / acres:.0%})" for o, a in own.items()]
        if len(ind):
            parts.append(f"[{ind.parcel_number.nunique()} private individual owner(s), names withheld] "
                         f"({ind.overlap_ac.sum() / acres:.0%})")
        ind_total = ind.overlap_ac.sum()
        largest = own.index[0] if len(own) and own.iloc[0] >= ind_total else "[private individuals, withheld]"
        pins = org.groupby("parcel_number").overlap_ac.sum().sort_values(ascending=False).index
        cj.loc[k, ["n_parcels", "parcel_overlap_ac", "parcel_overlap_share", "largest_owner", "owners_by_share",
                   "n_org_parcels", "org_parcel_pins", "n_individual_parcels", "individual_overlap_ac",
                   "parcel_county"]] = [
            str(g.parcel_number.nunique()), str(round(g.overlap_ac.sum(), 2)),
            str(round(min(g.overlap_ac.sum() / acres, 1.0), 3)), largest, "; ".join(parts),
            str(org.parcel_number.nunique()), ";".join(pins), str(ind.parcel_number.nunique()),
            str(round(ind_total, 2)), "Chatham"]
    write(cj, out_dir)
    left = cj[cj.n_parcels == "0"]
    print(f"Chatham-filled events: {x.id.nunique()}; still no parcel: {list(left.id)} ({left.acres.astype(float).sum():.2f} ac)")

def write(cj, out_dir):
    for c in PIN_COLS:
        assert cj[c].map(lambda s: all(t.isdigit() for t in s.split(";")) if s else True).all()
    cj.to_csv(os.path.join(out_dir, "case_join.csv"), index=False)
    try:
        from openpyxl import Workbook
    except ImportError:
        print("openpyxl not installed: case_join.xlsx not written"); return
    wb = Workbook(); ws = wb.active; ws.title = "case_join"
    ws.append(list(cj.columns))
    num = {"acres", "centroid_lat", "centroid_lon", "n_parcels", "parcel_overlap_ac", "parcel_overlap_share",
           "n_org_parcels", "n_individual_parcels", "individual_overlap_ac"}
    for row in cj.itertuples(index=False):
        ws.append([float(v) if (c in num and v != "") else v for c, v in zip(cj.columns, row)])
    for c in PIN_COLS:                      # store PINs as text so Excel keeps leading zeros
        col = list(cj.columns).index(c) + 1
        for r in range(2, len(cj) + 2):
            ws.cell(r, col).number_format = "@"
    ws.freeze_panes = "B2"
    wb.save(os.path.join(out_dir, "case_join.xlsx"))

if __name__ == "__main__":
    main(*sys.argv[1:4])
