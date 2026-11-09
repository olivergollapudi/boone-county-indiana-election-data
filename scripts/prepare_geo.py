#!/usr/bin/env python3
"""
prepare_geo.py - build the geography inputs for district normalization (Phase 2 setup).

Produces small, Boone-only, committed copies of every geographic input, plus a
provenance file, so the normalization pipeline never depends on files outside the repo.

  source_geo/precincts_<vintage>.geojson   Boone precinct shapes, one file per vintage
        2000, 2010, 2020, 2023, 2024 - clipped from IndianaMap's statewide voting-district
        layers (read from --indianamap-dir, default ~/Downloads). Attributes are copied
        unchanged under a common schema; geometry is copied unchanged.
  source_geo/census_blocks_2010.geojson    Boone Census blocks with total population (pop)
  source_geo/census_blocks_2020.geojson    and voting-age population (vap): TIGER block
        shapes joined to the P.L. 94-171 redistricting counts.
  source_geo/SOURCES.csv                   every input: where it came from, when, sha256.

Downloads (stored in build/downloads/, which is git-ignored; skipped if already there):
  tl_2020_18011_tabblock20.zip  ~1.1 MB  Census TIGER/Line 2020 blocks, Boone County
  tl_2010_18011_tabblock10.zip  ~1.3 MB  Census TIGER/Line 2010 blocks, Boone County
  in2020.pl.zip                 ~33 MB   2020 P.L. 94-171 redistricting data, Indiana
  in2010.pl.zip                 ~25 MB   2010 P.L. 94-171 redistricting data, Indiana
All from www2.census.gov (no API key needed).

Hard checks (the script stops with an error if any fails):
  * precinct counts per vintage: 27 / 54 / 53 / 53 / 53
  * every 2023 and 2024 precinct has House / Senate / Congress codes
  * every TIGER block gets a population row, and vice versa
  * block VAP and population sum exactly to the county's own totals in the same file
  * no block has VAP > population, and the county's adult share is plausible (60-85%)

For eyeballing: Boone County's census population was 56,640 (2010) and 70,812 (2020).

Run (from the repository root):
    python3 scripts/prepare_geo.py
    python3 scripts/prepare_geo.py --indianamap-dir /path/to/geojsons
"""
import argparse, csv, hashlib, io, sys, urllib.request, zipfile
from datetime import date
from pathlib import Path

import geopandas as gpd
import pandas as pd

from paths import ROOT, build_path

GEO_DIR = ROOT / "source_geo"
BOONE = "011"          # Boone County's FIPS code within Indiana (state 18)

# ---- IndianaMap statewide layers: file, county field, name field, id field, district fields
PRECINCT_LAYERS = {
    "2000": ("Voting_Districts_2000.geojson",           "county",     "name",   "vtd",        None),
    "2010": ("Voting_District_Boundaries_2010.geojson", "countyfp10", "name10", "geoid10",    None),
    "2020": ("Voting_District_Boundaries_2020.geojson", "countyfp20", "name20", "geoid20",    None),
    "2023": ("Voting_District_Boundaries_2023.geojson", "county",     "p23",    "p23_stfid",  ("h", "s", "c")),
    "2024": ("Voting_District_Boundaries_2024.geojson", "county",     "p24",    "p24_stfid",  ("h", "s", "c")),
}
EXPECTED_PRECINCTS = {"2000": 27, "2010": 54, "2020": 53, "2023": 53, "2024": 53}

CENSUS = {
    "2020": {
        "tiger": "https://www2.census.gov/geo/tiger/TIGER2020PL/STATE/18_INDIANA/18011/tl_2020_18011_tabblock20.zip",
        "pl":    "https://www2.census.gov/programs-surveys/decennial/2020/data/01-Redistricting_File--PL_94-171/Indiana/in2020.pl.zip",
        "geoid_field": "GEOID20",
    },
    "2010": {
        "tiger": "https://www2.census.gov/geo/tiger/TIGER2010/TABBLOCK/2010/tl_2010_18011_tabblock10.zip",
        "pl":    "https://www2.census.gov/census_2010/01-Redistricting_File--PL_94-171/Indiana/in2010.pl.zip",
        "geoid_field": "GEOID10",
    },
}

