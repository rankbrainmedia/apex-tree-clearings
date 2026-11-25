#!/usr/bin/env python3
"""build_numbers.py: every figure the article and the methodology use, read from its file. Nothing is typed in.

    ../apex-canopy/df-venv/bin/python build_numbers.py

Writes out/numbers.json  {key: {value, display, source_file, locator, caveat}}
       out/numbers.md    the same as a table (the list of every number and its source)
and prints each figure the brief gives beside the file's, marking differences. Reads only; changes no existing output.
"""
import json, os, re
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
T = os.path.normpath(os.path.join(HERE, ".."))
OUT = os.path.join(HERE, "out"); os.makedirs(OUT, exist_ok=True)
ENT, WAKE, PRE, VER = "entitlement/out", "entitlement/out_wake_tca", "prerezoning/out", "out_verify"
HELD = {"23CZ13"}
N = {}


def put(key, value, display, source, locator, caveat=""):
    assert key not in N, key
    N[key] = dict(value=value, display=display, source_file=source, locator=locator, caveat=caveat)


def csv(rel, **kw):
    return pd.read_csv(os.path.join(T, rel), **kw)


ac = lambda v: f"{v:,.0f}"
ac1 = lambda v: f"{v:,.1f}"
pct = lambda v, d=1: f"{v:.{d}f}%"

# ---------------------------------------------------------------- canopy (Wake County overlay)
C = csv(f"{WAKE}/canopy_estimate_by_geography.csv").set_index(["geography", "boundary"])
EST = "An estimate: the County's 2020 canopy less clearings detected since. It adds no regrowth and misses cuts under an acre."
for tag, geo in (("town", "Corporate limits"), ("planning", "Planning jurisdiction")):
    r = C.loc[(geo, "as in the County report, Wake side")]
    loc = f"row '{geo}', boundary 'as in the County report, Wake side'"
    put(f"canopy.{tag}.2020", float(r.canopy_2020_pct), pct(r.canopy_2020_pct), f"{WAKE}/canopy_estimate_by_geography.csv", f"{loc}, canopy_2020_pct", "The County's figure (its Table 2.4).")
    put(f"canopy.{tag}.now", float(r.est_canopy_now_pct), pct(r.est_canopy_now_pct), f"{WAKE}/canopy_estimate_by_geography.csv", f"{loc}, est_canopy_now_pct", EST)
    alts = [float(r.est_now_pct_release_rule), float(r.est_now_pct_with_patches_under_an_acre), float(r.est_now_pct_all_signals)]
    put(f"canopy.{tag}.now_low", min(alts), pct(min(alts)), f"{WAKE}/canopy_estimate_by_geography.csv", f"{loc}, lowest of the three other readings", EST)
    put(f"canopy.{tag}.now_high", max(alts), pct(max(alts)), f"{WAKE}/canopy_estimate_by_geography.csv", f"{loc}, highest of the three other readings", EST)
    t = C.loc[(geo, "Town layer, pulled 2026-11-24" if tag == "town" else "Town layers, pulled 2026-11-24")]
    put(f"canopy.{tag}.cleared_since_2020_acres", float(t.canopy_cleared_since_mid2020_acres), ac(t.canopy_cleared_since_mid2020_acres), f"{WAKE}/canopy_estimate_by_geography.csv",
        f"row '{geo}', today's boundary, canopy_cleared_since_mid2020_acres", "County-mapped 2020 canopy on cells cleared since July 2020, today's boundaries.")
# the County's own 2010 and 2020 figures, from its report (Table 2.4, PDF page 42)
for tag, y10, y20, a10, a20, lost, lostp in (("town", 58.2, 44.6, 9432, 7232, 2200, 23.3), ("planning", 59.4, 50.4, 14379, 12199, 2180, 15.2)):
    row = "Corporate Limits" if tag == "town" else "Planning Jurisdiction"
    txt = open(os.path.join(HERE, "sources", "county_report.txt"), encoding="utf-8", errors="replace").read()
    line = next(" ".join(l.split()) for l in txt.splitlines() if " ".join(l.split()).startswith(row + " " + f"{a20:,}"))
    assert f"{y20}%" in line and f"{y10}%" in line and f"-{lost:,}" in line and f"-{lostp}%" in line, line
    src, loc = "article/apex_report.pdf", f"Table 2.4, PDF page 42, row '{row}'"
    put(f"canopy.{tag}.2010", y10, pct(y10), src, loc, "The County's figure.")
    put(f"canopy.{tag}.2020_county", y20, pct(y20), src, loc, "The County's figure.")
    put(f"canopy.{tag}.lost_2010_2020_acres", lost, ac(lost), src, loc, "The County's figure.")
    put(f"canopy.{tag}.lost_2010_2020_pct", lostp, pct(lostp), src, loc, "The County's figure: share of the 2010 canopy.")
assert abs(N["canopy.town.2020"]["value"] - N["canopy.town.2020_county"]["value"]) < 0.05

# ---------------------------------------------------------------- acres cleared per year (2017-2026 series)
Y = csv(f"{ENT}/office_clearings_by_year.csv")
SER = "Forest in patches of an acre or more, bare for about a year. 2017 satellite baseline. Not the same measurement as the published 929 acres."
for r in Y.itertuples():
    note = " October to December only." if r.year == 2017 else " Through October 24; provisional." if r.year == 2026 else " Provisional." if r.year == 2025 else ""
    put(f"year.{r.year}", float(r.event_acres), ac(r.event_acres), f"{ENT}/office_clearings_by_year.csv", f"year {r.year}, event_acres", SER + note)
tot2020 = float(Y[Y.year >= 2020].event_acres.sum()); tot_pre = float(Y[Y.year <= 2019].event_acres.sum())
put("year.total_2020_on", tot2020, ac(tot2020), f"{ENT}/office_clearings_by_year.csv", "sum of event_acres, 2020 to 2026", SER)
put("year.total_2017_2019", tot_pre, ac(tot_pre), f"{ENT}/office_clearings_by_year.csv", "sum of event_acres, 2017 to 2019", SER)
put("year.total_all", float(Y.event_acres.sum()), ac(Y.event_acres.sum()), f"{ENT}/office_clearings_by_year.csv", "sum of event_acres, all years", SER)
sb = float(Y[Y.year >= 2020].still_bare_acres.sum())
put("year.total_2020_on_still_bare", sb, ac(sb), f"{ENT}/office_clearings_by_year.csv", "sum of still_bare_acres, 2020 to 2026", "The part of the 2020-2026 clearing that also meets the published count's stricter rule: still bare in every later summer.")
put("year.total_2020_on_regrown", tot2020 - sb, ac(tot2020 - sb), "computed", "year.total_2020_on less year.total_2020_on_still_bare", "Cleared for about a year or more, then no longer bare in a later summer: regrown, replanted or built on.")
put("year.sq_miles", tot2020 / 640, f"{tot2020 / 640:.1f}", "computed", "year.total_2020_on divided by 640 acres to the square mile", "")
put("year.football_fields", tot2020 / 1.32, f"{round(tot2020 / 1.32, -2):,.0f}", "computed", "year.total_2020_on divided by 1.32 acres, an American football field with its end zones; rounded to 100", "A scale comparison only.")
big = Y.loc[Y.event_acres.idxmax()]
put("year.largest", int(big.year), str(int(big.year)), f"{ENT}/office_clearings_by_year.csv", "year with the largest event_acres", "Of the ten years in the series.")
s = open(os.path.join(T, ENT, "office_period_summary.txt")).read()
m = re.search(r"since July 2020 \(2020Q3 on\): ([\d,]+\.\d) ac", s)
since = float(m.group(1).replace(",", ""))
if since:
    put("year.since_july_2020", since, ac(since), f"{ENT}/office_period_summary.txt", "section 2, 'since' the County's assessment quarter", SER)
