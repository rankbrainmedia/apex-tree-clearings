#!/usr/bin/env python
"""find_pages.py: for each downloaded case file, list the pages that mention each topic, so a reader goes straight to them.

    ../../apex-canopy/df-venv/bin/python find_pages.py [key ...]

Writes ../../apex-canopy/rca_cache/hits/<key>.md: one line per topic with page numbers, then every matching line with
its page number. It finds places to read. It extracts nothing: every value in the results is read from the page itself.
"""
import glob, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "..", "..", "apex-canopy", "rca_cache")
TOPICS = {
    "RCA": r"\bR\.?C\.?A\.?\b|resource conservation",
    "grading": r"mass[\s-]*grad|stage[d]?[\s-]*grad|staged grading|clear[\s-]*cut|grading",
    "buffers, floodplain, wetlands": r"stream buffer|riparian|flood\s?plain|wetland",
    "limits of disturbance": r"limits? of (land )?disturbance|disturbed area|land disturb|area (to be )?disturbed",
    "trees": r"tree (preserv|replace|replant|sav|protect|removal|survey)|replacement tree|existing tree|champion tree|specimen tree|hardwood|caliper|tree canopy|replant",
    "project acres": r"total (project |site |gross |tract |land )?(area|acreage|acres)|\d[\d,.]*\s*(\+/-|±|\+-)?\s*(total )?acres|\bacreage\b|\bAC\.?\b",
    "exhibits and sections": r"^\s*(exhibit|section|attachment)\s+[A-Z0-9]+\b|planned (unit )?development (text|plan)|PUD text|PD text|sustainable development",
}


def main(keys):
    os.makedirs(os.path.join(CACHE, "hits"), exist_ok=True)
    for key in keys or sorted(os.path.basename(d) for d in glob.glob(os.path.join(CACHE, "text", "*"))):
        pages = sorted(glob.glob(os.path.join(CACHE, "text", key, "p*.txt")))
        if not pages:
            continue
        out, lines = [f"# {key}: {len(pages)} pages", ""], []
        how = {int(os.path.basename(p)[1:5]): open(p + ".how").read() for p in pages if os.path.exists(p + ".how")}
        out.append("Pages read by OCR: " + (", ".join(str(n) for n, h in how.items() if h == "OCR") or "none"))
        for topic, pat in TOPICS.items():
            rx = re.compile(pat, re.I | re.M)
            hit = {}
            for p in pages:
                n = int(os.path.basename(p)[1:5])
                for ln in open(p).read().splitlines():
                    if rx.search(ln):
                        hit.setdefault(n, []).append(re.sub(r"\s+", " ", ln).strip()[:220])
            out.append(f"- **{topic}**: pages " + (", ".join(f"{n} ({len(v)})" for n, v in hit.items()) or "none"))
            if topic not in ("project acres", "exhibits and sections"):
                for n, v in hit.items():
                    lines += [f"  p{n} [{topic}] {x}" for x in v[:12]]
            elif topic == "exhibits and sections":
                for n, v in hit.items():
                    lines += [f"  p{n} [{topic}] {x}" for x in v[:4]]
        open(os.path.join(CACHE, "hits", key + ".md"), "w").write("\n".join(out + ["", "## Matching lines (pointers only: read the page)"] + lines) + "\n")
        print(key, len(pages), "pages")


if __name__ == "__main__":
    main(sys.argv[1:])