sources = []   # rows for SOURCES.csv


def fail(msg):
    sys.exit(f"STOP: {msg}")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url):
    """Fetch url into build/downloads/ once; return the local path."""
    dest = build_path("downloads") / url.rsplit("/", 1)[1]
    dest.parent.mkdir(exist_ok=True)
    if not dest.exists():
        print(f"  downloading {dest.name} ...")
        urllib.request.urlretrieve(url, dest)
    else:
        print(f"  using cached {dest.name}")
    return dest


# ----------------------------------------------------------------------------- precincts
def prepare_precincts(src_dir):
    for vintage, (fname, county_f, name_f, id_f, dist_f) in PRECINCT_LAYERS.items():
        src = src_dir / fname
        if not src.exists():
            fail(f"missing {src} (pass --indianamap-dir)")
        gdf = gpd.read_file(src)
        boone = gdf[gdf[county_f].astype(str).str.strip() == BOONE].copy()
        n = len(boone)
        if n != EXPECTED_PRECINCTS[vintage]:
            fail(f"{vintage}: found {n} Boone precincts, expected {EXPECTED_PRECINCTS[vintage]}")

        out = pd.DataFrame({
            "vintage": vintage,
            "precinct_name_raw": boone[name_f].astype(str).str.strip(),
            "source_id": boone[id_f].astype(str).str.strip(),
        })
        if dist_f:
            h, s, c = dist_f
            for col, f in (("in_house", h), ("in_senate", s), ("us_house", c)):
                vals = boone[f].astype(str).str.strip()
                if (vals == "").any() or vals.isin(["None", "nan"]).any():
                    fail(f"{vintage}: some precincts lack a '{f}' district code")
                out[col] = vals.str.lstrip("0")        # "024" -> "24"
        clipped = gpd.GeoDataFrame(out, geometry=boone.geometry.values, crs=gdf.crs)
        dest = GEO_DIR / f"precincts_{vintage}.geojson"
        clipped.to_file(dest, driver="GeoJSON")
        print(f"  precincts_{vintage}.geojson: {n} precincts")
        sources.append({"file": dest.name, "origin": f"IndianaMap statewide layer '{fname}'",
                        "retrieved": date.fromtimestamp(src.stat().st_mtime).isoformat(),
                        "source_sha256": sha256(src),
                        "note": "Boone County (FIPS 011) features only; geometry and attributes unchanged"})


# ----------------------------------------------------------------------------- census
def read_pl_2020(zpath):
    """2020 P.L. 94-171: pipe-delimited geoheader + segments. Returns
    {geocode: (pop, vap)} for Boone blocks and the county's own (pop, vap) record."""
    with zipfile.ZipFile(zpath) as z:
        geo = io.TextIOWrapper(z.open("ingeo2020.pl"), encoding="latin-1")
        logrec = {}                          # LOGRECNO -> (SUMLEV, GEOCODE)
        for line in geo:
            f = line.rstrip("\n").split("|")
            sumlev, lr, geocode = f[2], f[7], f[9]
            if geocode.startswith("18" + BOONE) and sumlev in ("750", "050"):
                logrec[lr] = (sumlev, geocode)
        pop = _segment_col(z, "in000012020.pl", "|", logrec)   # P1_001N total population
        vap = _segment_col(z, "in000022020.pl", "|", logrec)   # P3_001N population 18+
    return _split_blocks(logrec, pop, vap)


def read_pl_2010(zpath):
    """2010 P.L. 94-171: fixed-width geoheader + comma-delimited segments."""
    with zipfile.ZipFile(zpath) as z:
        geo = io.TextIOWrapper(z.open("ingeo2010.pl"), encoding="latin-1")
        logrec = {}
        for line in geo:
            sumlev, lr = line[8:11], line[18:25]
            state, county = line[27:29], line[29:32]
            if state == "18" and county == BOONE and sumlev in ("750", "050"):
                tract, block = line[54:60], line[61:65]
                geocode = "18" + BOONE + (tract + block if sumlev == "750" else "")
                logrec[lr] = (sumlev, geocode)
        pop = _segment_col(z, "in000012010.pl", ",", logrec)   # P0010001 total population
        vap = _segment_col(z, "in000022010.pl", ",", logrec)   # P0030001 population 18+
    return _split_blocks(logrec, pop, vap)