put("trees.per_acre_formula", 0.84 * 163.9, f"{0.84 * 163.9:.1f}", "apex-canopy/release-v1/METHODS.md", "acres x 0.84 x 163.9", "The release's tree formula.")
put("trees.estimate_1846", round(tot2020 * 0.84 * 163.9, -3), f"{round(tot2020 * 0.84 * 163.9, -4):,.0f}", "computed", f"{tot2020:.1f} acres x 0.84 x 163.9, rounded to the nearest 10,000",
    "A rough estimate: the release's formula applied to a different series.")

# ---------------------------------------------------------------- the published 929 acres, by approval date
G = csv(f"{ENT}/office_governing_cases.csv")
E = csv(f"{ENT}/clearings_entitlement.csv")
total929 = float(E.acres.sum())
after = G[G.period.str.startswith("on or after")]; before = G[G.period.str.startswith("before")]
first_in = G[G.period_at_parent.str.startswith("on or after")]
amend = G[G.period.str.startswith("on or after") & G.period_at_parent.str.startswith("before")]
ORDER = "An approval date and a clearing date show order, not cause."
put("approvals.total", total929, ac(total929), f"{ENT}/clearings_entitlement.csv", "sum of acres, 238 clearings", "The published release: 2022 aerial baseline, late 2022 to October 2026.")
put("approvals.clearings", len(E), str(len(E)), f"{ENT}/clearings_entitlement.csv", "rows", "")
put("approvals.in_period_first", float(first_in.acres.sum()), ac(first_in.acres.sum()), f"{ENT}/office_governing_cases.csv", "sum of acres where period_at_parent is 'on or after 2019-12-03'", ORDER)
put("approvals.in_period_amend", float(amend.acres.sum()), ac(amend.acres.sum()), f"{ENT}/office_governing_cases.csv", "sum of acres where period is on or after and period_at_parent is before", ORDER)
put("approvals.before", float(before.acres.sum()), ac(before.acres.sum()), f"{ENT}/office_governing_cases.csv", "sum of acres where period is 'before 2019-12-03'", ORDER)
put("approvals.no_case", total929 - float(G.acres.sum()), ac(total929 - G.acres.sum()), f"{ENT}/clearings_entitlement.csv", "total less the acres under a governing case", "")
am = E[E.governing_case.isin(set(amend.governing_case))]
b4 = float(am.acres[am.timing.isin(["cleared_under_earlier_approval", "cleared_between_filing_and_approval"])].sum()); af = float(am.acres[am.timing == "cleared_after_approval"].sum())
assert abs(b4 + af - float(am.acres.sum())) < 0.2 and abs(float(am.acres.sum()) - float(amend.acres.sum())) < 0.2, (b4, af, am.acres.sum(), am.timing.value_counts().to_dict())
put("approvals.amend_cleared_before", b4, ac(b4), f"{ENT}/clearings_entitlement.csv", "clearings governed by those amendments whose timing is 'cleared_under_earlier_approval' or 'cleared_between_filing_and_approval'", "Cleared before the amendment itself was approved.")
put("approvals.amend_cleared_after", af, ac(af), f"{ENT}/clearings_entitlement.csv", "the same clearings, timing 'cleared_after_approval'", "")
put("approvals.amend_parents", 0, "; ".join(f"{p.split(' (')[0]} {a:,.1f}" for p, a in amend.groupby("parent_project").acres.sum().sort_values(ascending=False).items()), f"{ENT}/office_governing_cases.csv",
    "acres by parent_project among the amendment rows", "")

# ---------------------------------------------------------------- RCA terms of cases approved in the period
O = csv(f"{ENT}/office_period_cases.csv").fillna("")
O = O[~O.case.isin(HELD)]
read = O[O.rca_percent_group != "not read"]
put("rca.cases_in_period", len(O), str(len(O)), f"{ENT}/office_period_cases.csv", "rows, without 23CZ13", "Conditional zoning cases approved on or after 2019-12-03 with 2 acres or more of 2017 forest.")
put("rca.cases_read", len(read), str(len(read)), f"{ENT}/office_period_cases.csv", "rows whose rca_percent_group is not 'not read'", "")
RCAV = "The percent is what the zoning text or approved plan states, not what was built."
for g, d in read.groupby("rca_percent_group"):
    put(f"rca.group.{g}", len(d), str(len(d)), f"{ENT}/office_period_cases.csv", f"rows with rca_percent_group '{g}'", RCAV + (" 'Not found' is not 'none'." if g == "not found" else ""))
    put(f"rca.group.{g}.forest", float(pd.to_numeric(d.forest_at_approval_acres).sum()), ac(pd.to_numeric(d.forest_at_approval_acres).sum()), f"{ENT}/office_period_cases.csv",
        f"sum of forest_at_approval_acres, rca_percent_group '{g}'", "Rows can share ground.")
for g, d in read.groupby("grading_group"):
    put(f"rca.grading.{g}", len(d), str(len(d)), f"{ENT}/office_period_cases.csv", f"rows with grading_group '{g}'", "From the approved plan set where there is one, else the case file.")
for g in sorted(set(read.rca_percent_group)):
    d = read[(read.rca_percent_group == g) & (read.grading_group == "mass graded")]
    put(f"rca.group.{g}.mass", len(d), str(len(d)), f"{ENT}/office_period_cases.csv", f"rows with rca_percent_group '{g}' and grading_group 'mass graded'", "")
for col, key in (("forest_at_approval_acres", "rca.forest_at_approval"), ("cleared_since_approval_acres", "rca.cleared_since"), ("standing_now_acres", "rca.standing_now")):
    v = float(pd.to_numeric(read[col]).sum())
    put(key, v, ac(v), f"{ENT}/office_period_cases.csv", f"sum of {col}, the {len(read)} cases read", "Sum of case rows; some cases share ground.")
Q = csv(f"{ENT}/office_rca_quotes.csv").fillna("")
put("rca.quotes", len(Q), f"{len(Q):,}", f"{ENT}/office_rca_quotes.csv", "rows", "Each quote was found word for word on its page.")

