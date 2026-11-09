#!/usr/bin/env python3
"""
inventory.py - Boone County election PDF cataloguer
---------------------------------------------------
Walks a folder of County Clerk election-results PDFs and classifies each one
WITHOUT modifying any file. For every PDF it answers four questions:

  1. What election?      -> year + type (primary / general / municipal / special)
  2. What report?        -> precinct-breakdown  vs  countywide-summary
  3. Is the text usable? -> embedded text (parseable)  vs  scanned (needs OCR)
  4. How big?            -> page count + extractable characters per page

Output:
  - a readable table printed to the terminal
  - build/inventory.csv (one row per file)

Run (from the repository root):
    python3 scripts/inventory.py

Classification is heuristic and meant for HUMAN REVIEW - that is the whole point
of the inventory step. Anything uncertain is marked with "??".
"""

import csv
import re
import sys
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    sys.exit("Missing dependency. Run:  pip install pdfplumber")

from paths import PDF_DIR, build_path


def extract_text(pdf):
    """Return (full_text, n_pages, chars_per_page). Never raises on a bad page."""
    parts, n_pages = [], 0
    with pdfplumber.open(pdf) as doc:
        n_pages = len(doc.pages)
        for page in doc.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                parts.append("")
    text = "\n".join(parts)
    cpp = len(text) / n_pages if n_pages else 0
    return text, n_pages, cpp


def classify(name, text):
    """Guess election year, type, and report type from text (filename as backup)."""
    hay = (text + " " + name).lower()

    # Year: pick the 4-digit 20xx that appears most often in the text/title.
    years = re.findall(r"20[0-2]\d", hay)
    year = max(years, key=years.count) if years else "??"

    # Election type
    if "municipal" in hay:
        etype = "municipal"
    elif "primary" in hay:
        etype = "primary"
    elif "special" in hay:
        etype = "special"
    elif "general" in hay:
        etype = "general"
    else:
        etype = "??"

    # Report type: a precinct breakdown repeats the word "precinct" many times
    # (one block per precinct); a countywide summary barely uses it.
    precinct_hits = len(re.findall(r"precinct", text, re.I))
    if precinct_hits >= 15 or "precinct" in name.lower():
        rtype = "precinct-breakdown"
    elif precinct_hits == 0:
        rtype = "countywide-summary"
    else:
        rtype = "?? (precinct-mentions=%d)" % precinct_hits

    return year, etype, rtype, precinct_hits


def main():
    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    if not pdfs:
        sys.exit("No PDFs found in %s" % PDF_DIR)

    rows = []
    for pdf in pdfs:
        text, n_pages, cpp = extract_text(pdf)
        year, etype, rtype, phits = classify(pdf.name, text)
        text_status = "embedded" if cpp >= 50 else "SCANNED -> OCR"
        rows.append({
            "file": pdf.name,
            "year": year,
            "election": etype,
            "report": rtype,
            "text": text_status,
            "pages": n_pages,
            "chars/pg": int(cpp),
            "precinct_mentions": phits,
        })

    # Print a readable, aligned table to the terminal.
    cols = ["file", "year", "election", "report", "text", "pages", "chars/pg"]
    widths = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in cols}
    header = "  ".join(c.ljust(widths[c]) for c in cols)
    print(header)
    print("-" * len(header))
    for r in rows:
        print("  ".join(str(r[c]).ljust(widths[c]) for c in cols))

    # Write inventory.csv to build/ (regenerated; not published).
    out = build_path("inventory.csv")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("\nWrote %s  (%d files catalogued)" % (out, len(rows)))


if __name__ == "__main__":
    main()
