#!/usr/bin/env python3
"""
finalize_ocr.py - split a geometry-parsed OCR election into (a) a CLEAN, 100%-
reconciling dataset for the master workbook and (b) a documented list of OMITTED
contests (approximate later; never fabricated into the master).
--------------------------------------------------------------------------------
Policy (the validation standard described in METHODOLOGY.md):
  * A contest is INCLUDED only if it is a vote-for-1 contest with a known VOTES=
    and its candidate totals sum EXACTLY to that VOTES=  (within-contest checksum = 0).
  * Everything else is OMITTED from the master and written to an omitted-contests
    log with its VOTES= target and the parsed shortfall, so it can be approximated
    in the analysis layer later. Nothing wrong ever enters the source of truth.

Outputs (for stem, e.g. 2008-general-precinct):
  results_long_<stem>-geom-clean.csv   - only rows in reconciling contests  -> INGEST
  omitted_<stem>.csv                   - one row per omitted contest         -> GAP LOG

Run:
    python3 finalize_ocr.py 2008-general-precinct
"""

import sys, csv
from pathlib import Path
from collections import defaultdict, OrderedDict

stem = sys.argv[1] if len(sys.argv) > 1 else "2008-general-precinct"
src = Path(f"results_long_{stem}-geom.csv")
rows = list(csv.DictReader(open(src)))

def num(v):
    try: return int(str(v).strip())
    except Exception: return None

# group rows by contest, preserving order
contests = OrderedDict()
for r in rows:
    k = (str(r["precinct_id"]), str(r["office"]), str(r.get("contest_party", "") or ""))
    contests.setdefault(k, []).append(r)

clean_rows, omitted = [], []
for (pid, office, cp), rs in contests.items():
    vf = str(rs[-1].get("vote_for", "")).strip()
    cv = num(rs[-1].get("contest_votes"))
    s = sum(num(x.get("total")) or 0 for x in rs)
    checkable = vf in ("1", "1.0") and cv is not None
    if checkable and s == cv:
        clean_rows.extend(rs)                       # reconciles exactly -> keep
    else:
        reason = ("checksum-fail" if checkable else
                  ("unverifiable-votefor-n" if cv is not None else "no-VOTES="))
        omitted.append({"source_file_id": rs[0].get("source_file_id", stem.upper()),
                        "precinct_id": pid, "office": office, "contest_party": cp,
                        "vote_for": vf, "contest_votes": cv if cv is not None else "",
                        "parsed_sum": s, "delta": (cv - s) if cv is not None else "",
                        "n_candidates": len(rs), "reason": reason})

# write clean ingestable csv (same schema as input)
clean_path = Path(f"results_long_{stem}-geom-clean.csv")
with open(clean_path, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=rows[0].keys()); w.writeheader(); w.writerows(clean_rows)

# write omitted gap log
omit_path = Path(f"omitted_{stem}.csv")
with open(omit_path, "w", newline="") as f:
    cols = ["source_file_id","precinct_id","office","contest_party","vote_for",
            "contest_votes","parsed_sum","delta","n_candidates","reason"]
    w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(omitted)

n_contests = len(contests)
n_omit = len(omitted)
print(f"{stem}")
print(f"  contests total            : {n_contests}")
print(f"  INCLUDED (reconcile 100%) : {n_contests - n_omit}  -> {clean_path.name} ({len(clean_rows):,} rows)")
print(f"  OMITTED (documented gap)  : {n_omit}  -> {omit_path.name}")
by = defaultdict(int)
for o in omitted: by[o["reason"]] += 1
for reason, c in sorted(by.items(), key=lambda kv: -kv[1]):
    print(f"      {reason:>24}: {c}")
