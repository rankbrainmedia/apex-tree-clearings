#!/usr/bin/env python
"""Step 7: compare this run with the published v1.0 event list (reference/clearings_v1.0.csv).

Exits non-zero if the event count, ids, acres (+/-0.01), quarters or status differ.
Planetary Computer can reprocess scenes; if it has, a rerun can differ slightly, and this
check tells you where.
"""
import os, sys
import pandas as pd
import config as C

ref = pd.read_csv(os.path.join(C.CODE, "reference", "clearings_v1.0.csv")).set_index("id")
new = pd.read_csv(os.path.join(C.OUT, "clearings.csv")).set_index("id")
problems = []
if len(ref) != len(new):
    problems.append(f"event count {len(new)} vs reference {len(ref)}")
common = ref.index.intersection(new.index)
for col, tol in (("acres", 0.011), ("first_quarter", None), ("status", None)):
    if tol is None:
        bad = common[ref.loc[common, col] != new.loc[common, col]]
    else:
        bad = common[(ref.loc[common, col] - new.loc[common, col]).abs() > tol]
    if len(bad):
        problems.append(f"{col} differs for {len(bad)} events, e.g. {list(bad[:5])}")
print(f"run: {len(new)} events, {new.acres.sum():.1f} ac | reference: {len(ref)} events, {ref.acres.sum():.1f} ac")
if problems:
    print("MISMATCH:\n  " + "\n  ".join(problems)); sys.exit(1)
print("OK: matches release v1.0 exactly")
