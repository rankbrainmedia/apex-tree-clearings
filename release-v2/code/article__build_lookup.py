#!/usr/bin/env python3
"""build_lookup.py: the project lookup table. One row per conditional zoning case approved on or after 2019-12-03 with 2 acres or
more of 2017 forest (79 cases; 23CZ13 is left out under the conflict rule).

    ../apex-canopy/df-venv/bin/python build_lookup.py

Reads ../entitlement/out/office_period_cases.csv (not changed), case_names.csv (the name shown for each case) and, for Hopson
Gateway (24CZ20), the reading in out/24CZ20/ and the plan-set reading already in ../entitlement/rca/extracted/24CZ20.plan710.json.
Writes out/lookup_rows.json (used by build_article.py for the table in the page) and out/lookup.html, a single file that sorts
and filters, for opening from disk or hosting later.
"""
import csv, html, json, os
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
T = os.path.normpath(os.path.join(HERE, ".."))
OUT = os.path.join(HERE, "out")
HELD = {"23CZ13"}
DISCLOSE = {"24CZ19": "Applicant named in Barnett v. Seymour. See the disclosure.", "24CZ20": "Lists the Seymour PUD as adjacent. See the disclosure.", "24CZ08": "Lists the Seymour PUD as adjacent. See the disclosure."}
GROUP = {"none/exempt": "None: stated exempt or not required", "5": "5%", "15": "15%", "20": "20%", "25": "25%", "30": "30%", "35": "35%", "40": "40%", "mixed by district": "Differs by part of the site",
         "not found": "No figure in the documents read", "other": "Other"}
GRADE = {"mass graded": "Mass graded", "stage graded": "Stage graded", "both, by phase": "Both, by phase", "not stated": "Not stated", "conditional in the text": "Conditional in the text"}

O = pd.read_csv(os.path.join(T, "entitlement", "out", "office_period_cases.csv"), dtype=str).fillna("")
O = O[~O.case.isin(HELD)]
NAMES = {r["case"]: r["display"] for r in csv.DictReader(open(os.path.join(HERE, "case_names.csv")))}
assert set(O.case) <= set(NAMES), sorted(set(O.case) - set(NAMES))
rows = []
# "standing" here is forest at approval not cleared since, so the three columns add up. The file's standing_now_acres is a different
# measure (2017 forest that reads as forest in 2026) and can be larger: it takes in ground cleared before approval that has regrown.
for r in O.itertuples():
    grp, basis, grade = r.rca_percent_group, r.rca_percent_basis, r.grading_group
    if r.case == "24CZ20":                                   # read 2026-11-25 for the article; the office-period file still says "not read"
        e = [x for f in ("24CZ20.pkt_24CZ20_pud.json", "24CZ20.pkt_24CZ20_ord.json") for x in (lambda d: d.get("entries", d) if isinstance(d, dict) else d)(json.load(open(os.path.join(OUT, "24CZ20", f))))]
        assert any("as required by UDO Section 8.1.2" in str(x.get("sentence", "")) for x in e), "the 24CZ20 reading changed"
        assert any("Mass Graded" in str(x.get("sentence", "")) for x in e)
        rca, grading = "No figure stated: \"RCA as required by UDO Section 8.1.2\"", "Mass graded"
    else:
        rca = GROUP[grp] + (f" ({basis})" if grp == "other" or (basis and not basis.startswith(("case reading", "plan reading", "parent reading", "stated exempt", "acres stated"))) else "")
        grading = GRADE.get(grade, grade)
    flag = DISCLOSE.get(r.case, "") or ("On ground owned by a public body." if r.public_owner_case in ("True", "true") else "")
    short = ("Fixed 100 acres for all of Veridea" if grp == "other" and "Veridea" in rca else "34%" if r.case == "20CZ14" else "27% (parent project)" if r.case == "20CZ05" else "2%" if r.case == "21CZ03" else "10%" if r.case == "21CZ27"
             else "Differs by part" if rca.startswith("Differs") else "None (exempt or not required)" if rca.startswith("None") else "No figure found" if rca.startswith("No figure in") else "No figure (\"as required by\" the ordinance)" if rca.startswith("No figure stated") else rca.split(" (")[0] if rca[:1].isdigit() else rca)
    rows.append(dict(case=r.case, name=NAMES[r.case], approved=r.approved[:10], rca_short=short, grading_short=grading.replace(" graded", "").replace("Both, by phase", "Both"), forest_at_approval=round(float(r.forest_at_approval_acres), 1), cleared_since=round(float(r.cleared_since_approval_acres), 1),
                     standing=round(max(float(r.forest_at_approval_acres) - float(r.cleared_since_approval_acres), 0), 1), rca=rca, grading=grading, url=r.town_case_file_url, flag=flag))
rows.sort(key=lambda d: -d["forest_at_approval"])
json.dump(rows, open(os.path.join(OUT, "lookup_rows.json"), "w"), indent=1)

