#!/usr/bin/env python
"""build_office.py: add the RCA readings to ../out/office_period_cases.csv and write the one-page summary.

    ../../apex-canopy/df-venv/bin/python build_office.py        (after ../office_period.py)

Every reading comes from extracted/*.json and is checked against its page first, as in build_filled.py. The table gets
one RCA percent group and one grading group per case:
  RCA percent group  from the required-percent readings: the case's own file first, then a plan set, then the parent
                     project. One figure -> that group. A base figure plus a mass-grading addition -> the total where the
                     document states it, else the base. Different figures for different districts -> "mixed by district".
                     A stated exemption with nothing offered -> "none/exempt". No reading -> "not found".
                     GROUP_OVERRIDES holds the cases Claude settled by reading the quotes, with the reason.
  Grading group      "mass graded", "stage graded", "conditional or both", "not stated", from the grading readings.
Writes ../out/office_period_cases.csv (RCA columns added), ../out/office_rca_quotes.csv, and section 4 of
../out/office_period_summary.txt.
"""
import glob, json, os, re, sys
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_filled as BF  # noqa: E402
from build_exemptions import STATEMENTS, EXEMPT, OVERLAY  # noqa: E402
OUT = os.path.join(HERE, "..", "out")
HOLD = {"23CZ13": "not read: conflict hold (Seymour Mixed Use PUD)",
        "24CZ20": "not read: conflict hold (its PUD text names the Seymour PUD as adjacent and ties a signal payment to it)"}
GROUPS = ["none/exempt", "5", "15", "20", "25", "30", "35", "40", "other", "mixed by district", "not found"]
VERIDEA = ("other", "Veridea's SD plan sets a fixed 100 acres for the whole development, not a percent")
GROUP_OVERRIDES = {       # case -> (group, reason): settled by Claude from the quotes, where the rule above cannot decide
    "25CZ18": VERIDEA, "26CZ03": VERIDEA, "26CZ10": VERIDEA,
    "24CZ23": ("not found", "the rezoning moved this ground out of Veridea's SD district (LI/SD-CZ to LI/CZ), so Veridea's fixed 100 acres is not its term; its own file states no RCA figure (a plan sheet shows 7.96 acres of RCA without saying required or provided)"),
    "25CZ15": ("other", "its only condition is that the Veridea SD plan applies: the fixed 100 acres for the whole development"),
    "20CZ05": ("other", "27% for the parent West Village PUD, including 2% if mass graded; nothing for the 2.78-acre petition itself"),
    "21CZ03": ("other", "2.0%: stated exempt at 1 unit per acre or less, with 2% required only because the site is mass graded"),
    "21CZ27": ("other", "10% on the plan set"),
    "20CZ14": ("other", "34% on both approved plan sets (24.71 ac); the PD text gives 30% plus 5% if single-family sections are mass graded"),
    "21CZ01": ("30", "25% base plus 5% additional; the plan set states the total as 30% (13.06 ac) and the site is mass graded"),
    "21CZ25": ("none/exempt", "plan set: the Villages of Apex PUD's overall RCA requirement is stated as already met, so none is required for this project"),
    "26CZ01": ("none/exempt", "applicant's statement in the application: RCA not required because of the density; nothing offered"),
    "24CZ19": ("mixed by district", "25% of the non-residential part; the residential part carries only the 5% mass-grading amount"),
    "25CZ05": ("25", "25% read from a draft concept plan in the file; the file is an application packet with no RCA condition"),
}
# Plan sets fetched for a case that turned out not to be that case's site are set aside (file renamed, not deleted):
#   22CZ24.plan452 is an offsite sewer plan (0 AC RCA for a utility corridor); 24CZ08.plan710 is the Hopson Gateway plan (24CZ20, held).


REJECTED = []


def load():
    quotes, notes = [], {}
    for fn in sorted(glob.glob(os.path.join(HERE, "extracted", "*.json"))):
        j = json.load(open(fn))
        notes.setdefault(j["case"], []).append(f"{j.get('doc', j['case'])}: {j.get('notes', '')}")
        for e in j.get("entries", []):
            e = dict(e, case=j["case"], doc=e.get("doc") or j.get("doc") or j["case"])
            ok = e.get("field") in BF.FIELDS and e.get("scope") in ("case", "parent", "plan") and not BF.check(e, e["doc"])
            if not ok:
                REJECTED.append((e["case"], e.get("field"), e["doc"], e.get("page")))
            if ok:
                quotes.append(dict(case=e["case"], scope=e["scope"], field=e["field"], value=str(e["value"]), primary=bool(e.get("primary", False)), document=e["doc"], page=e["page"],
                                   sentence=re.sub(r"\s+", " ", e["sentence"]).strip(), where=e.get("where", ""), note=e.get("note", "")))
    return pd.DataFrame(quotes), notes


