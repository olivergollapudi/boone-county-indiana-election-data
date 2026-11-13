# Data dictionary

Every published table, its grain (what one row is), and every column. All files are
UTF-8 CSV with a header row unless noted. How the values were produced and checked is in
[METHODOLOGY.md](METHODOLOGY.md).

Conventions used throughout:

- **Election IDs** look like `2024-GENERAL`, `2022-PRIMARY`, `2017-SPECIAL`. In the
  master files the same thing appears as `source_file_id` with a `-PRECINCT` suffix
  (`2024-GENERAL-PRECINCT`), naming the Clerk PDF the row came from.
- **Party codes** are as printed by the Clerk, normalized to letters (`R`, `D`, `L`, …).
  Blank means the ballot printed no party (nonpartisan races, judicial retention, public
  questions).
- **District codes** are plain numbers without leading zeros (`25`, not `025`).

---

## Master: `data/results_long_*.csv` (Results_Long)

Grain: one row per **election × contest × precinct × candidate**, exactly as the Clerk
reported it. `results_long_all.csv` holds the 26 text-based elections; the two
`-geom-clean.csv` files hold the scanned 2008 general and 2022 primary (see the OCR
known issue in METHODOLOGY.md §5). The workbook's Results_Long tab is these three files
plus the countywide-only 2008 primary.

| Column | Meaning |
|---|---|
| `source_file_id` | The Clerk report the row came from (`<year>-<type>-PRECINCT`). |
| `precinct_id` | Precinct number as printed in the report. |
| `precinct_name` | Precinct name as printed (spelling varies by year, e.g. `Center 1` / `Center 01`). |
| `office` | Contest title as printed. |
| `contest_party` | Ballot the contest was on in a primary (`R` / `D`); blank in generals. |
| `party` | Candidate's party, normalized. |
| `party_raw` | Candidate's party exactly as printed. |
| `vote_for` | Number of seats ("VOTE FOR n"). |
| `contest_votes` | The report's own total for the contest (`VOTES=`); the checksum target. |
| `candidate` | Candidate name, or `YES` / `NO` for retention and public questions, or `Write-In`. |
| `column_scheme` | What `split1-3` mean in that report: `M,A,P` (machine / absentee / provisional) or `E,A,W` (election day / absentee / walk-in). Kept as printed; never equated across schemes. |
| `split1`, `split2`, `split3` | Votes by method, in the order given by `column_scheme`. |
| `total` | Candidate's total votes in the precinct. **The number to use.** |
| `pct` | Percentage as printed (`total` ÷ `contest_votes` for vote-for-1 contests). |
| `granularity` | `precinct`, or `countywide` where the Clerk published no precinct breakdown. |
| `redistricting_era` | The district-map era the election fell under (e.g. `2001-2010 map`). |
| `recovered` | OCR files only. Blank normally; `unopposed` or `binary` where one unreadable cell was recovered from the contest's own printed total. |

## Master: `data/turnout_long.csv` (Turnout_Long)

Grain: one row per **election × precinct**, plus one `COUNTYWIDE` row per election.

| Column | Meaning |
|---|---|
| `source_file_id`, `precinct_id`, `precinct_name` | As in Results_Long. |
| `registered_voters` | Registered voters as printed. (The 2020 primary reports print 0 here for 49 of 53 precincts, at the source.) |
| `public_count` | Ballots cast. |
| `turnout_pct` | Turnout as printed. Validated: `public_count / registered_voters` = this, within rounding. |
| `split1-3`, `column_scheme` | Ballots by method, as in Results_Long. |
| `granularity` | `precinct` or `countywide`. |
| `recovered_split` | `yes` where one OCR-dropped split was recovered as `public_count` minus the other two. |
| `flag_core` | Non-blank if the turnout identity failed (describes the mismatch). |
| `flag_split` | Non-blank if the splits don't sum to `public_count` (e.g. OCR-dropped cells); core turnout is still valid. |

## Master: `data/omitted_*.csv`

Grain: one row per **contest from a scanned report that was left out** of the master.

