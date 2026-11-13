#!/usr/bin/env python3
"""
reconcile_all.py - independent countywide cross-check for the whole archive
---------------------------------------------------------------------------
For every election that HAS a clean (embedded) summary report, confirm that the
parsed precinct rows in results_long_all.csv sum up to the Clerk's separate
countywide summary, candidate by candidate. This is the strong defensibility
check (§5): two different documents from the same source agreeing.

Elections with only a precinct file (most legacy years) can't be cross-checked
here - they rely on the within-contest checksum already enforced by parse_all.py.

Reuses parse_all.py's patterns. Reads results_long_all.csv (override via env
BOONE_OUT). Modifies nothing.

Run (from the repository root):
    python3 scripts/reconcile_all.py
"""

import csv, os, re, sys, glob
from collections import defaultdict
from pathlib import Path

import parse_all as P     # reuse regexes + split_party

try:
    import pdfplumber
except ImportError:
    sys.exit("Missing dependency. Run:  pip install pdfplumber")

from paths import PDF_DIR, DATA_DIR

CSV    = Path(os.environ.get("BOONE_OUT", DATA_DIR / "results_long_all.csv"))

# summaries that are scanned -> no cross-check here (OCR later)
SKIP_SUMMARY = {"2011-primary-summary.pdf", "2022-primary-summary.pdf"}


def norm(s):
    return " ".join((s or "").split()).casefold()


def parse_summary(path):
    """Countywide summary -> {(office, contest_party, candidate): total}."""
    lines = []
    with pdfplumber.open(path) as doc:
        for pg in doc.pages:
            lines.extend((pg.extract_text() or "").split("\n"))
    out = defaultdict(int)
    office = office_party = None
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        m = P.RE_COMBO.search(line)
        if m:
            office_party, _, office = P.split_party(m.group(2).strip(), None); continue
        m = P.RE_VOTES.match(line)
        if m:
            rem = m.group(2).strip()
            if rem:
                office_party, _, office = P.split_party(rem, None)
            continue
        if P.RE_VFOR.match(line):
            continue
        m = P.RE_CAND.match(line)
        if m and office is not None:
            total = int(m.group(4))
            party, _, cand = P.split_party(m.group(6), office_party)
            out[(norm(office), office_party, norm(cand))] += total
            continue
        # standalone office line (modern general summaries put office on its own line)
        if not line[0].isdigit() and not P.NOISE.search(line) and "%" not in line:
            office_party, _, office = P.split_party(line, None)
    return out


def load_precinct_totals():
    """results_long_all.csv -> {source_key: {(office,contest_party,candidate): total}}."""
    if not CSV.exists():
        sys.exit(f"Missing {CSV.name} - run parse_all.py first.")
    data = defaultdict(lambda: defaultdict(int))
    with open(CSV, newline="") as f:
        for r in csv.DictReader(f):
            # source_file_id like "2024-GENERAL-PRECINCT" -> key "2024-general"
            key = "-".join(r["source_file_id"].split("-")[:2]).lower()
            cp = r["contest_party"] or None
            data[key][(norm(r["office"]), cp, norm(r["candidate"]))] += int(r["total"])
    return data


def cross_check():
    """Compare every clean countywide summary with the parsed precinct rows.

    Returns {election key e.g. "2024-general": result}, where result is None for a
    summary-only election (no precinct file), else a dict with:
      matched   candidates found in both documents
      mismatch  list of (key, summary total, precinct total) that disagree
      only_sum / only_prec   candidates found in just one document
    Used by main() below and by build_workbook.py, so the workbook's cross-check column
    is computed, never typed.
    """
    precinct = load_precinct_totals()
    summaries = [Path(f) for f in sorted(glob.glob(str(PDF_DIR / "*-summary.pdf")))
                 if Path(f).name not in SKIP_SUMMARY]
    results = {}
    for spath in summaries:
        ekey = "-".join(spath.stem.split("-")[:2]).lower()       # "2024-general"
        if ekey not in precinct:
            results[ekey] = None
            continue
        summ, prec = parse_summary(spath), precinct[ekey]
        both = set(summ) & set(prec)
        results[ekey] = {"matched": len(both),
                         "mismatch": [(k, summ[k], prec[k]) for k in both if summ[k] != prec[k]],
                         "only_sum": len(set(summ) - set(prec)),
                         "only_prec": len(set(prec) - set(summ))}
    return results


def main():
    print(f"{'election':18}{'matched':>8}{'agree':>7}{'MISMATCH':>9}{'only-sum':>9}{'only-prec':>10}")
    print("-" * 62)
    overall_bad = 0
    for ekey, r in cross_check().items():
        if r is None:
            print(f"{ekey:18}  (no precinct file to compare - summary-only)")
            continue
        bad = len(r["mismatch"])
        overall_bad += bad
        print(f"{ekey:18}{r['matched']:>8}{r['matched'] - bad:>7}{bad:>9}{r['only_sum']:>9}{r['only_prec']:>10}")
        for k, s, p in r["mismatch"][:4]:
            print(f"    MISMATCH {k}  summary={s}  precinct={p}")

    print("-" * 62)
    print(f"TOTAL candidate-level mismatches across all cross-checkable elections: {overall_bad}")
    print("0 = every parsed precinct total reconciles to the independent county summary.")
    if overall_bad:
        sys.exit("STOP: precinct totals disagree with a county summary - inspect before going on.")


if __name__ == "__main__":
    main()
