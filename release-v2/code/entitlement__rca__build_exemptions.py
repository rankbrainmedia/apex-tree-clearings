#!/usr/bin/env python
"""build_exemptions.py: the cases whose documents state an RCA exemption, "N/A", or only the mass-grading amount.

    ../../apex-canopy/df-venv/bin/python build_exemptions.py

Scope: the governing cases of the 238 clearings plus the 2022+ cases (exemption_cases.csv), without 23CZ13.
The statements in STATEMENTS were found with exemption_scan.py and read on the page by Claude; each is checked here
against the page text, word for word, before it is used. Acres, 2022 forest, cleared and current forest are measured on
the case boundary exactly as in entitlement.py.
Writes ../out/rca_exemptions.csv, ../out/rca_exemption_coverage.csv, ../out/rca_exemptions_summary.txt.
"""
import glob, os, re, sys
import numpy as np, pandas as pd, geopandas as gpd, rasterio, shapely
from rasterio import features

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build_filled import norm, page_text  # noqa: E402
ENT = os.path.join(HERE, ".."); AC = os.path.join(HERE, "..", "..", "apex-canopy"); OUT = os.path.join(ENT, "out")
TEXT = os.path.join(AC, "rca_cache", "text")
M2_AC = 4046.8564
CONFLICT = {"24CZ19": "applicant is Barnett Properties, LLC: disclosed (the applicant is named in Barnett v. Seymour)"}

PROJECT = {"15CZ24": "Colby Crossing", "23CZ09": "Hatcher Property (Weston Reserve)", "17CZ18": "Gracewood PUD", "22CZ09": "Utley Farms PUD", "24CZ09": "Castleberry Reserve",
           "24CZ19": "New Hill Commons", "23CZ18": "[street address] (Ashland)", "23CZ14": "Salem St Townhomes"}      # project names from the plan sets, in place of the map's applicant names
EXEMPT, OFFERED, NA_PROVIDED, MASS, OVERLAY = ("stated exempt, no RCA required", "stated exempt, RCA offered by zoning condition", "required reads N/A, RCA and buffer provided anyway",
                                               "only the mass-grading amount is required", "stated exempt: small town character overlay")
STATEMENTS = [
 dict(case="15CZ24", kind=EXEMPT, doc="plan248", page=1, rca_required="none", rca_provided="", sentence="RCA is not required for this project based on UDO section 8.1.2.C.3.",
      note="Colby Crossing plan set. The sheet quotes the UDO: residential developments with a maximum of two dwelling units per gross acre are exempt."),
 dict(case="23CZ09", kind=EXEMPT, doc="plan490", page=1, rca_required="N/A", rca_provided="", sentence="TOTAL RCA / BUFFER AREA REQUIRED N/A",
      note="Weston Reserve plan set. The cover also reads 'THIS PROJECT IS EXEMPT FROM PROVIDING RCA PER UDO' (low density single-family)."),
 dict(case="17CZ18", kind=NA_PROVIDED, doc="17CZ18", page=20, rca_required="N/A", rca_provided="59.25 acres (25%), RCA and landscape buffer together", sentence="RCA / LANDSCAPE BUFFER AREA REQUIRED N/A",
      note="Gracewood PUD case file, plan sheet. The next row reads 'RCA / LANDSCAPE BUFFER AREA PROVIDED 59.25 ACRES (25%)'; total project area 234.38 acres."),
 dict(case="23CZ18", kind=OFFERED, doc="23CZ18", page=3, rca_required="25% of gross site acreage, buffers and RCA together (4.84 ac on the plan set)", rca_provided="5.60 ac (26.9%) on the plan set",
      sentence="While this low-density development would otherwise be exempt from the RCA requirements established in UDO Sec. 8.1.2.C, this project shall provide buffers and RCA equal to or greater than 25% of the gross site acreage.", note="Zoning condition."),
 dict(case="24CZ09", kind=OFFERED, doc="24CZ09", page=20, rca_required="20% of the property (20.82 ac on the plan set)", rca_provided="25.67 ac (24.67%) on the plan set",
      sentence="UDO Section 8.1.2.C.3 does not require Resource Conservation Area (“RCA”) for low density developments 2 units/acre or less. However, the Development shall designate a minimum of twenty percent (20%) of the Property as RCA.",
      note="PUD text. The same section waives the extra 5% for mass grading."),
 dict(case="24CZ16", kind=OFFERED, doc="24CZ16", page=106, rca_required="UDO: none. Zoning condition: 40% (14.35 acres)", rca_provided="14.35 acres (40%)",
      sentence="REQUIRED RESOURCE NONE (DENSITY LESS THAN 2 DWELLING CONSERVATION AREA UNITS PER ACRE)", note="Plan cover in the case file, read by OCR; the table's two columns run together. Condition 4 (p102): 'The project shall provide 40% RCA (14.35 acres).'"),
 dict(case="22CZ09", kind=MASS, doc="plan480", page=1, rca_required="2.83 ac, 5%", rca_provided="2.84 ac (5.02%)", sentence="RCA Required: 2.83 Ac or 5% (per UDO for \"Mass Grading\")",
      note="Utley Farms plan set. The same sheet says low-density single-family developments are exempt from RCA requirements."),
 dict(case="24CZ19", kind=MASS, doc="plan650", page=1, rca_required="residential part: 5% of the residential site (1.844 ac); non-residential part: 25% (4.615 ac); 6.459 ac in all", rca_provided="7.19 ac",
      sentence="RCA CALCS (RES. MASS GRADING) 5% OF RESIDENTIAL SITE @ 1.844 AC.", note="New Hill Meadows plan set (the residential part of the PUD). Only the residential part is at the mass-grading amount."),
 dict(case="23CZ14", kind=OVERLAY, doc="23CZ14", page=7, rca_required="exempt", rca_provided="exempt", sentence="Gross square footage and percent of RCA required: Exempt by being in a small town character overlay district per UDO 6.3.1.",
      note="A different exemption from the low-density one: the site is in the small town character overlay."),
]

