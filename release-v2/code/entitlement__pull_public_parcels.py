#!/usr/bin/env python
"""pull_public_parcels.py: parcels owned by public bodies in and around Apex, for the public-owner flag.

    ../apex-canopy/df-venv/bin/python pull_public_parcels.py

Sources (public county ArcGIS services, current owner of record on the day of the pull):
  Wake County     maps.wakegov.com  Property/Parcels/MapServer/0          field OWNER
  Chatham County  gisservices.chathamcountync.gov  Chatham_CamaParcels    field current_owners
Only parcels whose owner name is a public body are requested and saved. No private owner is written to disk.
The name patterns below were checked on 2026-11-24 against every distinct owner name inside the bounding box of
the Town's zoning and rezoning layers (41,553 names in Wake, 289 in Chatham).
Output: inputs/public_parcels_<date>.geojson  (county, pin, owner, owner_class, geometry)
"""
import datetime, os, re, sys
import geopandas as gpd, numpy as np, pandas as pd, requests

HERE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "parcel-lookup/1.0"}
SERVICES = {
    "Wake": ("https://maps.wakegov.com/arcgis/rest/services/Property/Parcels/MapServer/0/query", "OWNER", "PIN_NUM"),
    "Chatham": ("https://gisservices.chathamcountync.gov/opendataagol/rest/services/Cadastral/Chatham_CamaParcels/MapServer/0/query", "current_owners", "parcel_number"),
}
# server-side filter: wide on purpose. CLASSES below decides what is kept.
LIKE = ["%TOWN OF%", "%COUNTY%", "%CNTY%", "%BOARD OF ED%", "%TRANSPORTATION%", "%TURNPIKE%", "%TRNPK%", "%STATE OF%", "UNITED STATE%"]
CLASSES = [  # first match wins
    ("Town of Apex", r"^(APEX,? TOWN OF|TOWN OF APEX|CARY,? TOWN OF APEX)"),
    ("Wake County Board of Education (WCPSS)", r"^(THE )?WAKE (COUNTY|CNTY) (BOARD|BD) OF ED"),
    ("Wake County", r"^(WAKE COUNTY( OF)?|COUNTY OF WAKE|HOUSING AUTH COUNTY OF WAKE|WAKE COUNTY BOARD OF ALCOHOLIC CONTROL)$"),
    ("Chatham County", r"^(CHATHAM COUNTY( OF)?|COUNTY OF CHATHAM|CHATHAM COUNTY BOARD OF ED\w*)$"),
    ("State of North Carolina (incl. NCDOT)", r"^(N ?C|NORTH CAROLINA) (DEPARTMENT|DEPT) OF TRANSP|^DEPARTMENT OF TRANSPORTATION$|TURNPIKE AUTH|TRNPK AUTH|^NORTH CAROLINA,? STATE OF$|^STATE OF NORTH CAROLINA"),
    ("United States", r"^UNITED STATES? OF AMERICA$|^UNITED STATES POSTAL SERVICE$"),
    ("Other town", r"^(CARY|HOLLY SPRINGS),? TOWN OF$|^TOWN OF (CARY|HOLLY SPRINGS)( NC)?$"),
]


def classify(owner):
    o = re.sub(r"[\s,]+$", "", re.sub(r"\s+", " ", str(owner or "").upper())).strip()
    for label, pat in CLASSES:
        if re.search(pat, o):
            return label
    return ""


def fetch(url, field, bbox):
    where = " OR ".join(f"{field} LIKE '{p}'" for p in LIKE)
    feats, off = [], 0
    while True:
        p = {"where": where, "outFields": "*", "f": "geojson", "outSR": 4326, "inSR": 4326, "geometry": ",".join(map(str, bbox)),
             "geometryType": "esriGeometryEnvelope", "spatialRel": "esriSpatialRelIntersects", "orderByFields": "OBJECTID",
             "resultOffset": off, "resultRecordCount": 1000}
        for attempt in range(4):
            try:
                j = requests.get(url, params=p, timeout=180, headers=UA).json()
                break
            except Exception as e:
                err = e
        else:
            raise SystemExit(f"parcel query failed: {err}")
        if "error" in j:
            raise SystemExit(f"parcel query error: {j['error']}")
        f = j.get("features", [])
        feats += f
        off += len(f)
        if not f:
            return feats


def main():
    zn = gpd.read_file(os.path.join(HERE, "inputs", "town_zoning_2026-11-24.geojson"))
    rz = gpd.read_file(os.path.join(HERE, "inputs", "town_rezoning_2026-11-24.geojson"))
    b = np.array([zn.total_bounds, rz.total_bounds])
    bbox = [b[:, 0].min(), b[:, 1].min(), b[:, 2].max(), b[:, 3].max()]
    parts = []
    for county, (url, field, pin) in SERVICES.items():
        g = gpd.GeoDataFrame.from_features(fetch(url, field, bbox), crs=4326)
        if not len(g):
            print(f"{county}: 0 parcels matched the server filter")
            continue
        g["owner"] = g[field].map(lambda s: re.sub(r"[\s,]+$", "", str(s or "")).strip())
        g["owner_class"] = g.owner.map(classify)
        dropped = sorted(set(g.owner[g.owner_class == ""]))
        print(f"{county}: {len(g)} parcels matched the server filter, {(g.owner_class != '').sum()} kept as public bodies, {len(dropped)} other owner names dropped (not saved)")
        for k, v in g[g.owner_class != ""].groupby("owner_class"):
            print(f"   {k}: {len(v)} parcels; names: {sorted(set(v.owner))}")
        g = g[g.owner_class != ""]
        parts.append(gpd.GeoDataFrame({"county": county, "pin": g[pin].astype(str), "owner": g.owner, "owner_class": g.owner_class}, geometry=g.geometry, crs=4326))
    out = pd.concat(parts, ignore_index=True)
    fn = os.path.join(HERE, "inputs", f"public_parcels_{datetime.date.today().isoformat()}.geojson")
    if os.path.exists(fn):
        os.remove(fn)
    out.to_file(fn, driver="GeoJSON")
    print(f"wrote {fn}: {len(out)} parcels")


if __name__ == "__main__":
    sys.exit(main())
