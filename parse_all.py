#!/usr/bin/env python3
"""
parse_all.py - unified, profile-detecting parser for ALL embedded precinct files
---------------------------------------------------------------------------------
Implements the axis-detection strategy from PARSING_STRATEGY.md. For each
`*-precinct.pdf` it auto-detects the format per-line (vote columns, precinct-header
style, contest-header order, candidate-party position) and emits the long-format
spine. Skips the two fully-scanned files (handled later by the OCR pipeline).

It writes ONE combined CSV and prints a PER-FILE validation table: precincts found
and the within-contest checksum (vote-for-1 candidate totals must equal VOTES=).
That table is the accuracy proof - read it before trusting any file.

Does NOT touch the master workbook. Output path can be overridden with env BOONE_OUT.

Run:
    cd ~/Documents/"Boone County Data"
    source .venv/bin/activate
    python3 parse_all.py
"""

import csv, os, re, sys, glob
from collections import defaultdict
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    sys.exit("Missing dependency. Run:  pip install pdfplumber")

FOLDER = Path(__file__).resolve().parent
OUT    = Path(os.environ.get("BOONE_OUT", FOLDER / "results_long_all.csv"))

# fully scanned -> OCR pipeline, not here
SKIP = {"2008-general-precinct.pdf", "2022-primary-precinct.pdf",
        "2008-general-precinct-Center1.pdf"}

# ---- line patterns ---------------------------------------------------------
RE_PID    = re.compile(r"Precinct ID:\s*(\S+)")
RE_PNAME  = re.compile(r"Precinct Name:\s*(.+?)\s*(?:-\s*-|$)")   # stop at name or " - -"
RE_NNNAME = re.compile(r"^(\d{2,4})-(\S.*?)\s*$")           # "01-Center 1" or "001-CENTER 1"
RE_COLHDR = re.compile(r"([EMAWP])\s+([EMAWP])\s+([EMAWP])\s+TOTAL")  # search, restricted letters
RE_VFOR   = re.compile(r"VOTE FOR\s+(\d+)")
RE_VOTES  = re.compile(r"VOTES=\s*([\d,]+)\s*(.*?)\s*$")     # number + optional office
# 2020-primary extracts the whole contest header on ONE line:
#   "VOTE FOR 1 (R) President of the U.S. VOTES= 134"
RE_COMBO  = re.compile(r"VOTE FOR\s+(\d+)\s+(.+?)\s+VOTES=\s*([\d,]+)")
RE_CAND   = re.compile(r"^(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+([\d.]+)%\s+(.+?)\s*$")
RE_LEADP  = re.compile(r"^\(([A-Z]{1,4})\)\s+(.+?)\s*$")     # leading party
RE_TRAILP = re.compile(r"^(.+?)\s+\(([A-Z]{1,4})\)\s*$")     # trailing party

PARTY_NORM = {"REP": "R", "DEM": "D", "LIB": "L", "IND": "I"}

# lines that are page chrome / structure, never an office name
NOISE = re.compile(
    r"(Summary Report|Election Date|EMS|Boone County|PUBLIC COUNT|VOTER TURNOUT|"
    r"REGISTERED VOTERS|PRECINCT STATUS|NUMBER OF PRECINCTS|PRECINCTS (REPORTED|NOT|"
    r"INCOMPLETE)|EQUIPMENT|# Of|# OF|Straight Party|Page \d|INBOO|GELEC|All Precincts|"
    r"TOTAL %|- - -|VOTES|VOTE FOR|Precinct (ID|Name)|^\d{1,2}/\d{1,2}/\d)")


def split_party(field, inherit):
    """Resolve a candidate's party from the name field; fall back to the contest party."""
    m = RE_LEADP.match(field)
    if m:
        raw = m.group(1); return PARTY_NORM.get(raw, raw), raw, m.group(2)
    m = RE_TRAILP.match(field)
    if m:
        raw = m.group(2); return PARTY_NORM.get(raw, raw), raw, m.group(1)
    # no tag on the row -> inherit the contest's party (primary), else None (referenda/write-in)
    return inherit, None, field


def era_for(year):
    y = int(year)
    if y <= 2010: return "2001-2010 map"
    if y <= 2020: return "2011-2020 map"
    return "2021-present map"


