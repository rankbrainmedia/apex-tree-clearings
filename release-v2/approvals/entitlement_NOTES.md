# Entitlement and timing of the clearings (2026-11-24, revised the same day)

Adam's question: when did each clearing happen relative to its zoning case, and how much forest sits inside
cases approved since 2022 that has not been cleared yet. Run `../apex-canopy/df-venv/bin/python entitlement.py`.
Results are in `out/`; `out/summary.txt` is the printed report and `out/chain_audit.txt` the case-history audit.
Working files for Adam's checks: `out/review_list.csv`, `out/freshness_25CZ_26CZ.csv`, `out/plan_check/`.

**Conflict flag.** 23CZ13, the Seymour Mixed Use PUD, is next to the author's home. It stays in every table, flagged
(`conflict_flag` column). **Headline tables and union totals leave it out by default**; one reference line gives
the total with it. They are disclosed on the methodology page.

## Sources

- Release v1.1: `clearings.geojson`, `case_join.csv` (owners, organisations only), `baseline_forest_10m.tif`.
- `../apex-canopy/s2/cache/detect.npz`: the detection step's per-quarter state for every 10 m cell (forest-like,
  cleared-like, no observation). The script checks that it matches the release (same baseline, same 238 outlines).
- Three public Town of Apex layers, pulled 2026-11-24 into `inputs/` (the release's own case join used a 2026-10-27 pull):
  - **Rezoning**: 69 cases with a filing date (`Submitted`), status and action date. **It is not a full list.** It holds
    40 of the 79 cases numbered 2022 or later that are on the zoning map. Missing ones include Utley Farms (22CZ09),
    Apex Gateway Phase 1 (22CZ24), Castleberry Reserve (24CZ09) and Hopson Gateway (24CZ20).
  - **Zoning_Conditions** (the zoning map): 763 districts. Each has its current case number, an approval date, and
    `BACK1`..`BACK14`: the earlier cases on the same ground, newest first. This is where the case history comes from.
  - **Development**: site and subdivision plan records with submittal and action dates.
- `inputs/public_parcels_2026-11-24.geojson`: parcels owned by public bodies, from the Wake and Chatham county parcel
  services (`pull_public_parcels.py`). 319 parcels: Town of Apex 135, other towns 72, State and NCDOT 53, Wake County 31,
  Wake County Board of Education 18, United States 10. Only public-body parcels are requested and saved. The name
  patterns were checked against all 41,553 distinct owner names in the area.
- `case_join.csv` has no dates. The dates used here come from the Town layers above.

## Definitions

- **Governing case**: the zoning-map case covering the largest share of the clearing (overlaps under 0.05 acre ignored).
  Each clearing gets one, so nothing is counted twice. In every clearing it covers more than half.
- **Case year**: the first two digits of the case number (25CZ18 is a 2025 case). Type: CZ conditional zoning,
  CU conditional use, RZ/TRZ general rezoning, ETJ zoning assigned when the area entered the ETJ.
- **Case history, one answer per case.** A case can cover several districts with different `BACK` lists. The history
  covering the most acres is the case's, and every table uses it.
  - `prior_conditional_case`: the CZ or CU case immediately before it on that ground.
  - `original_conditional_case` / `_year`: the conditional case in force at the start of 2022 (the newest one numbered
    before 2022). Where there is none, the earliest 2022+ conditional case in the list. **This is Claude's reading** of
    "the prior conditional case's year": for a chain like 26CZ03 < 25CZ18 < 09CZ07 it walks back to 09CZ07 instead of
    stopping at 25CZ18. Taking the immediate prior instead would move only 26CZ03 (2 clearings, 34 acres of ground).
  - `earliest_conditional_year_in_chain`: the oldest conditional case number anywhere in the list. Reported, not used.
    On districts merged from many old ones it can belong to one corner (89CU01 on the 933-acre Veridea district).
  - `earlier_cases_on_ground` and `type_by_ground` in the clearing table describe the one district under the clearing.
- **entitlement_type**
  - `pre2022_or_none`: governing case numbered before 2022, or no case number.
  - A 2022+ case is an **amendment** if its name says amendment, expansion or text (Adam's rule), or a conditional
    case from before 2022 is on its ground. `amendment_basis` says which. Amendments are split by the original's year:
    - `amendment_of_pre2022_original`: the original is numbered before 2022.
    - `amendment_of_2022plus_original`: the original is 2022 or later. One case, 26CZ10 Veridea Expansion V, has no
      earlier conditional case on its ground at all: it is an amendment by name only, the ground's first conditional
      approval is the case itself, so it is placed here (`original_basis` says so).
  - `new_rezoning_2022plus`: a 2022+ case with neither. Seven of the approved ones sit on ground with an earlier conditional case
    that is also 2022 or later (Castleberry Reserve 24CZ09 over 23CZ21, Apex Gateway Phase 1 22CZ24 over 22CZ02,
    Hopson Gateway 24CZ20 over 24CZ08 and others). Their names do not say amendment, so they stay "new".
    `prior_conditional_case` shows it.
- **Parent project** (`parent_project`, and `out/parent_projects.csv`). For every amendment the forest numbers are
  also given for the whole project being amended, not just the petition area.
  - The parent's boundary is every district on the zoning map that carries the amendment's original case, now or as
    an earlier case. Horton Park is the districts that carry 18CZ04: 146.9 acres, all on 17CZ19 ground. (17CZ19 also
    has a separate 27.9-acre LI-CZ district that never came under 18CZ04; it is not part of the PUD and is left out.)
  - Where the original is itself named an amendment, the label walks back one more step: "Horton Park (17CZ19 +
    18CZ04)". Three parents are named by hand (Veridea, Horton Park, Apex Gateway Phase 2). The rest are labelled by
    case number, because the Town's name for an old case is usually the applicant, not the project.
  - An amendment by name alone has no earlier case on its own ground. Its parent is the adjoining district whose
    name starts with the same word. That applies to one case: 26CZ10 Veridea Expansion V.
  - `amendment_scope` has three labels (Adam, 2026-11-24). Size is not used, and nothing is called a text change
    unless the petition says so:
    - **carve-out to a different district**: the amendment's zoning district differs from the parent's
      (`district_against_parent`), as with 24CZ23 Greenway, LI-CZ out of Veridea's SD-CZ.
    - **expansion onto new ground**: at least half the petition lies outside the parent.
    - **same district, conditions or phase**: the rest. For three of these (23CZ15, 25CZ03, 24CZ06) the amendment
      covers every district of its parent, so there is no other district to compare against.
  - Clearings carry `parent_project` too, from the district they sit in, so a project's clearings can be added up
    across its original case and its amendments.
- **Manual dates** (Adam, 2026-11-24), used in place of the Town layers and marked in `approved_basis`:
  22CZ21 approved 2023-03-28 (the map says 2014-06-03); 26CZ05 approved 2026-08-25, status Approved (the Rezoning layer
  says Proposed); 25CZ13 approved 2026-01-12, status Approved (both layers say 2026-01-13, a Tuesday; the 12th is a
  Monday). No result moved: the five clearings under 22CZ21 date from 2025, and the other two cases govern none.
- **timing**, comparing the first-detection quarter with the governing case's dates. Where the quarter ended before
  the filing date (January 1 of the case year stands in where the Rezoning layer has no filing date), the class is
  one of three:
  - `cleared_under_earlier_approval`: a conditional case numbered in an earlier year than the clearing was already on
    the ground (`conditional_case_year_before_clearing` = yes).
  - `cleared_before_any_approval`: no conditional case was on the ground before the clearing.
  - `cleared_before_case_filed_earlier_case_same_year`: the only earlier conditional case is numbered the same year
    as the clearing, and neither layer dates it, so the order is not known. **Added by Claude** for one clearing, C230.
  - `cleared_after_approval`: the quarter began after the approval date.
  - `cleared_between_filing_and_approval`: anything between, including the same quarter as either date. **Added by
    Claude**: Adam's three classes left this gap.
  - `undated`: no case number on the ground.
- `plan_timing` does the same against the earliest approved or under-construction Development record on the clearing.
- **Forest inside a case**, three measures, all on the release's 2022 baseline forest cells:
  - `forest_remaining_acres` (the first version's measure): baseline forest outside clearing outlines of an acre or more.
  - `current_forest_acres`: baseline forest cells that are forest-like in the 2026Q3 composite, the latest leaf-on one,
    by the detection step's own test (NDVI and NBR against that quarter's stable forest). **This is now the headline.**
  - `remaining_minus_current_acres`, with its parts: cells that failed the test in 2022Q3 as well (not a loss),
    cells that were forest-like in 2022Q3 and are not now but lie outside the 1-acre outlines (small clearings, edges,
    thinning), cells with no observation, and, counting the other way, cells inside an outline that were still
    forest-like in 2026Q3 (mostly outlines first detected in October 2026).
- **Public-owner case**: public bodies own at least 50% of the case area by today's parcel records
  (`public_owner_case`, `public_share_of_case`, `public_owners`). Clearings also carry `public_share_of_clearing`.
  "Without public-owner cases" in the union totals removes those cases **and the ground they cover**, because another
  case can sit on the same ground.
- **Trees**: cleared acres x 0.84 x 163.9. Standing forest x 163.9 (no 0.84: it is counted in forest cells).

## What came out

- 238 clearings, 929.2 acres, each counted once. None is governed by 23CZ13.
  - new 2022+ rezoning: 44 clearings, 181.5 acres (about 25,000 trees). 43 were first detected after approval.
  - amendment of a 2022+ original: 5 clearings, 45.6 acres, all Apex Gateway Phase 2 Amendment (23CZ15 over 22CZ26),
    all detected after approval.
  - amendment of a pre-2022 original: 65 clearings, 199.4 acres (about 27,400 trees). 23 (82.3 acres) were detected
    before the amendment was filed, all under an earlier approval, and 15 (39.8) between filing and approval.
  - No clearing is `cleared_before_any_approval` against its governing case. C230 (1.1 acres, Oct-Dec 2022, Hatcher
    Property 23CZ09 over 22CZ12) is the one unresolved: it needs 22CZ12's approval date.
  - pre-2022 or none: 124 clearings, 502.7 acres.
  - So 49 clearings, 227.1 acres, are under entitlements that begin in 2022 or later.
- Public owners: 5 clearings (53.6 acres) are under a public-owner case, all Felton Grove High School (20CZ12, Wake
  County Board of Education). Two more are on public parcels inside a private case: C005 (16.6 acres, Pleasant Plains
  Elementary) and C208 (1.2 acres, Wake County EMS). Without all seven: 231 clearings, 857.8 acres.
- Cases numbered 2022 or later and approved: 79. Leaving out 23CZ13 and counting each piece of ground once:
  2,992 acres, 1,694 acres of forest in 2022, 448 cleared in outlines.
  - **Current forest, 2026Q3: 1,187 acres** (about 194,600 trees). The earlier measure gives 1,246 remaining.
    About 21 acres of the 1,187 are inside outlines first detected in October 2026, which leaves 1,166.
  - By type, shared ground counted once (new first): new 507, amendment of a 2022+ original 81, amendment of a
    pre-2022 original 599. So **588 acres of current forest sit under entitlements that begin in 2022 or later**.
  - Without public-owner cases and their ground (Yard Waste Transfer Site, Pleasant Park, two small Town lots):
    1,139 acres in all, 540 under 2022+ entitlements.
  - With 23CZ13: 1,235 acres.
- **Parent projects.** 22 amendments trace to 17 parents. At the parent boundary:

  | Parent | Acres | Forest 2022 | Cleared | Current forest | Clearings |
  |---|---|---|---|---|---|
  | Veridea (09CZ07) | 1,148.3 | 670.2 | 144.4 | 497.2 | 49 (147.5 ac) |
  | Apex Gateway Phase 2 (22CZ26) | 236.5 | 104.7 | 45.8 | 71.1 | 5 (45.6 ac) |
  | Horton Park (17CZ19 + 18CZ04) | 146.9 | 134.9 | 82.3 | 54.7 | 24 (85.6 ac) |
  | 15CZ32 (parent of Smith Farm Phase 5) | 271.8 | 71.4 | 0.0 | 68.6 | 0 |
  | 15CZ33 (parent of West Village PUD Amendment) | 163.3 | 39.7 | 0.0 | 37.8 | 0 |
  | 21CZ08 (parent of Cash Corporate) | 121.3 | 54.7 | 29.7 | 23.5 | 10 (32.0 ac) |
  | 17CZ04 + 18CZ02 (parent of Friendship Station 3) | 198.0 | 47.2 | 19.3 | 21.4 | 4 (20.6 ac) |

  - Horton Park by petition area alone showed 25.3 acres of forest cleared; the whole PUD shows 82.3, because 23 of
    its 24 clearings are under the 2018 case, not the 2025 amendment. 14 of the amendment's 89.9 petition acres are
    outside the PUD, on new ground.
  - Veridea's four cases added up to 623 acres of current forest by petition area; the project boundary holds 497,
    counted once.
  - Sixteen parents with a pre-2022 original hold 741 acres of current forest (722 without public-owner ground).
    All cases with amendments counted at the parent boundary: 1,329 acres (1,262 without public-owner ground),
    against 1,187 by petition area.
  - Labels: five carve-outs to a different district (24CZ23, 22CZ15, 23CZ23, 25CZ16, 23CZ06), one expansion
    (26CZ10), sixteen same district, conditions or phase.
- 75 clearing-case pairs (63 clearings) were detected before an overlapping case was filed: 71 pairs under an earlier
  approval, 2 for C230, and 2 before any approval. Those two are C149 (1.7 acres, Oct-Dec 2022) and a 0.2-acre edge
  of C088, both inside the Horton Park PUD Amendment petition (25CZ23, filed Dec 1, 2025) on ground the zoning map
  still shows under 2007 ETJ zoning with no conditional case.
- The one sizeable question is still **C014**, 11.6 acres on Greenway Waste Solutions land, first detected Oct-Dec
  2023, a year before 24CZ23 was filed (Dec 2, 2024). The ground was inside the Veridea district (09CZ07) before that.
  **Correction:** the first version said a plan record on it was approved in April 2023. That record (Veridea Big
  Branch Pump Station 1) touches 0.09 acre of it. All four approved plan records together cover 5% of C014; 11.1 of
  its 11.6 acres are outside every approved plan record in the layer. Still a question to ask, not a finding.
- **Plan check** (`out/plan_check/`): for C014 and the 12 Veridea clearings marked cleared_before_plan_approval,
  `plan_records.csv` lists every Development record on the ground, `plan_coverage_by_clearing.csv` gives the share of
  each clearing inside them, and `plan_check.kml` has the clearing outlines and the 11 plan boundaries. The 12 Veridea
  clearings are 67% to 100% inside an approved or under-construction record, none of it approved before the quarter:
  the main one is East Village Non-Residential (Revision), TRC approved 2025-07-24. C062 and C120 are mostly inside
  East Village Non-Residential Ph 2A 3 4 5, which is under construction with no action date. The layer has no plan number;
  `plan_layer_fid` is the layer's id and `plan_document_id` the Town DocumentCenter id.
- **Review list** (`out/review_list.csv`): 40 cases with at least 2 acres of current forest, without 23CZ13 and the
  public-owner cases, with blank columns to fill in. `ground_shared_with` names other cases on the same ground, so
  acres are not counted twice. Hopson Gateway (24CZ20) is on it: 48.6 of its 99.7 acres are the Town's yard waste site.
- **Freshness** (`out/freshness_25CZ_26CZ.csv`): 40 cases numbered 25CZ01 to 26CZ18 in either layer, plus 25CZ11 and
  25CZ14, which are in neither. Worth a look against the agendas: 25CZ17 (approved 2026-02-24, not on the zoning map),
  25CZ06, 25CZ07 and 26CZ04 (on the map, not in the Rezoning layer), 25CZ08 (only as an earlier case under 25CZ18),
  25CZ09 (dates differ between layers), 26CZ08 (withdrawn, action dated 2026-11-24).

## The Veridea chain: why 1989, 2009 and 2023 all appeared

25CZ18 covers four districts on the zoning map (`out/chain_audit.txt` prints each one):

| District | Acres | Cases listed before it | Read alone |
|---|---|---|---|
| main Veridea district | 933.1 | 09CZ07, then older cases back to 89CU01 | prior 09CZ07 (2009), oldest number 1989 |
| former Veridea West Village | 130.8 | 25CZ15 | prior 25CZ15 (2025) |
| small piece | 1.5 | 25CZ08 | prior 25CZ08 (2025) |
| "Veridea Expansion" sliver | 0.6 | 23CZ03 | prior 23CZ03 (2023) |

- **2023** came from the 2022+ table. The first version read the first polygon of a case in file order, which for
  25CZ18 is the 0.6-acre sliver.
- **2009** was `prior_conditional_case` in the clearing table, read from the district under each clearing: the main one.
- **1989** was `original_conditional_year` in the clearing table: the oldest conditional case number anywhere in the
  main district's list. 89CU01 is a 1989 conditional use permit on some part of ground later merged into the
  district. The map does not say which part.
- Now 25CZ18 reads prior 09CZ07, original 09CZ07 (2009), on 88% of its ground, in every table. 26CZ03 reads prior
  25CZ18, original 09CZ07. 24CZ23 reads 09CZ07. 26CZ10 has no earlier conditional case (see above). 23CZ03 is no
  longer a district of its own; the sliver is all that the map shows of it.
- 43 of 577 cases have districts with different lists (`out/chain_varies_by_polygon.csv`). In 5 the type would differ
  by district: 25CZ18 (133 of 1,100 acres has a 2022+ original), and four where the odd piece is 1.2 acres or less
  (26CZ02, 25CZ24, 22CZ27, 26CZ13). No clearing sits on a district that disagrees with its case.
- One case changed type from this: 22CZ27 Center City Townhomes is now new (2.9 of its 4.1 acres has no earlier
  conditional case). It governs no clearing.

## Caveats

- The first-detection quarter is not the clearing date. In leaf-off quarters it can run up to one quarter early.
  `holds_if_detection_ran_a_quarter_early` in the before-filing list marks pairs that survive that.
- Filing dates exist for 40 of the 79 recent cases. The rest are year-only.
- Current forest is what stood in July to September 2026 inside approved boundaries. It includes land that has to
  stay (stream buffers, conservation area). It is not a forecast of what will be cut. It counts only cells the 2022
  baseline called forest, so forest the baseline missed is not in it, and neither are partial-canopy cells that never
  pass the test (28 acres inside these cases).
- Parcel owners are today's owners, not the owners when a case was filed. One record changed since the release's
  pull on 2026-10-27: the Pleasant Plains Elementary parcel (PIN [parcel number], under C005) was listed to the Wake County
  Board of Education then and is listed to the Town of Apex now, deed dated 2026-10-21. Public either way.
- Hopson Gateway (24CZ20) is 49% Town-owned, just under the flag: its districts on the zoning map take in the Town's
  yard waste site (24CZ08). The "without public" totals remove that ground through 24CZ08.
- Case rows overlap (Veridea's 25CZ18 covers 25CZ15, 26CZ03 and others), so rows cannot be added up. Use the union
  totals in `summary.txt`. The per-type union lines overlap too (by 97 acres of forest, the West Village ground); the
  "counted once" lines do not.
- A case boundary is the petition area where the Rezoning layer has the case, otherwise the districts the zoning map
  now labels with it (`boundary_from`).
- `plan_timing` counts a plan record that overlaps a clearing by 0.05 acre or more, however little of the clearing it
  covers. Of the 182 clearings marked cleared_after_plan_approval, 13 (86.7 acres) are less than half inside a record
  approved before the quarter, and 5 (55.2 acres: C002, C007, C014, C109, C202) are under a tenth.
  Read `plan_timing` for those with the coverage in mind. The rule has not been changed.
- Polygon repair changed. Six zoning districts and one plan record have a part nested inside another part. In each
  case checked, the nested part is ground that belongs to a different district or record, so it is a hole. The first
  version merged it in and counted that ground twice. No clearing's case, timing or plan timing changed; ten clearings
  list one plan record fewer.
- An overlap or a date order shows where and when. It does not show that a rule was broken. Clearing ahead of a
  rezoning can be timber harvest, agriculture or work allowed under the earlier zoning.

## Re-cut at 2019-12-03 (`office_period.py`, `rca/build_office.py`; added 2026-11-24)

Outputs: `out/office_period_onepage.txt` (the one page), `out/office_period_summary.txt` (full), `out/office_period_cases.csv`,
`out/office_rca_quotes.csv`, `out/office_governing_cases.csv`, `out/office_clearings_by_year.csv`.

- **Approval date**: the Rezoning layer's action date, else the date on the largest zoning-map district, with Adam's three
  manual dates. All 52 governing cases have one. Flagged: 07ETJ24 (its districts carry 2007 and 2026 dates; 2007 is used).
  Among all conditional zoning cases, 11CZ12 is dated before its own case year and 16CZ32 three years after.
  Nine cases were approved within four months of the cut; 19CZ18 is dated 2019-12-03 itself and counts as "on or after".
- **The release's 929 acres**: 660.4 under cases approved on or after the cut (165 clearings, 35 cases), 262.7 before
  (69 clearings, 17 cases), 6.0 on ground with no case. Counting amendments at the parent project's original approval:
  493.2 first approved in the period, 167.4 under amendments to earlier projects (Veridea 147.5, Apex Light Industrial
  18.2, Horton Park's 2025 amendment 1.7), 262.6 before. Horton Park's other 83.9 acres are under the 2018 case and were
  already "before".
- **Acres per year**, from the 2017 baseline detection (event rule, patches of an acre or more): 2017 (one quarter)
  112, 2018 240, 2019 93, 2020 279, 2021 178, 2022 190, 2023 286, 2024 200, 2025 456, 2026 (to October 24) 256.
  2017Q4 to 2019Q3: 423.4. The quarter the cut falls in: 22.3. 2020 on: 1,845.8. Since July 2020: 1,616.1.
- **Wake County's assessment date, confirmed.** The county's Land Cover Analysis & Tree Canopy Assessment "utilized
  leaf-on, multispectral aerial imagery, vintage 2020" from NAIP and compares 2010 with 2020. NAIP 2020 over Apex was
  flown July 11-12, 2020 (ten tiles) and September 21, 2020 (two eastern tiles). The Apex report gives 2,180 acres of
  canopy lost 2010-2020, a 15.2% decrease.
- **Cases in the period**: 126 conditional zoning cases approved on or after the cut; 80 have 2 acres or more of 2017
  forest. Forest at approval is 2017 forest not yet cleared (event rule) before the approval date.
- **RCA terms** were read for 78 of the 80 (1,103 quotes, none rejected). 23CZ13 and 24CZ20 are held under the conflict
  rule: a reader found that 24CZ20's PUD text names the Seymour PUD as the adjacent neighbourhood and ties a signal
  payment to it. Conflict checks are also open on 24CZ19 (Barnett Properties) and 24CZ08 (lists the Seymour PUD as adjacent).
- **Groups.** One RCA percent group per case: the case's own text first, then a plan set, then the parent. A base plus
  a mass-grading addition is counted at the total only where the document states the total. Fourteen cases were settled
  by hand, each with its reason in `rca_percent_basis` (`GROUP_OVERRIDES` in `rca/build_office.py`). Grading comes from
  the plan set where there is one.
- Two plan sets fetched for a case turned out not to be that case's site and were set aside: an offsite sewer plan
  under Apex Gateway Phase 1, and the Hopson Gateway plan under the Town's yard waste site.

## Lag from approval to clearing, and build-out (`lag_buildout.py`; added 2026-11-24)

Outputs: `out/lag_summary.txt`, `out/lag_cases.csv` (first approvals, one row per case), `out/lag_amendments.csv`
(one row per parent project), `out/lag_buildout_curve.csv`. Uses the 2017-2026 detection, not the 2022 release.

- **Forest at approval**: 2017 forest cells not first detected as cleared in a quarter that ended before the approval date.
- **Lag**: months from the approval date to the middle of the first quarter in which clearing since approval adds up
  to an acre. Good to about a month and a half either way, and the notes on the detection say winter quarters can run
  a quarter early. Clearing under an acre in total does not start the clock.
- **Year marks**: clearing detected in quarters that had ended by each anniversary, over forest at approval. A case
  counts at a mark only if the anniversary falls on or before 2026-09-30.
- **Three kinds of case.** *First approvals* have no earlier conditional case on most of their ground and no
  "amendment", "expansion" or "text" in their name: 82 of the 126 cases approved since 2019-12-03, 48 of them with 2
  acres or more of forest at approval (23CZ13 aside). *Amendments and re-approvals* (44 cases, 35 parent projects) are
  measured on the parent's boundary from the original's date and kept out of the lag. *Excluded*: 25CZ13 and 26CZ05
  (dates Adam supplied), and 18 parents whose original case is no longer a district and is not in the Rezoning layer,
  so only its case-number year is known.
- **Boundary of a first approval**: the Rezoning layer's petition boundary; where the case is not in that layer, every
  district that carries it or lists it in its history. This matters for 22CZ09 (Utley Farms), where 24CZ19 later took
  part of the ground: measured on all 102.6 acres, not the 2022 remainder.
- **Results**: 46 cases in the lag calculation; 22 have had an acre or more cleared. Median lag among those 20.9 months
  (middle half 16.0 to 27.2; 5.7 to 40.6). Counting the 24 still waiting (Kaplan-Meier), half of all cases have started
  by 27.2 months. Build-out, median share (lowest to highest), cases: year 1 0% (0 to 50%), 38; year 2 1% (0 to 75%),
  31; year 3 44% (0 to 86%), 26; year 4 50% (0 to 99%), 17; year 5 48% (8 to 84%), 10; year 6 one case, 68%.
- **Approved longer ago than the median lag with no acre cleared**: 11 cases, 114.8 acres of forest at approval. Three
  are on ground now owned by a public body (21CZ26, 23CZ05, 24CZ08).
- **Amendments**: only two parents first approved between the 2017 baseline and the cut can be measured: Horton Park
  (2017-11-07, first acre 2022Q4, 60 months, 62% cleared to date) and 19CZ03 (2019-04-02, 2023Q1, 46.5 months, 64%).
  Twelve parents were approved before the baseline (Veridea among them), so forest at approval cannot be measured;
  the file gives their 2017 forest and clearing since.
- Caveats: the cases that have started are the ones that have had time to, so the 20.9-month median is biased short;
  the 27.2 figure corrects for that. The year-5 median is below year 4 because different cases reach each mark.
  An approval date and a clearing date show order, not cause.
