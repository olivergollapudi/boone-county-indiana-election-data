# Boone County — Comprehensive Parsing Strategy (every format, 2008 → 2026)

> Built empirically: every `*-precinct.pdf` was opened and its layout auto-detected
> (vote columns, precinct-header style, party position, contest-header order, name
> case). This is the spec the parser (`parse_all.py`) implements. Items marked
> **[DECIDE]** were open questions at the time of writing; all were resolved during
> the build (see METHODOLOGY.md).

---

## 0. Core principle: detect axes, don't assume an "era"

The reports drift on SIX independent axes, and they do NOT flip together:

| Axis | Values seen | Switch year(s) |
|---|---|---|
| **A. Vote columns** | `M A P` (Machine/Absentee/Provisional), `A M P` (2011 only), `E A W` (Election-day/Absentee-paper/Walk-in) | MAP→EAW at **2019** |
| **B. Precinct header** | `NN-Name` (e.g. `01-Center 1`) → `Precinct ID:`+`Precinct Name:` | NN→ID at **2017** |
| **C. Contest-header order** | `VOTES= n [party] Office` then `VOTE FOR` → `VOTE FOR` then `[party] Office` then `VOTES=` | reorders at **2016** |
| **D. Party position (generals)** | TRAILING `Name (R)` → LEADING `(R) Name` | flips at **2016** |
| **E. Party position (primaries)** | on the contest line `(R) Office` (inline with VOTES pre-2020, on its own line 2023+); candidates always plain | stable concept |
| **F. Name case** | `CAPS` vs mixed | sporadic, per-file |

Because A flips at 2019, C/D at 2016, and B at 2017, **the parser reads each axis off the
report itself** (below) rather than keying on the year. The year is only a sanity check.

---

## 1. How to detect each axis (parser logic)

- **A. Columns** — find the header line `^([A-Z])\s+([A-Z])\s+([A-Z])\s+TOTAL`. The three
  capture groups ARE the column meaning and order. Store as `column_scheme` (e.g. `M,A,P`);
  map the three split integers positionally. Never hardcode E/A/W.
- **B. Precinct header / segmentation** — if `Precinct ID:` present → use it (+`Precinct Name:`);
  else a precinct starts at a line matching `^\d{2}-\S` (e.g. `01-Center 1`). Everything before
  the first precinct marker is the cumulative summary section → **skip for the precinct parse**.
- **C/E. Contest header** — a contest is bounded by `VOTE FOR n` and a `VOTES=\s*[\d,]+` token,
  in either order. The office is the text on the `VOTES=` line after the number, OR the
  standalone line after `VOTE FOR`. A leading `(R)` on that office text ⇒ **primary, party
  on the contest** (candidates plain).
- **D. Candidate party position** — for each candidate row, test in order:
  leading `^\([A-Z]{1,4}\)\s+` ⇒ party is leading; trailing `\([A-Z]{1,4}\)\s*$` ⇒ trailing;
  neither ⇒ inherit the contest's party (primary) or `None` (referenda Yes/No, Write-In).
- **F. Case** — store the candidate name verbatim as `candidate_raw`; also a normalized
  Title-Case `candidate` for joins. (Needed because 2008/2016/2018 are ALL CAPS.)

The candidate row itself is always: `int int int  TOTAL  pct%  <name±party>` →
`^(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+([\d.]+)%\s+(.+?)\s*$`, then peel party per axis D.

---

## 2. Per-file recipe table (what each precinct file actually is)

cols = vote-column scheme · pHdr = precinct-header style · genParty = general party position ·
order = contest-header order · case · quality.

