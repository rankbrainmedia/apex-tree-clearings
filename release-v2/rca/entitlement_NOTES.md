# Tree-save numbers from the Town's documents (2026-11-24)

For every row of `../out/review_list.csv`: what the rezoning case file, and where needed the approved plan set, says
about Resource Conservation Area (RCA), grading, buffers, disturbance and trees. Nothing here is estimated. Every value
has a page number and the exact sentence it came from.

Outputs, in `../out/`:
- `review_list_filled.csv`: the review list with the new columns. One set for the case area, one prefixed `parent_`
  for an amendment's parent project, one prefixed `plan_` for figures that describe a plan's own site. Each value
  column has a `_page` column. A field that is not in the document reads "not found".
- `rca_quotes.csv`: case, scope, field, value, document, page, sentence, and whether the page was read from the PDF's
  text or by OCR.
- `rca_quotes_rejected.csv`: quotes the check threw out (none in this run).
- `rca_summary.txt`: the counts and the "maximum further clearing" table.

**Connected cases raised by readers of the files.** Both cases stay in the tables. They are disclosed where they appear.
- 24CZ19 New Hill Commons: the applicant is Barnett Properties, LLC. The conflict rule names Barnett v. Seymour. The
  file does not say whether this is the same Barnett.
- 24CZ20 Hopson Gateway: the plan sheets label the adjoining parcel as Seymour Farm Properties, LLC, zoned PUD-CZ.

## How it was done

1. `fetch_docs.py` downloaded each row's `town_case_file_url` from the Town's DocumentCenter and wrote one text file
   per PDF page. A page with under 200 characters of text was treated as a scan and read with Tesseract at 300 dpi.
   37 files, 1,557 pages, 774 by OCR. Three links return 404: 24CZ20, 25CZ06, 25CZ07.
2. `find_pages.py` listed, per file, the pages that mention RCA, grading, buffers, disturbance, trees and acreage. It
   only points at pages.
3. Readers (Claude subagents, six batches) read the pages under `READER_BRIEF.md`: record only what the page says, quote
   exactly, the value's digits must be in the quoted sentence, skip the Town's blank checklist of suggested conditions,
   list what is not there as not found. One JSON per case in `extracted/`.
4. Where the rezoning file had no RCA acres, `plan_candidates.py` listed the approved or under-construction
   Development-layer records on the case's ground, and up to two per case were fetched (25 plan sets, 22 cases).
   The first sheets were read. Three follow-ups were needed: some PDFs open with application forms, so all pages were
   read for those; some site data tables are drawn as images, so `ocr_sheets.py` read those sheets by OCR and
   appended the text to the page file; and readers went back over both.
5. `build_filled.py` checks every quote: the sentence must be on the cited page word for word (spacing aside), and
   for a number the digits must be in the sentence. 522 quotes kept, 0 rejected. It then writes the outputs.

## Calls Claude made on review (each is noted on the entry)

- 24CZ10 Ashburn: three RCA acre figures; the 4.80 acres for the whole development is marked as the main one (the
  other two are its tracts).
- Apex Light Industrial (22CZ21, 26CZ06): the plan sets give an overall requirement of 13.91 acres for all three
  phases, 56.00 acres. That is the parent project (14CZ09, 56.1 acres on the map), so those rows are scoped `parent`.
  Phase III, which is 26CZ06, has no RCA figure of its own: the sheet says "TBD".
- 22CZ17 Townes at the Station and 24CZ19 New Hill Commons: the plan sheet's requirement is for the total project,
  which is the case, so those rows are scoped `case`.
- A plan figure is set against the case's forest only where one plan set was read and the plan and the case are the
  same ground (each at least 80% inside the other). Phase plans and plans of larger sites get no clearing figure.

## Results