fix = lambda g: gpd.GeoSeries(shapely.make_valid(g.geometry.values), index=g.index, crs=g.crs)
rz = gpd.read_file(os.path.join(ENT, "inputs", "town_rezoning_2026-11-24.geojson")).to_crs(32617); rz["geometry"] = fix(rz); rz["case"] = rz.Petition.str.strip().str.upper(); rz = rz.set_index("case")
zn = gpd.read_file(os.path.join(ENT, "inputs", "town_zoning_2026-11-24.geojson")).to_crs(32617); zn["geometry"] = fix(zn); zn["case"] = zn.CASE_NUMBE.fillna("").str.strip().str.upper()
cl = gpd.read_file(os.path.join(AC, "release-v1", "clearings.geojson")).to_crs(32617)
with rasterio.open(os.path.join(AC, "release-v1", "baseline_forest_10m.tif")) as src:
    base = src.read(1); tf = src.transform
PX = abs(tf.a * tf.e) / M2_AC
D = np.load(os.path.join(AC, "s2", "cache", "detect.npz"))
forest, cleared, now = base == 1, D["kept"], D["state_2026Q3"] == 0
T = pd.read_csv(os.path.join(OUT, "clearings_entitlement.csv")).fillna("")
X = pd.read_csv(os.path.join(HERE, "exemption_cases.csv")).fillna("")
tasks = pd.concat([pd.read_csv(os.path.join(HERE, f)) for f in ("plan_tasks.csv", "exemption_plan_tasks.csv")]).drop_duplicates(["case", "key"])


def measure(case):
    g = rz.geometry[case] if case in rz.index else zn[zn.case == case].geometry.union_all()
    m = features.rasterize([(g, 1)], out_shape=base.shape, transform=tf, fill=0, dtype="uint8").astype(bool)
    t = T[T.governing_case == case]
    name = (rz.Name[case] if case in rz.index else "") or "; ".join(sorted(set(zn.NAME[zn.case == case].fillna("").str.strip())))
    return dict(name=name, acres=round(g.area / M2_AC, 1), forest_2022_acres=round((m & forest).sum() * PX, 1), forest_cleared_acres=round((m & forest & cleared).sum() * PX, 1),
                current_forest_acres=round((m & forest & now).sum() * PX, 1), clearings_governed=len(t), clearing_acres_governed=round(t.acres.sum(), 1))


rows = []
for s in STATEMENTS:
    t = page_text(s["doc"], s["page"])
    assert t is not None and norm(s["sentence"]) in norm(t), f"quote not on the page: {s['case']} {s['doc']} p{s['page']}"
    rows.append(dict(case=s["case"], **dict(measure(s["case"]), **({"name": PROJECT[s["case"]]} if s["case"] in PROJECT else {})), statement=s["kind"], rca_required_as_stated=s["rca_required"], rca_provided_as_stated=s["rca_provided"], document=s["doc"], page=s["page"], sentence=s["sentence"],
                     note=s["note"], governs_clearings=bool(X.governs_clearings[X.case == s["case"]].iloc[0]), in_2022plus_table=bool(X.in_2022plus_table[X.case == s["case"]].iloc[0]), conflict_check=CONFLICT.get(s["case"], "")))
