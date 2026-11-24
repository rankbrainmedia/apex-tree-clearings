# 30-event validation sample

- `sample.csv`: the 30 events that were drawn. The draw was stratified by size (1–2 ac: 10, 2–5: 9, 5–15: 7, 15+: 4) and by
  first-detection season (16 leaf-off/transition, 14 leaf-on). The random seed and selection script weren't kept, so the sample is published as drawn.
- `tags.csv`: one row per event with these columns:
  - `tag`: CONFIRMED, FALSE or UNSURE.
  - `real_frac`: the analyst's visual estimate of how much of the outline is actually cleared, in steps of 0.05.
  - `imagery_used_for_tag`: the imagery the analyst looked at when tagging.
  - `recheck_on_release_images`: whether the tag still holds using only the published NAIP/Sentinel-2 images.
- `images/<id>.png`: six panels per event. NAIP 2020, NAIP 2022, then Sentinel-2 medians for 2022Q3 (baseline), the first-detection quarter,
  2026Q3 and 2026Q4 (1–24 Oct, partial). The yellow line is the event outline. Made with `code/08_sample_panels.py`.

**Result:** 30 CONFIRMED, 0 FALSE, 0 UNSURE. The 95% upper bound on the false-positive rate is 9.5% (exact binomial).
The area-weighted cleared fraction is 0.84.

**About the imagery:**
- 16 of the 30 tags were originally made with the Esri World Imagery basemap open alongside Sentinel-2. The Esri imagery isn't
  redistributable and isn't included here.
- Those 16 were re-checked against the published NAIP and Sentinel-2 panels only, and every tag still holds (see notes on C100, C163 and C228).
- The other 14 were tagged on Sentinel-2 alone from the start.
- No NAIP exists over Apex after Sep–Oct 2022, so every "after" view is 10 m Sentinel-2.
