#!/usr/bin/env python
"""build_filled.py: check every extracted quote against the page it cites, then write the filled review list.

    ../../apex-canopy/df-venv/bin/python build_filled.py

Reads extracted/<case>.json (one per review-list row, written by a reader working from the page text) and the page
text in ../../apex-canopy/rca_cache/text/. An entry is kept only if its sentence is on the cited page word for word
(spacing and line breaks aside) and, for a number, the digits of the value are in that sentence. Anything else is
dropped and listed in quotes_rejected.csv.

Writes ../out/review_list_filled.csv, ../out/rca_quotes.csv, ../out/rca_quotes_rejected.csv, ../out/rca_summary.txt.
"""
import glob, json, os, re
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "..", "..", "apex-canopy", "rca_cache")
OUT = os.path.join(HERE, "..", "out")
FIELDS = ["project_acres", "rca_required_pct", "rca_required_ac", "rca_provided", "rca_may_count", "grading_type", "rca_bonus_or_reduction",
          "stream_buffer_ac", "floodplain_ac", "wetland_ac", "limits_of_disturbance_ac", "tree_condition", "rca_exemption"]
NUMERIC = {"project_acres", "rca_required_pct", "rca_required_ac", "stream_buffer_ac", "floodplain_ac", "wetland_ac", "limits_of_disturbance_ac"}
NOT_FOUND = "not found"
B = "https://mccmeetingspublic.blob.core.usgovcloudapi.net/"
# The Town's DocumentCenter links for these three return 404 (checked 2026-11-24). The same documents are served from the Town's public meeting packets.
CURRENT_URLS = {
    "24CZ20": "PUD text (Attachment B, approved November 13, 2025): " + B + "apexnc-meet-68869fc8fe954895a63beaa49199ad40/ITEM-Attachment-001-6fd8e48c4c8c48369a95d9271d4b4283.pdf ; statement and ordinance: " + B + "apexnc-meet-68869fc8fe954895a63beaa49199ad40/ITEM-Attachment-001-7ff9d0de9c0b401aabd2928f33f59b23.pdf",
    "25CZ06": "staff report (June 24, 2025 Town Council): " + B + "apexnc-meet-2fb56594d71a4717b9c6e83615ad3fbc/ITEM-Attachment-001-5584fde7549444e3b1c2852486599658.pdf ; statement and ordinance: " + B + "apexnc-meet-2fb56594d71a4717b9c6e83615ad3fbc/ITEM-Attachment-001-14f524e33eb3472a8403f48ecbc54aeb.pdf",
    "25CZ07": "not found: no staff report or ordinance for this case turned up in the Town's meeting packets; the approval is in the October 14, 2025 minutes (" + B + "apexnc-meet-5a77db3d82744bf99be70f1d95d8777e/ITEM-Attachment-001-bcfbc8ec2eb941fab69400b9d3b5c421.pdf) and a plan cover sheet is at " + B + "apexnc-meet-a15ff460a2124bfc982fccec92075906/ITEM-Attachment-001-eec03aa7ba1145568a4b7eec4d780231.pdf",
}
PACKETS = {"pkt_09CZ07": "Ordinance #09CZ07 with the Veridea Sustainable Development Plan, 10 May 2011 (Town meeting-packet attachment)",
           "pkt_22CZ24_staff": "Staff report, Rezoning #22CZ24, January 24, 2023 Town Council meeting (Town meeting-packet attachment)"}
# Cases a reader of the files flagged as connected to the Seymour PUD. They stay in the tables; They are disclosed where they appear.
CONFLICT_CHECK = {"24CZ19": "applicant is Barnett Properties, LLC: disclosed (the applicant is named in Barnett v. Seymour)",
                  "24CZ20": "the plan sheets show the adjoining parcel as Seymour Farm Properties, LLC: disclosed (connected to the Seymour PUD)"}


def norm(s):
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("–", "-").replace("—", "-").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip().lower()


def page_text(doc, page):
    fn = os.path.join(CACHE, "text", doc, f"p{int(page):04d}.txt")
    return open(fn).read() if os.path.exists(fn) else None


def num(v):
    m = re.search(r"\d[\d,]*\.?\d*", str(v))
    return float(m.group(0).replace(",", "")) if m else None