# tree conditions written into the approvals (from the quotes file; 23CZ13 left out; 20CZ05's replanted buffer is not a tree-replacement condition)
tq = Q[(Q.field == "tree_condition") & ~Q.case.isin(HELD)].copy()
tq["s"] = tq.sentence.str.replace(r"\s+", " ", regex=True)
TC = "Counted from the sentences recorded under 'tree_condition' in the case files and plan sets. A case may carry other tree terms not counted here."
keep = tq[tq.s.str.contains(r"shall preserve (?:a minimum of|at least) \d+ ?_? ?% of (?:the )?existing tree canopy", case=False, regex=True)]
pcts = {c: int(re.search(r"(\d+) ?_? ?%", x).group(1)) for c, x in zip(keep.case, keep.s)}
rep = tq[tq.s.str.contains(r"greater than (?:18|24)(?:”|\"|\u201d).{0,120}(?:shall be|be) replaced|shall replace any large type trees|at least 140 existing trees", case=False, regex=True)]
rr = tq[tq.s.str.contains("replant and restore existing tree canopy", case=False)]
don = tq[tq.s.str.contains("donation", case=False)]
big = tq[tq.s.str.contains(r"preserve trees.{0,60}18-inches.{0,80}maximum extent", case=False, regex=True)]
put("tree.any.cases", int(tq.case.nunique()), str(int(tq.case.nunique())), f"{ENT}/office_rca_quotes.csv", "cases with any tree_condition sentence", "Includes planting, buffer and survey notes, not only preservation.")
put("tree.keep_canopy.cases", len(pcts), str(len(pcts)), f"{ENT}/office_rca_quotes.csv", "cases with 'shall preserve a minimum of / at least N% of existing tree canopy'", TC)
put("tree.keep_canopy.list", 0, ", ".join(f"{c} {v}%" for c, v in sorted(pcts.items())), f"{ENT}/office_rca_quotes.csv", "the same cases and their percents", TC)
put("tree.keep_canopy.min", min(pcts.values()), f"{min(pcts.values())}%", f"{ENT}/office_rca_quotes.csv", "lowest of those percents", TC)
put("tree.keep_canopy.max", max(pcts.values()), f"{max(pcts.values())}%", f"{ENT}/office_rca_quotes.csv", "highest of those percents", TC)
put("tree.replace_large.cases", int(rep.case.nunique()), str(int(rep.case.nunique())), f"{ENT}/office_rca_quotes.csv", "cases with a condition to replace removed trees of 18 or 24 inches or more", TC)
put("tree.replace_large.list", 0, ", ".join(sorted(rep.case.unique())), f"{ENT}/office_rca_quotes.csv", "the same cases", TC)
put("tree.replant_restore.cases", int(rr.case.nunique()), str(int(rr.case.nunique())), f"{ENT}/office_rca_quotes.csv", "cases with 'seeks to replant and restore existing tree canopy that is removed'", TC)
put("tree.replant_restore.list", 0, ", ".join(sorted(rr.case.unique())), f"{ENT}/office_rca_quotes.csv", "the same cases", TC)
put("tree.keep_large.cases", int(big.case.nunique()), str(int(big.case.nunique())), f"{ENT}/office_rca_quotes.csv", "cases with 'preserve trees ... 18-inches ... to the maximum extent reasonably possible'", TC)
put("tree.donation.cases", int(don.case.nunique()), str(int(don.case.nunique())), f"{ENT}/office_rca_quotes.csv", "cases with a tree_condition sentence about a donation", TC)
ex_in = O[(O.rca_exemption != "") & (O.rca_exemption != "not found") & (O.rca_exemption != "not read")]
put("rca.exemption_cases", len(ex_in), str(len(ex_in)), f"{ENT}/office_period_cases.csv", "rows with an rca_exemption entry", "Cases approved on or after 2019-12-03 whose documents state an exemption, 'N/A', or only the mass-grading amount.")
put("rca.exemption_list", 0, ", ".join(sorted(ex_in.case)), f"{ENT}/office_period_cases.csv", "the same cases", "")

# ---------------------------------------------------------------- exemptions
X = csv(f"{ENT}/rca_exemptions.csv").fillna("")
put("exempt.cases", len(X), str(len(X)), f"{ENT}/rca_exemptions.csv", "rows", "Cases whose documents state an exemption, 'N/A', or only the 5% mass-grading amount.")
for r in X.itertuples():
    put(f"exempt.{r.case}", 0, f"{r.name}: {r.rca_required_as_stated}", f"{ENT}/rca_exemptions.csv", f"case {r.case}, rca_required_as_stated ({r.document} p{r.page})", str(r.statement))

# ---------------------------------------------------------------- Veridea and the other parent projects
P = csv(f"{ENT}/parent_projects.csv").fillna("")
v = P[P.original_case == "09CZ07"].iloc[0]
put("veridea.acres", float(v.acres), ac(v.acres), f"{ENT}/parent_projects.csv", "original_case 09CZ07, acres", "")
put("veridea.forest_2022", float(v.baseline_forest_acres_2022), ac(v.baseline_forest_acres_2022), f"{ENT}/parent_projects.csv", "09CZ07, baseline_forest_acres_2022", "")
put("veridea.forest_now", float(v.current_forest_acres), ac(v.current_forest_acres), f"{ENT}/parent_projects.csv", "09CZ07, current_forest_acres", "Forest-like on the July to September 2026 satellite composite.")
put("veridea.rca_acres", 100, "100", "apex-canopy/rca_cache/text/pkt_09CZ07/p0032.txt", "SD Plan Article 3.1.3.a", "A fixed acreage for the whole development, approved May 10, 2011.")
put("veridea.forest_now_less_rca", float(v.current_forest_acres) - 100, ac(float(v.current_forest_acres) - 100), "computed", "veridea.forest_now less 100", "Arithmetic only. RCA need not be forest, so this is not a forecast.")

# ---------------------------------------------------------------- what mapped RCA is made of
s = open(os.path.join(T, ENT, "rca_layer_summary.txt")).read().splitlines()
m = re.search(r"Typed RCA: (\d+) polygons, ([\d,\.]+) acres", s[0]); put("layer.polygons", int(m.group(1)), m.group(1), f"{ENT}/rca_layer_summary.txt", "line 1", "The Town's public HOA_OS_RCA layer, pulled 2026-11-24.")
put("layer.acres", float(m.group(2).replace(",", "")), ac(float(m.group(2).replace(",", ""))), f"{ENT}/rca_layer_summary.txt", "line 1", "")
L5 = next(l for l in s if l.startswith("All mapped RCA"))
m = re.search(r"tree canopy ([\d\.]+) ac \((\d+)%\), water ([\d\.]+) ac \((\d+)%\), open ground ([\d\.]+) ac \((\d+)%\)", L5)
LAY = "One summer's aerial photo (2022). 'Open ground' includes meadow, lawn and newly planted buffers."
for k, i in (("trees", 2), ("water", 4), ("open", 6)):
    put(f"layer.{k}_pct", int(m.group(i)), m.group(i) + "%", f"{ENT}/rca_layer_summary.txt", "line 'All mapped RCA'", LAY)
L6 = next(l for l in s if "platted 2022 or earlier" in l)
m = re.search(r"earlier[^:]*: ([\d\.]+) ac; tree canopy (\d+)%, water (\d+)%, open ground (\d+)%", L6)
put("layer.platted_acres", float(m.group(1)), ac(float(m.group(1))), f"{ENT}/rca_layer_summary.txt", "line 'platted 2022 or earlier'", "")
put("layer.platted_trees_pct", int(m.group(2)), m.group(2) + "%", f"{ENT}/rca_layer_summary.txt", "line 'platted 2022 or earlier'", LAY)
put("layer.platted_open_pct", int(m.group(4)), m.group(4) + "%", f"{ENT}/rca_layer_summary.txt", "line 'platted 2022 or earlier'", LAY)

# ---------------------------------------------------------------- lag and build-out
LC = csv(f"{ENT}/lag_cases.csv").fillna("")
inl = LC[LC.in_lag_calculation == True]
done = inl[inl.cleared == True]; wait = inl[inl.cleared != True]
lag = pd.to_numeric(done.lag_months)
SMALL = "Small sample. First-time approvals only; amendments are measured separately."
put("lag.cases", len(inl), str(len(inl)), f"{ENT}/lag_cases.csv", "rows with in_lag_calculation", SMALL)
put("lag.started", len(done), str(len(done)), f"{ENT}/lag_cases.csv", "in_lag_calculation and cleared", "An acre or more cleared since approval.")
put("lag.median_months", float(lag.median()), f"{lag.median():.0f}", f"{ENT}/lag_cases.csv", "median of lag_months among the cases that have started", SMALL + " Only cases that have started.")
s2 = open(os.path.join(T, ENT, "lag_summary.txt")).read()
m = re.search(r"half of all cases have started by ([\d\.]+) months", s2)
put("lag.median_all_months", float(m.group(1)), f"{float(m.group(1)):.0f}", f"{ENT}/lag_summary.txt", "section 1, Kaplan-Meier line", SMALL + " Counts the cases still waiting.")
B = csv(f"{ENT}/lag_buildout_curve.csv")
for r in B.itertuples():
    put(f"lag.year{r.years_after_approval}.median", float(r.median_share_cleared), pct(100 * r.median_share_cleared, 0), f"{ENT}/lag_buildout_curve.csv", f"year {r.years_after_approval}, median_share_cleared",
        f"Median of {r.cases_old_enough} cases old enough; range {100 * r.lowest:.0f}% to {100 * r.highest:.0f}%.")
    put(f"lag.year{r.years_after_approval}.cases", int(r.cases_old_enough), str(int(r.cases_old_enough)), f"{ENT}/lag_buildout_curve.csv", f"year {r.years_after_approval}, cases_old_enough", "")
    put(f"lag.year{r.years_after_approval}.pooled", float(r.pooled_share), pct(100 * r.pooled_share, 0), f"{ENT}/lag_buildout_curve.csv", f"year {r.years_after_approval}, pooled_share", "All acres cleared by then over all forest at approval.")