def pcts(values):
    out = []
    for v in values:
        out += [float(x) for x in re.findall(r"(\d{1,2}(?:\.\d+)?)\s?%", v)]
    return out


def group_for(case, q, exempt):
    if case in GROUP_OVERRIDES:
        return GROUP_OVERRIDES[case]
    if case in exempt and exempt[case] in (EXEMPT, OVERLAY):
        return "none/exempt", "stated exempt, nothing offered"
    for scope in ("case", "plan", "parent"):
        g = q[(q.field == "rca_required_pct") & (q.scope == scope)].sort_values("primary", ascending=False, kind="stable")
        if not len(g):
            continue
        vals = [round(x) for x in pcts(list(g.value))]
        vals = [v for v in vals if v in (5, 10, 15, 20, 22, 25, 30, 35, 40, 45, 50)]
        if not vals:
            continue
        distinct = sorted(set(vals))
        basis = f"{scope} reading"
        if len(distinct) == 1:
            v = distinct[0]
        elif any(re.search(r"district|residential|commercial|non-res|townhome|single", x, re.I) for x in g.value) and not any(re.search(r"mass", x, re.I) for x in g.value):
            return "mixed by district", f"{basis}: {' | '.join(g.value)[:120]}"
        else:
            v = vals[0]
            basis += f", first of {distinct}"
        return (str(v) if str(v) in GROUPS else "other"), basis
    if q[(q.field == "rca_required_ac")].shape[0]:
        return "other", "acres stated without a percent"
    return "not found", ""


def grading_for(q):
    """Plan sets first (they state what was approved), then the case file. A plan that says both, or two plans that differ, is 'both, by phase'."""
    def kind(v):
        v = v.lower()
        if re.search(r"heading|typical-lot|typical lot|planting", v):
            return ""
        mass, stage = "mass" in v, bool(re.search(r"stage|staged", v))
        return "both" if mass and stage else "mass" if mass else "stage" if stage else ""
    g = q[q.field == "grading_type"].sort_values("primary", ascending=False, kind="stable")
    plan = [k for k in (kind(v) for v in g.value[g.scope == "plan"]) if k]
    if plan:
        ks = set(plan)
        return "both, by phase" if len(ks) > 1 or "both" in ks else "mass graded" if ks == {"mass"} else "stage graded"
    rest = list(g.value[g.scope != "plan"])
    if not rest:
        return "not stated"
    v = " | ".join(rest).lower()
    if re.search(r"\bif\b|conditional|expected|not stated outright|assumed", v):
        return "conditional in the text"
    k = kind(v)
    return "both, by phase" if k == "both" else "mass graded" if k == "mass" else "stage graded" if k == "stage" else "not stated"


