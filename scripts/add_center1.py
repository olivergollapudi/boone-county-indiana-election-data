#!/usr/bin/env python3
"""
add_center1.py - fold the stray 2008 Center 1 precinct into the 2008 GENERAL election.
--------------------------------------------------------------------------------------
Center 1 (precinct 01) of the 2008 general is a separate scanned 3-page PDF, missing from
the main 2008 general file. This runs the SAME geometry pipeline + turnout extractor on
its OCR boxes, relabels the output as 2008-GENERAL-PRECINCT / precinct 01, keeps only the
contests that reconcile (same inclusion gate as everything else), and appends both the
results and the turnout row to the existing clean CSVs.

Idempotent: any existing 2008-GENERAL precinct-01 rows are removed first, so re-running
does not double-count.

ORDER MATTERS: run this AFTER finalize_ocr.py (which rewrites the 2008 clean CSV) and
AFTER extract_turnout.py (which rewrites turnout_long.csv); otherwise those scripts drop
the precinct-01 rows this one adds.

Prereq (OCR cache, already in ocr_cache/):
        python3 scripts/dump_boxes.py 2008-general-precinct-Center1.pdf 0 2
Run (from the repository root):
        python3 scripts/add_center1.py   ->  then python3 scripts/build_workbook.py
"""

import csv, json, re
from pathlib import Path
from collections import OrderedDict
import geometry_parse as G
from paths import OCR_DIR, DATA_DIR

STEM   = "2008-general-precinct-Center1"
SID    = "2008-GENERAL-PRECINCT"          # relabel so it joins the 2008 general election
PREC   = "01"
CLEAN  = DATA_DIR / "results_long_2008-general-precinct-geom-clean.csv"
TURN   = DATA_DIR / "turnout_long.csv"
BOXES  = OCR_DIR / f"{STEM}-appleboxes.json"


def num(v):
    try: return int(str(v).strip())
    except Exception: return None


def parse_turnout_from_boxes(path):
    """Read the precinct-01 turnout header GEOMETRICALLY from the OCR boxes: for each
    label, take the number sitting on the same row in the value column (x ~0.34-0.47).
    Robust to the label/value column order that flat-line reconstruction scrambles."""
    boxes = json.loads(Path(path).read_text())
    for pno in sorted(boxes, key=lambda k: int(k)):
        toks = boxes[pno]
        if "PUBLIC COUNT" not in " ".join(t[0] for t in toks):
            continue
        yc = lambda t: t[2] + t[4] / 2

        def val(label):
            lt = [t for t in toks if label in t[0]]
            if not lt:
                return None
            ly = yc(lt[0])
            cand = [(abs(yc(t) - ly), int(t[0].replace(",", ""))) for t in toks
                    if 0.34 < t[1] + t[3] / 2 < 0.47 and re.fullmatch(r"[\d,]+", t[0].strip())
                    and abs(yc(t) - ly) < 0.012]
            return min(cand)[1] if cand else None

        turnout = None
        rt = [t for t in toks if "REGISTERED VOTERS" in t[0]]
        if rt:
            ly = yc(rt[0])
            pcts = [t for t in toks if "%" in t[0] and abs(yc(t) - ly) < 0.012]
            if pcts:
                m = re.search(r"(\d+\.\d+)", pcts[0][0])
                turnout = float(m.group(1)) if m else None
        return {"source_file_id": SID, "precinct_id": PREC, "precinct_name": "Center 1",
                "registered_voters": val("REGISTERED VOTERS"), "public_count": val("PUBLIC COUNT"),
                "turnout_pct": turnout, "split1": val("Machine Ballots"),
                "split2": val("Absentee Ballots"), "split3": val("Provisional Ballots"),
                "column_scheme": "M,A,P", "granularity": "precinct"}
    return None


def main():
    if not BOXES.exists():
        raise SystemExit(f"Missing {BOXES.name} — run: python3 scripts/dump_boxes.py {STEM}.pdf 0 2")

    # ---------- RESULTS ----------
    rows = G.parse_file(STEM)
    for r in rows:
        r["source_file_id"] = SID
    contests = OrderedDict()
    for r in rows:
        contests.setdefault((r["precinct_id"], r["office"], r["contest_party"] or ""), []).append(r)
    clean, omitted = [], 0
    for rs in contests.values():
        vf = str(rs[-1]["vote_for"]); cv = num(rs[-1]["contest_votes"])
        s = sum(num(x["total"]) or 0 for x in rs)
        if vf in ("1", "1.0") and cv is not None and s == cv:
            clean.extend(rs)
        else:
            omitted += 1

    existing = list(csv.DictReader(open(CLEAN)))
    cols = list(existing[0].keys())
    kept = [e for e in existing if not (e["source_file_id"] == SID and e["precinct_id"] == PREC)]
    for r in clean:
        kept.append({c: r.get(c, "") for c in cols})
    with open(CLEAN, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(kept)
    added_prec = len({(r["office"], r["contest_party"]) for r in clean})
    print(f"RESULTS: added {len(clean)} rows / {added_prec} contests for precinct 01 "
          f"({omitted} contests omitted); {CLEAN.name} now {len(kept)} rows")

    # ---------- TURNOUT ----------
    row = parse_turnout_from_boxes(BOXES)
    tout = [row] if row else []
    for r in tout:                                   # recover one dropped split from public count
        sp = [r["split1"], r["split2"], r["split3"]]
        miss = [i for i in range(3) if sp[i] is None]
        if len(miss) == 1 and r["public_count"] is not None:
            sp[miss[0]] = r["public_count"] - sum(v for v in sp if isinstance(v, int))
            r["split1"], r["split2"], r["split3"] = sp

    texisting = list(csv.DictReader(open(TURN)))
    tcols = list(texisting[0].keys())
    tkept = [e for e in texisting if not (e["source_file_id"] == SID and e["precinct_id"] == PREC)]
    for r in tout:
        tkept.append({c: r.get(c, "") for c in tcols})
    with open(TURN, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=tcols); w.writeheader(); w.writerows(tkept)
    for r in tout:
        ok = (r["turnout_pct"] and r["registered_voters"] and r["public_count"] and
              abs(round(r["public_count"] / r["registered_voters"] * 100, 2) - r["turnout_pct"]) <= 0.05)
        print(f"TURNOUT: precinct 01 reg={r['registered_voters']} public={r['public_count']} "
              f"turnout={r['turnout_pct']}  core-valid={bool(ok)}")
    if not tout:
        print("TURNOUT: no precinct-01 turnout block found — check the OCR.")


if __name__ == "__main__":
    main()
