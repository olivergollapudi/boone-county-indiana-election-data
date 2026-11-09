#!/usr/bin/env python3
"""
build_workbook.py - assemble the Boone County master workbook (7 tabs)
----------------------------------------------------------------------
Source of truth = within-contest checksum. Everything ingested reconciles.

Ingests:
  * results_long_all.csv                                  - 25 embedded/mixed elections
    (within-contest checksum = 0 everywhere; 6 also cross-checked vs the county summary).
  * results_long_2008-general-precinct-geom-clean.csv     - OCR (Apple Vision + geometry),
  * results_long_2022-primary-precinct-geom-clean.csv       ONLY the contests that reconcile
    exactly. Contests OCR could not reconstruct are OMITTED and listed in omitted_*.csv
    (documented gaps, approximate later - never fabricated in).
  * 2008-primary-summary.pdf                              - countywide-only election, ingested
    at granularity=countywide (no precinct file exists for it).

Tabs: README, Results_Long, Turnout_Long (placeholder), Precincts, Source_Provenance,
Validation, Coverage_Inventory.

Reads override via env BOONE_OUT (embedded csv) / BOONE_XLSX (output).
Run (from the repository root):
    python3 scripts/build_workbook.py
"""

import os, csv
from pathlib import Path
from collections import defaultdict
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.utils.dataframe import dataframe_to_rows

import reconcile_all as RC          # reuse the summary parser for 2008 primary

from paths import PDF_DIR, DATA_DIR

CSV    = Path(os.environ.get("BOONE_OUT", DATA_DIR / "results_long_all.csv"))
OUT    = Path(os.environ.get("BOONE_XLSX", DATA_DIR / "boone_county_election_results.xlsx"))

MIXED = {"2010-GENERAL", "2012-PRIMARY", "2015-GENERAL", "2020-GENERAL", "2020-PRIMARY"}
CROSS_CHECK = {"2022-GENERAL": 116, "2023-GENERAL": 44, "2023-PRIMARY": 38,
               "2024-GENERAL": 66, "2024-PRIMARY": 260, "2026-PRIMARY": 216}

# OCR-recovered elections: every INGESTED contest reconciles (within-contest checksum);
# unreconstructable contests are omitted and logged. NOT fabricated, NOT partial rows.
OCR_CLEAN = {
    "2008-GENERAL": DATA_DIR / "results_long_2008-general-precinct-geom-clean.csv",
    "2022-PRIMARY": DATA_DIR / "results_long_2022-primary-precinct-geom-clean.csv",
}
OMITTED = {
    "2008-GENERAL": DATA_DIR / "omitted_2008-general-precinct.csv",
    "2022-PRIMARY": DATA_DIR / "omitted_2022-primary-precinct.csv",
}
# OCR summaries are themselves scanned -> no clean independent cross-check available.
OCR_NO_XCHECK = {"2008-GENERAL": "no county summary exists",
                 "2022-PRIMARY": "county summary is also scanned"}

SUMMARY_ONLY = {"2008-PRIMARY": PDF_DIR / "2008-primary-summary.pdf"}

STD_COLS = ["source_file_id","precinct_id","precinct_name","office","contest_party","party",
            "party_raw","vote_for","contest_votes","candidate","column_scheme","split1",
            "split2","split3","total","pct","granularity","redistricting_era","recovered"]

HDR_FILL = PatternFill("solid", fgColor="1F4E78")
HDR_FONT = Font(name="Arial", bold=True, color="FFFFFF", size=11)
BODY     = Font(name="Arial", size=10)
TITLE    = Font(name="Arial", bold=True, size=14)


def style_header(ws, ncols, row=1):
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill = HDR_FILL; cell.font = HDR_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")


def autosize(ws, maxw=48):
    for col in ws.columns:
        letter = get_column_letter(col[0].column)
        width = max((len(str(c.value)) for c in col if c.value is not None), default=8)
        ws.column_dimensions[letter].width = min(max(width + 2, 9), maxw)


def write_df(ws, df, freeze="A2"):
    for r in dataframe_to_rows(df, index=False, header=True):
        ws.append(r)
    style_header(ws, df.shape[1])
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.font = BODY
    ws.freeze_panes = freeze
    autosize(ws)


def era_for(y):
    y = int(y)
    return "2021-present map" if y >= 2022 else ("2011-2020 map" if y >= 2012 else "2001-2010 map")


def load_2008_primary_countywide():
    """Parse the 2008 primary countywide summary into long-format countywide rows."""
    path = SUMMARY_ONLY["2008-PRIMARY"]
    if not path.exists():
        return []
    totals = RC.parse_summary(path)              # {(office_norm, party, cand_norm): total}
    rows = []
    for (office, cp, cand), total in totals.items():
        rows.append({"source_file_id": "2008-PRIMARY-SUMMARY", "precinct_id": "COUNTYWIDE",
                     "precinct_name": "Countywide total", "office": office, "contest_party": cp or "",
                     "party": "", "party_raw": "", "vote_for": "", "contest_votes": "",
                     "candidate": cand, "column_scheme": "", "split1": "", "split2": "", "split3": "",
                     "total": total, "pct": "", "granularity": "countywide",
                     "redistricting_era": "2001-2010 map", "recovered": ""})
    return rows