def main():
    R = pd.read_csv(os.path.join(OUT, "office_period_cases.csv")).fillna("")
    R = R[[c for c in R.columns if not c.startswith(("rca_", "grading", "tree_", "documents_", "reader_", "exemption"))]]
    Q, notes = load()
    exempt = {s["case"]: s["kind"] for s in STATEMENTS}
    rows = []
    for r in R.itertuples():
        q = Q[Q.case == r.case] if len(Q) else Q
        row = r._asdict(); row.pop("Index")
        if r.case in HOLD:
            row.update(rca_percent_group="not read", rca_percent_basis=HOLD[r.case], grading_group="not read", documents_read=HOLD[r.case])
            rows.append(row); continue
        grp, basis = group_for(r.case, q, exempt)
        row.update(rca_percent_group=grp, rca_percent_basis=basis, grading_group=grading_for(q))
        for f in ("rca_required_pct", "rca_required_ac", "rca_provided", "rca_may_count", "grading_type", "rca_bonus_or_reduction", "rca_exemption", "tree_condition"):
            g = q[q.field == f].sort_values("primary", ascending=False, kind="stable")
            row[f] = " | ".join(dict.fromkeys(f"[{s}] {v}" if s != "case" else v for s, v in zip(g.scope, g.value)))[:900] if len(g) else "not found"
            row[f + "_page"] = "; ".join(dict.fromkeys(f"{'' if d == r.case else d + ' '}p{p}" for d, p in zip(g.document, g.page))) if len(g) else ""
        if r.case in exempt:
            s = next(x for x in STATEMENTS if x["case"] == r.case)
            row["rca_exemption"] = (f"{s['kind']}: \"{s['sentence']}\"" + ("" if row["rca_exemption"] == "not found" else " | " + row["rca_exemption"]))[:900]
            row["rca_exemption_page"] = f"{'' if s['doc'] == r.case else s['doc'] + ' '}p{s['page']}" + ("; " + row["rca_exemption_page"] if row["rca_exemption_page"] else "")
        row["documents_read"] = "; ".join(sorted({n.split(":")[0] for n in notes.get(r.case, [])})) or "none found to read"
        row["reader_notes"] = " || ".join(notes.get(r.case, []))[:1500]
        rows.append(row)
    F = pd.DataFrame(rows)
    F.to_csv(os.path.join(OUT, "office_period_cases.csv"), index=False)
    Q[Q.case.isin(set(F.case) - set(HOLD))].to_csv(os.path.join(OUT, "office_rca_quotes.csv"), index=False)

    H = F[~F.case.isin(HOLD)]
    num = dict(cases=("case", "size"), forest_2017=("forest_2017_acres", "sum"), forest_at_approval=("forest_at_approval_acres", "sum"), cleared_since_approval=("cleared_since_approval_acres", "sum"), standing_now=("standing_now_acres", "sum"))
    L = []
    say = L.append
    say(f"\n4. RCA terms of the {len(H)} conditional zoning cases approved on or after 2019-12-03 with 2 ac or more of 2017 forest ({', '.join(HOLD)} held out, not read).")
    say(f"   Documents read for {int((H.documents_read != 'none found to read').sum())} of them; {len(Q[Q.case.isin(H.case)])} quotes, each found word for word on its page (office_rca_quotes.csv).")
    say("   Acres are sums of case rows (some cases share ground). Forest is 2017 baseline forest inside the case boundary.")
    say("\n   By RCA percent required:")
    t = H.groupby("rca_percent_group").agg(**num).reindex([g for g in GROUPS if g in set(H.rca_percent_group)]).round(1)
    say(t.to_string())
    say("\n   By grading:")
    say(H.groupby("grading_group").agg(**num).reindex([g for g in ("mass graded", "stage graded", "both, by phase", "conditional in the text", "not stated") if g in set(H.grading_group)]).round(1).to_string())
    say("\n   RCA percent group by grading group (cases):")
    say(pd.crosstab(H.rca_percent_group, H.grading_group).reindex([g for g in GROUPS if g in set(H.rca_percent_group)]).to_string())
    ex = H[H.rca_exemption != "not found"]
    say(f"\n   Exemption or mass-grading-only statements: {len(ex)} cases: " + ", ".join(ex.case))
    tc = H[H.tree_condition != "not found"]
    say(f"   A tree condition or tree note recorded: {len(tc)} cases. RCA acres stated: {int((H.rca_required_ac != 'not found').sum())} cases.")
    say("\n   Cases by group:")
    for g in [x for x in GROUPS if x in set(H.rca_percent_group)]:
        d = H[H.rca_percent_group == g]
        say(f"   {g}: " + ", ".join(f"{r.case} ({r.forest_at_approval_acres:g})" for r in d.sort_values("forest_at_approval_acres", ascending=False).itertuples()))
    rej = [r for r in REJECTED if r[0] in set(H.case)]
    say(f"\n   Quotes thrown out by the page check for these cases: {len(rej)}" + ("" if not rej else ": " + "; ".join(f"{c} {f} {d} p{p}" for c, f, d, p in rej)))
    fn = os.path.join(OUT, "office_period_summary.txt")
    txt = open(fn).read().split("\n4. RCA terms")[0].rstrip("\n")
    open(fn, "w").write(txt + "\n" + "\n".join(L) + "\n")
    print("\n".join(L))

    # ---- the one-page summary
    T = pd.read_csv(os.path.join(OUT, "clearings_entitlement.csv")).fillna("")
    G = pd.read_csv(os.path.join(OUT, "office_governing_cases.csv")).fillna("")
    Y = pd.read_csv(os.path.join(OUT, "office_clearings_by_year.csv"))
    after, before = G[G.period.str.startswith("on or after")], G[G.period.str.startswith("before")]
    amend = G[(G.period.str.startswith("on or after")) & (G.period_at_parent.str.startswith("before"))]
    P = ["OFFICE PERIOD: forest and RCA terms of cases approved on or after 2019-12-03", "(private working summary; nothing here names 23CZ13 or 24CZ20 terms, which are held under the conflict rule)", ""]
    P.append(f"The release's 929 acres of clearings (late 2022 to October 2026), by the approval date of the case on the ground:")
    P.append(f"  approved on or after 2019-12-03: {after.acres.sum():,.0f} ac ({int(after.clearings.sum())} clearings, {len(after)} cases); before: {before.acres.sum():,.0f} ac ({int(before.clearings.sum())} clearings, {len(before)} cases); no case: {T.acres.sum() - after.acres.sum() - before.acres.sum():,.0f} ac.")
    P.append(f"  Of the {after.acres.sum():,.0f}, {amend.acres.sum():,.0f} ac are under amendments to projects first approved before the cut (Veridea, Horton Park, Apex Light Industrial); {after.acres.sum() - amend.acres.sum():,.0f} ac are under cases first approved in the period.")
    yb, ya = Y[Y.year <= 2019].event_acres.sum(), Y[Y.year >= 2020].event_acres.sum()
    P.append("")
    P.append(f"All forest cleared in the jurisdiction since autumn 2017 (2017 baseline): {Y.event_acres.sum():,.0f} ac. Late 2017 through 2019: {yb:,.0f} ac. 2020 to October 2026: {ya:,.0f} ac.")
    P.append("  By year: " + ", ".join(f"{int(r.year)} {r.event_acres:,.0f}" for r in Y.itertuples()) + "  (2017 is one quarter; 2026 runs to October 24)")
    P.append("")
    P.append(f"Conditional zoning cases approved on or after 2019-12-03 with 2 ac or more of 2017 forest: {len(F)} ({len(H)} read; {', '.join(HOLD)} held).")
    P.append(f"  Forest at approval {H.forest_at_approval_acres.sum():,.0f} ac, cleared since approval {H.cleared_since_approval_acres.sum():,.0f} ac, standing now {H.standing_now_acres.sum():,.0f} ac (sums of case rows; some cases share ground).")
    P.append("")
    P.append("RCA percent required            cases   forest at approval   cleared since   standing now")
    for g in [x for x in GROUPS if x in set(H.rca_percent_group)]:
        d = H[H.rca_percent_group == g]
        P.append(f"  {g + ('%' if g.isdigit() else ''):28s} {len(d):5d} {d.forest_at_approval_acres.sum():16,.0f} {d.cleared_since_approval_acres.sum():15,.0f} {d.standing_now_acres.sum():14,.0f}")
    P.append("  'other' is mostly Veridea: a fixed 100 acres for the whole development (4 cases, "
             f"{H[H.case.isin(['25CZ18', '26CZ03', '26CZ10', '25CZ15'])].forest_at_approval_acres.sum():,.0f} ac of forest at approval), plus 2%, 10%, 27% and 34%.")
    P.append("  'not found' means the documents read give no RCA figure: mostly short ordinances with no plan record.")
    P.append("")
    P.append("Grading                         cases   forest at approval   cleared since   standing now")
    for g in [x for x in ("mass graded", "stage graded", "both, by phase", "conditional in the text", "not stated") if x in set(H.grading_group)]:
        d = H[H.grading_group == g]
        P.append(f"  {g:28s} {len(d):5d} {d.forest_at_approval_acres.sum():16,.0f} {d.cleared_since_approval_acres.sum():15,.0f} {d.standing_now_acres.sum():14,.0f}")
    P.append("")
    P.append(f"Stated exemptions or mass-grading-only amounts: {len(ex)} cases ({', '.join(ex.case)}).")
    P.append(f"RCA acres stated for {int((H.rca_required_ac != 'not found').sum())} cases; a tree condition or tree note for {len(tc)}.")
    P.append("")
    P.append("Read with care: the percent is what the zoning text or approved plan states, not what was built. RCA may include buffers, ponds and play lawns.")
    P.append("An approval date and a clearing date show order, not cause. Disclosed: 24CZ19 and 24CZ08; 23CZ13 and 24CZ20 are held.")
    P.append("Sources and quotes: office_period_cases.csv, office_rca_quotes.csv (every quote checked word for word against its page).")
    open(os.path.join(OUT, "office_period_onepage.txt"), "w").write("\n".join(P) + "\n")


if __name__ == "__main__":
    main()