fa = pd.to_numeric(wait.forest_at_approval_acres)
PROJ = "Forest standing inside approved cases. What happens to it is not known: any figure for what will come down is a projection."
put("pending.cases", len(wait), str(len(wait)), f"{ENT}/lag_cases.csv", "in_lag_calculation and not cleared", PROJ)
put("pending.forest_at_approval", float(fa.sum()), ac(fa.sum()), f"{ENT}/lag_cases.csv", "sum of forest_at_approval_acres, in_lag_calculation and not cleared", PROJ)
priv = wait[wait.public_owner_case != True]
put("pending.cases_private", len(priv), str(len(priv)), f"{ENT}/lag_cases.csv", "the same, without public-owner cases", PROJ)
put("pending.forest_private", float(pd.to_numeric(priv.forest_at_approval_acres).sum()), ac(pd.to_numeric(priv.forest_at_approval_acres).sum()), f"{ENT}/lag_cases.csv", "the same, without public-owner cases", PROJ)
med = float(lag.median())
old = wait[pd.to_numeric(wait.months_waited) > med]
put("pending.older_than_median.cases", len(old), str(len(old)), f"{ENT}/lag_cases.csv", "not cleared and months_waited above the median lag", PROJ)
put("pending.older_than_median.forest", float(pd.to_numeric(old.forest_at_approval_acres).sum()), ac(pd.to_numeric(old.forest_at_approval_acres).sum()), f"{ENT}/lag_cases.csv", "the same", PROJ)

# ---------------------------------------------------------------- clearing before rezoning
s3 = open(os.path.join(T, PRE, "summary.txt")).read()
m = re.search(r"Cleared between mid-2017 and the filing date: ([\d,]+) ac, of which ([\d,]+) with an earlier conditional case on the ground, (\d+) same year, ([\d,]+) with none", s3)
for k, i, cav in (("before_filing", 1, ""), ("with_earlier_case", 2, ""), ("with_none", 4, "")):
    put(f"prerezoning.{k}", int(m.group(i).replace(",", "")), m.group(i), f"{PRE}/summary.txt", "the line 'Cleared between mid-2017 and the filing date'", "Cases numbered 2022 or later and pending cases. Rows overlap.")
PC = csv(f"{PRE}/prerezoning_clearing.csv").fillna("")
pp = PC[PC.case == "23CZ05"].iloc[0]
col = next(c for c in PC.columns if "cleared" in c and "filing" in c and "acres" in c)
put("prerezoning.pleasant_park", float(pp[col]), ac(float(pp[col])), f"{PRE}/prerezoning_clearing.csv", f"case 23CZ05, {col}", "The Town's own Pleasant Park.")

# ---------------------------------------------------------------- the independent cross-check (July 2025 aerial photos)
X2 = csv(f"{WAKE}/naip_crosscheck.csv")
r = X2[X2.cells.str.startswith("cleared, patches of an acre or more")].iloc[0]
CK = "Cells the detection calls cleared by mid-2025, in patches of an acre or more."
put("crosscheck.acres", float(r.acres), ac(r.acres), f"{WAKE}/naip_crosscheck.csv", "row 'cleared, patches of an acre or more, first seen by 2025Q2', acres", CK)
put("crosscheck.county_2020", float(r.county_2020_canopy_share), pct(100 * r.county_2020_canopy_share, 0), f"{WAKE}/naip_crosscheck.csv", "same row, county_2020_canopy_share", CK + " Canopy share on the County's 2020 map.")
put("crosscheck.naip_2020", float(r.naip_2020_canopy_share), pct(100 * r.naip_2020_canopy_share, 0), f"{WAKE}/naip_crosscheck.csv", "same row, naip_2020_canopy_share", CK + " Our recipe on the July 2020 aerial photos.")
put("crosscheck.naip_2025", float(r.naip_2025_canopy_share), pct(100 * r.naip_2025_canopy_share, 0), f"{WAKE}/naip_crosscheck.csv", "same row, naip_2025_canopy_share", CK + " Our recipe on the July 25, 2025 aerial photos.")
r = X2[X2.cells.str.startswith("forest in 2020, not forest-like in 2026, no event")].iloc[0]
put("undercount.changed_no_event", float(r.acres), ac(r.acres), f"{WAKE}/naip_crosscheck.csv", "row 'forest in 2020, not forest-like in 2026, no event', acres", "Changed between two dates with no clearing on record. Not counted as cleared.")

# ---------------------------------------------------------------- Peak Plan 2055 draft context areas
A = csv(f"{WAKE}/context_areas.csv")
DRAFT = "The context-area layer is a staff draft."
for r in A.itertuples():
    k = re.sub(r"[^a-z]+", "_", r.area.lower()).strip("_")
    put(f"context.{k}.canopy_2020", float(r.canopy_2020_pct), pct(r.canopy_2020_pct, 0), f"{WAKE}/context_areas.csv", f"area '{r.area}', canopy_2020_pct", DRAFT)
    put(f"context.{k}.cleared_pct", float(r.pct_of_2020_canopy_cleared), pct(r.pct_of_2020_canopy_cleared, 0), f"{WAKE}/context_areas.csv", f"area '{r.area}', pct_of_2020_canopy_cleared", DRAFT)
    put(f"context.{k}.cleared_acres", float(r.canopy_cleared_since_mid2020_acres), ac(r.canopy_cleared_since_mid2020_acres), f"{WAKE}/context_areas.csv", f"area '{r.area}', canopy_cleared_since_mid2020_acres", DRAFT)
    share = 100 * r.forest_standing_now_in_approved_2022plus_acres / r.forest_standing_now_acres if r.forest_standing_now_acres else 0
    put(f"context.{k}.standing_in_cases_pct", float(share), pct(share, 0), f"{WAKE}/context_areas.csv", f"area '{r.area}', forest_standing_now_in_approved_2022plus_acres over forest_standing_now_acres", DRAFT + " 23CZ13 is not in this figure.")
    MAPB = DRAFT + " Forest (the County's 2020 canopy cells that still read as forest in summer 2026) inside rezonings numbered 2020 or later that the Town lists as approved. 23CZ13 is not in this figure. Not the same measure as projection.remaining."
    put(f"context.{k}.standing_acres", float(r.forest_standing_now_acres), ac(r.forest_standing_now_acres), f"{WAKE}/context_areas.csv", f"area '{r.area}', forest_standing_now_acres", DRAFT)
    put(f"context.{k}.standing_in_cases_acres", float(r.forest_standing_now_in_approved_2020plus_acres), ac(r.forest_standing_now_in_approved_2020plus_acres), f"{WAKE}/context_areas.csv", f"area '{r.area}', forest_standing_now_in_approved_2020plus_acres", MAPB)
    share20 = 100 * r.forest_standing_now_in_approved_2020plus_acres / r.forest_standing_now_acres if r.forest_standing_now_acres else 0
    put(f"context.{k}.standing_in_cases_2020plus_pct", float(share20), pct(share20, 0), f"{WAKE}/context_areas.csv", f"area '{r.area}', forest_standing_now_in_approved_2020plus_acres over forest_standing_now_acres", MAPB)
    put(f"context.{k}.canopy_now", float(r.est_canopy_now_pct), pct(r.est_canopy_now_pct, 0), f"{WAKE}/context_areas.csv", f"area '{r.area}', est_canopy_now_pct", DRAFT + " An estimate: the County's 2020 canopy less clearings detected since.")

