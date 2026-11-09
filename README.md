# Boone County, Indiana — Precinct-Level Election Results (2012–2024)

A clean, normalized dataset of precinct-level election returns for **Boone County, Indiana** (county seat: Lebanon;
not to be confused with Boone counties in other states), on a consistent **53-precinct** frame. Returns come from [OpenElections](https://github.com/openelections/openelections-data-in);
precinct names are matched to the state's [IndianaMap](https://indianamap.org) GIS naming. Presidential totals
and turnout were validated against the Boone County Clerk's figures and match exactly (see
[METHODOLOGY.md](METHODOLOGY.md)).

## Why this exists

Across years, the same precinct is spelled many ways (`Center 1`, `01-Center 01`, `CENTER 01`, `Center 01`),
which makes multi-year precinct analysis painful. This repo fixes that: every row uses one canonical
precinct name, so elections can be compared precinct by precinct.

## What's here

| File (in `data/`) | Contents |
|---|---|
| `boone_precinct_master_long.csv` | **Master file.** Tidy long format, one row per precinct × election × office × candidate (12,698 rows) |
| `boone_<office>_by_precinct.csv` | Wide pivots (precinct × candidate-year): President, Governor, U.S. Senate, U.S. House, State Senate, State House, Attorney General |
| `boone_turnout_over_time.csv` | Per-precinct turnout: 2012, 2014, 2016, 2018, 2020, 2024 |
| `boone_presidential_over_time.csv` | County presidential totals and D/R shares, 2012–2024 |
| `Boone_Precinct_Master.xlsx` | Everything above in one workbook, with a provenance sheet |

**Elections covered:** general elections 2012, 2014, 2016, 2018, 2020, 2024; primaries 2018 and 2020.

### Master file columns

`year, election_date, election_type, precinct, office, district, candidate, party, votes`

Non-candidate rows (e.g., `Registered Voters`, `Ballots Cast`) appear under `office`.

## Known gaps

Not available at precinct level from OpenElections, and deliberately not invented: 2008 and 2010 generals,
the 2022 general, primaries other than 2018 and 2020, and reliable straight-ticket counts (the 2024
straight-ticket figures don't reconcile with the clerk's). Details in [METHODOLOGY.md](METHODOLOGY.md).

## Reproducing

The full process (exact source files, precinct-name normalization rules, validation) is documented in
[METHODOLOGY.md](METHODOLOGY.md).

## Sources and credit

- Election returns: [OpenElections](https://openelections.net) (official county/state canvasses, transcribed)
- Precinct naming: [IndianaMap](https://indianamap.org)
- Validation: Boone County Clerk

Compiled by Oliver Gollapudi.