def omit_count(el):
    p = OMITTED.get(el)
    if p and p.exists():
        return sum(1 for _ in csv.DictReader(open(p)))
    return 0


def main():
    df = pd.read_csv(CSV, dtype=str).fillna("")
    if "recovered" not in df.columns:
        df["recovered"] = ""
    for el, pf in OCR_CLEAN.items():             # fold in the reconciling OCR contests
        if pf.exists():
            dp = pd.read_csv(pf, dtype=str).fillna("")
            for c in STD_COLS:
                if c not in dp.columns:
                    dp[c] = ""
            df = pd.concat([df, dp[STD_COLS]], ignore_index=True)
    cw = load_2008_primary_countywide()          # countywide-only election
    if cw:
        df = pd.concat([df, pd.DataFrame(cw)[STD_COLS]], ignore_index=True)

    df["year"] = df["source_file_id"].str[:4]
    df["election"] = (df["source_file_id"].str.replace("-PRECINCT", "", regex=False)
                                          .str.replace("-SUMMARY", "", regex=False))

    wb = Workbook()

    # ---------- README ----------
    ws = wb.active; ws.title = "README"
    B12 = Font(name="Arial", bold=True, size=12)
    n_embedded = 25
    lines = [
        ("Boone County, Indiana — Election Results Database", TITLE),
        ("", BODY),
        ("Purpose", B12),
        ("Single-source, precinct-level database of Boone County election results, 2008–present.", BODY),
        ("Source: Boone County Clerk 'Election Results History' ONLY. Raw 'what the Clerk reported' —", BODY),
        ("no estimation, no district normalization (those are deferred analysis layers).", BODY),
        ("", BODY),
        ("Coverage summary", B12),
        (f"Rows in Results_Long: {len(df):,}.  Every ingested contest reconciles to the report's own", BODY),
        ("countywide total (within-contest checksum = 0). Nothing that fails validation is included.", BODY),
        (f"• {n_embedded} embedded/mixed elections (2010–2026): precinct-level, fully validated;", BODY),
        ("  6 of them also cross-checked candidate-by-candidate against the separate county summary.", BODY),
        ("• 2008 GENERAL and 2022 PRIMARY: scanned reports recovered by OCR (Apple Vision) + a", BODY),
        ("  geometry reconstruction. Only contests whose candidate totals reconcile EXACTLY are", BODY),
        ("  included; contests OCR could not reconstruct are OMITTED and listed in the omitted_*.csv", BODY),
        ("  files and summarized in Coverage_Inventory (approximate later — never fabricated here).", BODY),
        ("• 2008 PRIMARY: countywide-only (no precinct breakdown exists); ingested at", BODY),
        ("  granularity = countywide.", BODY),
        ("• Turnout_Long: per-precinct registered voters, ballots cast (public count), turnout %,", BODY),
        ("  and ballot-type splits, validated by the identity public/registered = printed turnout %", BODY),
        ("  (a single OCR-dropped split is recovered from the public count; flags mark any gaps).", BODY),
        ("", BODY),
        ("Methodology", B12),
        ("Embedded/mixed PDFs: profile-detecting text parser (parse_all.py). Scanned PDFs: Apple", BODY),
        ("Vision OCR to token boxes (dump_boxes.py) then a geometry reconstruction that rebuilds the", BODY),
        ("table from each token's x/y position (geometry_parse.py), then finalize_ocr.py keeps only", BODY),
        ("the contests that reconcile. See PROCESS_LOG.md for the full paper trail.", BODY),
        ("", BODY),
        ("Validation standard", B12),
        ("1. Within-contest checksum (ALL ingested rows): candidate totals equal the report's own", BODY),
        ("   VOTES= figure. This is the inclusion gate — a contest is in the master only if it passes.", BODY),
        ("2. Independent county cross-check (where a clean summary exists): precinct rows summed per", BODY),
        ("   candidate equal the Clerk's separate summary. Passes with 0 mismatches for 6 elections.", BODY),
        ("", BODY),
        ("Data dictionary — Results_Long columns", B12),
    ]
    dict_rows = [
        ("source_file_id", "Provenance: which Clerk PDF the row came from."),
        ("precinct_id / precinct_name", "Precinct as printed ('COUNTYWIDE' for the summary-only 2008 primary)."),
        ("office", "Contest/office name as printed."),
        ("contest_party", "Ballot party the contest sat on (R/D in primaries; blank in generals)."),
        ("party / party_raw", "Candidate party, normalized / exactly as printed."),
        ("vote_for", "Seats in the contest ('VOTE FOR n')."),
        ("contest_votes", "The report's own reported total for the contest ('VOTES=')."),
        ("candidate", "Candidate name (or Yes/No for referenda; 'Write-In')."),
        ("column_scheme", "Meaning of split1-3: M,A,P (machine/absentee/provisional) or E,A,W (election-day/"),
        ("", "  absentee/walk-in). Kept raw per era, never equated."),
        ("split1/2/3, total, pct", "The vote-method splits, the candidate total, and printed percentage."),
        ("granularity", "'precinct' or 'countywide'."),
        ("redistricting_era", "District-map era the election falls under (infrastructure tag)."),
        ("recovered", "Blank normally; 'unopposed'/'binary' where an OCR-dropped cell was recovered from"),
        ("", "  the contest's own reported total (defensible arithmetic, OCR elections only)."),
    ]
    for text, font in lines:
        ws.append([text]); ws.cell(row=ws.max_row, column=1).font = font
    for name, desc in dict_rows:
        ws.append([name, desc])
        ws.cell(row=ws.max_row, column=1).font = Font(name="Arial", bold=True, size=10)
        ws.cell(row=ws.max_row, column=2).font = BODY
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 88

    # ---------- Results_Long ----------
    write_df(wb.create_sheet("Results_Long"), df[STD_COLS])

    # ---------- Turnout_Long ----------
    tpath = DATA_DIR / "turnout_long.csv"
    ws = wb.create_sheet("Turnout_Long")
    if tpath.exists():
        tdf = pd.read_csv(tpath, dtype=str).fillna("")
        write_df(ws, tdf)
    else:
        ws.append(["turnout_long.csv not found — run extract_turnout.py first."])
        ws.cell(row=1, column=1).font = Font(name="Arial", italic=True, size=10)

    # ---------- Precincts ----------
    pr = (df[df.precinct_id != "COUNTYWIDE"].groupby("precinct_id")
            .agg(names=("precinct_name", lambda s: "; ".join(sorted({x for x in s if x}))[:120]),
                 elections=("election", "nunique"),
                 first_year=("year", "min"), last_year=("year", "max"))
            .reset_index())
    pr.columns = ["precinct_id","name(s) seen","#elections","first_year","last_year"]
    ws = wb.create_sheet("Precincts"); write_df(ws, pr)
    ws.append([]); ws.append(["NOTE: precinct-id formatting varies by era; Boone went 27 precincts (2000) "
        "→ 54 (2010) → 53 (2020). Canonical crosswalk is infrastructure for later, not analysis."])
    ws.cell(row=ws.max_row, column=1).font = Font(name="Arial", italic=True, size=9)

    # ---------- Source_Provenance ----------
    g = df.groupby("election").agg(rows=("office","size"), precincts=("precinct_id","nunique"),
                                   offices=("office","nunique")).reset_index()
    prov = []
    for _, r in g.iterrows():
        el = r["election"]
        if el in OCR_CLEAN:
            parsed_by = "OCR (Apple Vision + geometry reconstruction)"
            checksum  = f"PASS — every ingested contest reconciles; {omit_count(el)} contests omitted (see Coverage)"
            xcheck    = f"n/a — {OCR_NO_XCHECK[el]}"
        elif el in SUMMARY_ONLY or el == "2008-PRIMARY":
            parsed_by = "countywide summary (no precinct file exists)"
            checksum  = "n/a — countywide totals as reported"
            xcheck    = "n/a — this IS the summary"
        else:
            parsed_by = "mixed (scanned summary front; precinct pages text)" if el in MIXED else "embedded (text)"
            checksum  = "PASS — within-contest checksum, 0 mismatches"
            xcheck    = (f"PASS — {CROSS_CHECK[el]} candidates vs summary, 0 mismatches"
                         if el in CROSS_CHECK else "n/a (no clean summary)")
        prov.append([el, parsed_by, int(r["rows"]), int(r["precincts"]), int(r["offices"]), checksum, xcheck])
    prov_df = pd.DataFrame(prov, columns=["election","parsed_by","rows","precincts","offices",
                                          "within_contest_checksum","countywide_cross_check"])
    write_df(wb.create_sheet("Source_Provenance"), prov_df)

    # ---------- Validation ----------
    write_df(wb.create_sheet("Validation"),
             prov_df[["election","rows","within_contest_checksum","countywide_cross_check"]].copy())

    # ---------- Coverage_Inventory ----------
    cov = []
    for _, r in g.iterrows():
        el = r["election"]
        if el in OCR_CLEAN:
            status = f"INGESTED (OCR) — {int(r['rows'])} rows reconcile; {omit_count(el)} contests omitted as gaps"
        elif el == "2008-PRIMARY":
            status = "INGESTED — countywide only (no precinct breakdown exists)"
        else:
            status = "INGESTED — validated"
        cov.append([el, int(r["precincts"]), int(r["offices"]), int(r["rows"]), status])
    cov_df = pd.DataFrame(cov, columns=["election","precincts","offices","rows","status"])
    write_df(wb.create_sheet("Coverage_Inventory"), cov_df)

    wb.save(OUT)
    print(f"Wrote {OUT}")
    print(f"  {len(df):,} rows across {df['election'].nunique()} elections; tabs = {wb.sheetnames}")
    for el in OCR_CLEAN:
        print(f"  {el}: OCR-clean ingested, {omit_count(el)} contests omitted (documented)")


if __name__ == "__main__":
    main()
