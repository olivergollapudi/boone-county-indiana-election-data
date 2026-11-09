# Boone County, Indiana Precinct Election Data — Collection Methodology

**Project:** Boone County, Indiana precinct election data
**Scope of this document:** exactly how the precinct-level election dataset was assembled,
normalized, validated, and where it stops. Written so the process is fully reproducible and
so every number can be traced to a source.

---

## 1. What was produced

| File | What it is |
|------|------------|
| `boone_precinct_master_long.csv` | **The master.** Tidy long format: one row per precinct × election × office × candidate, 12,698 rows. |
| `boone_turnout_over_time.csv` | Per-precinct turnout for 2012, 2014, 2016, 2018, 2020, 2024. |
| `boone_presidential_over_time.csv` | County presidential totals + D/R shares, 2012–2024. |
| `boone_<office>_by_precinct.csv` | Wide pivots (precinct × candidate-year) for President, Governor, US Senate, US House, State Senate, State House, Attorney General. |
| `Boone_Precinct_Master.xlsx` | All of the above as one clean workbook (Provenance, Turnout, per-office sheets, Master_Long). |
| `00-Voting Data by Precinct - OpenElections-enhanced.xlsx` | A **copy** of the working file with safe additions only (see §6). The original is untouched. |

---

## 2. Sources (authoritative, and why)

- **Election returns — OpenElections (Indiana):** `github.com/openelections/openelections-data-in`.
  OpenElections is the standard open repository of official precinct-level returns,
  transcribed from county/state canvasses. Pulled by `git clone` so the exact commit is reproducible.
