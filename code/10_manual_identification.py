#!/usr/bin/env python
"""Step 10 (added in v1.1): add the manual review column to case_join.csv / case_join.xlsx.

`inputs/manual_identification_2026-10-27.csv` holds what the analyst identified by eye from Google Earth
history on 2026-10-27, for the 22 events that matched no rezoning, development or residential-phase case.
The column is descriptive only. It is not used in any count, acreage or case-match total.

Usage: python 10_manual_identification.py <case_join.csv in> <out dir>
"""
import os, sys
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib
write = importlib.import_module("09_chatham_parcels").write

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "inputs", "manual_identification_2026-10-27.csv")

def main(cj_path, out_dir):
    cj = pd.read_csv(cj_path, dtype=str, keep_default_na=False)
    m = pd.read_csv(SRC, dtype=str, keep_default_na=False)
    assert m.id.is_unique and m.id.isin(cj.id).all(), "manual ids must be unique and present in case_join"
    cj = cj.drop(columns=["manual_identification"], errors="ignore")
    cj["manual_identification"] = cj.id.map(dict(zip(m.id, m.manual_identification))).fillna("")
    unmatched = cj[(cj.rezoning_cases == "") & (cj.development_cases == "") & (cj.residential_phases == "")].id
    print(f"manual ids: {len(m)}; unmatched events: {len(unmatched)}; "
          f"unmatched without a manual id: {sorted(set(unmatched) - set(m.id))}; "
          f"manual ids on matched events: {sorted(set(m.id) - set(unmatched))}")
    write(cj, out_dir)

if __name__ == "__main__":
    main(*sys.argv[1:3])