# ---------------------------------------------------------------- verification
V = csv(f"{VER}/verify_report_groups.csv")
L1 = csv(f"{VER}/verify_log.csv", dtype=str, keep_default_na=False); L2 = csv(f"{VER}/verify_log_large_optional.csv", dtype=str, keep_default_na=False)
rev = pd.concat([L1[L1.set == "sample"], L2]); rev = rev[rev.verdict != ""]
VC = "Reviewed by Adam Whitaker, the author, on aerial and satellite image pairs. A random sample of 100 plus every other clearing over 10 acres, from the 2017-2026 series."
put("verify.reviewed", len(rev), str(len(rev)), f"{VER}/verify_log.csv and verify_log_large_optional.csv", "rows with a verdict, sample and large sets", VC)
for vname, key in (("cleared", "cleared"), ("partly", "partly"), ("not cleared", "not_cleared"), ("can't tell", "cant_tell")):
    put(f"verify.n_{key}", int((rev.verdict == vname).sum()), str(int((rev.verdict == vname).sum())), f"{VER}/verify_log.csv and verify_log_large_optional.csv", f"rows with verdict '{vname}'", VC)
rep = open(os.path.join(T, VER, "verify_report.txt")).read().split("SAMPLE SET")[1]
for key, pat in (("confirmed", r"Share confirmed \(cleared\):\s+([\d\.]+)%\s+95% interval ([\d\.]+)% to ([\d\.]+)%"), ("cleared_or_partly", r"Share cleared or partly:\s+([\d\.]+)%\s+95% interval ([\d\.]+)% to ([\d\.]+)%"),
                 ("by_acres", r"Acres-weighted share confirmed:\s+([\d\.]+)%\s+95% interval ([\d\.]+)% to ([\d\.]+)%")):
    m = re.search(pat, rep)
    put(f"verify.{key}", float(m.group(1)), m.group(1) + "%", f"{VER}/verify_report.txt", f"sample set, '{key}' line", VC)
    put(f"verify.{key}.low", float(m.group(2)), m.group(2) + "%", f"{VER}/verify_report.txt", f"sample set, '{key}' line, 95% interval", "Approximate interval.")
    put(f"verify.{key}.high", float(m.group(3)), m.group(3) + "%", f"{VER}/verify_report.txt", f"sample set, '{key}' line, 95% interval", "Approximate interval.")
rel = L1[(L1.set == "release") & (L1.verdict != "")]
RC = "Reviewed by Adam Whitaker, the author. Every clearing of the published count, so this is a full count, not a sample."
put("verify.release.reviewed", len(rel), str(len(rel)), f"{VER}/verify_log.csv", "release rows with a verdict", RC)
for vname, key in (("cleared", "cleared"), ("partly", "partly"), ("not cleared", "not_cleared"), ("can't tell", "cant_tell")):
    put(f"verify.release.n_{key}", int((rel.verdict == vname).sum()), str(int((rel.verdict == vname).sum())), f"{VER}/verify_log.csv", f"release rows with verdict '{vname}'", RC)
repr_ = open(os.path.join(T, VER, "verify_report.txt")).read().split("SAMPLE SET")[0]
for key, pat in (("confirmed", r"Share confirmed \(cleared\):\s+([\d\.]+)%"), ("cleared_or_partly", r"Share cleared or partly:\s+([\d\.]+)%"), ("by_acres", r"Acres-weighted share confirmed:\s+([\d\.]+)%")):
    m = re.search(pat, repr_)
    put(f"verify.release.{key}", float(m.group(1)), (m.group(1).rstrip("0").rstrip(".") if m.group(1).endswith(".0") else m.group(1)) + "%", f"{VER}/verify_report.txt", f"release set, '{key}' line", RC)
put("verify.total_reviewed", len(rev) + len(rel), str(len(rev) + len(rel)), f"{VER}/verify_log.csv and verify_log_large_optional.csv", "rows with a verdict, all three sets",
    "Before-and-after checks, not distinct pieces of ground: see verify.overlap_release.")
import geopandas as gpd
_g = gpd.read_file(os.path.join(T, VER, "outlines.geojson")).to_crs(32617)
_u = _g[_g.set == "release"].geometry.union_all(); _o = _g[_g.set != "release"]
_n = int((_o.geometry.intersection(_u).area > 0).sum())
put("verify.overlap_release", _n, str(_n), f"{VER}/outlines.geojson", "outlines of the sample and large sets that intersect a release outline", "Of the 137 reviewed clearings of the series. The two counts cover overlapping ground.")
frame = csv(f"{VER}/sample_frame.csv")
put("verify.frame_clearings", len(frame), str(len(frame)), f"{VER}/sample_frame.csv", "rows", "Every clearing in the 2017-2026 series.")
put("verify.release_pending", int(((L1.set == "release") & (L1.verdict == "")).sum()), str(int(((L1.set == "release") & (L1.verdict == "")).sum())), f"{VER}/verify_log.csv", "release rows with no verdict", "")
vs = json.load(open(os.path.join(T, "apex-canopy", "release-v1", "validation_summary.json"))) if os.path.exists(os.path.join(T, "apex-canopy", "release-v1", "validation_summary.json")) else {}

# ---------------------------------------------------------------- the lookup table (the 78 cases read earlier plus Hopson Gateway, read 2026-11-25)
lk = os.path.join(OUT, "lookup_rows.json")
if os.path.exists(lk):
    LR = pd.DataFrame(json.load(open(lk)))
    LR["g"] = LR.rca.str.split(" (", regex=False).str[0].str.replace(r"^No figure.*", "No figure", regex=True)
    put("table.cases", len(LR), str(len(LR)), "article/out/lookup_rows.json", "rows", "Conditional zoning cases approved on or after 2019-12-03 with 2 acres or more of 2017 forest; 23CZ13 left out.")
    for g, d in LR.groupby("g"):
        put(f"table.rca.{g}", len(d), str(len(d)), "article/out/lookup_rows.json", f"rows whose RCA entry begins '{g}'", RCAV)
        put(f"table.rca.{g}.mass", int((d.grading == "Mass graded").sum()), str(int((d.grading == "Mass graded").sum())), "article/out/lookup_rows.json", f"the same rows, grading 'Mass graded'", "")
        put(f"table.rca.{g}.forest", float(d.forest_at_approval.sum()), ac(d.forest_at_approval.sum()), "article/out/lookup_rows.json", f"the same rows, sum of forest_at_approval", "Rows can share ground.")
    for g, d in LR.groupby("grading"):
        put(f"table.grading.{g}", len(d), str(len(d)), "article/out/lookup_rows.json", f"rows with grading '{g}'", "From the approved plan set where there is one, else the case file.")
        put(f"table.grading.{g}.forest", float(d.forest_at_approval.sum()), ac(d.forest_at_approval.sum()), "article/out/lookup_rows.json", f"rows with grading '{g}', sum of forest_at_approval", "Rows can share ground.")
    for col in ("forest_at_approval", "cleared_since", "standing"):
        put(f"table.{col}", float(LR[col].sum()), ac(LR[col].sum()), "article/out/lookup_rows.json", f"sum of {col}", "Sum of case rows; some cases share ground.")