E = pd.DataFrame(rows).sort_values(["statement", "acres"], ascending=[True, False])
E.to_csv(os.path.join(OUT, "rca_exemptions.csv"), index=False)

# coverage: what was there to read for each case
cov = []
for c in X.case:
    docs = [c] + sorted(set(tasks.key[tasks.case == c])) + sorted(os.path.basename(d) for d in glob.glob(os.path.join(TEXT, f"pkt_{c}*")))
    docs = [d for d in docs if glob.glob(os.path.join(TEXT, d, "p*.txt"))]
    hit = any(re.search(r"(RCA|RESOURCE\s+CONSERVATION)[^\n]{0,120}(\d[\d,.]*\s*(AC|ACRES|SF|%)|N/?A|EXEMPT|NONE|NOT REQUIRED)", open(p).read(), re.I) for d in docs for p in glob.glob(os.path.join(TEXT, d, "p*.txt")))
    cov.append(dict(case=c, documents_read=", ".join(docs), pages=sum(len(glob.glob(os.path.join(TEXT, d, "p*.txt"))) for d in docs), plan_set_read=any(d.startswith("plan") for d in docs),
                    rca_figure_or_statement_in_text=hit, exemption_statement=(E.statement[E.case == c].iloc[0] if c in set(E.case) else ""),
                    governs_clearings=bool(X.governs_clearings[X.case == c].iloc[0]), in_2022plus_table=bool(X.in_2022plus_table[X.case == c].iloc[0])))
C = pd.DataFrame(cov); C.to_csv(os.path.join(OUT, "rca_exemption_coverage.csv"), index=False)

pd.set_option("display.width", 320, "display.max_columns", 30, "display.max_colwidth", 70)
L = []
say = L.append
say(f"RCA exemptions, 'N/A' and mass-grading-only amounts stated in the documents. Scope: {len(X)} cases (the clearings' {int(X.governs_clearings.sum())} governing cases plus the {int(X.in_2022plus_table.sum())} cases numbered 2022 or later; 23CZ13 is held out under the conflict rule).")
say(f"Documents read: {int((C.documents_read != '').sum())} cases have at least one ({int(C.pages.sum())} pages); {int(C.plan_set_read.sum())} have a plan set as well as, or instead of, the rezoning file; {int((C.documents_read == '').sum())} have none ({', '.join(C.case[C.documents_read == ''])}).")
say(f"An RCA figure or statement appears in the text for {int(C.rca_figure_or_statement_in_text.sum())} cases. For the other {int(((C.documents_read != '') & ~C.rca_figure_or_statement_in_text).sum())} the documents say nothing either way: most are short ordinances with no plan record, so an exemption cannot be ruled in or out for them.")
say(f"\nStated exemption, N/A or mass-grading-only: {len(E)} cases.")
say(E[["case", "name", "statement", "acres", "forest_2022_acres", "forest_cleared_acres", "current_forest_acres", "clearings_governed", "clearing_acres_governed", "rca_required_as_stated", "rca_provided_as_stated"]]
    .rename(columns={"forest_2022_acres": "forest_2022", "forest_cleared_acres": "cleared", "current_forest_acres": "current", "clearings_governed": "clearings", "clearing_acres_governed": "clearing_ac", "rca_required_as_stated": "rca_required", "rca_provided_as_stated": "rca_provided"})
    .assign(name=lambda d: d.name.str[:22], rca_required=lambda d: d.rca_required.str[:52], rca_provided=lambda d: d.rca_provided.str[:34]).to_string(index=False))
for kind, g in E.groupby("statement"):
    say(f"   {kind}: {len(g)} cases, {g.acres.sum():,.1f} ac, forest 2022 {g.forest_2022_acres.sum():,.1f} ac, cleared {g.forest_cleared_acres.sum():,.1f} ac, current forest {g.current_forest_acres.sum():,.1f} ac")
none = E[E.statement == EXEMPT]
say(f"\nNo RCA at all required and none offered: {', '.join(none.case)} ({none.acres.sum():,.1f} ac, {none.forest_cleared_acres.sum():,.1f} ac of forest cleared).")
say("Conflict check: " + "; ".join(f"{k}: {v}" for k, v in CONFLICT.items()))
open(os.path.join(OUT, "rca_exemptions_summary.txt"), "w").write("\n".join(L) + "\n")
print("\n".join(L))
