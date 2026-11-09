#!/usr/bin/env python3
"""
geometry_parse.py - rebuild the EMS precinct table from Apple Vision TOKEN BOXES
--------------------------------------------------------------------------------
Format-aware geometry reconstruction. Instead of trusting OCR reading order, we use
each token's (x, y) to rebuild the table grid, auto-detecting the layout so the SAME
code handles both report styles seen in this project:

  * 2008 general : precinct banner "NN-Name", vote columns M A P (machine/absentee/
    provisional), general-election offices (no ballot party).
  * 2022 primary : "Precinct ID: NN" / "Precinct Name: ...", vote columns E A W
    (election-day/absentee/walk-in), offices prefixed with the ballot party "(R)"/"(D)".

Steps per page:
  1. estimate page SKEW from the header row (TOTAL + the split-column letters) and
     straighten every token's y.
  2. auto-detect COLUMN centers by clustering the numeric tokens (rightmost cluster
     below the % column = TOTAL; the rest are the vote splits, left to right).
  3. cluster tokens into ROWS by corrected y; split a row if it holds two candidates.
  4. walk rows holding contest context (VOTES=<n> <office>, VOTE FOR n) and emit one
     long-format record per candidate row.

Recovery (defensible, report-sourced): omitted zero cells = 0; one missing split with
total present = total - others; total missing = sum of splits; UNOPPOSED lone
candidate at ~100% = the contest VOTES= (recovers an OCR-dropped column); binary
YES/NO where one side lacks a TOTAL token = VOTES= - the trustworthy side.

Writes results_long_<stem>-geom.csv and prints the within-contest checksum.
Run:  python3 geometry_parse.py 2008-general-precinct
      python3 geometry_parse.py 2022-primary-precinct
"""

import sys, csv, json, re
from pathlib import Path
from collections import defaultdict
import parse_all as P

XREF = 0.47                 # reference x for skew straightening (near the % column)
ROW_GAP = 0.006             # corrected-y gap that starts a new row
NAME_X = 0.52               # tokens right of this are office/candidate text
PCT_LO = 0.44               # % column lives at/after this x
SPLIT_LETTERS = ("E", "M", "A", "W", "P")   # possible vote-split column headers

RE_NN     = re.compile(r"^(\d{2,4})-(\S.*)$")            # "49-Worth"
RE_PID    = re.compile(r"Precinct ID:\s*(\w+)")          # "Precinct ID: 01"
RE_PNAME  = re.compile(r"Precinct Name:\s*(.+?)\s*$")    # "Precinct Name: Center 01"
RE_VOTESN = re.compile(r"VOTES\s*[=:.\-]?\s*([\d,]+)")
RE_VFOR   = re.compile(r"VOTE FOR\s+(\d+)")


def tok_cx(t): return t[1] + t[3] / 2.0
def tok_cy(t): return t[2] + t[4] / 2.0


def estimate_skew(tokens):
    """Fit the slope of the header row (TOTAL + split-letter cells)."""
    totals = [t for t in tokens if t[0].strip() == "TOTAL"]
    if not totals:
        return 0.0
    y0 = tok_cy(totals[0])
    band = [t for t in tokens if abs(tok_cy(t) - y0) < 0.012
            and (t[0].strip() == "TOTAL" or t[0].strip() in SPLIT_LETTERS)]
    if len(band) < 2:
        return 0.0
    xs = [tok_cx(t) for t in band]; ys = [tok_cy(t) for t in band]
    mx = sum(xs) / len(xs); my = sum(ys) / len(ys)
    den = sum((x - mx) ** 2 for x in xs) or 1e-9
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den


def detect_columns(tokens):
    """Cluster numeric-token x's into column centers. Return (split_xs, total_x)."""
    xs = sorted(tok_cx(t) for t in tokens
                if re.fullmatch(r"[\d,]+", t[0].strip()) and tok_cx(t) < PCT_LO + 0.02)
    if not xs:
        return [], None
    clusters, cur = [], [xs[0]]
    for x in xs[1:]:
        if x - cur[-1] > 0.035:
            clusters.append(cur); cur = []
        cur.append(x)
    clusters.append(cur)
    centers = [sum(c) / len(c) for c in clusters if len(c) >= 2] or [sum(c) / len(c) for c in clusters]
    if len(centers) >= 2:
        return centers[:-1], centers[-1]        # rightmost = TOTAL
    return [], (centers[0] if centers else None)