def parse_file(path, normalize=None):
    name = path.name
    stem = name[:-4]
    year = stem[:4]
    source_id = stem.upper()
    era = era_for(year)

    lines = []
    with pdfplumber.open(path) as doc:
        for pg in doc.pages:
            lines.extend((pg.extract_text() or "").split("\n"))
    if normalize:                          # optional OCR cleanup hook
        lines = [normalize(l) for l in lines]

    rows = []
    pid = pname = None
    office = office_party = None
    vote_for = contest_votes = None
    scheme = None
    for _l in lines:                     # column scheme is constant per file; find it once
        _m = RE_COLHDR.search(_l)
        if _m:
            scheme = ",".join(_m.groups()); break
    in_cumulative = False        # True inside an "Election Summary Report" (countywide) section

    def reset_contest():
        nonlocal office, office_party, vote_for, contest_votes
        office = office_party = None
        vote_for = contest_votes = None

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        # --- section banner: cumulative countywide vs per-precinct ---
        if "Election Summary Report" in line:
            in_cumulative = True
        elif "Precinct Summary Report" in line:
            in_cumulative = False

        # --- precinct boundary (reset contest only when the id actually changes) ---
        m = RE_PID.search(line)
        if m:
            if m.group(1) != pid:
                pid = m.group(1); pname = None; reset_contest()
            pm = RE_PNAME.search(line)          # run-together lines carry the name here too
            if pm: pname = pm.group(1)
            continue
        m = RE_NNNAME.match(line)
        if m and not RE_CAND.match(line):
            if m.group(1) != pid:
                pid = m.group(1); pname = m.group(2); reset_contest()
            continue
        m = RE_PNAME.search(line)
        if m:
            pname = m.group(1); continue

        # combined one-line contest header (2020-primary run-together extraction)
        m = RE_COMBO.search(line)
        if m:
            vote_for = int(m.group(1))
            office_party, _, office = split_party(m.group(2).strip(), None)
            contest_votes = int(m.group(3).replace(",", ""))
            continue

        m = RE_VFOR.match(line)
        if m:
            vote_for = int(m.group(1)); continue

        m = RE_VOTES.match(line)
        if m:
            contest_votes = int(m.group(1).replace(",", ""))
            rem = m.group(2).strip()
            if rem:                                   # legacy: office on the VOTES line
                office_party, _, office = split_party(rem, None)
            continue

        # candidate row
        m = RE_CAND.match(line)
        if m:
            if pid and office is not None and not in_cumulative:
                s1, s2, s3, total = (int(m.group(i)) for i in (1, 2, 3, 4))
                party, party_raw, cand = split_party(m.group(6), office_party)
                rows.append({
                    "source_file_id": source_id, "precinct_id": pid, "precinct_name": pname,
                    "office": office, "contest_party": office_party,
                    "party": party, "party_raw": party_raw,
                    "vote_for": vote_for, "contest_votes": contest_votes,
                    "candidate": cand, "column_scheme": scheme,
                    "split1": s1, "split2": s2, "split3": s3, "total": total,
                    "pct": float(m.group(5)), "granularity": "precinct",
                    "redistricting_era": era,
                })
            continue

        # otherwise: a free-text line. In modern files this is the office (party may lead).
        if pid and not RE_CAND.match(line) and not line[0].isdigit() and not NOISE.search(line):
            office_party, _, office = split_party(line, None)
            contest_votes = None

    return rows, scheme


def checksum(rows):
    """Count vote-for-1 contests whose candidate totals != VOTES=."""
    agg = defaultdict(lambda: [0, None, None])
    for r in rows:
        k = (r["precinct_id"], r["office"], r["contest_party"])   # party splits primary R vs D
        agg[k][0] += r["total"]; agg[k][1] = r["contest_votes"]; agg[k][2] = r["vote_for"]
    bad = sum(1 for s, v, vf in agg.values() if vf == 1 and v is not None and s != v)
    return len(agg), bad


def main():
    files = [Path(f) for f in sorted(glob.glob(str(FOLDER / "*-precinct.pdf")))
             if Path(f).name not in SKIP]
    all_rows = []
    print(f"{'file':30}{'rows':>7}{'prec':>6}{'contests':>9}{'vf1-bad':>8}  scheme")
    print("-" * 78)
    for path in files:
        rows, scheme = parse_file(path)
        ncontests, bad = checksum(rows)
        precs = len({r['precinct_id'] for r in rows})
        flag = "" if bad == 0 else "  <-- CHECK"
        print(f"{path.name:30}{len(rows):>7}{precs:>6}{ncontests:>9}{bad:>8}  {scheme}{flag}")
        all_rows.extend(rows)

    if all_rows:
        with open(OUT, "w", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
            wr.writeheader(); wr.writerows(all_rows)
    print("-" * 78)
    print(f"TOTAL rows: {len(all_rows)}   ->  {OUT}")
    print("Accuracy = every 'vf1-bad' is 0. Any nonzero: stop and inspect that file.")


if __name__ == "__main__":
    main()
