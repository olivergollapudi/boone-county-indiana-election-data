# Boone County Election Database — How It Was Built and Validated

> How `boone_county_election_results.xlsx` was produced and why it can be trusted.
> Written for two readers: someone who wants the overview, and someone who wants to
> audit every line. `PARSING_STRATEGY.md` has the report-format spec. Every script
> named here is in this repository.

---

## 0. The one-sentence version

Every number in the workbook came from a Boone County Clerk PDF, was re-derived by a
script (never typed by hand), and was only allowed into the master **if the candidate
vote totals it produced added up exactly to the total the Clerk's own report printed for
that contest.** Anything that failed that test was left out and written to a documented
"omitted" list instead of being guessed at.

That test — "the parts equal the whole the source itself states" — is what "validated"
means here, and it was applied to all 20,670 single-winner contests in the file, which
all passed.

---

## 1. What "validated" means in this project (the core idea)

Election reports have a useful built-in redundancy. For each contest, the Clerk's report
prints:

- a line for each candidate with their vote total, and
- a contest total, printed as `VOTES= NNN`.

If our parse is correct, the candidate totals we extracted must sum to that `VOTES=`
number. If they don't, we misread something. This is the **within-contest checksum**, and
it is the backbone of the whole project because it catches both kinds of error at once:

1. **Parsing errors** — we attached a row to the wrong contest, split a column wrong, etc.
2. **OCR errors** — a digit or a whole row was misread on a scanned page.

We use it two ways:

- **As a validator** (for text-based reports we can parse directly).
- **As an inclusion gate** (for OCR'd reports): a contest is written into the master
  *only if* it passes. This is why the master can be trusted even though two of its
  elections came from imperfect scans — the bad contests never got in.

Where a **second independent document** exists for the same election (the Clerk publishes
both a precinct breakdown *and* a separate countywide summary), we add a stronger check:

- **Independent countywide cross-check** — sum our precinct rows per candidate and confirm
  they equal the Clerk's separate summary, candidate by candidate. Two different documents,
  same source, agreeing. Six elections have a clean summary and all six reconcile with
  **zero mismatches**.

So: one validation layer everywhere, two layers where a second document exists.

---

## 2. The data and the shape of the master

- **Source:** the Boone County Clerk "Election Results History" page — and *only* that.
  No OpenElections, no third parties. One source = one provenance chain to defend.
- **Coverage:** 28 elections, 2008–2026 (generals, primaries, odd-year municipals,
  and one 2017 special).
- **Format:** one long "spine" — **one row per election × precinct × contest ×
  candidate** — so every messy race type (multi-seat, yes/no referendum, nonpartisan,
  judicial retention) fits the same table. `boone_county_election_results.xlsx`,
  **51,833 rows**, seven tabs:

  | Tab | What it is |
  |---|---|
  | README | Purpose, methodology, data dictionary |
  | Results_Long | The source of truth — every candidate row |
  | Turnout_Long | Placeholder (turnout extraction deferred) |
  | Precincts | Precinct reference across the 27→54→53 evolution |
  | Source_Provenance | Which PDF fed each election, how parsed, validation status |
  | Validation | Per-election checksum + cross-check results |
  | Coverage_Inventory | What's present, what's omitted, and why |

Each row carries a `source_file_id` so any number can be traced back to the exact PDF it
came from.

---

## 3. The pipeline, stage by stage

The elections fell into two groups that needed very different handling: **text PDFs**
(most years) and **scanned PDFs** (2008 general, 2022 primary). Here is the whole flow.

### Stage 1 — Inventory and categorization
**Scripts:** `inventory.py`, `categorize.py`
**Why:** you can't parse what you haven't classified. Some PDFs have selectable text;
some are images of paper that need OCR.
**How:** each PDF is opened and its pages counted as text vs. image. Files are labeled
EMBEDDED (all text), MIXED (a few scanned summary pages, but the precinct pages are text),
or SCANNED (images — need OCR). This produced the work queue: 25 elections parseable
directly, 2 needing OCR.

### Stage 2 — Parse the text reports
**Script:** `parse_all.py` → `results_long_all.csv` (48,583 rows)
**Why:** turn 25 elections' worth of PDF text into clean structured rows.
**How:** the EMS "Precinct Summary Report" has a consistent block structure — a precinct
banner, then per contest a `VOTES= NNN Office`, a `VOTE FOR n`, and candidate lines like
`374 152 0 526 100.00% MATT KINCAID (R)` (the vote-method splits, the total, the percent,
the name with an embedded `(R)`/`(D)`). The parser is a small state machine that walks the
lines, tracks "which precinct / which contest am I in," and emits one row per candidate.
It **auto-detects format variants** that drift across years (2-digit vs 3-digit precinct
numbers, machine/absentee/provisional vs election-day/absentee/walk-in column schemes,
party position, etc.) rather than assuming a fixed layout. As it parses, it prints the
within-contest checksum for every file — all zero.

### Stage 3 — Independent cross-check on the text reports
**Script:** `reconcile_all.py`
**Why:** the within-contest checksum proves internal consistency; this proves agreement
with a *second* document.
**How:** for every election that also has a clean countywide summary PDF, it parses that
summary independently and compares, candidate by candidate, against our summed precinct
rows. Result: **2022 general (116), 2023 general (44), 2023 primary (38), 2024 general
(66), 2024 primary (260), 2026 primary (216) — 0 mismatches total.**

At this point the 25 text elections are done and doubly-checked.

### Stage 4 — The scanned reports: why they were hard
2008 general and 2022 primary are scans (images). Two OCR attempts had already been tried
before this build:

- **Tesseract OCR** — misread too many digits; ~13% of contests failed the checksum.
  Not defensible.
- **Apple Vision OCR, read as flat text** — much better digit accuracy, but still only
  ~88% of contests reconciled. The reason turned out to be important: Apple Vision was
  reading the *numbers correctly*, but when its output was flattened back into text
  "lines," numbers and names from a dense, slightly-skewed table landed on the wrong
  lines. **The failure was table reconstruction, not character recognition.**

That diagnosis is what unlocked the solution.

### Stage 5 — Geometry reconstruction (the key innovation)
**Scripts:** `dump_boxes.py` → `geometry_parse.py`
**Why:** if the digits are right but the layout is scrambled, stop flattening the page
and instead rebuild the table from where each token physically sits.
**How, in detail:**

1. **`dump_boxes.py`** re-runs Apple Vision but keeps each recognized token's **bounding
   box** — its (x, y) position on the page, normalized 0–1. These are cached to a JSON so
   the OCR only runs once.

2. **`geometry_parse.py`** rebuilds each page's table from those coordinates:
   - **Deskew.** Scanned pages tilt slightly. The code measures the tilt from the
     `M A P TOTAL` header row (fitting a line through those cells) and straightens every
     token's vertical position so a table row becomes truly horizontal. Without this, a
     left-column number can drift into the row above or below.
   - **Find the columns.** It clusters all the numeric tokens by horizontal position into
     column centers; the rightmost cluster (just left of the `%` column) is the TOTAL,
     the others are the vote splits. This is done per page, so it works whether the report
     uses M/A/P (2008) or E/A/W (2022) — no hard-coded column positions.
   - **Build the rows.** Tokens are grouped into rows by their straightened vertical
     position, anchored to the top of each row so two closely-stacked candidates don't
     merge. A safety rule splits any row that accidentally captured two candidates.
   - **Read each row.** A number is assigned to a column by its x-position; the text to
     the right is the candidate name; the `%` marks the row as a candidate line. Contest
     context (`VOTES=`, `VOTE FOR`, the office name, and the `(R)`/`(D)` ballot party) is
     tracked as it walks down the page.
   - **Format-awareness.** The same script handles both reports: two precinct-label styles
     (`49-Worth` vs `Precinct ID: 01`), both column schemes, and the fact that 2008 prints
     `VOTE FOR` *after* the contest header while 2022 prints it *before* (a timing detail
     that, unhandled, silently dropped the seat count).
   - **Skip the cumulative section.** The countywide "Election Summary Report" pages at the
     end of each file are ignored, so their big totals don't get mistaken for a precinct's.

3. **Defensible recovery of OCR-dropped cells.** Apple Vision sometimes omits a zero cell,
   drops one split column, or loses a digit. The code recovers these **only from the
   report's own arithmetic**, never from outside estimation:
   - omitted zero cell → 0;
   - one split missing but the total is present → missing split = total − others;
   - total missing but splits present → total = sum of splits;
   - **unopposed** candidate at 100% with a dropped column → total = the contest's own
     `VOTES=` (an unopposed candidate by definition received the contest total);
   - **binary Yes/No** (referenda, judicial retention) where one side's total was lost →
     that side = `VOTES=` − the side that has a trustworthy total.

   Every one of these is an identity forced by numbers the Clerk already printed. Rows
   fixed this way are tagged in the `recovered` column so the intervention is transparent.

   This took 2008 general from 88% to 92% and, crucially, made the *reason* for every
   remaining failure a genuine, unrecoverable OCR loss (a name or digit simply not on the
   page) rather than a reconstruction mistake.

### Stage 6 — Keep only what reconciles
**Script:** `finalize_ocr.py`
**Why:** the decision (yours) was that the master must be 100% correct — so anything that
doesn't reconcile is excluded, not approximated, and is documented so it can be
approximated *later* in the analysis layer if ever needed.
**How:** it groups the geometry output by contest and includes a contest **only if** it is
a single-winner race with a known `VOTES=` and its candidate totals sum exactly to it.
Everything else goes to `omitted_<election>.csv` with its `VOTES=` target and the parsed
shortfall, tagged by reason:

- **2008 general:** 847 contests included (1,973 rows); 133 omitted (71 checksum-fails
  from genuine OCR loss + 62 multi-seat races that can't be single-winner-checked).
- **2022 primary:** 656 contests included (1,149 rows); 208 omitted (143 fails + 65
  multi-seat).

Note: the omitted contests are dominated by (a) multi-seat races the check can't verify
and (b) a handful of down-ballot races where OCR dropped a candidate's row on the densest
pages. The omitted files preserve each contest's reported `VOTES=`, so a future analysis
step can approximate the missing precinct splits without re-touching the master.

### Stage 7 — The countywide-only election
2008 **primary** has no precinct breakdown anywhere — only a countywide summary. Per the
project rule to log every race at the finest level the Clerk reports (and never silently
drop countywide-only contests), it is ingested at `granularity = countywide`, clearly
distinguished from precinct-level rows.

### Stage 7b — Turnout
**Script:** `extract_turnout.py` → `turnout_long.csv` → the `Turnout_Long` tab
**Why:** the reports also print, per precinct, the registered voters, total ballots cast
(public count), turnout %, and ballot counts by type (machine/absentee/provisional or
election-day/absentee/walk-in). This is different data at a different grain (one row per
precinct per election), so it lives in its own tab.
**How:** the per-precinct header block is parsed from the same PDFs (and from the two
scanned elections' cached OCR), layout-agnostically (labels and values are matched
wherever they sit on the page). Two built-in validations mirror the results checksum:
- **core (the gate):** `public_count / registered_voters` must equal the printed
  turnout % — a three-way consistency check tying the key numbers together;
- **splits:** the ballot-type counts must sum to the public count; a single OCR-dropped
  split is recovered from the public count, and any remaining gap is flagged, not guessed.

Result: **1,245 rows across 27 elections; the core turnout identity passes on all 1,189
checkable precincts (0 failures)**, and the ballot-type breakdown reconciles for 1,187 of
them. The 2008 *primary* has no precinct-level turnout (summary-only), and the 2020
reports print registered voters / turnout % as zero at the source — both documented, not
errors on our side.

### Stage 8 — Assemble the workbook
**Script:** `build_workbook.py`
**How:** it concatenates the 25 embedded elections + the two OCR clean sets + the 2008
countywide rows into the long spine, then builds the seven tabs — including
Source_Provenance (how each election was parsed and its validation status),
Validation (the checksum + cross-check results), and Coverage_Inventory (row counts and
the omission notes). Nothing that failed validation is written in.

---

## 4. The final verification (what makes it "verified," not just "built")

After the workbook was assembled, the within-contest checksum was recomputed **directly
from the finished `Results_Long` tab** — not from intermediate files — keying each contest
by (election, precinct, office, ballot party):

```
checkable single-winner contests: 20,670
PASS: 20,670    FAIL: 0
```

Every single-winner contest in the delivered file reconciles to the Clerk's own reported
total. Combined with the six independent countywide cross-checks (0 mismatches), this is
the proof the workbook is validated.

### How to re-verify it yourself (nothing to take on faith)
```bash
cd ~/Documents/"Boone County Data"
source .venv/bin/activate
python3 parse_all.py       # re-parses the 25 text elections; every 'vf1-bad' prints 0
python3 reconcile_all.py   # independent cross-check; TOTAL mismatches must be 0
python3 geometry_parse.py 2008-general-precinct   # re-runs OCR reconstruction + checksum
python3 geometry_parse.py 2022-primary-precinct
python3 finalize_ocr.py 2008-general-precinct     # regenerates clean + omitted split
python3 finalize_ocr.py 2022-primary-precinct
python3 build_workbook.py  # rebuilds the workbook from scratch
```
Every step is deterministic and prints its own numbers. The scripts are commented and were
written to be read.

---

## 5. Honest limitations (so the file is used correctly)

- **The master is "what the Clerk reported," never an estimate.** No number was inferred
  from another race. Approximating missing precinct splits is deliberately a *later*
  analysis step, not baked in.
- **Two OCR elections are complete but not exhaustive.** 2008 general and 2022 primary
  contain only their reconciling contests; the omitted lists (`omitted_*.csv`) record what
  was left out and why. 2008 general also has no separate summary, so it rests on the
  single within-contest layer (still the same pass/fail bar as everything else); 2022's
  summary is itself a scan, so its second layer isn't cleanly available either.
- **Multi-seat and nonpartisan races** (council at-large, convention delegates) can't use
  the single-winner checksum, so where they came from a scan they were conservatively
  omitted rather than included unverified.
- **Turnout is now included** (Turnout_Long tab), validated by the turnout identity. Two
  edges: 2008 primary has no precinct-level turnout (summary-only), and 2020's reports
  print registered voters / turnout % as zero at the source (public count and ballot
  splits are still captured and reconcile).
- **Precinct 01 / Center 1 of 2008** was in a separate stray PDF; it has now been OCR'd,
  reconstructed, validated, and folded into 2008 general as precinct 01 (via
  `add_center1.py`), so 2008 general is complete at all 49 precincts.

None of these affect the correctness of what *is* in the file; they define its edges.

---

## 6. Why you can trust it, in three sentences

Every value is machine-derived from a single official source and traceable to its PDF.
Every included contest passes the report's own internal arithmetic, and six elections
additionally agree with a second independent document — all with zero discrepancies.
Anything that couldn't meet that bar was excluded and written down rather than guessed,
so the master contains only defensible, reconciling data.
