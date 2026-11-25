#!/usr/bin/env python
"""ocr_sheets.py: read plan sheets whose site data table is drawn as an image rather than text.

    ../../apex-canopy/df-venv/bin/python ocr_sheets.py plan565:1-3 plan624:1-2 ...

For each named page the sheet is rendered at 300 dpi and read by Tesseract twice (block layout and sparse text). The OCR
text is appended to the page's text file under a marker line, so a quote can be checked against it like any other.
"""
import os, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "..", "..", "apex-canopy", "rca_cache")
MARK = "\n\n===== OCR of the sheet image (300 dpi) =====\n"


def one(job):
    key, n = job
    fn, out = os.path.join(CACHE, "docs", key + ".pdf"), os.path.join(CACHE, "text", key, f"p{n:04d}.txt")
    old = open(out).read() if os.path.exists(out) else ""
    if MARK in old:
        return key, n, "already done"
    base = os.path.join(CACHE, "text", key, f"_ocr{n:04d}")
    subprocess.run(["pdftoppm", "-f", str(n), "-l", str(n), "-r", "300", "-gray", "-png", "-singlefile", fn, base], capture_output=True)
    if not os.path.exists(base + ".png"):
        return key, n, "render failed"
    t = ""
    for psm in ("3", "11"):
        t += f"\n--- layout mode {psm} ---\n" + subprocess.run(["tesseract", base + ".png", "-", "--psm", psm, "-l", "eng"], capture_output=True, env=dict(os.environ, OMP_THREAD_LIMIT="1")).stdout.decode("utf-8", "replace")
    os.remove(base + ".png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w").write(old + MARK + t); open(out + ".how", "w").write("text layer + OCR" if len(re.sub(r"\s", "", old)) > 50 else "OCR")
    return key, n, f"{len(re.sub(r'\\s', '', t))} characters, RCA mentioned {len(re.findall(r'(?i)RCA|resource conservation', t))} times"


jobs = []
for a in sys.argv[1:]:
    key, rng = a.split(":")
    lo, hi = (rng.split("-") + [rng])[:2]
    jobs += [(key, n) for n in range(int(lo), int(hi) + 1)]
with ThreadPoolExecutor(8) as ex:
    for r in ex.map(one, jobs):
        print(*r, flush=True)
