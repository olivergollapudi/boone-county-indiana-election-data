"""
paths.py - the one place that says where every kind of file lives.

Every pipeline script imports these constants instead of assuming files sit next to it,
so the folder layout can be read (and changed) in one spot:

    source_pdfs/   the Boone County Clerk's result reports (raw evidence, never modified)
    ocr_cache/     cached Apple Vision OCR output for the scanned reports
    data/          validated outputs that are published (workbook + CSVs)
    build/         intermediate files the pipeline regenerates (git-ignored)

Scripts are run from anywhere, e.g.  python3 scripts/parse_all.py
"""
from pathlib import Path

ROOT      = Path(__file__).resolve().parent.parent
PDF_DIR   = ROOT / "source_pdfs"
OCR_DIR   = ROOT / "ocr_cache"
DATA_DIR  = ROOT / "data"
BUILD_DIR = ROOT / "build"


def build_path(name):
    """Path for an intermediate file in build/, creating the folder on first use."""
    BUILD_DIR.mkdir(exist_ok=True)
    return BUILD_DIR / name
