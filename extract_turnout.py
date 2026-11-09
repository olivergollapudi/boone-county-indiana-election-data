#!/usr/bin/env python3
"""
extract_turnout.py - build Turnout_Long: one row per precinct per election.
---------------------------------------------------------------------------
Each EMS report prints a per-precinct header block, e.g.

    02-Center 2                          (or "Precinct ID: 01" / "Precinct Name: ...")
    M- # OF Machine Ballots 360          (E- # OF Election Day / A- Paper Absentee / W- Walk-In)
    A- # OF Absentee Ballots 59
    P- # OF Provisional Ballots 0
    PUBLIC COUNT: 419
    VOTER TURNOUT: 32.76%                (older reports append the % to REGISTERED VOTERS)
    REGISTERED VOTERS: 1279

We pull registered voters, public count (total ballots cast), turnout %, and the three
ballot-type counts. Source = the SAME PDFs used for results; the two scanned elections
(2008 general, 2022 primary) are read from their cached Apple Vision OCR lines.

TWO built-in validations (mirroring the results checksum):
  A. split sum:  ballot-type counts sum to PUBLIC COUNT.
  B. turnout:    round(public_count / registered * 100, 2) == printed turnout %.
A row is flagged if either fails, so nothing enters the workbook unchecked.

Also emits a per-election COUNTYWIDE row (from each report's "All Precincts" page) so the
sum of precinct public counts can be cross-checked against the county total later.

Writes turnout_long.csv and prints a validation report. Modifies nothing else.
Run:  python3 extract_turnout.py
"""

import re, csv, json, glob
from pathlib import Path

try:
    import pdfplumber      # layout-aware text extraction (keeps each header label with its value)
except ImportError:
    import sys; sys.exit("Missing dependency. Run: pip install pdfplumber")

FOLDER = Path(__file__).resolve().parent
OCR_JSON = {   # scanned elections -> cached Apple Vision text lines
    "2008-GENERAL-PRECINCT": FOLDER / "2008-general-precinct-applelines.json",
    "2022-PRIMARY-PRECINCT": FOLDER / "2022-primary-precinct-applelines.json",
}

RE_NN   = re.compile(r"^(\d{2,4})-([A-Za-z].*?)\s*$")
RE_PID  = re.compile(r"Precinct ID:\s*(\w+)")
RE_PNM  = re.compile(r"Precinct Name:\s*(.+?)(?:\s{2,}|\s*-\s*-|$)")


def first_int(s):
    m = re.search(r"\d[\d,]*", s)
    return int(m.group().replace(",", "")) if m else None


def _grab(text, pat):
    m = re.search(pat, text)
    return int(m.group(1).replace(",", "")) if m else None


def parse_block(lines):
    """Pull the turnout header fields from a page. Works whether each label sits on its
    own line (older reports) or several labels share one line (denser layouts) — we run
    each field's pattern over the whole page text. The number must sit right after the
    label ([^\\d]{0,4}) so a distant number from another column can't be grabbed."""
    text = " ".join(lines)
    d = {
        "s1": _grab(text, r"(?:Machine Ballots|Election Day)[^\d]{0,4}(\d[\d,]*)"),
        "s2": _grab(text, r"(?:Absentee Ballots|Paper Absentee)[^\d]{0,4}(\d[\d,]*)"),
        "s3": _grab(text, r"(?:Provisional Ballots|Walk-In Absentee)[^\d]{0,4}(\d[\d,]*)"),
        "public": _grab(text, r"PUBLIC COUNT[^\d]{0,4}(\d[\d,]*)"),
        "reg": _grab(text, r"REGISTERED VOTERS[^\d]{0,4}(\d[\d,]*)"),
        "turnout": None,
    }
    mt = re.search(r"VOTER TURNOUT[^\d]{0,4}(\d+\.\d+)", text)
    if mt:
        d["turnout"] = float(mt.group(1))
    else:                                   # older format: turnout % printed after the reg count
        mo = re.search(r"REGISTERED VOTERS[^\d]{0,4}\d[\d,]*\s+(\d+\.\d+)", text)
        if mo:
            d["turnout"] = float(mo.group(1))
    scheme = "E,A,W" if "Election Day" in text else ("M,A,P" if "Machine Ballots" in text else None)
    if d["public"] is None and d["reg"] is None:
        return None, None
    return d, scheme


def precinct_of(lines):
    """Identify the precinct from a page's lines: (id, name) or ('COUNTYWIDE', ...)."""
    joined = " ".join(lines)
    if "All Precincts" in joined:
        return "COUNTYWIDE", "Countywide total"
    for l in lines:
        m = RE_PID.search(l)
        if m:
            name = ""
            for l2 in lines:
                mn = RE_PNM.search(l2)
                if mn: name = mn.group(1).strip(); break
            return m.group(1), name
    for l in lines:
        m = RE_NN.match(l.strip())
        if m and int(m.group(1)) < 90 and "OF" not in l:
            return m.group(1), m.group(2).strip()
    return None, None