| File | cols | pHdr | party (gen / prim) | order | case | quality |
|---|---|---|---|---|---|---|
| 2008-general-precinct | (MAP) | (NN) | trailing | VOTES-first | CAPS | **SCAN→OCR** |
| 2008-primary-summary | MAP | n/a | prim: on-contest | VOTES-first | CAPS | emb (summary only) |
| 2010-general-precinct | MAP | NN | trailing | VOTES-first | CAPS | **MIX** (front summary scanned) |
| 2010-primary-precinct | MAP | NN | prim: on-contest | VOTES-first | mix | emb |
| 2011-general-precinct | **AMP** | NN | trailing (+`(I)`) | VOTES-first | mix | emb · municipal |
| 2011-primary-precinct | **AMP** | NN | prim: on-contest | VOTES-first | CAPS | emb (summary is SCAN) |
| 2012-general-precinct | MAP | NN | trailing | VOTES-first | mix | emb (all text) |
| 2012-primary-precinct | MAP | NN | prim: on-contest | VOTES-first | mix | **MIX** |
| 2014-general-precinct | MAP | NN | trailing | VOTES-first | mix | emb |
| 2014-primary-precinct | MAP | NN | prim: on-contest | VOTES-first | mix | emb |
| 2015-general-precinct | MAP | NN | trailing (+`(I)`) | VOTES-first | mix | **MIX** · municipal |
| 2015-primary-precinct | MAP | NN | prim: on-contest | VOTES-first | mix | emb · municipal |
| 2016-general-precinct | MAP | NN | **leading** | **VOTE-FOR-first** | CAPS | emb |
| 2016-primary-precinct | MAP | NN | prim: on-contest | **VOTE-FOR-first** | CAPS | emb |
| 2017-special-precinct | MAP | **ID** | (special) | VOTE-FOR-first | CAPS | emb |
| 2018-general-precinct | MAP | ID | leading | VOTE-FOR-first | CAPS | emb |
| 2018-primary-precinct | MAP | ID | prim: on-contest | VOTE-FOR-first | CAPS | emb |
| 2019-general-precinct | **EAW** | ID | leading | VOTE-FOR-first | CAPS | emb |
| 2019-primary-precinct | EAW | ID | prim: on-contest | VOTE-FOR-first | CAPS | emb |
| 2020-general-precinct | EAW | ID | leading | VOTE-FOR-first | mix | **MIX** |
| 2020-primary-precinct | EAW* | ID | prim: on-contest | VOTE-FOR-first | CAPS | **MIX** (*verify cols) |
| 2022-general-precinct | EAW | ID | leading | VOTE-FOR-first | mix | emb |
| 2022-primary-precinct | (EAW) | (ID) | prim: on-contest | VOTE-FOR-first | — | **SCAN→OCR** |
| 2023-general-precinct | EAW | ID | leading | VOTE-FOR-first | mix | emb · municipal |
| 2023-primary-precinct | EAW | ID | prim: on-contest (own line) | VOTE-FOR-first | mix | emb |
| 2024-general-precinct | EAW | ID | leading | VOTE-FOR-first | mix | emb |
| 2024-primary-precinct | EAW | ID | prim: on-contest (own line) | VOTE-FOR-first | mix | emb |
| 2026-primary-precinct | EAW | ID | prim: on-contest (own line) | VOTE-FOR-first | mix | emb · **PILOT (proven)** |

\* 2020-primary column header didn't auto-detect cleanly — verify EAW vs MAP when we reach it.

---

## 3. Named profiles (axis bundles) for the build order

These are just convenient bundles of the axes above; the parser still detects per file.

- **P1 Modern primary** — EAW · ID · party on own `(R) Office` line · VOTE-FOR-first.
  Files: 2026, 2024, 2023, 2019 primaries (and 2020/2022 primaries). **Proven (pilot).**
- **P2 Modern general** — EAW/MAP · ID/NN · LEADING candidate party · VOTE-FOR-first.
  Files: 2024, 2023, 2022, 2020, 2019, 2018, 2016 generals. **Mini-pilot in progress (2024).**
- **P3 Legacy general** — MAP · NN · TRAILING candidate party · VOTES-first.
  Files: 2014, 2012, 2010 generals.