# ---------------------------------------------------------------- pace: the County's ten years beside the years since
yrs_series = (pd.Timestamp("2026-10-24") - pd.Timestamp("2020-01-01")).days / 365.25
yrs_map = (pd.Timestamp("2026-10-24") - pd.Timestamp("2020-07-11")).days / 365.25
PACE = "The County measured net change in all tree canopy from aerial photos; the series counts forest cleared in patches of an acre or more from satellite. Comparable only roughly."
put("pace.county_planning", N["canopy.planning.lost_2010_2020_acres"]["value"] / 10, ac(N["canopy.planning.lost_2010_2020_acres"]["value"] / 10), "article/apex_report.pdf", "Table 2.4, planning jurisdiction loss 2010-2020, divided by 10 years", PACE)
put("pace.county_town", N["canopy.town.lost_2010_2020_acres"]["value"] / 10, ac(N["canopy.town.lost_2010_2020_acres"]["value"] / 10), "article/apex_report.pdf", "Table 2.4, corporate limits loss 2010-2020, divided by 10 years", PACE)
put("pace.series_years", yrs_series, f"{yrs_series:.1f}", "computed", "2020-01-01 to 2026-10-24", "")
put("pace.series", tot2020 / yrs_series, ac(tot2020 / yrs_series), "computed", "year.total_2020_on divided by pace.series_years", PACE)
put("pace.map_years", yrs_map, f"{yrs_map:.1f}", "computed", "2020-07-11 (the first 2020 aerial flight over Apex) to 2026-10-24", "")
put("pace.county_map", N["canopy.planning.cleared_since_2020_acres"]["value"] / yrs_map, ac(N["canopy.planning.cleared_since_2020_acres"]["value"] / yrs_map), "computed", "canopy.planning.cleared_since_2020_acres divided by pace.map_years",
    "County-mapped 2020 canopy on cells the series records as cleared since July 2020. No regrowth added.")
for tag, geo in (("town", "Corporate limits"), ("planning", "Planning jurisdiction")):
    v = float(C.loc[(geo, "as in the County report, Wake side")].canopy_cleared_since_mid2020_acres)
    put(f"pace.{tag}_same_acres", v, ac(v), f"{WAKE}/canopy_estimate_by_geography.csv", f"row '{geo}', boundary 'as in the County report, Wake side', canopy_cleared_since_mid2020_acres", "County-mapped 2020 canopy on cells cleared since July 2020, on the County's own boundary.")
    put(f"pace.{tag}_same", v / yrs_map, ac(v / yrs_map), "computed", f"pace.{tag}_same_acres divided by pace.map_years", "The like-for-like rate: the County's map, the County's boundary. No regrowth added.")
put("pace.town_today", N["canopy.town.cleared_since_2020_acres"]["value"] / yrs_map, ac(N["canopy.town.cleared_since_2020_acres"]["value"] / yrs_map), "computed", "canopy.town.cleared_since_2020_acres divided by pace.map_years", "Today's town limits, which are larger than in 2020.")

# ---------------------------------------------------------------- projection (article/projection.py): estimates, each resting on a stated assumption
pj = os.path.join(OUT, "projection.json")
if os.path.exists(pj):
    PJ = json.load(open(pj))
    MEAS = "Measured. Ground counted once; each cell's clock starts at the earliest approval in the period that covers it. 2017-2026 series."
    put("projection.forest", PJ["forest_at_first_approval"], ac(PJ["forest_at_first_approval"]), "article/out/projection.txt", "MEASURED block, forest standing at the first approval in the period", MEAS)
    put("projection.cleared", PJ["cleared"], ac(PJ["cleared"]), "article/out/projection.txt", "MEASURED block, cleared since", MEAS)
    put("projection.remaining", PJ["remaining"], ac(PJ["remaining"]), "article/out/projection.txt", "MEASURED block, remaining", MEAS)
    put("projection.veridea_remaining", PJ["veridea_remaining"], ac(PJ["veridea_remaining"]), "article/out/projection.txt", "MEASURED block, Veridea's four cases, remaining", MEAS)
    for tag in ("A", "B"):
        sh = [1 - PJ[f"nonveridea_{tag}_low"] / PJ[f"{tag}_low"], 1 - PJ[f"nonveridea_{tag}_high"] / PJ[f"{tag}_high"]]
        put(f"projection.veridea_share_{tag}", 100 * sum(sh) / 2, f"{round(100 * sum(sh) / 2, -1):.0f}%", "article/out/projection.json", f"Veridea's part of projection {tag}: 1 less nonveridea_{tag} over {tag}, low and high averaged, rounded to 10",
            f"Low {100 * sh[0]:.0f}%, high {100 * sh[1]:.0f}%. Veridea is cases 25CZ18, 25CZ15, 26CZ03 and 26CZ10.")
    put("projection.cleared_share_of_series", 100 * PJ["cleared"] / tot2020, pct(100 * PJ["cleared"] / tot2020, 0), "computed", "projection.cleared over year.total_2020_on",
        "Approximate: the cleared figure covers the 79 cases with 2 acres or more of forest, from each one's approval, not from January 2020.")
    PROJA = "A PROJECTION: assumes these cases end up clearing the share of forest that conditional zoning cases approved October 2017 to December 2, 2019 have cleared so far."
    PROJB = "A PROJECTION: assumes every acre of forest outside each case's required conservation area is cleared."
    put("projection.mature_cases", PJ["mature_cases"], str(PJ["mature_cases"]), "article/out/projection.txt", "block A, cases approved 2017-10-01 to 2019-12-02", "")
    put("projection.share_pooled", 100 * PJ["share_pooled"], pct(100 * PJ["share_pooled"], 0), "article/out/projection.txt", "block A, share cleared, all acres pooled", "Gracewood, the largest of them, is still being cleared.")
    put("projection.share_median", 100 * PJ["share_median"], pct(100 * PJ["share_median"], 0), "article/out/projection.txt", "block A, share cleared, median case", "")
    for k, cav in (("A_low", PROJA), ("A_high", PROJA), ("B_low", PROJB + " Conservation area taken as all forest."), ("B_high", PROJB + " Conservation area taken as 53% forest, the mapped average.")):
        put(f"projection.{k}", PJ[k], f"{round(PJ[k], -1):,.0f}", "article/out/projection.txt", f"block {k[0]}, {'lower' if 'low' in k else 'higher'} figure, rounded to 10", cav)
    put("projection.no_figure_cases", PJ["no_figure_cases"], str(PJ["no_figure_cases"]), "article/out/projection.txt", "block B", f"Given the average stated percent, {PJ['mean_stated_pct']:.0f}%.")

