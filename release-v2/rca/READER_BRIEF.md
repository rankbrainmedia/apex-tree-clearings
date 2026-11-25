# Reading a case file for tree-save numbers

You are reading Town of Apex rezoning case files (public PDFs, already turned into one text file per page) and
recording what each one says about tree and open-space protection. The output is checked by a script: every sentence
you record must be on the page you cite, word for word. Anything that is not is thrown away.

## Where things are

- Page text: `apex-canopy/rca_cache/text/<CASE>/p0001.txt`, `p0002.txt`, ...
  The number in the file name is the PDF page number. That is the page number to record.
  `p0001.txt.how` says whether the page came from the PDF's text layer or from OCR. OCR text has errors.
- A topic index per case: `apex-canopy/rca_cache/hits/<CASE>.md`.
  It lists pages that mention RCA, grading, buffers, limits of disturbance, trees, acres and exhibit headings.
  Use it to find pages. Then read the pages themselves. Also read pages the index may have missed: the PD/PUD text
  (often an exhibit, with numbered sections), the list of zoning conditions, and the staff report's summary.
- Write one file per case: `entitlement/rca/extracted/<CASE>.json`.

## What to record

For each case, look for these fields. "RCA" is Resource Conservation Area.

| field | what it is |
|---|---|
| `project_acres` | total project acres as the document states them |
| `rca_required_pct` | RCA required, as a percent of the site |
| `rca_required_ac` | RCA required, in acres |
| `rca_provided` | RCA provided or proposed, percent and/or acres, if stated |
| `rca_may_count` | what the document says may count as RCA (stream buffers, floodplain, ponds, play lawns, perimeter buffers, and so on) |
| `grading_type` | whether the site is mass graded or stage graded (staged) |
| `rca_bonus_or_reduction` | any RCA increase, bonus, credit or reduction, and what triggers it |
| `stream_buffer_ac` | stream or riparian buffer acres |
| `floodplain_ac` | floodplain acres |
| `wetland_ac` | wetland acres |
| `limits_of_disturbance_ac` | limits of disturbance, or disturbed area, in acres |
| `tree_condition` | any zoning condition about tree preservation, tree replacement, tree surveys or replanting |

`scope` says whose numbers they are:
- `"case"`: the area this rezoning petition covers.
- `"parent"`: the whole parent project, when the case is an amendment and the file carries the parent project's
  PD/PUD/SD text or numbers for the full project (often as an exhibit). The task list tells you which cases are
  amendments and what their parent is. If a number is for the full project, it is `parent`, even though it is in
  the amendment's file. If the case is not an amendment, everything is `case`.

## Rules

1. **Record only what the page says.** No estimates, no arithmetic, no inference. If the document gives a percent
   and no acres, record the percent and leave acres out. Do not multiply.
2. **Quote exactly.** `sentence` is copied from the page text file as it is, including OCR mistakes. Join lines with
   a single space. Do not fix spelling, do not drop words from the middle, do not add anything. Keep it to the
   sentence or table row that carries the value (one to three lines). For a table row, copy the row.
3. **The value must be in the sentence.** For a number field, the digits you put in `value` must appear in `sentence`.
4. **Adopted or proposed terms only.** Many files include the Town's blank checklist of *suggested* conditions (for
   example from the Environmental Advisory Board, with empty blanks or check boxes). Those are not this project's
   conditions. Skip them unless the document shows the applicant accepted one with a filled-in value, and say so in
   `note`. Skip boilerplate about the UDO in general, neighbour comments and meeting minutes, unless they state a
   project number that appears nowhere else (then say in `note` where it is from).
5. **Prefer the governing text.** Where the same value appears several times, take it from the PD/PUD text or the
   list of zoning conditions first, then the staff report. Record the exhibit and section in `where`
   (for example "Exhibit B, Section 9"), if the page or a nearby heading shows it.
6. `rca_may_count` and `tree_condition` can have several entries, one per sentence. Other fields: one entry per
   scope, unless the document gives genuinely different figures (then record each and explain in `note`).
7. If a field is not in the document, do not make an entry for it. List it in `not_found`.
8. Do not use any source other than the page text files. No web lookups.

## Output format

```json
{
  "case": "25CZ23",
  "doc": "25CZ23",
  "entries": [
    {"field": "rca_required_pct", "scope": "parent", "value": "20%", "page": 61,
     "sentence": "exact text from p0061.txt", "where": "Exhibit B, Section 9", "note": ""}
  ],
  "not_found": {"case": ["wetland_ac"], "parent": ["limits_of_disturbance_ac"]},
  "notes": "One or two plain sentences: what kind of document this is, where the PD text and conditions are (page ranges), and anything a reviewer should know (for example, half the pages are OCR and hard to read)."
}
```

Before you finish a case, re-open each cited page file and confirm every `sentence` is there word for word.

## Plan sets (second pass)

Where a rezoning file has no RCA acres, the project's approved subdivision or site plan is read instead. Plan sets are
under the same folders with a key like `plan526` (the Development layer's record id): page text in
`.../rca_cache/text/plan526/`, index in `.../rca_cache/hits/plan526.md`. Only the first sheets were converted
(up to 8), because the site data table is normally on the cover sheet or sheet C001.

- Look for the same fields in the **site data table** and the general notes: site or project acreage, RCA required
  (percent and acres), RCA provided, what is counted as RCA, mass or staged grading and any RCA addition for it,
  stream buffer, floodplain and wetland acres, limits of disturbance or disturbed area, tree notes.
- Use `"scope": "plan"` for every entry: the numbers describe the plan's own site, which may be the whole case or
  only one phase of it. Put the sheet name or number in `where` (for example "Sheet C001, Site Data").
- Plan sheets come out of the PDF with table columns run together. Quote the table row or line exactly as it is in
  the page text file. If a row is too scrambled to tell which number belongs to which label, do not record it; say
  so in `notes`.
- Write `entitlement/rca/extracted/<CASE>.<PLANKEY>.json`
  (for example `23CZ18.plan526.json`) with `"case": "<CASE>"` and `"doc": "<PLANKEY>"`. One file per plan set.
  In `notes`, give the project name on the cover sheet, the sheet you used, and whether the plan appears to cover
  the whole project or one phase.

## One more field (office-period pass)

| field | what it is |
|---|---|
| `rca_exemption` | any statement that the project is exempt from RCA, that RCA is "N/A" or "none", that the UDO does not require RCA for it (for example low density, two units per acre or fewer, or the small town character overlay), or that only the mass-grading amount applies. Quote the sentence. If the project offers RCA anyway, say so in `note` and record that figure under the RCA fields. |

Everything else is as above: exact quotes, PDF page numbers, nothing inferred, nothing computed.