- RCA acres found for 23 of 40 cases: 5 from the rezoning file, 18 only from a plan set. RCA percent found for 23.
- "Maximum further clearing" (current forest in 2026Q3 minus the RCA acres required) could be worked out for 16.
  It runs from 27.1 acres (New Hill Commons, disclosed) and 25.3 (Horton Park, on the parent boundary)
  down to minus 7.3 (Apex Light Industrial's parent). Nine are negative: less forest is standing than the RCA figure.
- Horton Park check: 25CZ23, Exhibit B, Section 9, PDF page 69: "The PUD (146.899 acres) ... minimum of 20% ...",
  "no less than 20% (29.38 acres)". Parent current forest 54.7 acres, so 25.3.
- Not found for 17, including four of the larger ones: Welch Homestead (35% if mass graded, no acres), Greenway
  Waste, Jessie Drive Industrial, Apex Gateway Phase 1. 23CZ09 Hatcher is stated as exempt ("N/A").

## Things to check on the sheet image

- **Veridea.** Two plan sets (East Village Non-Residential, NC Children's Health) carry an RCA table reading "overall
  required 100.00 AC", with East Village 112.55 AC, South Village (East) 8.27 AC, West Village 70.87 AC and NC
  Children's 28.41 AC. The sheets do not say what "overall" covers and call the areas preliminary. No Veridea
  rezoning file read here contains the SD plan text, so the Veridea requirement itself was not found.
- 24CZ22 Courtyards on Wimberly: RCA required 7.19 acres is clear; RCA provided reads "238 AC," in both OCR passes.
- 22CZ17 Townes at the Station: the Phase 1-2 sheet reads required 5.74 acres (35%); the Phase 3 sheet's OCR reads
  "9.74 ACRES (55%)". The 5.74 is used; the Phase 3 reading is left out.
- 22CZ23 Yellowbridge: the 14.79 acres sits under the "RCA to be Provided" label but the line itself says "Req'd",
  with 14.82 acres provided on the next line.
- 23CZ18 Ashland and 22CZ17: the figure is RCA and buffers together, not RCA alone.
- 24CZ05, 23CZ16, 24CZ03, 24CZ16, 22CZ22, 25CZ09: the file gives more than one project acreage. All are recorded.
- Plan sets marked preliminary or "not approved for construction" on the sheet: 25CZ06 Brightwood Reserve, 25CZ07
  Estates at Old Raleigh. The Development layer lists both as approved.

## Limits

- A document that says nothing is "not found", not "none". Many rezoning files are a short ordinance or an
  application packet with no PD text, and for amendments the parent's PD text is attached only for Horton Park.
- OCR text has errors. Quotes are copied as OCR read them, so a quote can carry a wrong digit that is on the page
  that way. `read_by` in the quotes file shows which are OCR (104 of 522).
- RCA can be met with land that is not forest where the document allows it (buffers, ponds, play lawns), and forest
  outside the RCA is not all buildable. "Maximum further clearing" is an upper bound from two numbers.
- Only the first sheets of most plan sets were read. Tree survey, RCA plan and zoning-condition sheets further in
  were not.

Page text and PDFs are in `../../apex-canopy/rca_cache/` (not in git).

## Follow-ups (later on 2026-11-24)

**1. Veridea's RCA requirement.** The source is the Veridea Sustainable Development Plan adopted with ordinance #09CZ07
(dated 10 May 2011), found as a 135-page attachment in the Town's public meeting packets (`pkt_09CZ07`).
- Article 3.1.3 (PDF page 32): "a. 100 acres shall be designated for Resource Conservation Area." It is one of three
  parts of "a minimum of 250 acres of land" to be designated during site plan and subdivision approval.
- Article 3.4.3.1 (page 38): the UDO's RCA rule "shall apply to the Development as a whole as opposed to individual site
  plans or Subdivision Plans"; open space and recreation area count at 50%; off-site RCA may replace on-site RCA.
- So yes: 100 acres is the requirement for all of Veridea. It is a fixed acreage, not a percent, and the plan gives no
  total acreage to turn it into one. The "OVERALL REQUIRED 100.00 AC" on the plan sheets repeats it.
- The same article replaces the UDO's tree and vegetation conservation section with the plan's own landscape standards.
- The 25CZ18 file itself has no RCA standard; its Exhibit A lists changes and none touches RCA. Nothing read here shows
  the 100 acres being raised when later cases added ground (West Village, the expansions).
- Against the parent boundary used in this analysis (1,148 acres, 497 acres of current forest) that leaves 397 acres.
  The parent boundary is the 2011 ground; the current Veridea petition area (25CZ18) holds 557 acres of forest.

**2. Exemptions** (`build_exemptions.py`, `../out/rca_exemptions.csv`, `rca_exemption_coverage.csv`). 110 cases in
scope; documents for 106; an RCA figure or statement in the text for 67. Nine state an exemption, "N/A" or only the
mass-grading amount. Two require nothing and offer nothing: 23CZ09 Hatcher Property (Weston Reserve) and 15CZ24 Colby
Crossing. For 39 cases the documents say nothing either way. 23CZ13 was not read.

**3. The Town's RCA layer** (`rca_layer.py`, `../out/rca_layer_*.csv|txt`). The public `HOA_OS_RCA` layer has 785
polygons typed RCA, 1,123 acres. NAIP 2022 is the latest NAIP flight, so there is one 1 m date. Mapped RCA is 53%
tree canopy, 2% water and 45% open ground; for RCA platted by 2022, 49% tree canopy. 32.4 acres of mapped RCA are
inside clearing outlines detected since late 2022. Water is a simple NDVI and NDWI rule and will miss shaded or
weedy ponds.

**4. Dead links.** The DocumentCenter ids for 24CZ20, 25CZ06 and 25CZ07 are gone, including an older id for 24CZ20 in
another Town layer. The files are in the Town's public meeting packets; addresses are in `current_case_file_url` in
the filled list. No staff report or ordinance was found for 25CZ07. 24CZ20's PUD text was located but not read,
disclosed.

**5. Hand search.** Welch Homestead (25CZ10), Jessie Drive Industrial (25CZ09) and Camp Branch Lane (25CZ19) each
have a plan set listed as Proposed in the Development layer, with RCA acres on it: 28.61, 12.96 and 7.77. These are
applicants' figures before approval. Apex Gateway Phase 1 (22CZ24): the staff report was found and has no RCA figure;
the case only changes a tree replacement condition, and there is no plan record on its ground. New Hill Holleman Rd
(24CZ03): nothing in the case file or the Planning Board report, and no plan record.
