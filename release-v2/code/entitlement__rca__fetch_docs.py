#!/usr/bin/env python
"""fetch_docs.py: download the Town's case file for every row of ../out/review_list.csv and turn every page into text.

    ../../apex-canopy/df-venv/bin/python fetch_docs.py [extra.csv]

Each PDF comes from the row's town_case_file_url (apexnc.org DocumentCenter, public). Page text is the PDF's own text
layer (pdftotext -layout). A page with fewer than 200 characters of text is treated as a scan: it is rendered at
300 dpi and read with Tesseract. Needs poppler (pdftotext, pdftoppm, pdfinfo) and tesseract on the PATH.
An optional extra.csv (columns key,url) adds other documents, used for Development-layer plan sets.

Writes ../../apex-canopy/rca_cache/docs/<key>.pdf, text/<key>/p0001.txt ..., and docs.csv (not in git).
"""
import csv, hashlib, os, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "..", "..", "apex-canopy", "rca_cache")
DOCS, TEXT = os.path.join(CACHE, "docs"), os.path.join(CACHE, "text")
os.makedirs(DOCS, exist_ok=True); os.makedirs(TEXT, exist_ok=True)
MIN_TEXT = 200
MAX_PAGES = int(os.environ.get("MAX_PLAN_PAGES", 8))      # sheets read from a plan set (a key starting with 'plan')
OCR_DPI = 300


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, **kw)


def download(key, url):
    fn = os.path.join(DOCS, key + ".pdf")
    if not os.path.exists(fn) or os.path.getsize(fn) < 1000:
        r = run(["curl", "-sS", "-L", "-m", "600", "-A", "Mozilla/5.0 (document fetch)", "-o", fn, "-w", "%{http_code} %{content_type}", url])
        status = r.stdout.decode().strip()
    else:
        status = "cached"
    head = open(fn, "rb").read(5) if os.path.exists(fn) else b""
    return fn, status, head == b"%PDF-"


def page_text(args):
    key, fn, n = args
    out = os.path.join(TEXT, key, f"p{n:04d}.txt")
    if os.path.exists(out):
        t = open(out).read()
        return n, len(re.sub(r"\s", "", t)), open(out + ".how").read() if os.path.exists(out + ".how") else "?"
    t = run(["pdftotext", "-f", str(n), "-l", str(n), "-layout", fn, "-"]).stdout.decode("utf-8", "replace")
    how = "text layer"
    if len(re.sub(r"\s", "", t)) < MIN_TEXT:
        base = os.path.join(TEXT, key, f"_p{n:04d}")
        run(["pdftoppm", "-f", str(n), "-l", str(n), "-r", str(OCR_DPI), "-gray", "-png", "-singlefile", fn, base])
        if os.path.exists(base + ".png"):
            o = run(["tesseract", base + ".png", "-", "--psm", "3", "-l", "eng"]).stdout.decode("utf-8", "replace")
            os.remove(base + ".png")
            if len(re.sub(r"\s", "", o)) > len(re.sub(r"\s", "", t)):
                t, how = o, "OCR"
    open(out, "w").write(t); open(out + ".how", "w").write(how)
    return n, len(re.sub(r"\s", "", t)), how


def main():
    rows = [(r.case, r.town_case_file_url) for r in pd.read_csv(os.path.join(HERE, "..", "out", "review_list.csv")).fillna("").itertuples() if r.town_case_file_url]
    if len(sys.argv) > 1:
        rows = [(r["key"], r["url"]) for r in csv.DictReader(open(sys.argv[1]))]
    def one(kv):
        key, url = kv
        fn, status, ok = download(key, url)
        if not ok:
            print(key, "NOT A PDF", status, flush=True)
            return dict(key=key, url=url, status=status, is_pdf=False)
        info = run(["pdfinfo", fn]).stdout.decode("utf-8", "replace")
        pages = int(re.search(r"Pages:\s+(\d+)", info).group(1))
        os.makedirs(os.path.join(TEXT, key), exist_ok=True)
        todo = min(pages, MAX_PAGES) if key.startswith("plan") else pages          # plan sets: the site data table is on the first sheets
        with ThreadPoolExecutor(6) as ex:
            res = list(ex.map(page_text, [(key, fn, n) for n in range(1, todo + 1)]))
        ocr = sum(1 for _, _, h in res if h == "OCR"); empty = sum(1 for _, c, _ in res if c < 50)
        print(key, pages, "pages,", ocr, "by OCR,", empty, "nearly empty,", round(os.path.getsize(fn) / 1e6, 1), "MB", flush=True)
        return dict(key=key, url=url, status=status, is_pdf=True, bytes=os.path.getsize(fn), sha256=hashlib.sha256(open(fn, "rb").read()).hexdigest(), pages=pages, pages_read=todo, pages_ocr=ocr, pages_nearly_empty=empty)

    with ThreadPoolExecutor(5) as ex:                      # five documents at a time
        log = list(ex.map(one, rows))
    fn = os.path.join(CACHE, "docs.csv")
    old = pd.read_csv(fn) if os.path.exists(fn) else pd.DataFrame()
    new = pd.DataFrame(log)
    pd.concat([old[~old.key.isin(new.key)] if len(old) else old, new]).to_csv(fn, index=False)


if __name__ == "__main__":
    main()
