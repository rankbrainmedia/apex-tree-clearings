#!/usr/bin/env python
"""parcels_check_release.py: the single-residential-parcel test of parcels_check.py, run on the 238 clearings of the published count.

    ../apex-canopy/df-venv/bin/python parcels_check_release.py

Same rule and same public county parcel services as parcels_check.py (whose functions it reuses). Writes
../out_verify/single_parcel_check_release.csv (no private owner names). The raw pull, with owner names, stays in the git-ignored cache:
apex-canopy/verify_cache/parcels_raw_release.csv. Used before a public release to decide which before-and-after pictures show one home.
"""
import os, re
HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "parcels_check.py")).read()
ns = {"__file__": os.path.join(HERE, "parcels_check.py")}
exec(compile(src.split('\nI = pd.read_csv(os.path.join(OUT, "items.csv")')[0], "parcels_check.py", "exec"), ns)
pd, gpd, OUT, CACHE, parcels_for = ns["pd"], ns["gpd"], ns["OUT"], ns["CACHE"], ns["parcels_for"]
ORG, ENTITY, RES_USE, RES_CLASS, SINGLE, NEAR = ns["ORG"], ns["ENTITY"], ns["RES_USE"], ns["RES_CLASS"], ns["SINGLE"], ns["NEAR"]
I = pd.read_csv(os.path.join(OUT, "items.csv"), dtype=str).fillna(""); I = I[I.set == "release"]
G = gpd.read_file(os.path.join(OUT, "outlines.geojson")).to_crs(32617); G = G[G.set == "release"].set_index("id")
raw_fn = os.path.join(CACHE, "parcels_raw_release.csv")
RAW = pd.read_csv(raw_fn, dtype={"pin": str}).fillna("") if os.path.exists(raw_fn) else None
rows, raws = [], []
for k, r in enumerate(I.itertuples()):
    geom = G.geometry[r.id]; acres = geom.area / 4046.8564
    p = RAW[RAW.clearing_id == r.id].copy() if RAW is not None and (RAW.clearing_id == r.id).any() else parcels_for(geom).assign(clearing_id=r.id)
    raws.append(p)
    if k % 20 == 19:
        pd.concat(raws, ignore_index=True).to_csv(raw_fn, index=False); print(k + 1, flush=True)
    base = dict(id=r.id, set=r.set, acres=r.acres, first_quarter=r.first_quarter, governing_case=r.governing_case)
    if not len(p):
        rows.append(dict(base, parcels_under_outline=0, single_residential_parcel="no", why="no parcel under the outline")); continue
    p["owner"] = p.owner.fillna("").astype(str).str.upper(); p["use"] = p.use.fillna("").astype(str); p["land_class"] = p.land_class.fillna("").astype(str)
    p = p.sort_values("ov", ascending=False); top = p.iloc[0]
    share = min(float(top.ov) / acres, 1.0); res = bool(RES_USE.search(top.use) or RES_CLASS.search(top.land_class)); is_org = bool(ORG.search(top.owner))
    owner = "individual(s)" if not is_org else ("a trust or estate" if ENTITY.search(top.owner) and not re.search(r"\b(LLC|INC|CORP|LP|LLP|LTD|COMPANY|BANK)\b", top.owner) else top.owner.title())
    flag = "yes" if (share >= SINGLE and res) else "near miss" if (share >= NEAR and res) else "no"
    rows.append(dict(base, parcels_under_outline=int((p.ov >= 0.05 * acres).sum()), share_on_largest_parcel=round(share, 2), largest_parcel_use=top.use, largest_parcel_land_class=top.land_class, largest_parcel_deed_acres=top.deed_acres,
                     largest_parcel_owner=owner, single_residential_parcel=flag))
pd.concat(raws, ignore_index=True).to_csv(raw_fn, index=False)
R = pd.DataFrame(rows).fillna(""); R.to_csv(os.path.join(OUT, "single_parcel_check_release.csv"), index=False)
print(R.single_residential_parcel.value_counts().to_dict())
print(R[R.single_residential_parcel != "no"].to_string(index=False))