| Column | Meaning |
|---|---|
| `source_file_id`, `precinct_id`, `office`, `contest_party`, `vote_for` | Identify the contest. |
| `contest_votes` | The report's printed total. |
| `parsed_sum` | What the OCR'd candidate rows added up to. |
| `delta` | `contest_votes − parsed_sum`. |
| `n_candidates` | Candidate rows read. |
| `reason` | `checksum-fail` (numbers don't add up), `unverifiable-votefor-n` (multi-seat contest, checksum can't apply), `no-VOTES=` (total unreadable). |

## Reference: `data/precinct_crosswalk.csv`

Grain: one row per **current precinct**. Columns: `precinct`, `town`, `council_district`
(Boone County Council district, read from the Clerk's ballots).

---

## Normalized: `data/normalized/results_by_current_district.csv`

Grain: one row per **election × current district × contest × candidate**. Produced by
`scripts/normalize.py`. Each election's votes appear three times, once per district type,
so **always filter on `district_type`** before summing.

| Column | Meaning |
|---|---|
| `election` | Election ID. |
| `district_type` | `in_house` (Indiana House), `in_senate` (Indiana Senate), `us_house` (U.S. House). Current (2021-enacted) lines. |
| `district` | District number. |
| `district_name` | Readable label, e.g. `Indiana House 25`. |
| `office`, `contest_party`, `candidate`, `party` | As in Results_Long. |
| `votes` | Votes cast in the part of Boone County inside this district. Fractional where a precinct was split between districts (4 decimals). |
| `n_precincts` | Number of reported precincts contributing any votes. |
| `contest_coverage` | Share (0–1) of this district's precincts, weighted by how much of each lies in the district, where this contest was on the ballot. Below 1 means the figure describes only part of the district (common for local races). |
| `votes_from_split_precincts` | Part of `votes` that came from precincts divided between districts (i.e. depends on the population weights). |
| `votes_from_straddling` | Part of `votes` from precincts with less than 95% of adults in one district. |
| `geometry_basis` | Which precinct map was used: `as_of_election`, `assumed_2020_shapes` (2012–2018), `assumed_2010_shapes` (2008). See METHODOLOGY.md §7. |
| `data_quality` | `verified`, or `ocr_labels_unverified` for 2008 general and 2022 primary. |
| `provisional` | `True` for elections whose report is not yet the certified canvass (currently the 2026 primary and general; the list is `scripts/provisional.py`). |

**Only the part of each district inside Boone County is covered.** All four House
districts, both Senate districts and the congressional district extend beyond the
county; these figures are Boone County's portion, not district-wide results.

## Normalized: `data/normalized/precinct_district_shares.csv`

Grain: one row per **map-vintage precinct × district type × district** it touches.

| Column | Meaning |
|---|---|
| `vintage` | Precinct map year: `2010`, `2020` or `2024`. |
| `precinct_key` | Normalized precinct name (e.g. `CENTER 6`). |
| `district_type`, `district` | As above. |
| `share` | Fraction of the precinct's votes allocated to this district (voting-age population share). Sums to 1 per precinct and district type. |
| `share_area` | The same split by land area, for reference. |
| `vap_in_part` | Voting-age population of the precinct's blocks in this district. |
| `weight_basis` | `vap_2010`, `vap_2020`, or `area_fallback` (precinct had no adults). |
| `straddles` | `True` if under 95% of the precinct's adults are in one district. |

## Normalized: `data/normalized/election_precinct_map.csv`

Grain: one row per **election × reported precinct**: how each reported precinct was
matched to a map shape.

| Column | Meaning |
|---|---|
| `election`, `precinct_id`, `precinct_name` | As reported. |
| `vintage`, `geometry_basis` | Map used for that election. |
| `name_key` | Reported name, normalized. |
| `precinct_key` | Map precinct it was matched to. |
| `match` | `name`, or `name_fix` where an explicit, documented exception in `normalize.py` applied. |

## Comparison baseline: `data/normalized/results_by_district_as_drawn.csv`

Grain: one row per **election × district as drawn at the time × contest × candidate**.
Produced by `scripts/as_drawn.py`. Each precinct is assigned, whole, to the district
printed on its own ballot in that map era, so nothing is estimated. Put next to
`results_by_current_district.csv`, it shows how a district number's history differs from
the history of today's district.

| Column | Meaning |
|---|---|
| `election` | Election ID. |
| `redistricting_era` | `2001-2010 map`, `2011-2020 map` or `2021-present map` (as tagged in Results_Long). |
| `district_type`, `district`, `district_name` | The district as drawn at the time. Numbers are reused across maps for different places (e.g. House 28). |
| `office`, `contest_party`, `candidate`, `party` | As in Results_Long. |
| `votes` | Votes in the Boone County part of the district at the time (whole numbers). |
| `n_precincts` | Precincts in that district at the time that reported the contest. |
| `exists_in_boone_today` | `True` if this district number is used in Boone under today's map. |
| `data_quality`, `provisional` | As in the normalized results. |

`data/normalized/precinct_district_as_drawn.csv` — one row per **map era × precinct ×
district type**: `district`, and `seen_in` (the elections whose ballots showed it).
`data/normalized/as_drawn_validation.csv` — checks A1–A3 (see METHODOLOGY.md §7).

## Normalized: other files

- `set_aside.csv` — Results_Long rows that could not be allocated, with `reason`. Currently empty.
- `normalization_validation.csv` — each validation check (`check`, `scope`, `result`, `detail`).
- `current_districts.geojson` — today's district outlines within Boone County (WGS84);
  properties `district_type`, `district`.

## Analysis: `analysis/`

Generated by `scripts/analysis_2026.py`. `2026_general.md` is the written 2026 analysis;
`2026_general_tables.csv` holds every number it quotes, one per row (`section`, `item`,
`field`, `value`), so any figure in the text can be traced and checked.

## Maps: `maps/`

PNG images made by `scripts/make_maps.py`, plus `captions.csv` (`file`, `title`,
`caption`): the full caption of every image, for alt text and reuse. Every number drawn
comes from the tables above.

## Interactive map data: `site/data/`

Written by `scripts/build_site.py` (checks W1–W7: every precinct has a shape; precinct
votes equal Results_Long; district votes equal precinct votes; W4 every chart appears on
the "Charts & maps" page once; W5–W7 below). `results.json` holds, per
contest and year: each precinct's candidate rows as reported (`c` = [candidate, party,
votes]) and two-party margin (`m`); each current district's re-expressed rows, margin,
precinct count (`n`), votes from split precincts (`split`) and contest coverage (`cov`).