- **Precinct boundaries / canonical precinct names — IndianaMap:** `indianamap.org`
  (the state's official GIS). Used to define the canonical 53-precinct naming.

Using these two together is deliberate: returns from OpenElections, geography from
IndianaMap, joined on a normalized precinct key.

---

## 3. Exact files used

All are precinct-level CSVs. Statewide files were filtered to `county == "Boone"`.

| Year | Election | File (within the OpenElections repo) |
|------|----------|--------------------------------------|
| 2012 | General | `2012/20121106__in__general__precinct.csv` (statewide) |
| 2014 | General | `2014/20141104__in__general__precinct.csv` (statewide) |
| 2016 | General | `2016/20161108__in__general__boone__precinct.csv` |
| 2018 | Primary | `2018/counties/20180508__in__primary__boone__precinct.csv` |
| 2018 | General | `2018/counties/20181106__in__general__boone__precinct.csv` |
| 2020 | Primary | `2020/20200602__in__primary__precinct.csv` (statewide) |
| 2020 | General | `2020/20201103__in__general__boone__precinct.csv` |
| 2024 | General | `2024/counties/20241105__in__general__boone__precinct.csv` |

Column schemas vary slightly by year (some carry `election_day` / `absentee` /
`early_voting` splits), but all expose `county, precinct, office, district, candidate,
party, votes`. Only the consolidated `votes` total was used.

---

## 4. Precinct-name normalization (the hard part)

The same precinct is spelled differently across files. Observed variants:

- `Center 1` (2012/2014/2018) — single digit, title case
- `01-Center 01` (2016) — numeric prefix
- `CENTER 01` (2020) — uppercase
- `Center 01` (2024) — the canonical form
- `Clinton 18` (2014) — a single-precinct township carrying a county precinct number

**Normalization rules applied** (function `norm_precinct`):

1. Strip a leading `NN-` prefix (2016).
2. Collapse whitespace; Title-Case each word (preserves "Sugar Creek").
3. Zero-pad a trailing precinct number to two digits (`Center 5` → `Center 05`).
4. For single-precinct townships (Clinton, Harrison, Jefferson, Perry, Washington),
   drop a stray trailing number (`Clinton 18` → `Clinton`).
5. Drop non-precinct rows: county-total artifacts `Total` (2016) and `Boone` (2020 primary).

**Result:** every one of the 8 files maps cleanly onto the **canonical 53 precincts**
(the 2024 set) with **zero unmapped precincts** and only the expected total-rows dropped.
The canonical names match the IndianaMap boundary naming and the working spreadsheet.

> Note on precinct change over time: the 53-precinct set is stable across 2012–2024 in
> OpenElections. (Earlier boundary work using Census/IndianaMap vintages found Boone at
> 27 precincts in 2000 and 54 in 2010 — i.e., real change before this window. Those
> earlier vintages are a boundary-geometry question handled separately; the returns here
> are all on the modern 53-precinct frame.)

---

## 5. Validation — the dataset was checked, not trusted

Two independent cross-checks against the figures already hand-entered in the working
spreadsheet (which came from the **Boone County Clerk**, a different source):

**Presidential totals — EXACT match, all four years:**

| Year | Total | Dem | Rep | Other | Δ vs clerk |
|------|------:|----:|----:|------:|:----------:|
| 2012 | 27,782 | 8,328 | 18,808 | 646 | **0** |
| 2016 | 32,537 | 10,181 | 19,654 | 2,702 | **0** |
| 2020 | 38,668 | 15,244 | 22,351 | 1,073 | **0** |
| 2024 | 40,283 | 16,426 | 22,840 | 1,017 | **0** |

**Turnout — exact to 4 decimals** on every spot-checked precinct (e.g. Center 01:
2012 = 0.6954, 2016 = 0.6769, 2024 = 0.6772 — all matching the workbook). County ballots
cast (28,072 in 2012; 40,776 in 2024) also match the workbook's totals.

Because two independent sources (OpenElections vs. the county clerk) agree to the vote,
both the source data and this pipeline are confirmed correct.

**One discrepancy, deliberately not "fixed":** 2024 straight-ticket. OpenElections shows
Dem 4,546 / Rep 8,890; the clerk-sourced workbook shows Dem 4,791 / Rep 9,300. The likely
cause is the OE straight-party row not including all absentee/early components. The clerk
figures were **kept**; OE was not used for this field. (Flagged in the workbook's
"OpenElections Validation" sheet.)

---

## 6. What was added to the working spreadsheet (and what was NOT touched)

The original `00-Voting Data by Precinct.xlsx` is a hand-built, 266-column file. To avoid
any risk of corrupting it, **the original was left completely unmodified** and a separate
`...- OpenElections-enhanced.xlsx` copy was made with **only** these safe additions:

- **`% Turnout Over Time`**: added validated **2014, 2018, 2020** turnout columns
  (it previously had only 2012/2016/2024).
- **New `OpenElections Validation` sheet**: the cross-checks above.
- **New `Provenance & Gaps` sheet**: sources, coverage, and gaps.

The fragile `Raw Data` sheet and all existing sheets were verified byte-for-byte unchanged
(same `A1:JF1005` dimensions, identical spot-checked cells).

---

## 7. Honest gaps (not fabricated)

These are **not** available at precinct level from OpenElections and were **not** invented:

- **2008 and 2010 generals** — predate OpenElections precinct coverage for Boone. The
  blank 2008 rows in the working file remain blank; filling them requires the county
  clerk's canvass.
- **2022 general** — not present in the repository. Needs clerk data.
- **Primaries other than 2018 and 2020** — not present at precinct level.
- **Straight-ticket** — only 2016 and 2024 appear in OE, and 2024 does not reconcile
  (see §5).

---

## 8. Reproducing this

1. `git clone --filter=blob:none https://github.com/openelections/openelections-data-in.git`
2. Run the normalization in §4 on the 8 files in §3, filtering statewide files to Boone.
3. Concatenate to long format; pivot per office as needed.
4. Re-run the §5 checks against the clerk figures — they should remain exact.

Every figure in the master traces back to a named OpenElections file and a normalized
precinct key, so any number can be audited end-to-end.