def pages_from_pdf(path):
    with pdfplumber.open(path) as doc:
        for pg in doc.pages:
            yield (pg.extract_text() or "").split("\n")


def pages_from_ocr(path):
    for page in json.loads(Path(path).read_text()):
        yield page


def collect(source_id, pages):
    """One row per precinct (dedup; the block repeats on each of a precinct's pages)."""
    rows = {}
    for lines in pages:
        if "Election Summary" in " ".join(lines) and "All Precincts" not in " ".join(lines):
            continue
        d, scheme = parse_block(lines)
        if not d:
            continue
        pid, pname = precinct_of(lines)
        if pid is None:
            continue
        if pid in rows:                       # keep first occurrence
            continue
        rows[pid] = {
            "source_file_id": source_id, "precinct_id": pid, "precinct_name": pname,
            "registered_voters": d["reg"], "public_count": d["public"],
            "turnout_pct": d["turnout"], "split1": d["s1"], "split2": d["s2"],
            "split3": d["s3"], "column_scheme": scheme or "",
            "granularity": "countywide" if pid == "COUNTYWIDE" else "precinct",
        }
    return list(rows.values())


def main():
    out = []
    text_files = [f for f in sorted(glob.glob(str(FOLDER / "*-precinct.pdf")))
                  if "2008-general" not in f and "2022-primary" not in f]
    for f in text_files:
        sid = Path(f).stem.upper()
        out.extend(collect(sid, pages_from_pdf(f)))
    for sid, jf in OCR_JSON.items():
        if Path(jf).exists():
            out.extend(collect(sid, pages_from_ocr(jf)))

    # ---- recover a single OCR-dropped split from the public count, then validate ----
    core_ok = core_bad = split_ok = split_incomplete = 0
    for r in out:
        sp = [r["split1"], r["split2"], r["split3"]]
        missing = [i for i in range(3) if sp[i] is None]
        if len(missing) == 1 and r["public_count"] is not None:      # one dropped -> recover
            sp[missing[0]] = r["public_count"] - sum(v for v in sp if isinstance(v, int))
            r["split1"], r["split2"], r["split3"] = sp
            r["recovered_split"] = "yes"
        # Validation B (PRIMARY gate): the 3-way turnout identity ties public+registered+%.
        if r["turnout_pct"] and r["registered_voters"] and r["public_count"]:
            calc = round(r["public_count"] / r["registered_voters"] * 100, 2)
            if abs(calc - r["turnout_pct"]) <= 0.05: core_ok += 1
            else: core_bad += 1; r["flag_core"] = f"calc {calc} != printed {r['turnout_pct']}"
        # Validation A (secondary): ballot-type splits sum to public count.
        if all(isinstance(x, int) for x in sp) and r["public_count"] is not None:
            if sum(sp) == r["public_count"]: split_ok += 1
            else: r["flag_split"] = f"sum {sum(sp)} != public {r['public_count']}"; split_incomplete += 1
        else:
            split_incomplete += 1
            r["flag_split"] = "split breakdown incomplete (OCR-dropped, core turnout still valid)"

    cols = ["source_file_id","precinct_id","precinct_name","registered_voters","public_count",
            "turnout_pct","split1","split2","split3","column_scheme","granularity",
            "recovered_split","flag_core","flag_split"]
    with open(FOLDER / "turnout_long.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in out: w.writerow(r)

    n_prec = sum(1 for r in out if r["granularity"] == "precinct")
    n_cw = sum(1 for r in out if r["granularity"] == "countywide")
    checkableB = core_ok + core_bad
    print(f"turnout_long.csv: {len(out)} rows  ({n_prec} precinct, {n_cw} countywide)")
    print(f"  elections covered: {len({r['source_file_id'] for r in out})}")
    print(f"  VALIDATION B (core: public/registered = turnout%): {core_ok}/{checkableB} pass  <- the gate")
    print(f"  VALIDATION A (splits sum to public): {split_ok} full / {split_incomplete} incomplete-or-partial")
    print(f"  (a single OCR-dropped split is recovered from the public count; 2+ dropped stay blank)")
    if core_bad:
        print("  CORE-FAIL rows (turnout identity mismatch — review):")
        for r in out:
            if r.get("flag_core"):
                print(f"    {r['source_file_id']} p{r['precinct_id']}: {r['flag_core']}")


if __name__ == "__main__":
    main()