def build_rows(tokens):
    slope = estimate_skew(tokens)
    for t in tokens:
        t.append(tok_cy(t) - slope * (tok_cx(t) - XREF))     # t[5] = corrected y
    tokens.sort(key=lambda t: (-t[5], t[1]))
    rows, cur, anchor = [], [], None
    for t in tokens:
        if cur and (anchor - t[5]) > ROW_GAP:
            rows.append(cur); cur = []; anchor = None
        cur.append(t)
        anchor = t[5] if anchor is None else max(anchor, t[5])
    if cur:
        rows.append(cur)
    fixed = []                                   # split a row that holds two candidates
    for r in rows:
        if sum(1 for t in r if "%" in t[0]) >= 2:
            ys = sorted({round(t[5], 4) for t in r}, reverse=True)
            gaps = [(ys[i] - ys[i + 1], ys[i + 1]) for i in range(len(ys) - 1)]
            _, cut = max(gaps)
            fixed.append([t for t in r if t[5] > cut])
            fixed.append([t for t in r if t[5] <= cut])
        else:
            fixed.append(r)
    return fixed


def parse_candidate(row, split_xs, total_x):
    """('CAND', dict) | ('FRAG', name) | None."""
    pct = None; name_parts = []; splits = {}; total = None
    for t in row:
        s = t[0].strip(); cx = tok_cx(t)
        if "%" in s and pct is None:
            m = re.search(r"\d+\.\d+|\d+", s.replace(" ", ""))
            pct = float(m.group()) if m else 0.0
        elif cx > NAME_X and re.search(r"[A-Za-z]", s):
            name_parts.append((cx, s))
        elif re.fullmatch(r"[\d,]+", s):
            v = int(s.replace(",", ""))
            if total_x is not None and abs(cx - total_x) < 0.03:
                total = v
            else:
                idx = min(range(len(split_xs)), key=lambda i: abs(cx - split_xs[i])) if split_xs else None
                if idx is not None and abs(cx - split_xs[idx]) < 0.04:
                    splits[idx] = v
    name = " ".join(s for _, s in sorted(name_parts))
    if pct is None:
        return ("FRAG", name) if name_parts else None
    n = max(3, len(split_xs))
    sp = [splits.get(i, 0) for i in range(len(split_xs))] + [0] * (n - len(split_xs))
    had_total = total is not None
    known = [splits[i] for i in splits]
    if not had_total:
        total = sum(known) if known else None
    else:
        missing = [i for i in range(len(split_xs)) if i not in splits]
        if len(missing) == 1:                    # recover the one dropped split
            rec = total - sum(splits.values())
            if rec >= 0:
                sp[missing[0]] = rec
    return ("CAND", {"splits": sp[:3], "total": total, "pct": pct,
                     "name": name, "had_total": had_total, "recovered": ""})