def _segment_col(z, name, sep, logrec):
    """First data column (field 5, after FILEID,STUSAB,CHARITER,CIFSN,LOGRECNO) by LOGRECNO."""
    vals = {}
    for line in io.TextIOWrapper(z.open(name), encoding="latin-1"):
        f = line.rstrip("\n").split(sep)
        if f[4] in logrec:
            vals[f[4]] = int(f[5])
    return vals


def _split_blocks(logrec, pop, vap):
    blocks, county = {}, None
    for lr, (sumlev, geocode) in logrec.items():
        if sumlev == "750":
            blocks[geocode] = (pop[lr], vap[lr])
        else:
            county = (pop[lr], vap[lr])
    if county is None:
        fail("county-level record not found in the P.L. file")
    return blocks, county


def prepare_blocks(year):
    cfg = CENSUS[year]
    tiger, pl = download(cfg["tiger"]), download(cfg["pl"])
    blocks, (county_pop, county_vap) = (read_pl_2020 if year == "2020" else read_pl_2010)(pl)

    shapes = gpd.read_file(tiger)
    shapes = shapes[[cfg["geoid_field"], "geometry"]].rename(columns={cfg["geoid_field"]: "geoid"})
    ids_shape, ids_pl = set(shapes["geoid"]), set(blocks)
    if ids_shape != ids_pl:
        fail(f"{year}: {len(ids_shape - ids_pl)} TIGER blocks lack counts, "
             f"{len(ids_pl - ids_shape)} counted blocks lack shapes")
    shapes["pop"] = shapes["geoid"].map(lambda g: blocks[g][0])
    shapes["vap"] = shapes["geoid"].map(lambda g: blocks[g][1])

    if shapes["pop"].sum() != county_pop or shapes["vap"].sum() != county_vap:
        fail(f"{year}: block sums (pop {shapes['pop'].sum()}, vap {shapes['vap'].sum()}) "
             f"!= county record (pop {county_pop}, vap {county_vap})")
    # The sum check proves the block<->county join, not that we read the right COLUMN
    # (any column sums consistently). Voting-age population can never exceed total
    # population, and the adult share of a county is always well inside 60-85%.
    if (shapes["vap"] > shapes["pop"]).any():
        fail(f"{year}: some blocks have vap > pop - wrong column read from the P.L. file")
    if not 0.60 <= county_vap / county_pop <= 0.85:
        fail(f"{year}: adult share {county_vap / county_pop:.1%} is implausible - wrong column?")

    dest = GEO_DIR / f"census_blocks_{year}.geojson"
    shapes.to_crs("EPSG:4326").to_file(dest, driver="GeoJSON")
    print(f"  census_blocks_{year}.geojson: {len(shapes):,} blocks, "
          f"pop {county_pop:,}, vap {county_vap:,}  (block sums = county record)")
    for url, path in ((cfg["tiger"], tiger), (cfg["pl"], pl)):
        sources.append({"file": dest.name, "origin": url, "retrieved": date.today().isoformat(),
                        "source_sha256": sha256(path), "note": "Boone County blocks only"})


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--indianamap-dir", type=Path, default=Path.home() / "Downloads")
    args = ap.parse_args()
    GEO_DIR.mkdir(exist_ok=True)

    print("Precinct layers (IndianaMap):")
    prepare_precincts(args.indianamap_dir)
    print("Census blocks:")
    for year in ("2010", "2020"):
        prepare_blocks(year)

    with open(GEO_DIR / "SOURCES.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["file", "origin", "retrieved", "source_sha256", "note"])
        w.writeheader(); w.writerows(sources)
    print(f"Wrote {GEO_DIR / 'SOURCES.csv'}")


if __name__ == "__main__":
    main()