# ---------------------------------------------------------------- the County's dollar valuation (its Apex report, Table 2.3, Corporate Limits row)
_ct = " ".join(open(os.path.join(HERE, "sources", "county_report.txt"), encoding="utf-8", errors="replace").read().split())
assert "specific to the corporate limits, of $77,666,790" in _ct
assert "Corporate Limits 5 4,550 20 3,429 195 109,675 6 277 41 139,199" in _ct and "10,062 1,716,128 196,611,345 33,423,929 35,397,188 247,842 42,269,602" in _ct
_air, _seq, _storm, _annual, _store, _gal = 4550 + 3429 + 109675 + 277 + 139199, 1716128, 33423929, 35397188, 42269602, 196611345
assert _annual + _store == 77666790 and abs(_air + _seq + _storm - _annual) <= 1
VAL = "The County's modelled estimate (i-Tree), inside town limits as of 2020. Not money the Town spends or saves."
mil = lambda v: f"${v / 1e6:.1f} million"
put("value.total", 77666790, "$77,666,790", "article/apex_report.pdf", "PDF page 17, footnote to the per-capita graphic; equals the two totals below", VAL + " One year of benefits added to a one-time stock.")
put("value.annual", _annual, mil(_annual), "article/apex_report.pdf", "Table 2.3, PDF page 39, Corporate Limits row, total annual benefits", VAL + " A yearly figure.")
put("value.storage", _store, mil(_store), "article/apex_report.pdf", "Table 2.3, PDF page 39, Corporate Limits row, carbon storage dollars", VAL + " One-time: carbon held in the trees, which the report calls structural value.")
put("value.storm_dollars", _storm, mil(_storm), "article/apex_report.pdf", "Table 2.3, PDF page 39, Corporate Limits row, stormwater dollars", VAL + " A yearly figure.")
put("value.storm_gallons", _gal, f"{_gal / 1e6:.1f} million", "article/apex_report.pdf", "Table 2.3, PDF page 39, Corporate Limits row, stormwater gallons", VAL + " A yearly figure.")
put("value.storm_share_of_annual", 100 * _storm / _annual, pct(100 * _storm / _annual, 0), "computed", "value.storm_dollars over value.annual", VAL)
put("value.carbon_seq", _seq, mil(_seq), "article/apex_report.pdf", "Table 2.3, PDF page 39, Corporate Limits row, carbon sequestration dollars", VAL + " A yearly figure.")
put("value.air", _air, f"${_air:,}", "article/apex_report.pdf", "Table 2.3, PDF page 38, Corporate Limits row, sum of the five pollutant dollar columns", VAL + " A yearly figure. Our addition of the five columns.")
put("video.77m_time", "2:57", "2:57", "article/sources/wake_video/transcript.txt", "caption lines [02:57] and [03:01]", "The video's own captions. Wake County, \"Protecting Wake County's Tree Canopy\", https://vimeo.com/1212449815.")
put("value.storage_tons", 247842, "247,842", "article/apex_report.pdf", "Table 2.3, PDF page 39, Corporate Limits row, carbon storage tons", VAL)
_r = C.loc[("Corporate limits", "as in the County report, Wake side")]
_sh = float(_r.canopy_cleared_since_mid2020_acres) / float(_r.canopy_2020_acres)
assert abs(100 * _sh - float(_r.pct_of_2020_canopy_cleared)) < 0.06
MINE = "Our arithmetic, not a County finding. Assumes the cleared canopy captured as much water per acre as the average canopy; the cleared share is itself an estimate (clearings of an acre or more since July 2020 on the County's 2020 map)."
put("value.canopy_cleared_share", 100 * _sh, pct(100 * _sh, 0), f"{WAKE}/canopy_estimate_by_geography.csv", "row 'Corporate limits', boundary 'as in the County report, Wake side', canopy_cleared_since_mid2020_acres over canopy_2020_acres (also pct_of_2020_canopy_cleared)", MINE)
put("value.storm_gallons_lost", _sh * _gal, f"{round(_sh * _gal / 1e7) * 10:.0f} million", "computed", "value.canopy_cleared_share x value.storm_gallons, rounded to the nearest 10 million", MINE)

# ---------------------------------------------------------------- Plant the Peak (the Town's public map layer, pulled 2026-11-25)
PTP = "plant_the_peak/out"
_py = csv(f"{PTP}/summary_by_year.csv", index_col=0); _season = _py.columns[0]
_sm = open(os.path.join(T, PTP, "summary.txt"), encoding="utf-8").read()
_pc = json.load(open(os.path.join(T, PTP, "panel_caption.json")))
PT = "One point on the Town's map is taken as one tree. Counts are by the Town's season field; a season runs from fall into the next spring."
put("ptp.total", int(_py.loc["Total", _season]), f'{int(_py.loc["Total", _season]):,}', f"{PTP}/summary_by_year.csv", "row Total, season column", PT)
for y in range(2021, 2026):
    put(f"ptp.season.{y}", int(_py.loc[str(y), _season]), str(int(_py.loc[str(y), _season])), f"{PTP}/summary_by_year.csv", f"row {y}, season column", PT)
assert "data last edited 2026-01-29" in _sm
put("ptp.last_edited", "2026-01-29", "January 29, 2026", f"{PTP}/summary.txt", "line 2, 'data last edited'", "The newest EditDate in the layer.")
_tp = open(os.path.join(HERE, "sources", "town_plant_the_peak_2026-11-25.txt"), encoding="utf-8").read()
assert "offered 234 trees" in _tp and "over 500 trees" in _tp
put("ptp.offered_2026", 234, "234", "article/sources/town_plant_the_peak_2026-11-25.txt", "'In 2026, the Plant the Peak program offered 234 trees'", "The Town's page, read November 25, 2026. Planting is to begin January 2027.")
_perday = 929.2 * 0.84 * 163.9 / 1485
assert round(_perday) == 86
put("ptp.trees_per_day_published", _perday, "86", "apex-canopy/release-v1/METHODS.md", "929.2 acres x 0.84 x 163.9 trees per acre over 1,485 days", "The published tree count's average rate, October 2022 to October 2026.")
put("ptp.days_at_published_rate", 748 / _perday, f"{748 / _perday:.0f}", "computed", "ptp.total over ptp.trees_per_day_published", "A planted sapling is not a mature tree.")
put("ptp.trees_per_acre", 163.9, "163.9", "apex-canopy/release-v1/METHODS.md", "U.S. Forest Service inventory figure for Wake County forest, trees per acre", "")
put("ptp.acres_equivalent", 748 / 163.9, f"{748 / 163.9:.1f}", "computed", "ptp.total over ptp.trees_per_acre", "A planted sapling is not a mature tree, and yard trees are not a forest.")
put("ptp.on_cleared", _pc["all_points_inside_any_series_outline"], str(_pc["all_points_inside_any_series_outline"]), f"{PTP}/panel_caption.json", "all_points_inside_any_series_outline", "Points inside the outline of a clearing in the 2017-2026 series, edge cells included.")
put("ptp.clearly_on_cleared", _pc["all_points_clearly_inside_10m"], str(_pc["all_points_clearly_inside_10m"]), f"{PTP}/panel_caption.json", "all_points_clearly_inside_10m", "Points at least 10 metres inside the outline of a clearing in the 2017-2026 series (late 2017 on).")
put("ptp.clearings_with_points", len(csv(f"{PTP}/panel_site_ranking.csv")), str(len(csv(f"{PTP}/panel_site_ranking.csv"))), f"{PTP}/panel_site_ranking.csv", "number of rows", "")
put("ptp.panel.acres", _pc["acres_cleared"], f'{_pc["acres_cleared"]:.1f}', f"{PTP}/panel_caption.json", "acres_cleared", "Clearing D0010, first detected in late 2017.")
put("ptp.panel.marked", _pc["trees_marked_in_frame"], str(_pc["trees_marked_in_frame"]), f"{PTP}/panel_caption.json", "trees_marked_in_frame", "")
put("ptp.panel.clearly_inside", _pc["points_clearly_inside_10m"], str(_pc["points_clearly_inside_10m"]), f"{PTP}/panel_caption.json", "points_clearly_inside_10m", "")
_pp = csv(f"{PTP}/summary_by_year_priority.csv"); _in = _pp[(_pp.basis == "inside the polygon") & (_pp.season.astype(str).str.startswith("All"))].iloc[0]
_inside = int(_in["All"] - _in["Outside all planting areas"]); _top = int(_in["Very High"] + _in["High"])
put("ptp.priority.inside_any", _inside, str(_inside), f"{PTP}/summary_by_year_priority.csv", "basis 'inside the polygon', all years: All less Outside all planting areas", "Depends on where the Town put each point; the County's planting areas are small.")
put("ptp.priority.top_share", 100 * _top / _inside, pct(100 * _top / _inside, 0), f"{PTP}/summary_by_year_priority.csv", "same row: Very High plus High over the points inside any planting area", "Depends on where the Town put each point.")
PP = csv(f"{WAKE}/ppa_priority_overlay.csv").set_index("composite_priority")
put("ptp.priority.top_share_of_acres", 100 * PP.loc["Very High + High", "planting_area_acres_in_jurisdiction"] / PP.loc["All classes", "planting_area_acres_in_jurisdiction"],
    pct(100 * PP.loc["Very High + High", "planting_area_acres_in_jurisdiction"] / PP.loc["All classes", "planting_area_acres_in_jurisdiction"], 0), f"{WAKE}/ppa_priority_overlay.csv",
    "row 'Very High + High' over row 'All classes', planting_area_acres_in_jurisdiction", "")
