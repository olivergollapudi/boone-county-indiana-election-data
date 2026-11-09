#!/usr/bin/env python3
"""
dump_boxes.py - re-OCR a few pages with Apple Vision and save the RAW token boxes
---------------------------------------------------------------------------------
Why. The cached …-applelines.json kept only the reconstructed text LINES, not the
per-token (x, y) coordinates. To rebuild the table by GEOMETRY (assign each number to
a column by its x-position, keep each name glued to its row by y-position) we need
those coordinates back. This re-runs the SAME Apple Vision engine we already trust for
digit accuracy, but saves every token's bounding box instead of throwing it away.

It writes a cache (…-appleboxes.json) so we only pay the OCR cost once, and prints the
tokens for the requested pages sorted top->bottom, left->right so we can SEE the grid
(column x-positions, and how far apart a split name/number row actually sits).

Coordinates are normalized 0..1 with origin BOTTOM-LEFT (Apple Vision's convention):
each token is [text, x_left, y_bottom, w, h].

The PDF name is looked up in source_pdfs/; the cache is written to ocr_cache/.

Run (macOS only, from the repository root):
    python3 scripts/dump_boxes.py                 # default: 2008 pages 141-143 (precinct 49)
    python3 scripts/dump_boxes.py 2008-general-precinct.pdf 141 143
    python3 scripts/dump_boxes.py 2022-primary-precinct.pdf 0 2
"""

import io, sys, json
from pathlib import Path

try:
    import fitz                       # PyMuPDF
    from ocrmac import ocrmac
    from PIL import Image
except ImportError as e:
    sys.exit(f"Missing dependency ({e}). Run:  pip install ocrmac pymupdf pillow")

DPI = 350

from paths import PDF_DIR, OCR_DIR

SRC   = PDF_DIR / Path(sys.argv[1] if len(sys.argv) > 1 else "2008-general-precinct.pdf").name
START = int(sys.argv[2]) if len(sys.argv) > 2 else 141      # 0-based page index (matches the JSON list index)
END   = int(sys.argv[3]) if len(sys.argv) > 3 else 143      # inclusive


def ocr_page_boxes(page):
    pix = page.get_pixmap(dpi=DPI)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    ann = ocrmac.OCR(img, recognition_level="accurate",
                     language_preference=["en-US"]).recognize()
    out = []
    for text, conf, box in ann:            # box = (x, y, w, h), normalized, origin bottom-left
        if text.strip():
            x, y, w, h = box
            out.append([text, round(x, 4), round(y, 4), round(w, 4), round(h, 4)])
    return out


def main():
    if not SRC.exists():
        sys.exit(f"Missing {SRC}")
    doc = fitz.open(SRC)
    cache_path = OCR_DIR / (SRC.stem + "-appleboxes.json")
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}

    verbose = (END - START) <= 4            # only dump per-token detail for small ranges
    for p in range(START, END + 1):
        if p >= len(doc):
            break
        print(f"OCR page {p}/{len(doc)-1} …", file=sys.stderr)
        toks = ocr_page_boxes(doc[p])
        cache[str(p)] = toks
        if verbose:
            toks_sorted = sorted(toks, key=lambda t: (-(t[2] + t[4] / 2), t[1]))
            print(f"\n===== PAGE {p}  ({len(toks)} tokens) =====")
            print(f"  {'y_ctr':>6} {'x_left':>7}  text")
            for text, x, y, w, h in toks_sorted:
                print(f"  {y + h/2:6.3f} {x:7.3f}  {text!r}")

    cache_path.write_text(json.dumps(cache))
    print(f"\nSaved boxes for pages {START}-{END} to {cache_path.name} "
          f"(re-run other page ranges to append).", file=sys.stderr)


if __name__ == "__main__":
    main()
