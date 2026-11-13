#!/usr/bin/env python3
"""
build_site.py - write the data behind the interactive map (site/).

The page (site/index.html) only DISPLAYS what this script writes; every number on it comes
from the published tables, never typed in:

  site/data/results.json          per contest x year:
        precincts  <- Results_Long (data/results_long_all.csv): each precinct's candidate
                      rows exactly as reported (name, party, votes) + two-party margin
        districts  <- data/normalized/results_by_current_district.csv: votes re-expressed
                      on today's Indiana House / Senate / U.S. House districts
  site/data/precincts_2010.geojson  precinct shapes for 2010 (2010 Census map)
  site/data/precincts_2024.geojson  precinct shapes for 2012-2024 (2012-2018 assumed, as in
                                    the static maps)
  site/data/districts.geojson       today's district outlines

Same contests, colors, precinct matching and 2008 exclusion as scripts/make_maps.py (it
imports them), so the web map and the PNGs cannot drift apart.

CHECKS - exits non-zero and writes nothing if any fails:
  W1  every reported precinct of every mapped contest matches a precinct shape
  W2  per contest x year x candidate, the precinct votes written == Results_Long
  W3  per contest x year x candidate x district type, district votes written ==
      precinct votes (normalization conserves votes; tolerance 0.01 for 4-dp rounding)

Run (from the repository root, after normalize.py):
    python3 scripts/build_site.py
"""
import json, sys
from collections import defaultdict

import pandas as pd

from paths import DATA_DIR, ROOT
from make_maps import (CONTESTS, BLUE_ARM, RED_ARM, MARGIN_EDGES, NO_DATA, key,
                       load_results, contest_rows, precinct_layer, shapes_for)
from provisional import PROVISIONAL

SITE = ROOT / "site"
OUT = SITE / "data"
NORM = DATA_DIR / "normalized"
DISTRICT_TYPES = {"in_house": "Indiana House", "in_senate": "Indiana Senate", "us_house": "U.S. House"}


def fail(msg):
    sys.exit(f"STOP: {msg}")


def margin(R, D):
    return round(100 * (R - D) / (R + D), 2) if (R + D) > 0 else None


def main():
    results = load_results()
    # read text columns as text: a write-in has NO party, and a blank must stay "" (pandas
    # would otherwise make it NaN, which groupby silently drops - W3 caught exactly that)
    norm = pd.read_csv(NORM / "results_by_current_district.csv",
                       dtype={"district": str, "party": str, "contest_party": str, "candidate": str})
    for col in ("party", "contest_party", "candidate"):
        norm[col] = norm[col].fillna("")
    shapes = {v: precinct_layer(v).to_crs("EPSG:4326") for v in ("2010", "2024")}
    keys = {v: set(g["pkey"]) for v, g in shapes.items()}

    data = {"palette": {"blue": BLUE_ARM, "red": RED_ARM, "edges": MARGIN_EDGES, "no_data": NO_DATA},
            "district_types": DISTRICT_TYPES, "contests": {}}
    problems = []
    for slug, (label, pattern, years) in CONTESTS.items():
        data["contests"][slug] = {"label": label, "years": {}}
        for year in years:
            rows, office = contest_rows(results, year, pattern)
            vintage = "2010" if int(year) < 2012 else "2024"
            _, basis = shapes_for(year)
            rows = rows.assign(pkey=rows["precinct_name"].map(key).replace(
                {"WORTH 1": "WORTH"} if vintage == "2010" else {}))

            # W1: every reported precinct has a shape
            missing = sorted(set(rows["pkey"]) - keys[vintage])
            if missing:
                problems.append(f"W1 {slug} {year}: no shape for {missing}")

            precincts = {}
            for pk, g in rows.groupby("pkey"):
                cands = [[r.candidate, r.party, int(r.votes)] for r in g.itertuples()]
                R = sum(v for _, p, v in cands if p == "R"); D = sum(v for _, p, v in cands if p == "D")
                precincts[pk] = {"name": g["precinct_name"].iloc[0], "c": cands, "m": margin(R, D)}

            # W2: precinct votes written == Results_Long, per candidate
            written = defaultdict(int)
            for p in precincts.values():
                for cand, party, v in p["c"]:
                    written[(cand, party)] += v
            src = rows.groupby(["candidate", "party"])["votes"].sum()
            for (cand, party), v in src.items():
                if written[(cand, party)] != int(v):
                    problems.append(f"W2 {slug} {year} {cand}: wrote {written[(cand, party)]}, source {int(v)}")

            # districts, from the normalized table
            nd = norm[(norm["election"] == f"{year}-GENERAL") & (norm["office"] == office)]
            districts = {}
            for dt in DISTRICT_TYPES:
                districts[dt] = {}
                for dist, g in nd[nd["district_type"] == dt].groupby("district"):
                    cands = [[r.candidate, r.party, round(float(r.votes), 1)] for r in g.itertuples()]
                    R = sum(v for _, p, v in cands if p == "R"); D = sum(v for _, p, v in cands if p == "D")
                    districts[dt][dist] = {"c": cands, "m": margin(R, D),
                                           "n": int(g["n_precincts"].max()),
                                           "split": round(float(g["votes_from_split_precincts"].sum()), 1),
                                           "cov": round(float(g["contest_coverage"].min()), 3)}
                # W3: district votes conserve the precinct votes, per candidate
                got = nd[nd["district_type"] == dt].groupby(["candidate", "party"])["votes"].sum()
                for (cand, party), v in src.items():
                    if abs(got.get((cand, party), 0) - v) > 0.01 * max(1, len(districts[dt])):
                        problems.append(f"W3 {slug} {year} {dt} {cand}: districts {got.get((cand, party), 0):.2f}, source {v}")

            R, D = int(rows[rows.party == "R"]["votes"].sum()), int(rows[rows.party == "D"]["votes"].sum())
            data["contests"][slug]["years"][year] = {
                "office": office, "source": f"{year}-GENERAL-PRECINCT", "shapes": vintage, "basis": basis,
                "provisional": PROVISIONAL.get(f"{year}-GENERAL"),     # reason text, or None
                "county_margin": margin(R, D), "precincts": precincts, "districts": districts}

    print("CHECKS")
    for name in ("W1 every precinct has a shape", "W2 precinct votes == Results_Long",
                 "W3 district votes == precinct votes"):
        bad = [p for p in problems if p.startswith(name[:2])]
        print(f"  {'PASS' if not bad else 'FAIL'}  {name}" + (f"  ({len(bad)} problems)" if bad else ""))
    if problems:
        print("\n".join("   " + p for p in problems[:20]))
        fail("checks failed - nothing written")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(data, separators=(",", ":")))
    for v, g in shapes.items():
        g[["pkey", "geometry"]].to_file(OUT / f"precincts_{v}.geojson", driver="GeoJSON",
                                        COORDINATE_PRECISION=6)
    import geopandas as gpd
    d = gpd.read_file(NORM / "current_districts.geojson")
    d["district"] = d["district"].astype(str)
    d.to_file(OUT / "districts.geojson", driver="GeoJSON", COORDINATE_PRECISION=6)
    sizes = {p.name: f"{p.stat().st_size / 1e6:.2f} MB" for p in sorted(OUT.iterdir())}
    print(f"\nWrote {OUT}/  {sizes}")


if __name__ == "__main__":
    main()