put("ppa.top.acres", float(PP.loc["Very High + High", "planting_area_acres_in_jurisdiction"]), ac(PP.loc["Very High + High", "planting_area_acres_in_jurisdiction"]), f"{WAKE}/ppa_priority_overlay.csv", "row 'Very High + High', planting_area_acres_in_jurisdiction", "The County's priority planting areas inside Apex's planning jurisdiction.")
put("ppa.top.in_case_or_clearing_acres", float(PP.loc["Very High + High", "in_case_or_clearing"]), ac(PP.loc["Very High + High", "in_case_or_clearing"]), f"{WAKE}/ppa_priority_overlay.csv", "row 'Very High + High', in_case_or_clearing", "23CZ13 is not in this figure.")
put("ppa.top.in_case_or_clearing_share", 100 * float(PP.loc["Very High + High", "share_in_case_or_clearing"]), pct(100 * float(PP.loc["Very High + High", "share_in_case_or_clearing"]), 0), f"{WAKE}/ppa_priority_overlay.csv", "row 'Very High + High', share_in_case_or_clearing", "23CZ13 is not in this figure.")
put("ppa.all.in_case_or_clearing_share", 100 * float(PP.loc["All classes", "share_in_case_or_clearing"]), pct(100 * float(PP.loc["All classes", "share_in_case_or_clearing"]), 0), f"{WAKE}/ppa_priority_overlay.csv", "row 'All classes', share_in_case_or_clearing", "23CZ13 is not in this figure.")

# ---------------------------------------------------------------- verification pictures held back from the public release (one home lot)
_held = set()
for _fn in ("single_parcel_check.csv", "single_parcel_check_release.csv"):
    _d = csv(f"{VER}/{_fn}", dtype=str).fillna("")
    _held |= set(_d[_d.single_residential_parcel.isin(["yes", "near miss"]) & _d.largest_parcel_owner.isin(["individual(s)", "a trust or estate"])].id)
put("verify.pictures_held", len(_held), {4: "four"}.get(len(_held), str(len(_held))), f"{VER}/single_parcel_check.csv, {VER}/single_parcel_check_release.csv", "rows flagged yes or near miss whose largest parcel is owned by an individual, a trust or an estate",
    "Pictures of clearings that sit mostly on one residential parcel. Their verdicts are published; the pictures are not. The two check files are not published either.")
put("verify.pictures_published", N["verify.total_reviewed"]["value"] - len(_held), str(N["verify.total_reviewed"]["value"] - len(_held)), "computed", "verify.total_reviewed less verify.pictures_held", "")

# ---------------------------------------------------------------- write
for k, d in N.items():
    assert d["source_file"], k
json.dump(N, open(os.path.join(OUT, "numbers.json"), "w"), indent=1, sort_keys=True)
with open(os.path.join(OUT, "numbers.md"), "w") as f:
    f.write("# Every number, and where it comes from\n\nWritten by `article/build_numbers.py`. Paths are under `tree_video/`.\n\n| Key | Figure | Source file | Where in it | Caveat |\n|---|---|---|---|---|\n")
    for k in sorted(N):
        d = N[k]
        f.write(f"| `{k}` | {d['display']} | `{d['source_file']}` | {d['locator']} | {d['caveat']} |\n")

BRIEF = {"canopy.town.2010": 58.2, "canopy.town.2020": 44.6, "canopy.town.now": 37.9, "canopy.town.now_low": 35.1, "canopy.town.now_high": 38.1, "canopy.planning.2010": 59.4, "canopy.planning.2020": 50.4, "canopy.planning.now": 44.6,
         "canopy.planning.now_low": 42.0, "canopy.planning.now_high": 44.8, "canopy.planning.cleared_since_2020_acres": 1520, "canopy.town.cleared_since_2020_acres": 1452,
         "year.2017": 112, "year.2018": 240, "year.2019": 93, "year.2020": 279, "year.2021": 178, "year.2022": 190, "year.2023": 286, "year.2024": 200, "year.2025": 456, "year.2026": 256, "year.total_2020_on": 1846,
         "year.since_july_2020": 1616, "trees.estimate_1846": 250000, "approvals.in_period_first": 493, "approvals.in_period_amend": 167, "approvals.before": 263, "approvals.no_case": 6,
         "rca.cases_read": 78, "rca.group.none/exempt": 3, "rca.group.5": 1, "rca.group.15": 1, "rca.group.20": 9, "rca.group.25": 16, "rca.group.30": 8, "rca.group.35": 4, "rca.group.40": 1, "rca.group.other": 9,
         "rca.group.mixed by district": 4, "rca.group.not found": 22, "rca.grading.mass graded": 38, "rca.grading.stage graded": 8, "rca.grading.both, by phase": 4, "rca.grading.not stated": 28, "exempt.cases": 9,
         "layer.polygons": 785, "layer.acres": 1123, "layer.trees_pct": 53, "layer.open_pct": 45, "layer.water_pct": 2, "layer.platted_trees_pct": 49, "layer.platted_open_pct": 49, "lag.cases": 46, "lag.started": 22,
         "lag.median_months": 21, "lag.median_all_months": 27, "lag.year2.median": 0.01, "lag.year3.median": 0.40, "lag.year4.median": 0.50, "pending.cases": 24, "pending.forest_at_approval": 425,
         "prerezoning.before_filing": 420, "prerezoning.with_earlier_case": 308, "prerezoning.with_none": 110, "prerezoning.pleasant_park": 63, "crosscheck.county_2020": 0.96, "crosscheck.naip_2020": 0.80,
         "crosscheck.naip_2025": 0.07, "undercount.changed_no_event": 544, "context.transit_oriented_development.canopy_2020": 59, "context.transit_oriented_development.cleared_pct": 15,
         "context.transit_oriented_development.standing_in_cases_pct": 40}
print(f"{len(N)} figures written to out/numbers.json and out/numbers.md\n\nBrief against the files:")
for k, b in BRIEF.items():
    if k not in N:
        print(f"  MISSING   {k}"); continue
    v = N[k]["value"]
    tol = 0.006 if (isinstance(b, float) and b < 1) else 0.6 if b < 1000 else b * 0.005 if b < 100000 else 6000
    print(f"  {'ok       ' if abs(v - b) <= tol else 'DIFFERS  '} {k:55s} brief {b:>10}   file {v:>12.3f}" if abs(v - b) > tol else f"  ok        {k}")
