# Boone County, Indiana — Precinct-Level Election Results, 2008–2026

Precinct-level election results for **Boone County, Indiana**, parsed from the Boone County
Clerk's official result reports. Covers every election the Clerk publishes from 2008
onward: primaries, generals, odd-year municipal elections, and specials, at every level
the Clerk reports (federal, state, county, municipal, township, school board, judicial
retention, and public questions).

Every number comes from a Clerk PDF in this repository and was extracted by a script in
this repository. Nothing was typed by hand, estimated, or taken from another source.

## At a glance

| | |
|---|---|
| Source | Boone County Clerk, "Election Results History" (`boonecounty.in.gov/offices/clerk/election-results-history/`) |
| Elections | 28 (2008 primary through 2026 primary) |
| Result rows | 51,879 (one row per election × contest × precinct × candidate) |
| Turnout rows | 1,245 (one row per election × precinct) |
| Validation | 20,670 single-winner contests checked; 0 failures |

## Files

| File | What it is |
|---|---|
| `boone_county_election_results.xlsx` | The assembled database: README, Results_Long, Turnout_Long, Precincts, Source_Provenance, Validation, Coverage_Inventory |
| `results_long_all.csv` | Results for the 25 text-based (embedded) elections |
| `results_long_2008-general-precinct-geom-clean.csv`, `results_long_2022-primary-precinct-geom-clean.csv` | Results for the two scanned elections. Only contests that reconcile exactly are included |
| `omitted_*.csv` | Contests from the scanned elections that could not be reconstructed exactly, so they were left out. Each one is listed with its reported total |
| `turnout_long.csv` | Per-precinct registered voters, ballots cast, turnout %, and ballot-type counts |
| `precinct_crosswalk.csv` | Current precincts with their town and county council district |
| `*.pdf` | The Clerk's source reports (`*-precinct.pdf` = precinct breakdown, `*-summary.pdf` = countywide summary) |
| `*-appleboxes.json`, `*-applelines.json` | Cached OCR output for the scanned reports, so the pipeline can be rerun without macOS |
| `*.py` | The pipeline (see below) |
| `METHODOLOGY.md` | How the data was built and validated, in plain English |
| `PARSING_STRATEGY.md` | Technical spec of the report formats and how the parser handles each one |

The column definitions are in the workbook's README tab and in `METHODOLOGY.md` §2.

## How it was validated

Each Clerk report prints a total for every contest (`VOTES=`). A contest is included only
if its candidate totals add up exactly to that printed total. For the six elections where
the Clerk also publishes a separate countywide summary, the precinct rows were also summed
and checked against that summary, candidate by candidate, with zero mismatches.
Multi-seat contests can't use the single-winner check. See `METHODOLOGY.md` for how they
were handled.

## Known gaps

- **2008 primary:** the Clerk published only a countywide summary, so this election is
  countywide only.
- **2008 general and 2022 primary:** the source reports are scans. Contests that could
  not be reconstructed exactly are excluded and listed in `omitted_*.csv`.
- **2020:** the Clerk's reports print registered voters and turnout % as zero. Ballots
  cast are still recorded.
- **2026 general:** not yet included. It will be added after the county certifies results.

## Rebuild from source

Requires Python 3.11+.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 parse_all.py         # parse the 25 text-based elections -> results_long_all.csv
python3 reconcile_all.py     # cross-check against countywide summaries (expect 0 mismatches)
python3 geometry_parse.py 2008-general-precinct   # rebuild scanned tables from cached OCR boxes
python3 geometry_parse.py 2022-primary-precinct
python3 finalize_ocr.py 2008-general-precinct     # keep only reconciling contests
python3 finalize_ocr.py 2022-primary-precinct
python3 add_center1.py       # add 2008 precinct Center 1, which the Clerk published separately
python3 extract_turnout.py   # -> turnout_long.csv
python3 build_workbook.py    # -> boone_county_election_results.xlsx
```

Rerunning OCR from the PDFs (`dump_boxes.py`) requires macOS because it uses Apple
Vision. Every other step runs on any platform from the cached JSON files.

## License and citation

A license has not been chosen yet. Until one is added, please contact the maintainer
before reusing the data.
