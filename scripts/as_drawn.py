#!/usr/bin/env python3
"""
as_drawn.py - results by district AS THE LINES WERE DRAWN AT THE TIME (no normalization).

This is the comparison baseline for normalize.py. It answers "what did 'House 25' (or any
district number) look like in Boone County in each election, using the lines in force at
that election?" Put next to the normalized results (today's lines), it shows how much a
district number's history is really a history of different places.

Where each precinct's district comes from - the Clerk's own ballots, nothing else:
  Every precinct's ballot prints its State Rep, State Senate and U.S. Rep contest with the
  district number. Within one map era (2001-2010, 2011-2020, 2021-present - the
  `redistricting_era` column of Results_Long) a precinct's districts don't change, so a
  precinct's district is read from ANY election in that era where the contest was on its
  ballot (state senate seats are staggered, so one election rarely covers every precinct).
  Precincts are matched across elections with the same precinct keys normalize.py uses
  (data/normalized/election_precinct_map.csv).

Aggregation is exact: each precinct belongs wholly to one district at the time, so votes
are summed, never split.

VALIDATION - exits non-zero and writes nothing if any fails:
  A1  no precinct shows two different districts of one type within one era
  A2  every reported precinct gets a district of each type, or is listed in the set-aside
  A3  votes conserved: allocated + set aside == Results_Long, for every election x contest
      x candidate and every district type

OUTPUTS (data/normalized/)
  precinct_district_as_drawn.csv     era x precinct x district type -> district, with the
                                     elections whose ballots showed it
  results_by_district_as_drawn.csv   election x district (as drawn) x contest x candidate

Run (after normalize.py, from the repository root):
    python3 scripts/as_drawn.py
"""
import re, sys

import pandas as pd

from paths import DATA_DIR
from normalize import DISTRICT_TYPES, OCR_ELECTIONS, load_results

OUT = DATA_DIR / "normalized"
TODAY = {   # district numbers that exist in Boone under today's map (from the 2024 layer)
    "in_house": {"24", "25", "28", "41"}, "in_senate": {"7", "29"}, "us_house": {"4"}}
PATTERNS = {
    "in_house":  re.compile(r"STATE\s+REP\w*\.?\s+(?:DIST\w*\.?\s*)?(\d+)"),
    "in_senate": re.compile(r"STATE\s+SEN\w*\.?\s+(?:DIST\w*\.?\s*)?(\d+)"),
    "us_house":  re.compile(r"(?:U\.?\s*S\.?|UNITED\s+STATES)\s+REP\w*\.?\s+(?:DIST\w*\.?\s*)?(\d+)"),
}


def fail(msg):
    sys.exit(f"STOP: {msg}")


