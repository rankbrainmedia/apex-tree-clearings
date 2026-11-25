# Apex tree clearings: data release v2.0

An addition to release v1.1. Each folder holds the outputs of one analysis and `code/` the scripts that made them; `numbers.md` lists every figure in the report (Apex Trees Count, in preparation) with the file and row it comes from. Notes on method and limits are the `*_NOTES.md` files.

`verification/` holds the before-and-after pictures for the 375 checks, less the few held back (`release/`, `sample/`, `large/`), both verdict logs (`verify_log.csv`, `verify_log_large_optional.csv`) and the review page (`review.html`). `plant-the-peak/` holds summary tables only.

Not included: the Town's case-file PDFs (linked from the tables); the Plant the Peak point file, which carries home addresses (pull it from the Town's public layer with `plant_the_peak__overlay.py --pull`); the picture of any clearing that sits on a single home lot (`verification/PICTURES_HELD_BACK.csv`); and any record naming a private individual. A rezoning case that the zoning map names after a private applicant appears as `[private applicant]` with its case number. Every street address and county parcel number is replaced by `[street address]` or `[parcel number]`, including where one appears inside a sentence quoted from a Town case file; the case number and page beside each quotation lead to the original.