def parse_file(stem):
    boxes = json.loads(Path(f"{stem}-appleboxes.json").read_text())
    source_id = stem.upper()
    era = P.era_for(stem[:4])
    # scheme label from the ballot legend (provenance only)
    alltext = " ".join(t[0] for pg in boxes.values() for t in pg)
    scheme = "E,A,W" if "Election Day" in alltext else "M,A,P"
    out = []
    pid = pname = None
    for pno in sorted(boxes, key=lambda k: int(k)):
        toks = [list(t) for t in boxes[pno]]
        if "Election Summary" in " ".join(t[0] for t in toks):
            continue                              # skip countywide cumulative section
        split_xs, total_x = detect_columns(toks)
        rows = build_rows(toks)
        office = office_party = None; contest_votes = vote_for = None
        pending = []; last_frag = None; pending_vf = None
        seen = {}                                 # (office,party)->count within precinct, for duplicates

        def flush():
            cur_o, cur_p, cur_v, cur_vf = office, office_party, contest_votes, vote_for
            reals = [c for c in pending if "NO CANDIDATE FILED" not in (c["name"] or "").upper()]
            names = {(c["name"] or "").strip().upper() for c in pending}
            if (cur_v and names <= {"YES", "NO"} and len(pending) == 2
                    and sum(c["total"] or 0 for c in pending) != cur_v):
                strong = [c for c in pending if c["had_total"]]
                weak = [c for c in pending if not c["had_total"]]
                if len(strong) == 1 and len(weak) == 1 and strong[0]["total"] is not None:
                    w = weak[0]; w["total"] = cur_v - strong[0]["total"]
                    w["splits"] = [w["total"], 0, 0]; w["recovered"] = "binary"
            for c in pending:
                name, total, pct = c["name"], c["total"], c["pct"]
                splits = list(c["splits"]); recovered = c["recovered"]
                is_real = "NO CANDIDATE FILED" not in (name or "").upper()
                if (is_real and pct and pct >= 99.9 and len(reals) == 1
                        and cur_v and total != cur_v):
                    total = cur_v; resid = total - sum(splits)
                    if resid > 0:
                        for i in range(3):
                            if splits[i] == 0:
                                splits[i] = resid; break
                        else:
                            splits[0] += resid
                    recovered = "unopposed"
                if total is None:
                    total = sum(splits)
                party, praw, cand = P.split_party(name, cur_p)
                out.append({
                    "source_file_id": source_id, "precinct_id": pid, "precinct_name": pname,
                    "office": cur_o, "contest_party": cur_p, "party": party, "party_raw": praw,
                    "vote_for": cur_vf, "contest_votes": cur_v, "candidate": cand,
                    "column_scheme": scheme, "split1": splits[0], "split2": splits[1],
                    "split3": splits[2], "total": total, "pct": pct, "granularity": "precinct",
                    "redistricting_era": era, "page": int(pno), "recovered": recovered})
            pending.clear()

        for row in rows:
            text = " ".join(t[0].strip() for t in sorted(row, key=lambda z: z[1]))
            mnn = RE_NN.match(text.strip())
            mpid = RE_PID.search(text)
            if mpid or (mnn and int(mnn.group(1)) < 90 and "OF" not in text):
                flush()
                pid = mpid.group(1) if mpid else mnn.group(1)
                if mnn and not mpid:
                    pname = mnn.group(2).strip()
                office = office_party = None; contest_votes = vote_for = None
                seen = {}; last_frag = None
                continue
            mpn = RE_PNAME.search(text)
            if mpn:
                pname = mpn.group(1).strip(); continue
            mv = RE_VOTESN.search(text)
            if mv and "VOTES" in text:
                flush()
                contest_votes = int(mv.group(1).replace(",", ""))
                rem = (text[:mv.start()] + " " + text[mv.end():]).strip(" .-|")
                src = rem if rem else (last_frag or "")
                src = src.replace("{", "(").replace("}", ")").replace("[", "(").replace("]", ")")
                if src:
                    office_party, _, office = P.split_party(src, None)
                if office is not None:               # disambiguate repeated offices (e.g. Public Question)
                    key = (office, office_party)
                    seen[key] = seen.get(key, 0) + 1
                    if seen[key] > 1:
                        office = f"{office} ({seen[key]})"
                # vote_for timing: 2022 puts "VOTE FOR n" BEFORE this header (-> pending_vf);
                # 2008 puts it AFTER (caught below while vote_for is still None).
                vote_for = pending_vf; pending_vf = None
                last_frag = None
                continue
            mf = RE_VFOR.search(text)
            if mf:
                n = int(mf.group(1))
                if office is not None and vote_for is None:
                    vote_for = n                     # 2008: VOTE FOR follows the header
                else:
                    pending_vf = n                   # 2022: VOTE FOR precedes the next header
                continue
            parsed = parse_candidate(row, split_xs, total_x)
            if not parsed:
                continue
            if parsed[0] == "FRAG":
                last_frag = parsed[1]; continue
            rec = parsed[1]
            if not rec["name"] and last_frag:
                rec["name"] = last_frag; last_frag = None
            if office and pid:
                pending.append(rec)
        flush()
    return out


def checksum(rows):
    agg = defaultdict(lambda: [0, None, None])
    for r in rows:
        k = (str(r["precinct_id"]), str(r["office"]), str(r["contest_party"] or ""))
        agg[k][0] += int(r["total"] or 0); agg[k][1] = r["contest_votes"]; agg[k][2] = r["vote_for"]
    checkable = {k: v for k, v in agg.items() if str(v[2]) in ("1", "1.0") and v[1] is not None}
    fails = {k: v for k, v in checkable.items() if v[0] != v[1]}
    return len(checkable), len(checkable) - len(fails), fails


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    stem = args[0] if args else "2008-general-precinct"
    rows = parse_file(stem)
    ncheck, npass, fails = checksum(rows)
    print(f"stem={stem}  rows={len(rows)}  precincts={len({r['precinct_id'] for r in rows})}")
    print(f"CONTEST checksum: {npass}/{ncheck} pass ({100*npass/max(ncheck,1):.1f}%)  FAIL={len(fails)}")
    for (pid, off, cp), (s, cv, vf) in sorted(fails.items(), key=lambda kv: -abs(kv[1][1]-kv[1][0]))[:25]:
        print(f"   p{pid:>3} {cp:>2} sum={s:>5} VOTES={cv:>5} d={cv-s:>5}  {off[:42]}")
    out = Path(f"results_long_{stem}-geom.csv")
    cols = ["source_file_id","precinct_id","precinct_name","office","contest_party","party",
            "party_raw","vote_for","contest_votes","candidate","column_scheme","split1",
            "split2","split3","total","pct","granularity","redistricting_era","recovered"]
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)
    print(f"wrote {out.name}")


if __name__ == "__main__":
    main()