`results.json` → `turnout` holds, per even-year general election (2010–2026), from
`turnout_long.csv`: each precinct's registered voters (`reg`) and ballots cast (`ballots`),
and, where the report uses the E,A,W ballot-type columns (2020 onward, `method` = true),
ballots cast on election day (`e`), by mail / paper absentee (`a`) and early in person /
walk-in absentee (`w`). `districts` holds the same counts allocated to today's districts
with the precinct shares in `precinct_district_shares.csv` (so they can be fractional), and
`county` the precinct totals. Checks: W5 every turnout precinct has a shape; W6 the
district totals equal the precinct totals for every count; W7 `e + a + w` = `ballots` for
every precinct. The map page computes only turnout (`ballots ÷ reg`), shares
(`e`, `a` or `w` ÷ `ballots`) and differences between two years from these counts.
The GeoJSON files are the precinct shapes (2010; 2024, used for 2012 onward) and today's
district outlines.

## Geography inputs: `source_geo/`

- `precincts_<vintage>.geojson` — Boone precinct shapes from IndianaMap; properties
  `vintage`, `precinct_name_raw`, `source_id`, and for 2023/2024 `in_house`, `in_senate`,
  `us_house`.
- `census_blocks_<year>.geojson` — Census blocks; properties `geoid`, `pop` (total
  population), `vap` (voting-age population).
- `SOURCES.csv` — origin, retrieval date and sha256 of every input.