- **P4 Legacy primary** — MAP · NN · party on `VOTES= n (R) Office` · VOTES-first · often CAPS.
  Files: 2014, 2012, 2010 primaries; 2016/2018 primaries (CAPS, ID/NN mix).
- **P5 Municipal (odd-year)** — like P3 but `A M P` possible, independents `(I)`, referenda,
  and a `Straight Party Summary Information` block to skip. Files: 2011, 2015 (and odd-year
  2023/2019 which already parse as P1/P2).

Build/prove order (each a gated mini-pilot: parse → checksum → reconcile-if-summary → approve):
**P2 (2024 general) → P3 (2014 general) → P4 (2010 primary) → P5 (2011 municipal) → scale → OCR.**

---

## 4. Special-case handling rules (apply in every profile)

- **Referenda / Public Questions** — rows are `Yes`/`No` (or `YES`/`NO`); `party=None`,
  `office` = the question text (e.g. `Public Question ZCSC`). **[DECIDE]** keep as candidate rows.
- **`No Candidate Filed`** — a real 0-vote row; **[DECIDE]** keep (documents the contest existed).
- **`Write-In`** — `party=None`, candidate `Write-In`.
- **Independents / nonpartisan** — keep `(I)`, `(NP)` verbatim in `party_raw`.
- **Party-label drift** — normalize `REP→R, DEM→D, LIB→L, IND→I` into `party`; keep `party_raw`.
- **`Straight Party Summary Information`** block (2011+) — a per-precinct straight-ticket
  tally, NOT a contest. **[DECIDE]** skip for now (it's derived, not a race).
- **Multi-seat** `VOTE FOR n>1` (e.g. `City Council At Large … VOTE FOR 2`) — each candidate a
  row; `vote_for=n`; the vote-for-1 checksum is skipped for these (sums legitimately exceed VOTES=).
- **Fusion / running-mate names** (`Trump \ Vance`, `Romney-Ryan`) — keep the full string.
- **CAPS names** — store `candidate_raw` verbatim + a normalized `candidate`.

---

## 5. Validation (unchanged, per profile)

1. **Within-contest checksum (always):** for every `VOTE FOR 1` contest, candidate TOTALs must
   equal the contest `VOTES=`. Must be 0 failures before ingestion.
2. **Countywide cross-check (where a clean summary exists):** sum precinct rows per candidate =
   the separate summary report. Available for 2022/2023/2024 (+2026); most legacy years are
   precinct-only → checksum #1 only. OCR'd files MUST pass #1 before ingestion.
3. Every row carries `source_file_id`, `granularity`, `redistricting_era`, `column_scheme`.

---

## 6. OCR queue (do last)

- `2022-primary-precinct` (196 pp, fully scanned) — highest value, big job.
- `2008-general-precinct` (147 pp, fully scanned).
- `2008-general-precinct-Center1` (3 pp stray — **[DECIDE]** keep or drop).
- Scanned summaries (cross-check only, optional): `2022-primary-summary`, `2011-primary-summary`.
- **MIX files need NO OCR for the data** — their precinct pages are embedded text; only the
  front summary image is unreadable, and we don't parse that. (2010-gen, 2012-gen, 2012-pri,
  2015-gen, 2020-gen, 2020-pri.)

Pipeline for SCAN files: Tesseract → same line text → same profile detection + parser →
mandatory checksum (OCR digit misreads are the main poison risk).

---

## 7. Output schema (long spine, uniform across all profiles)

`source_file_id, precinct_id, precinct_name, office, party, party_raw, vote_for,
contest_votes, candidate, candidate_raw, column_scheme, split1, split2, split3, total,
pct, granularity, redistricting_era`

`split1/2/3` are positional; `column_scheme` (e.g. `M,A,P`) says what they mean. This keeps
"what the Clerk reported" exact while letting every era live in one table.
