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
  site/data/gallery.json            the "Charts & maps" page: sections, and each image's
                                    title + caption from maps/captions.csv
  site/maps/                        local copy of maps/*.png for previewing (git-ignored;
                                    the publishing workflow copies maps/ in itself)

Same contests, colors, precinct matching and 2008 exclusion as scripts/make_maps.py (it
imports them), so the web map and the PNGs cannot drift apart.

CHECKS - exits non-zero and writes nothing if any fails:
  W1  every reported precinct of every mapped contest matches a precinct shape
  W2  per contest x year x candidate, the precinct votes written == Results_Long
  W3  per contest x year x candidate x district type, district votes written ==
      precinct votes (normalization conserves votes; tolerance 0.01 for 4-dp rounding)
  W4  every image in maps/ is on the "Charts & maps" page exactly once, with its caption
  W5  every precinct's turnout row (even-year generals 2010-2026) matches a precinct shape
  W6  turnout allocated to today's districts conserves every count (registered, ballots,
      and each ballot method) - same precinct->district shares as the vote normalization
  W7  where the "how people voted" layer is shown (2020+, E/A/W reports), election day +
      mail + early in person == ballots cast, for every precinct

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


# ---- turnout and "how people voted" layers ----------------------------------------------
# Even-year general elections (odd-year municipal elections cover only some precincts).
TURNOUT_YEARS = ["2010", "2012", "2014", "2016", "2018", "2020", "2022", "2024", "2026"]
# Ballot-method columns mean the same thing only where the report uses the E,A,W scheme:
# E = election day, A = paper absentee (mail), W = walk-in absentee (early in person).
# Earlier reports use M,A,P (machine / absentee / provisional), which cannot be split into
# election day vs early in person, so the method layer starts in 2020.
METHOD_SCHEME = "E,A,W"
# Each ramp passed the dataviz palette validator (--ordinal); none is a party color except
# the margin-change layer, whose direction genuinely is partisan.
LAYER_PALETTE = {
    "turnout": {"ramp": ["#78bf9f", "#4ea585", "#2a8a68", "#156e4f", "#084a33"], "edges": [40, 50, 60, 70]},
    "turnout_change": {"up": ["#78bf9f", "#4ea585", "#2a8a68", "#156e4f"],      # higher turnout
                       "down": ["#ef9f6f", "#e07f48", "#c2602c", "#94431a"],    # lower turnout
                       "edges": [2, 5, 10]},
    "share": {"ramp": ["#b3a9ee", "#8f80e6", "#6250d6", "#4a3aa8", "#33287a"], "edges": [10, 25, 50, 75]},
    "margin_change": {"edges": [5, 10, 20, 30]},
}


def shares_vintage(year):
    """Which precinct map's district shares apply to an election (same rule as normalize.py)."""
    y = int(year)
    return "2024" if y >= 2020 else "2020" if y >= 2012 else "2010"


def build_turnout(keys):
    """Per even-year general election: each precinct's registered voters, ballots cast and
    ballot-method counts (Turnout_Long), plus today's districts allocated with the same
    precinct->district shares used for the vote normalization.

    W5  every precinct's turnout row matches a precinct shape
    W6  per election and district type, district totals == precinct totals (registered,
        ballots, and each method), i.e. the allocation conserves every count
    W7  where a method breakdown is shown, election day + mail + early == ballots cast
    """
    t = pd.read_csv(DATA_DIR / "turnout_long.csv", dtype=str, keep_default_na=False)
    shares = pd.read_csv(NORM / "precinct_district_shares.csv", dtype={"district": str, "vintage": str})
    num = lambda v: int(v) if str(v).strip() not in ("", "nan") else None
    out, problems = {}, []
    for year in TURNOUT_YEARS:
        rows = t[(t["source_file_id"] == f"{year}-GENERAL-PRECINCT") & (t["granularity"] == "precinct")]
        vintage = "2010" if int(year) < 2012 else "2024"
        scheme = rows["column_scheme"].iloc[0]
        precincts = {}
        for r in rows.itertuples():
            pk = key(r.precinct_name)
            if vintage == "2010" and pk == "WORTH 1":
                pk = "WORTH"                       # same name fix as the results (normalize.py)
            if pk not in keys[vintage]:
                problems.append(f"W5 {year}: no shape for turnout precinct {r.precinct_name}")
                continue
            rec = {"name": r.precinct_name, "reg": num(r.registered_voters), "ballots": num(r.public_count)}
            if scheme == METHOD_SCHEME:
                e, a, w = num(r.split1), num(r.split2), num(r.split3)
                if None in (e, a, w) or e + a + w != rec["ballots"]:
                    problems.append(f"W7 {year} {r.precinct_name}: method counts do not add up to ballots")
                rec.update({"e": e, "a": a, "w": w})
            precincts[pk] = rec

        fields = ["reg", "ballots"] + (["e", "a", "w"] if scheme == METHOD_SCHEME else [])
        sh = shares[shares["vintage"] == shares_vintage(year)].copy()
        # the file stores shares rounded to 6 decimals; rescale each precinct's shares to sum
        # to exactly 1 per district type, so the allocation conserves counts to the vote
        sh["share"] = sh["share"] / sh.groupby(["precinct_key", "district_type"])["share"].transform("sum")
        districts = {}
        for dt in DISTRICT_TYPES:
            acc = defaultdict(lambda: defaultdict(float))
            for s in sh[sh["district_type"] == dt].itertuples():
                p = precincts.get(s.precinct_key)
                if not p:
                    continue
                for f in fields:
                    acc[s.district][f] += (p[f] or 0) * s.share
            districts[dt] = {d: {f: round(v[f], 2) for f in fields} for d, v in acc.items()}
            for f in fields:   # W6: allocation conserves every count
                tot_p = sum((p[f] or 0) for p in precincts.values())
                tot_d = sum(v[f] for v in acc.values())
                if abs(tot_p - tot_d) > 0.01:
                    problems.append(f"W6 {year} {dt} {f}: districts {tot_d:.2f} vs precincts {tot_p}")
        county = {f: sum((p[f] or 0) for p in precincts.values()) for f in fields}
        out[year] = {"source": f"{year}-GENERAL-PRECINCT", "shapes": vintage, "scheme": scheme,
                     "method": scheme == METHOD_SCHEME, "provisional": PROVISIONAL.get(f"{year}-GENERAL"),
                     "precincts": precincts, "districts": districts, "county": county}
    return out, problems


# ---- the "Charts & maps" page (site/gallery.html) ---------------------------------------
# Which image goes in which section, in display order. Titles and captions are NOT written
# here: they come from maps/captions.csv (written by make_maps.py), so the page always shows
# exactly the caption that is on the image.
GALLERY = [
    ("2026", "2026 general election (provisional)",
     "2026 had no President, Governor or U.S. Senate race, so it is compared with 2022 on the "
     "statewide offices that were on every ballot in both years. Figures come from the Clerk's "
     "election-night report and are provisional until certified.",
     ["statewide_offices_2022_2026.png", "swing_secretary_of_state_2022_2026.png",
      "margin_secretary_of_state.png", "trend_secretary_of_state.png",
      "margin_us_house_4.png", "trend_us_house_4.png", "turnout_2026_general.png"]),
    ("why-normalize", "Why normalize: a district number is not a place",
     "Each district number using the lines in force at the time (dashed) versus the same number "
     "on today's lines (solid). Boone's lines were redrawn for 2012 and 2022 and numbers were reused "
     "for different areas.",
     ["compare_in_house_president.png", "district_lines_in_house.png", "compare_in_house_us_senate.png",
      "compare_in_senate_president.png", "compare_in_senate_us_senate.png",
      "compare_us_house_president.png", "compare_us_house_us_senate.png"]),
    ("precincts", "Results by precinct",
     "Each precinct colored by its own reported result, with today's Indiana House lines on top.",
     ["margin_president.png", "margin_governor.png", "margin_us_senate.png"]),
    ("districts", "How today's districts voted",
     "Results re-expressed on today's districts (Boone County part of each), election by election.",
     ["trend_president.png", "trend_governor.png", "trend_us_senate.png"]),
    ("change", "Change over time",
     "How each precinct's margin moved across the period.",
     ["precinct_trends_president.png", "swing_president_2012_2024.png", "swing_president_2016_2024.png"]),
    ("turnout", "Turnout",
     "Ballots cast divided by registered voters, as printed in each precinct's report.",
     ["turnout_2024_general.png"]),
]


def build_gallery():
    """Gallery sections with each image's title and caption from maps/captions.csv.

    W4: every image in maps/ appears on the page exactly once, and every listed image exists
    and has a caption - so the website can never silently miss or duplicate a chart."""
    import csv as _csv
    caps = {r["file"]: r for r in _csv.DictReader(open(ROOT / "maps" / "captions.csv"))}
    pngs = {p.name for p in (ROOT / "maps").glob("*.png")}
    listed = [f for *_, files in GALLERY for f in files]
    problems = []
    dupes = sorted({f for f in listed if listed.count(f) > 1})
    if dupes: problems.append(f"listed twice: {dupes}")
    if pngs - set(listed): problems.append(f"in maps/ but not on the page: {sorted(pngs - set(listed))}")
    if set(listed) - pngs: problems.append(f"listed but missing from maps/: {sorted(set(listed) - pngs)}")
    if set(listed) - set(caps): problems.append(f"no caption in captions.csv: {sorted(set(listed) - set(caps))}")
    print(f"  {'PASS' if not problems else 'FAIL'}  W4 every chart on the page exactly once, with its caption")
    if problems:
        fail("; ".join(problems))
    return [{"id": sid, "title": title, "intro": intro,
             "images": [{"file": f, "title": caps[f]["title"], "caption": caps[f]["caption"]} for f in files]}
            for sid, title, intro, files in GALLERY]


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

    data = {"palette": {"blue": BLUE_ARM, "red": RED_ARM, "edges": MARGIN_EDGES, "no_data": NO_DATA,
                        "layers": LAYER_PALETTE},
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

    data["turnout"], t_problems = build_turnout(keys)
    problems += t_problems

    print("CHECKS")
    for name in ("W1 every precinct has a shape", "W2 precinct votes == Results_Long",
                 "W3 district votes == precinct votes",
                 "W5 every turnout precinct has a shape",
                 "W6 district turnout == precinct turnout (every count conserved)",
                 "W7 election day + mail + early == ballots cast"):
        bad = [p for p in problems if p.startswith(name[:2])]
        print(f"  {'PASS' if not bad else 'FAIL'}  {name}" + (f"  ({len(bad)} problems)" if bad else ""))
    if problems:
        print("\n".join("   " + p for p in problems[:20]))
        fail("checks failed - nothing written")

    gallery = build_gallery()      # W4 - stops before anything is written if it fails

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(data, separators=(",", ":")))
    (OUT / "gallery.json").write_text(json.dumps(gallery, indent=1, ensure_ascii=False))
    # Local copy of the images so the page can be previewed with a plain web server. It is
    # git-ignored: the publishing workflow copies maps/ into the site itself, so the images
    # are stored in the repository once.
    import shutil
    shutil.rmtree(SITE / "maps", ignore_errors=True)
    shutil.copytree(ROOT / "maps", SITE / "maps", ignore=shutil.ignore_patterns("*.csv"))
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
