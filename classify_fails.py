#!/usr/bin/env python3
"""
classify_fails.py - READ-ONLY diagnostic: WHY does each contest fail its checksum?
----------------------------------------------------------------------------------
Purpose. check_csv.py tells us HOW MANY contests fail. This tells us WHY, by sorting
every failing contest into buckets so we can separate:

  (A) SEGMENTATION / LABEL-COLLISION  -> code problem, NOT manual keying.
      Two or more real contests share one (precinct, office, party) key because the
      OCR gave them the same (often generic/garbled) office string. Tells: the key
      contains more than one distinct vote_for value, or more than one distinct
      contest_votes value, or an obviously-generic office name (Public Question,
      Conv Delegate) that repeats. Hand-editing these would corrupt good rows.

  (B) TRUE UNDER-READ  -> genuine manual fix from the PDF.
      A single clean contest (one vote_for=1, one VOTES=) whose candidate totals sum
      to LESS than VOTES= -> a dropped candidate row or a dropped vote-split column.

  (C) TRUE OVER-READ   -> investigate (usually a duplicated row or a neighbor's row
      bleeding in); a single clean contest whose totals sum to MORE than VOTES=.

  (D) OFF-BY-ONE       -> almost always a write-in read as 0; trivial.

This script MODIFIES NOTHING. It only reads the CSV(s) and prints a breakdown, plus
a few example contests per bucket so we can eyeball them.

Usage:
    python3 classify_fails.py            # the two corrected OCR CSVs (defaults)
    python3 classify_fails.py a.csv b.csv
"""

import sys, csv
from collections import defaultdict

DEFAULTS = [
    "results_long_2008-general-precinct-corrected.csv",
    "results_long_2022-primary-precinct-corrected.csv",
]

# office strings that are generic enough that OCR routinely collapses several
# distinct contests onto them (used only to LABEL a suspected segmentation case)
GENERIC = ("public question", "conv delegate", "convention delegate",
           "precinct committee", "committeeman", "committeeperson", "delegate")


def num(v):
    try:
        return int(str(v).strip())
    except Exception:
        return None


def pnorm(s):
    s = str(s).strip()
    return str(int(s)) if s.isdigit() else s


def classify(path):
    try:
        rows = list(csv.DictReader(open(path)))
    except FileNotFoundError:
        print(f"\n### {path}\n  (file not found - skipping)")
        return
    if not rows:
        print(f"\n### {path}\n  (empty)")
        return

    # group every row by the contest key the checksum uses
    groups = defaultdict(list)
    for r in rows:
        key = (pnorm(r.get("precinct_id", "")),
               str(r.get("office", "")).strip(),
               str(r.get("contest_party", "") or "").strip())
        groups[key].append(r)

    seg = under = over = off1 = 0          # bucket counters
    ex = {"SEG": [], "UNDER": [], "OVER": []}   # a few examples each

    for (pid, off, cp), rs in groups.items():
        vfs = {str(r.get("vote_for", "")).strip() for r in rs}
        cvs = {num(r.get("contest_votes")) for r in rs if num(r.get("contest_votes")) is not None}
        # is this contest even checkable the same way check_csv checks it?
        # check_csv only checks vote_for==1 with a known single VOTES=.
        vote_for_1 = any(v in ("1", "1.0") for v in vfs)
        if not (vote_for_1 and cvs):
            continue
        s = sum(num(r.get("total")) or 0 for r in rs)
        cv_single = num(rs[-1].get("contest_votes"))  # same pick as check_csv
        if cv_single is None or s == cv_single:
            continue  # passes (or not comparable) -> not a fail

        # --- it's a FAIL; now decide WHY ---------------------------------
        multi_vf = len({v for v in vfs if v not in ("", "0", "0.0")}) > 1
        multi_cv = len(cvs) > 1
        generic = any(g in off.lower() for g in GENERIC)
        delta = cv_single - s

        if multi_vf or multi_cv or generic:
            seg += 1
            if len(ex["SEG"]) < 6:
                why = []
                if multi_vf: why.append(f"vote_for values={sorted(vfs)}")
                if multi_cv: why.append(f"VOTES= values={sorted(cvs)}")
                if generic:  why.append("generic office name")
                ex["SEG"].append((pid, cp, off[:42], s, cv_single, "; ".join(why)))
        elif abs(delta) == 1:
            off1 += 1
        elif delta > 0:
            under += 1
            if len(ex["UNDER"]) < 6:
                ex["UNDER"].append((pid, cp, off[:42], s, cv_single, f"missing {delta}"))
        else:
            over += 1
            if len(ex["OVER"]) < 6:
                ex["OVER"].append((pid, cp, off[:42], s, cv_single, f"extra {-delta}"))

    total = seg + under + over + off1
    print(f"\n### {path}")
    print(f"  total failing contests classified: {total}")
    print(f"    (A) SEGMENTATION / label-collision : {seg:>4}   <- CODE fix, not manual")
    print(f"    (B) TRUE UNDER-READ (dropped rows) : {under:>4}   <- genuine manual keying")
    print(f"    (C) TRUE OVER-READ  (extra rows)   : {over:>4}   <- investigate")
    print(f"    (D) OFF-BY-ONE (write-in as 0)     : {off1:>4}   <- trivial")

    for label, key in (("A/SEGMENTATION", "SEG"), ("B/UNDER-READ", "UNDER"), ("C/OVER-READ", "OVER")):
        if ex[key]:
            print(f"\n  examples - {label}:")
            print(f"    {'prec':>5} {'pty':>3}  {'sum':>6} {'VOTES=':>6}  office / reason")
            for pid, cp, off, s, cv, why in ex[key]:
                print(f"    {pid:>5} {cp:>3}  {s:>6} {cv:>6}  {off}  [{why}]")


def main():
    for p in (sys.argv[1:] or DEFAULTS):
        classify(p)
    print()


if __name__ == "__main__":
    main()