def check(e, doc):
    t = page_text(e.get("doc") or doc, e.get("page", 0))
    if t is None:
        return "page not in the document"
    if norm(e["sentence"]) not in norm(t):
        return "sentence is not on the cited page word for word"
    if e["field"] in NUMERIC and not re.match(r"(?i)\s*(no|none|not)\b", str(e["value"])):       # "none on site" is a statement, not a number
        n = num(e["value"])
        if n is None:
            return "value has no number"
        digits = re.sub(r"[^\d.]", "", re.search(r"\d[\d,]*\.?\d*", str(e["value"])).group(0)).rstrip(".")
        if digits not in re.sub(r",", "", e["sentence"]):
            return "the value's digits are not in the sentence"
    return ""


def main():
    R = pd.read_csv(os.path.join(OUT, "review_list.csv")).fillna("")
    docs = pd.read_csv(os.path.join(CACHE, "docs.csv")).set_index("key")
    PT = pd.read_csv(os.path.join(HERE, "plan_tasks.csv")).fillna("") if os.path.exists(os.path.join(HERE, "plan_tasks.csv")) else pd.DataFrame(columns=["case", "key", "plan_name", "share_of_case_inside_plan", "plan_status", "plan_action_date"])
    global DOCNAME, DOCURL
    DOCNAME = {r.key: f"plan set: {r.plan_name} ({r.plan_status}{', ' + str(r.plan_action_date) if r.plan_action_date else ''})" for r in PT.itertuples()}
    DOCNAME.update(PACKETS)
    DOCURL = docs.url.to_dict()
    quotes, rejected, notes, plan_notes = [], [], {}, {}
    for fn in sorted(glob.glob(os.path.join(HERE, "extracted", "*.json"))):
        j = json.load(open(fn))
        if str(j.get("doc", j["case"])).startswith("plan"):
            plan_notes.setdefault(j["case"], []).append(f"{j['doc']}: {j.get('notes', '')}")
        else:
            notes[j["case"]] = j.get("notes", "")
        for e in j.get("entries", []):
            e = dict(e, case=j["case"], doc=e.get("doc") or j.get("doc") or j["case"])
            why = "unknown field" if e.get("field") not in FIELDS else "scope must be case, parent or plan" if e.get("scope") not in ("case", "parent", "plan") else check(e, e["doc"])
            (rejected if why else quotes).append(dict(case=e["case"], scope=e["scope"], field=e["field"], value=e["value"], primary=bool(e.get("primary", False)), where=e.get("where", ""), note=e.get("note", ""),
                                                      document=e["doc"], document_name=DOCNAME.get(e["doc"], "rezoning case file " + e["doc"]), document_url=DOCURL.get(e["doc"], ""), page=e["page"], sentence=re.sub(r"\s+", " ", e["sentence"]).strip(),
                                                      **({"rejected_because": why} if why else {}), read_by=("OCR" if (open(os.path.join(CACHE, "text", e["doc"], f"p{int(e['page']):04d}.txt.how")).read() if os.path.exists(os.path.join(CACHE, "text", e["doc"], f"p{int(e['page']):04d}.txt.how")) else "") == "OCR" else "text layer")))
    Q = pd.DataFrame(quotes); J = pd.DataFrame(rejected)
    Q.to_csv(os.path.join(OUT, "rca_quotes.csv"), index=False)
    J.to_csv(os.path.join(OUT, "rca_quotes_rejected.csv"), index=False)
    rows = []
    for r in R.itertuples():
        row = r._asdict(); row.pop("Index")
        d = docs.loc[r.case] if r.case in docs.index else None
        row.update(source_doc_url=r.town_case_file_url, source_doc_pages=(int(d.pages) if d is not None and d.is_pdf else ""), source_doc_pages_read_by_ocr=(int(d.pages_ocr) if d is not None and d.is_pdf else ""),
                   document_read=("yes" if r.case in notes else "no: the Town's link returns 404" if d is not None and not d.is_pdf else "no"))
        q = Q[Q.case == r.case] if len(Q) else Q
        pt = PT[PT.case == r.case]
        row["plan_sets_read"] = "; ".join(f"{x.key} {x.plan_name} (covers {float(x.share_of_case_inside_plan):.0%} of the case)" for x in pt.itertuples() if any(n.startswith(x.key + ":") for n in plan_notes.get(r.case, [])))
        for scope, pre in (("case", ""), ("parent", "parent_"), ("plan", "plan_")):
            if (scope == "parent" and not r.parent_project) or (scope == "plan" and not row["plan_sets_read"]):
                continue
            for f in FIELDS:
                g = q[(q.scope == scope) & (q.field == f)] if len(q) else q
                g = g.sort_values("primary", ascending=False, kind="stable") if len(g) else g            # the whole-site figure first, where a reviewer marked one
                row[pre + f] = " | ".join(dict.fromkeys(str(v) for v in g.value)) if len(g) else NOT_FOUND
                row[pre + f + "_page"] = "; ".join(dict.fromkeys(f"{'' if d0 == r.case else d0 + ' '}p{p}" for d0, p in zip(g.document, g.page))) if len(g) else ""
        # maximum further clearing: current forest less the RCA acres the document requires, on the boundary the RCA figure is for
        # one plan set whose site is the case (each at least 80% inside the other): only then is its RCA figure set against the case's forest
        whole = len(pt) == 1 and float(pt.share_of_case_inside_plan.iloc[0]) >= 0.8 and float(pt.share_of_plan_inside_case.iloc[0]) >= 0.8
        for scope, pre, cur in (("case", "", r.current_forest_acres), ("parent", "parent_", r.parent_current_forest_acres if r.parent_project else ""), ("plan", "plan_", r.current_forest_acres if whole else "")):
            v = row.get(pre + "rca_required_ac", NOT_FOUND)
            n = num(v.split(" | ")[0]) if v and v != NOT_FOUND and not re.match(r"(?i)\s*(no|none|not)\b", v) else None
            row[pre + "maximum_further_clearing_ac"] = round(float(cur) - n, 1) if n is not None and cur != "" else ""
        row["conflict_check"] = CONFLICT_CHECK.get(r.case, "")
        row["current_case_file_url"] = CURRENT_URLS.get(r.case, "")
        row["reader_notes"] = notes.get(r.case, "")
        row["plan_reader_notes"] = " || ".join(plan_notes.get(r.case, []))
        rows.append(row)
    F = pd.DataFrame(rows)
    for c in ("rca_required_ac", "buffer_floodplain_ac", "limits_of_disturbance_ac"):          # the blank columns of review_list.csv are replaced by the sourced ones
        pass
    F = F.drop(columns=[c for c in ("buffer_floodplain_ac",) if c in F.columns])        # replaced by stream_buffer_ac, floodplain_ac and wetland_ac; reviewer and notes stay blank for Adam
    F.to_csv(os.path.join(OUT, "review_list_filled.csv"), index=False)

    L = []
    say = L.append
    has = lambda col: ((F[col].fillna("").astype(str).isin(["", NOT_FOUND]) == False) & ~F[col].fillna("").astype(str).str.match(r"(?i)\s*(no|none|not)\b")) if col in F else pd.Series(False, index=F.index)
    exempt = F[F.get("plan_rca_required_ac", pd.Series("", index=F.index)).fillna("").astype(str).str.match(r"(?i)\s*none")]
    c_, p_, s_ = has("rca_required_ac"), has("parent_rca_required_ac"), has("plan_rca_required_ac")
    anyf = F[c_ | p_ | s_]
    rz_docs = docs[docs.index.isin(F.case)]; pl_docs = docs[docs.index.isin(PT.key)]          # docs.csv also holds files fetched for the exemption scan
    say(f"Tree-save numbers for the {len(F)} review-list cases, read from the Town's own documents.")
    say(f"Rezoning case files: {int(rz_docs.is_pdf.sum())} read ({int(rz_docs.pages.sum())} pages, {int(rz_docs.pages_ocr.sum())} by OCR); {int((~rz_docs.is_pdf).sum())} links return 404 ({', '.join(rz_docs.index[~rz_docs.is_pdf])}).")
    say(f"Plan sets, where the rezoning file had no RCA acres: {int(pl_docs.is_pdf.sum())} fetched, first sheets read; {int((F.plan_sets_read != '').sum())} cases have at least one read.")
    say(f"Quotes kept: {len(Q)}, each found word for word on its page. Rejected by the check: {len(J)} (rca_quotes_rejected.csv).")
    qa = Q[(Q.field == "rca_required_ac") & ~Q.value.astype(str).str.match(r"(?i)\s*(no|none|not)\b")]
    in_rz = set(qa.case[~qa.document.str.startswith("plan")]); in_plan = set(qa.case[qa.document.str.startswith("plan")])
    say(f"\nRCA acres FOUND: {len(anyf)} of {len(F)} cases. Source: the rezoning case file, ordinance or staff report for {len(in_rz)}, a plan set only for {len(in_plan - in_rz)}.")
    say(f"   The figure is for the case area in {int(c_.sum())}, for the parent project in {int(p_.sum())}, and for a plan's own site (one phase, or a site that is not the case) in {int((s_ & ~c_ & ~p_).sum())}.")
    comp = F[(pd.to_numeric(F.get("maximum_further_clearing_ac"), errors="coerce").notna()) | (pd.to_numeric(F.get("parent_maximum_further_clearing_ac"), errors="coerce").notna()) | (pd.to_numeric(F.get("plan_maximum_further_clearing_ac"), errors="coerce").notna())]
    say(f"   'Maximum further clearing' could be worked out for {len(comp)} of them: the rest have a figure for part of the case only.")
    say(f"RCA acres NOT FOUND: {len(F) - len(anyf)} cases" + (f", of which {len(exempt)} is stated as not required" if len(exempt) else "") + ".")
    say(f"RCA percent found, with or without acres: {int((has('rca_required_pct') | has('parent_rca_required_pct') | has('plan_rca_required_pct')).sum())} cases.")
    say("\nFound. 'Maximum further clearing' = current forest (2026Q3, this analysis) minus the RCA acres the document requires, on the boundary the figure is for:")
    T = []
    for r in anyf.itertuples():
        d = r._asdict()
        for pre, bnd, cur in (("", "case area", r.current_forest_acres), ("parent_", "parent: " + str(r.parent_project)[:30], r.parent_current_forest_acres), ("plan_", "plan set" + ("" if d.get("plan_maximum_further_clearing_ac", "") != "" else " (part of the case, or several)"), r.current_forest_acres)):
            v = d.get(pre + "rca_required_ac", NOT_FOUND)
            if v in ("", NOT_FOUND) or pd.isna(v) or re.match(r"(?i)\s*(no|none|not)\b", str(v)):
                continue
            T.append(dict(case=r.case + ("*" if r.case in CONFLICT_CHECK else ""), name=r.name[:26], boundary=bnd, stated_acres=str(d.get(pre + "project_acres", ""))[:34], rca_pct=str(d.get(pre + "rca_required_pct", ""))[:30], rca_acres_required=str(v)[:40], page=d.get(pre + "rca_required_ac_page", ""),
                          current_forest=cur if d.get(pre + "maximum_further_clearing_ac", "") != "" else "", maximum_further_clearing=d.get(pre + "maximum_further_clearing_ac", "")))
    if T:
        say(pd.DataFrame(T).to_string(index=False))
    say("   * disclosed: " + "; ".join(f"{k}: {v}" for k, v in CONFLICT_CHECK.items()))
    if len(exempt):
        say("\nStated as not required: " + "; ".join(f"{r.case} {r.name} (plan set: RCA required N/A)" for r in exempt.itertuples()))
    say("\nRCA acres not found in any document read:")
    nf = F[~F.case.isin(anyf.case)]
    pcts = nf.apply(lambda r: next((str(r[c]) for c in ("rca_required_pct", "parent_rca_required_pct", "plan_rca_required_pct") if c in nf and str(r[c]) not in ("", NOT_FOUND, "nan")), NOT_FOUND), axis=1)
    say(nf[["case", "name", "current_forest_acres", "document_read", "plan_sets_read"]].assign(name=lambda d: d.name.str[:28], rca_percent=pcts.str[:60], plan_sets_read=lambda d: d.plan_sets_read.str[:60]).to_string(index=False))
    say("\nHow to read it: RCA can be met with land that is not forest (buffers, ponds, lawns, where the document allows it), and forest outside the RCA is not all")
    say("buildable. 'Maximum further clearing' is an upper bound from two numbers, not a forecast. A negative value means less forest is standing than the RCA figure.")
    open(os.path.join(OUT, "rca_summary.txt"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
