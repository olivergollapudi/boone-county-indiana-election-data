#!/usr/bin/env python3
"""
categorize.py - per-file text-quality categorizer (which PDFs need OCR)
-----------------------------------------------------------------------
For every PDF, counts how many pages are image (scanned) vs text (embedded)
and assigns a category:

  EMBEDDED  - all pages are text            -> parse directly (already done)
  MIXED     - some scanned, some text       -> the scanned part is the front
                                               summary; precinct pages are text,
                                               so NO OCR needed for the data
  SCANNED   - all (or nearly all) pages image -> needs the OCR pipeline

A page is "scanned" if it yields < 50 extractable characters.

Run:
    cd ~/Documents/"Boone County Data"
    source .venv/bin/activate
    python3 categorize.py
"""

import glob, warnings
import pdfplumber
warnings.filterwarnings("ignore")

print(f"{'file':32}{'pages':>6}{'scanned':>8}{'text':>6}  category")
print("-" * 70)
for f in sorted(glob.glob("*.pdf")):
    with pdfplumber.open(f) as doc:
        n = len(doc.pages)
        scanned = sum(1 for p in doc.pages if len(p.extract_text() or "") < 50)
    text = n - scanned
    if scanned == 0:
        cat = "EMBEDDED"
    elif scanned >= n - 1:                 # all (or all-but-one) pages are images
        cat = "SCANNED  -> OCR"
    else:
        cat = f"MIXED (scanned pages = front summary; no OCR needed)"
    print(f"{f:32}{n:>6}{scanned:>8}{text:>6}  {cat}")
