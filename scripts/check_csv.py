#!/usr/bin/env python3
"""
check_csv.py - READ-ONLY checksum reporter for a parsed/corrected long CSV
--------------------------------------------------------------------------
Reports, for one or more results_long_*.csv files, how many VOTE-FOR-1 contests
currently reconcile (candidate totals sum to the contest's reported VOTES=), and
lists the ones that still FAIL so we can see exactly how much manual work remains.

This does NOT modify anything. It only reads the CSV(s) and prints a report.
Same checksum definition the parser/reconciler use: for each contest keyed by
(precinct_id, office, contest_party) with vote_for==1 and a known contest_votes,
sum(total) must equal contest_votes.

Usage (from the repository root):
    python3 scripts/check_csv.py                           # the two raw OCR parses in build/
    python3 scripts/check_csv.py data/results_long_all.csv # or any file(s) you name
"""

import sys, csv
from collections import defaultdict
from paths import BUILD_DIR

DEFAULTS = [
    str(BUILD_DIR / "results_long_2008-general-precinct-geom.csv"),
    str(BUILD_DIR / "results_long_2022-primary-precinct-geom.csv"),
]


def num(v):
    try:
        return int(str(v).strip())
    except Exception:
        return None


def pnorm(s):
    s = str(s).strip()
    return str(int(s)) if s.isdigit() else s


def report(path):
    try:
        rows = list(csv.DictReader(open(path)))
    except FileNotFoundError:
        print(f"\n### {path}\n  (file not found — skipping)")
        return
    if not rows:
        print(f"\n### {path}\n  (empty)")
        return

    # contest -> [sum_total, contest_votes, vote_for, n_rows]
    agg = defaultdict(lambda: [0, None, None, 0])
    for r in rows:
        key = (pnorm(r.get("precinct_id", "")),
               str(r.get("office", "")).strip(),
               str(r.get("contest_party", "") or "").strip())
        a = agg[key]
        a[0] += num(r.get("total")) or 0
        a[1] = num(r.get("contest_votes"))
        a[2] = str(r.get("vote_for", "")).strip()
        a[3] += 1

    # only vote-for-1 contests with a known VOTES= are checkable
    checkable = {k: v for k, v in agg.items()
                 if v[2] in ("1", "1.0") and v[1] is not None}
    fails = {k: v for k, v in checkable.items() if v[0] != v[1]}

    tot = len(checkable)
    ok = tot - len(fails)
    print(f"\n### {path}")
    print(f"  rows: {len(rows):,}   checkable vote-for-1 contests: {tot}")
    print(f"  PASS: {ok}/{tot} ({100*ok/max(tot,1):.1f}%)   FAIL: {len(fails)}")

    if fails:
        # sort by |deficit| descending so the big misses surface first
        ordered = sorted(fails.items(), key=lambda kv: -abs(kv[1][1] - kv[1][0]))
        trivial = sum(1 for _, v in ordered if abs(v[1] - v[0]) == 1)
        print(f"  (of the fails, {trivial} are off by exactly 1 — usually a write-in read as 0)")
        print(f"  {'precinct':>8} {'party':>5}  {'sum':>6} {'VOTES=':>6} {'delta':>6}  office")
        for (pid, off, cp), (s, cv, vf, n) in ordered[:60]:
            print(f"  {pid:>8} {cp:>5}  {s:>6} {cv:>6} {cv-s:>6}  {off[:48]}")
        if len(ordered) > 60:
            print(f"  ... and {len(ordered)-60} more failing contests")


def main():
    paths = sys.argv[1:] or DEFAULTS
    for p in paths:
        report(p)
    print()


if __name__ == "__main__":
    main()