def main():
    results = load_results()
    pr = results[(results["granularity"] == "precinct") & results["votes"].notna()].copy()
    emap = pd.read_csv(OUT / "election_precinct_map.csv", dtype=str)
    emap = emap.drop_duplicates(["election", "precinct_name"])[["election", "precinct_name", "precinct_key"]]
    pr = pr.merge(emap, on=["election", "precinct_name"], how="left", validate="many_to_one")
    era_of = pr.drop_duplicates("election").set_index("election")["redistricting_era"].to_dict()

    # ---- read each precinct's district (per era) off its own ballots -----------------------
    seen = []
    text_only = pr[~pr["election"].isin(OCR_ELECTIONS)]          # OCR office titles are noisy
    for (el, era, pk, office) in text_only[["election", "redistricting_era", "precinct_key",
                                            "office"]].drop_duplicates().itertuples(index=False):
        for dt, pat in PATTERNS.items():
            m = pat.search(str(office).upper())
            if m:
                seen.append({"era": era, "precinct_key": pk, "district_type": dt,
                             "district": m.group(1).lstrip("0"), "election": el})
    seen = pd.DataFrame(seen)
    assign = (seen.groupby(["era", "precinct_key", "district_type"])
                  .agg(district=("district", lambda s: sorted(set(s))),
                       seen_in=("election", lambda s: ";".join(sorted(set(s)))))
                  .reset_index())

    checks = []
    def check(name, scope, ok, detail=""):
        checks.append({"check": name, "scope": scope, "result": "PASS" if ok else "FAIL", "detail": detail})

    conflicts = assign[assign["district"].map(len) > 1]
    check("A1 one district per precinct per era", f"{len(assign)} era x precinct x type", conflicts.empty,
          "; ".join(f"{r.era} {r.precinct_key} {r.district_type}: {r.district}" for r in conflicts.head(5).itertuples()))
    assign["district"] = assign["district"].map(lambda d: d[0])

    # ---- allocate (whole precincts) --------------------------------------------------------
    alloc, aside = [], []
    for dt in DISTRICT_TYPES:
        a = assign[assign.district_type == dt][["era", "precinct_key", "district"]]
        m = pr.merge(a, left_on=["redistricting_era", "precinct_key"], right_on=["era", "precinct_key"], how="left")
        aside.append(m[m["district"].isna()].assign(district_type=dt, reason="no ballot in this era shows the district"))
        alloc.append(m[m["district"].notna()].assign(district_type=dt))
    alloc, aside = pd.concat(alloc, ignore_index=True), pd.concat(aside, ignore_index=True)
    missing = aside.drop_duplicates(["election", "precinct_key", "district_type"])
    check("A2 every precinct assigned or set aside", f"{pr[['election', 'precinct_key']].drop_duplicates().shape[0]} election-precincts x 3",
          True, f"{len(missing)} precinct x type set aside: " +
          "; ".join(f"{r.election} {r.precinct_key} {r.district_type}" for r in missing.head(8).itertuples()))

    gk = ["election", "office", "contest_party", "candidate", "party"]
    src = pr.groupby(gk)["votes"].sum()
    n_bad = 0
    for dt in DISTRICT_TYPES:
        got = alloc[alloc.district_type == dt].groupby(gk)["votes"].sum().reindex(src.index, fill_value=0)
        off = aside[aside.district_type == dt].groupby(gk)["votes"].sum().reindex(src.index, fill_value=0)
        n_bad += int(((got + off - src).abs() > 1e-9).sum())
    check("A3 votes conserved (allocated + set aside = Results_Long)", f"{len(src)} x 3 district types", n_bad == 0,
          f"{n_bad} failures")

    print("VALIDATION")
    for c in checks:
        print(f"  {c['result']}  {c['check']}  [{c['scope']}]  {c['detail']}")
    if any(c["result"] == "FAIL" for c in checks):
        fail("validation failed - nothing written")

    # ---- outputs ---------------------------------------------------------------------------
    assign.to_csv(OUT / "precinct_district_as_drawn.csv", index=False)
    out = (alloc.groupby(["election", "redistricting_era", "district_type", "district"] + gk[1:])
                .agg(votes=("votes", "sum"), n_precincts=("precinct_key", "nunique")).reset_index())
    out["district_name"] = out["district_type"].map(DISTRICT_TYPES) + " " + out["district"]
    out["exists_in_boone_today"] = [d in TODAY[t] for t, d in zip(out.district_type, out.district)]
    out["data_quality"] = out["election"].map(lambda e: "ocr_labels_unverified" if e in OCR_ELECTIONS else "verified")
    out["provisional"] = out["election"].str.startswith("2026")
    out = out[["election", "redistricting_era", "district_type", "district", "district_name", "office",
               "contest_party", "candidate", "party", "votes", "n_precincts", "exists_in_boone_today",
               "data_quality", "provisional"]].sort_values(["election", "district_type", "district", "office"])
    out.to_csv(OUT / "results_by_district_as_drawn.csv", index=False)
    pd.DataFrame(checks).to_csv(OUT / "as_drawn_validation.csv", index=False)

    print(f"\nWrote {OUT}/results_by_district_as_drawn.csv ({len(out):,} rows)")
    for dt in DISTRICT_TYPES:
        eras = assign[assign.district_type == dt].groupby("era")["district"].apply(lambda s: sorted(set(s), key=int))
        print(f"  {DISTRICT_TYPES[dt]:15} " + "  |  ".join(f"{e}: {', '.join(d)}" for e, d in eras.items()))


if __name__ == "__main__":
    main()