CSS = """body{font:15px/1.45 -apple-system,Segoe UI,Helvetica,Arial,sans-serif;margin:0;background:#f4f4f1;color:#1c1c1c}
header{position:sticky;top:0;background:#fff;border-bottom:1px solid #cfcfc8;padding:10px 16px;display:flex;gap:10px 16px;flex-wrap:wrap;align-items:center}
h1{font-size:17px;margin:0}input,select{font:inherit;padding:5px 9px;border:1px solid #9a9a92;border-radius:5px}
main{padding:14px 16px 60px}table{border-collapse:collapse;width:100%;background:#fff}th,td{border-bottom:1px solid #e2e2dc;padding:7px 10px;text-align:left;vertical-align:top}
th{cursor:pointer;position:sticky;top:57px;background:#fafaf7;white-space:nowrap}th.n,td.n{text-align:right}th[aria-sort]{color:#0b4f8a}
.flag{color:#8a4b00;font-size:13px}.small{color:#555;font-size:13px}a{color:#0b4f8a}
@media(max-width:760px){th{position:static}table,thead,tbody,tr,td{display:block}thead{display:none}tr{border-bottom:2px solid #cfcfc8;padding:6px 0}td{border:0;padding:2px 10px}td.n{text-align:left}td::before{content:attr(data-label) ": ";color:#666}}"""
JS = """const COLS=[['case','Case'],['name','Project'],['approved','Approved'],['forest_at_approval','Forest at approval (ac)',1],['cleared_since','Cleared since (ac)',1],['standing','Not cleared (ac)',1],['rca','RCA required'],['grading','Grading']];
let sortKey='forest_at_approval',dir=-1;
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function draw(){const q=document.getElementById('q').value.toLowerCase(),g=document.getElementById('g').value;
 let r=ROWS.filter(d=>(!q||(d.case+' '+d.name+' '+d.rca).toLowerCase().includes(q))&&(!g||d.grading===g));
 r.sort((a,b)=>(a[sortKey]>b[sortKey]?1:a[sortKey]<b[sortKey]?-1:0)*dir);
 document.getElementById('head').innerHTML=COLS.map(([k,l,n])=>`<th class="${n?'n':''}" ${k===sortKey?`aria-sort="${dir>0?'ascending':'descending'}"`:''} onclick="by('${k}')">${l}${k===sortKey?(dir>0?' ▲':' ▼'):''}</th>`).join('')+'<th>Town case file</th>';
 document.getElementById('body').innerHTML=r.map(d=>`<tr>${COLS.map(([k,l,n])=>`<td class="${n?'n':''}" data-label="${l}">${n?d[k].toFixed(1):esc(d[k])}${k==='name'&&d.flag?`<div class="flag">${esc(d.flag)}</div>`:''}</td>`).join('')}<td data-label="Town case file">${d.url?`<a href="${esc(d.url)}" target="_blank" rel="noopener">open</a>`:'no link'}</td></tr>`).join('');
 const s=k=>r.reduce((t,d)=>t+d[k],0);
 document.getElementById('n').textContent=`${r.length} of ${ROWS.length} cases · forest at approval ${s('forest_at_approval').toFixed(0)} ac · cleared since ${s('cleared_since').toFixed(0)} ac · not cleared ${s('standing').toFixed(0)} ac (sums of rows; some cases share ground)`}
function by(k){if(k===sortKey)dir=-dir;else{sortKey=k;dir=['forest_at_approval','cleared_since','standing'].includes(k)?-1:1}draw()}
document.getElementById('g').innerHTML='<option value="">any grading</option>'+[...new Set(ROWS.map(d=>d.grading))].sort().map(x=>`<option>${x}</option>`).join('');draw();"""
page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Apex rezoning cases: forest and tree-save terms</title><style>{CSS}</style></head><body>
<header><h1>Apex rezoning cases approved since December 3, 2019</h1><input id="q" type="search" placeholder="filter by case, name or RCA" oninput="draw()" aria-label="Filter"><select id="g" onchange="draw()" aria-label="Grading"></select><span id="n" class="small"></span></header>
<main><p class="small">Conditional zoning cases approved on or after December 3, 2019 with 2 acres or more of forest in 2017. Forest figures come from satellite detection (10 m cells, patches of an acre or more). "RCA required" is what the zoning text or approved plan states,
not what was built, and RCA is not all trees. An approval date and a clearing date show order, not cause. Click a column heading to sort.</p>
<table><thead><tr id="head"></tr></thead><tbody id="body"></tbody></table></main>
<script>const ROWS={json.dumps(rows).replace("</", "<\\/")};{JS}</script></body></html>"""
open(os.path.join(OUT, "lookup.html"), "w").write(page)
print(len(rows), "rows; with a case-file link:", sum(bool(r["url"]) for r in rows), "| flagged:", [(r["case"], r["flag"][:28]) for r in rows if r["flag"]])
for r in rows[:6] + [x for x in rows if x["case"] in ("24CZ20", "21CZ03", "20CZ14", "24CZ19")]:
    print(f"  {r['case']} | {r['name'][:34]:34s} | {r['approved']} | {r['forest_at_approval']:7.1f} {r['cleared_since']:7.1f} {r['standing']:7.1f} | {r['rca'][:95]} | {r['grading']}")
