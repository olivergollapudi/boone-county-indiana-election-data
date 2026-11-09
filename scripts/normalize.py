#!/usr/bin/env python3
"""
normalize.py - re-express every election's precinct results on TODAY's districts.

"Today's districts" = the 2021-enacted Indiana House, Indiana Senate and U.S. House
lines, read from the 2024 precinct layer (every 2024 precinct carries its district codes
and sits wholly inside one district of each type).

METHOD (decided in Phase 1 - see METHODOLOGY.md for the plain-English version)
  Each election is matched to the precinct map in force at the time, as closely as the
  available maps allow:

    election years   precinct shapes used        geometry_basis
    2020 - 2026      2024 layer (= 2020 = 2023)  as_of_election
    2012 - 2018      2020 layer                  assumed_2020_shapes  (same 53 names; no
                                                  map from those years exists)
    2010 - 2011      2010 layer                  as_of_election
    2008             2010 layer                  assumed_2010_shapes  (no 2008 map exists)

  For each old precinct, its votes are split across today's districts in proportion to
  where its adults live: Census blocks (2010 blocks for the 2010 layer, 2020 blocks
  otherwise) are assigned to the precinct and to the district they overlap most, and
  share(precinct, district) = voting-age population in both / voting-age population of
  the precinct. A precinct with no adults at all falls back to area shares (flagged).
  Votes are never rounded inside the pipeline; outputs carry 4 decimals.

VALIDATION - the script exits non-zero (and writes nothing to data/) if ANY of these fail:
  V1  every precinct's shares sum to 1 for each district type
  V2  every election-precinct either matches a precinct shape or is listed in set_aside
  V3  for every election x contest x candidate and every district type:
        votes allocated to districts + votes set aside == votes in Results_Long
  V4  2024-layer precincts get share 1 to the district their own attributes name
  V5  for text-based elections under the current map (2022+), the district number in
      each precinct's own State Rep / State Senate / U.S. Rep contest matches the GIS
      district (two independent sources agreeing). OCR elections: reported, not enforced.

OUTPUTS (data/normalized/)
  results_by_current_district.csv   the normalized results (one row per election x
                                    district x contest x candidate)
  precinct_district_shares.csv      every precinct-to-district share and how it was made
  election_precinct_map.csv         which precinct shape each reported precinct used
  set_aside.csv                     result rows that could not be allocated, with reason
  normalization_validation.csv      every check, its scope, and pass/fail
  current_districts.geojson         today's district outlines within Boone County

Run (from the repository root):
    python3 scripts/normalize.py
"""
import re, sys
from collections import defaultdict

import geopandas as gpd
import pandas as pd

from paths import DATA_DIR, ROOT

GEO = ROOT / "source_geo"
OUT = DATA_DIR / "normalized"
AREA_CRS = "EPSG:26916"            # UTM zone 16N (metres) - for overlap areas
DISTRICT_TYPES = {"in_house": "Indiana House", "in_senate": "Indiana Senate", "us_house": "U.S. House"}
STRADDLE = 0.95                    # a precinct is flagged if < 95% of its adults are in one district
OCR_ELECTIONS = {"2008-GENERAL", "2022-PRIMARY"}   # labels not yet verified (see README "Known issues")

RESULT_FILES = ["results_long_all.csv",
                "results_long_2008-general-precinct-geom-clean.csv",
                "results_long_2022-primary-precinct-geom-clean.csv"]

# Explicit, reviewed exceptions to plain name matching. Nothing else is guessed.
NAME_FIXES = {
    # (election, normalized name as reported) -> normalized name on the map
    ("2008-GENERAL", "GENTER 4"): "CENTER 4",     # OCR typo; precinct ID 04 = Center 4
    ("2010-GENERAL", "WORTH 1"): "WORTH",         # 2010 Census map calls it WORTH
    ("2010-PRIMARY", "WORTH 1"): "WORTH",
    ("2011-GENERAL", "WORTH 1"): "WORTH",
}
# Map shapes that are pieces of one reported precinct (Whitestown parts of Eagle precincts
# on the 2010 Census map). Merged into their parent before computing shares.
MERGE_SUFFIX = " WHITESTOWN"


def fail(msg):
    sys.exit(f"STOP: {msg}")


def key(name):
    """Normalize a precinct name for matching: 'Center 01', 'CENTER 1', 'Worth1',
    'EAGLE 10 (ZIONSVILLE)' -> 'CENTER 1', 'WORTH 1', 'EAGLE 10'."""
    s = str(name).upper().strip()
    s = re.sub(r"\s*\(.*?\)\s*", " ", s)          # drop "(ZIONSVILLE)"-style notes
    s = re.sub(r"([A-Z])(\d)", r"\1 \2", s)        # WORTH1 -> WORTH 1
    s = re.sub(r"\s+0*(\d+)\s*$", r" \1", s)       # trailing number without zero-padding
    return re.sub(r"\s+", " ", s).strip()


def election_of(source_file_id):
    return source_file_id.replace("-PRECINCT", "")


def vintage_for(election):
    y = int(election[:4])
    if y >= 2020: return "2024", "as_of_election"
    if y >= 2012: return "2020", "assumed_2020_shapes"
    if y >= 2010: return "2010", "as_of_election"
    return "2010", "assumed_2010_shapes"


# ----------------------------------------------------------------------------- geography
def read_geo(name):
    """Read a source_geo layer in metres, repairing any invalid polygons first."""
    g = gpd.read_file(GEO / name).to_crs(AREA_CRS)
    g["geometry"] = g.geometry.make_valid()
    return g


def current_districts():
    p = read_geo("precincts_2024.geojson")
    out = []
    for dt in DISTRICT_TYPES:
        d = p.dissolve(by=dt, as_index=False)[[dt, "geometry"]].rename(columns={dt: "district"})
        d["district_type"] = dt
        out.append(d)
    return gpd.GeoDataFrame(pd.concat(out, ignore_index=True), crs=AREA_CRS)


def largest_overlap(blocks, zones, zone_col):
    """Assign each block to the zone it overlaps most. Returns {block geoid: zone}."""
    inter = gpd.overlay(blocks[["geoid", "geometry"]], zones[[zone_col, "geometry"]],
                        how="intersection", keep_geom_type=True)
    inter["a"] = inter.geometry.area
    best = inter.sort_values("a").groupby("geoid").tail(1)
    return dict(zip(best["geoid"], best[zone_col]))


def shares_for_vintage(vintage, districts):
    """share(precinct, district) for every precinct of one map vintage."""
    prec = read_geo(f"precincts_{vintage}.geojson")
    prec["pkey"] = prec["precinct_name_raw"].map(key).str.replace(MERGE_SUFFIX + "$", "", regex=True)
    merged_pieces = int((prec["precinct_name_raw"].str.upper().str.endswith(MERGE_SUFFIX)).sum())
    prec = prec.dissolve(by="pkey", as_index=False)[["pkey", "geometry"]]

    year = "2010" if vintage == "2010" else "2020"
    blocks = read_geo(f"census_blocks_{year}.geojson")
    b2p = largest_overlap(blocks, prec, "pkey")
    unassigned = blocks[~blocks["geoid"].isin(b2p)]
    if unassigned["vap"].sum() > 0:
        fail(f"vintage {vintage}: {len(unassigned)} blocks ({unassigned['vap'].sum()} adults) "
             f"fall outside every precinct")

    rows = []
    for dt in DISTRICT_TYPES:
        dz = districts[districts["district_type"] == dt]
        b2d = largest_overlap(blocks, dz, "district")
        bl = blocks.assign(pkey=blocks["geoid"].map(b2p), district=blocks["geoid"].map(b2d))
        # area shares straight from precinct x district geometry (reference + fallback)
        pd_inter = gpd.overlay(prec, dz[["district", "geometry"]], how="intersection",
                               keep_geom_type=True)
        pd_inter["a"] = pd_inter.geometry.area
        area = pd_inter.groupby(["pkey", "district"])["a"].sum()
        area_share = area / area.groupby(level=0).transform("sum")
        vap = bl.groupby(["pkey", "district"])["vap"].sum()
        vap_tot = bl.groupby("pkey")["vap"].sum()
        for pk in prec["pkey"]:
            use_area = vap_tot.get(pk, 0) == 0
            src = area_share.loc[pk] if use_area else (vap.loc[pk] / vap_tot[pk])
            for dist, s in src.items():
                if s <= 0: continue
                rows.append({"vintage": vintage, "precinct_key": pk, "district_type": dt,
                             "district": str(dist), "share": float(s),
                             "share_area": float(area_share.get((pk, dist), 0.0)),
                             "vap_in_part": int(vap.get((pk, dist), 0)),
                             "weight_basis": "area_fallback" if use_area else f"vap_{year}"})
    print(f"  vintage {vintage}: {len(prec)} precincts "
          f"({merged_pieces} map pieces merged into parents), {year} blocks")
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- results
def load_results():
    frames = [pd.read_csv(DATA_DIR / f, dtype=str).fillna("") for f in RESULT_FILES]
    r = pd.concat(frames, ignore_index=True)
    r["election"] = r["source_file_id"].map(election_of)
    r["votes"] = pd.to_numeric(r["total"], errors="coerce")
    return r


def ballot_district_check(results, gis):
    """V5: district number printed on each precinct's own ballot vs the GIS district.
    gis = {(precinct_key, district_type): district} from the 2024 layer's own attributes."""
    pats = {"in_house":  re.compile(r"STATE\s+REP\w*\.?\s+(?:DIST\w*\.?\s*)?(\d+)"),
            "in_senate": re.compile(r"STATE\s+SEN\w*\.?\s+(?:DIST\w*\.?\s*)?(\d+)"),
            "us_house":  re.compile(r"(?:U\.?\s*S\.?|UNITED\s+STATES)\s+REP\w*\.?\s+(?:DIST\w*\.?\s*)?(\d+)")}
    cur = results[results["election"].str[:4].astype(int) >= 2022]
    checked, mismatches = 0, []
    for (el, pk, office) in cur[["election", "precinct_key", "office"]].drop_duplicates().itertuples(index=False):
        for dt, pat in pats.items():
            m = pat.search(office.upper())
            if not m: continue
            checked += 1
            if gis.get((pk, dt)) != m.group(1).lstrip("0"):
                mismatches.append({"election": el, "precinct_key": pk, "district_type": dt,
                                   "ballot_district": m.group(1).lstrip("0"),
                                   "gis_district": gis.get((pk, dt)), "office": office})
    return checked, pd.DataFrame(mismatches)


# ----------------------------------------------------------------------------- main
def main():
    print("Geography:")
    districts = current_districts()
    shares = pd.concat([shares_for_vintage(v, districts) for v in ("2010", "2020", "2024")],
                       ignore_index=True)
    checks = []

    def check(name, scope, ok, detail=""):
        checks.append({"check": name, "scope": scope, "result": "PASS" if ok else "FAIL",
                       "detail": detail})

    # V1 shares sum to 1
    sums = shares.groupby(["vintage", "precinct_key", "district_type"])["share"].sum()
    bad = sums[(sums - 1).abs() > 1e-9]
    check("V1 shares sum to 1", f"{len(sums)} precinct x district-type pairs", bad.empty,
          "; ".join(f"{k}: {v:.6f}" for k, v in bad.head(5).items()))

    # V4 2024 precincts nest exactly in their own attribute districts
    p24 = gpd.read_file(GEO / "precincts_2024.geojson")
    p24["pkey"] = p24["precinct_name_raw"].map(key)
    gis_2024 = {(r.pkey, dt): getattr(r, dt) for r in p24.itertuples() for dt in DISTRICT_TYPES}
    s24 = shares[shares.vintage == "2024"].set_index(["precinct_key", "district_type", "district"])["share"]
    v4_bad = [(r.pkey, dt) for r in p24.itertuples() for dt in DISTRICT_TYPES
              if abs(s24.get((r.pkey, dt, getattr(r, dt)), 0) - 1) > 1e-9]
    check("V4 2024 precincts nest in their own districts", f"{len(p24)} precincts x 3 types",
          not v4_bad, "; ".join(map(str, v4_bad[:5])))

    print("Results:")
    results = load_results()
    is_prec = results["granularity"] == "precinct"
    set_aside = results[~is_prec].assign(reason="countywide-only row (no precinct to allocate)")
    pr = results[is_prec].copy()
    nonnum = pr["votes"].isna()
    set_aside = pd.concat([set_aside, pr[nonnum].assign(reason="non-numeric vote total")])
    pr = pr[~nonnum]

    # match each reported precinct to a precinct shape
    emap = pr[["election", "precinct_id", "precinct_name"]].drop_duplicates().copy()
    emap["vintage"], emap["geometry_basis"] = zip(*emap["election"].map(vintage_for))
    emap["name_key"] = emap["precinct_name"].map(key)
    emap["precinct_key"] = [NAME_FIXES.get((e, k), k) for e, k in zip(emap.election, emap.name_key)]
    emap["match"] = ["name_fix" if (e, k) in NAME_FIXES else "name" for e, k in zip(emap.election, emap.name_key)]
    known = set(zip(shares.vintage, shares.precinct_key))
    emap["matched"] = [(v, k) in known for v, k in zip(emap.vintage, emap.precinct_key)]
    unmatched = emap[~emap.matched]
    # one row per (election, reported name) so the merge can never duplicate result rows
    emap_by_name = emap.drop_duplicates(["election", "precinct_name"])
    pr = pr.merge(emap_by_name[["election", "precinct_name", "vintage", "precinct_key", "matched",
                                "geometry_basis"]], on=["election", "precinct_name"], validate="many_to_one")
    set_aside = pd.concat([set_aside, pr[~pr.matched].assign(reason="no matching precinct shape")])
    pr = pr[pr.matched]
    check("V2 every reported precinct matched or set aside",
          f"{len(emap)} election-precincts", True,
          f"{len(unmatched)} set aside: " + "; ".join(f"{r.election} {r.precinct_name}" for r in unmatched.itertuples()))

    # allocate
    alloc = pr.merge(shares, on=["vintage", "precinct_key"])
    alloc["alloc_votes"] = alloc["votes"] * alloc["share"]
    alloc["straddles"] = alloc.groupby(["election", "precinct_key", "district_type"])["share"].transform("max") < STRADDLE
    gkeys = ["election", "office", "contest_party", "candidate", "party"]

    # V3 conservation: allocated + set aside == source, per contest-candidate and district type
    src = results[results["votes"].notna()].groupby(gkeys)["votes"].sum()
    aside = (set_aside[set_aside["votes"].notna()].groupby(gkeys)["votes"].sum()
             if len(set_aside) else pd.Series(dtype=float))
    worst, n_bad = 0.0, 0
    for dt in DISTRICT_TYPES:
        got = alloc[alloc.district_type == dt].groupby(gkeys)["alloc_votes"].sum()
        diff = (got.reindex(src.index, fill_value=0) + aside.reindex(src.index, fill_value=0) - src).abs()
        worst, n_bad = max(worst, diff.max()), n_bad + int((diff > 1e-6).sum())
    check("V3 votes conserved (allocated + set aside = Results_Long)",
          f"{len(src)} election x contest x candidate, x 3 district types", n_bad == 0,
          f"largest difference {worst:.2e} votes; {n_bad} failures")

    # V5 ballot vs GIS
    checked, mism = ballot_district_check(pr, gis_2024)
    text_mism = mism[~mism["election"].isin(OCR_ELECTIONS)] if len(mism) else mism
    check("V5 ballot district = GIS district (text elections, 2022+)",
          f"{checked} precinct x district contests checked", text_mism.empty,
          f"{len(text_mism)} text mismatches; {len(mism) - len(text_mism)} in OCR elections (reported only)")

    # ---- report validation; stop before writing data if anything failed
    vdf = pd.DataFrame(checks)
    print("\nVALIDATION")
    for c in checks:
        print(f"  {c['result']}  {c['check']}  [{c['scope']}]  {c['detail']}")
    if (vdf["result"] == "FAIL").any():
        if len(mism): print("\nBallot/GIS mismatches:\n" + mism.head(20).to_string(index=False))
        fail("validation failed - nothing written to data/normalized/")

    # ---- outputs
    OUT.mkdir(exist_ok=True)
    # contest coverage per district: share of the district's precinct-weight that had the contest
    elec_w = alloc.drop_duplicates(["election", "precinct_key", "district_type", "district"]) \
                  .groupby(["election", "district_type", "district"])["share"].sum()
    cont_w = alloc.drop_duplicates(["election", "office", "contest_party", "precinct_key",
                                    "district_type", "district"]) \
                  .groupby(["election", "office", "contest_party", "district_type", "district"])["share"].sum()
    alloc["split_votes"] = alloc["alloc_votes"].where(alloc["share"] < 1, 0.0)
    alloc["straddle_votes"] = alloc["alloc_votes"].where(alloc["straddles"], 0.0)
    out = (alloc.groupby(["election", "district_type", "district"] + gkeys[1:])
                .agg(votes=("alloc_votes", "sum"),
                     n_precincts=("precinct_key", "nunique"),
                     votes_from_split_precincts=("split_votes", "sum"),
                     votes_from_straddling=("straddle_votes", "sum"),
                     geometry_basis=("geometry_basis", "first"))
                .reset_index())
    cov = cont_w.reset_index(name="cw").merge(elec_w.reset_index(name="ew"),
                                              on=["election", "district_type", "district"])
    cov["contest_coverage"] = cov["cw"] / cov["ew"]
    out = out.merge(cov[["election", "office", "contest_party", "district_type", "district", "contest_coverage"]],
                    on=["election", "office", "contest_party", "district_type", "district"])
    out["data_quality"] = out["election"].map(lambda e: "ocr_labels_unverified" if e in OCR_ELECTIONS else "verified")
    out["provisional"] = out["election"].str.startswith("2026")
    out["district_name"] = out["district_type"].map(DISTRICT_TYPES) + " " + out["district"]
    for c in ("votes", "votes_from_split_precincts", "votes_from_straddling", "contest_coverage"):
        out[c] = out[c].round(4)
    out = out[["election", "district_type", "district", "district_name", "office", "contest_party",
               "candidate", "party", "votes", "n_precincts", "contest_coverage",
               "votes_from_split_precincts", "votes_from_straddling", "geometry_basis",
               "data_quality", "provisional"]].sort_values(["election", "district_type", "district", "office"])
    out.to_csv(OUT / "results_by_current_district.csv", index=False)

    shares.assign(straddles=shares.groupby(["vintage", "precinct_key", "district_type"])["share"]
                  .transform("max") < STRADDLE) \
          .round({"share": 6, "share_area": 6}) \
          .to_csv(OUT / "precinct_district_shares.csv", index=False)
    emap.drop(columns=["matched"]).to_csv(OUT / "election_precinct_map.csv", index=False)
    set_aside.drop(columns=["votes"], errors="ignore").to_csv(OUT / "set_aside.csv", index=False)
    vdf.to_csv(OUT / "normalization_validation.csv", index=False)
    districts.to_crs("EPSG:4326").to_file(OUT / "current_districts.geojson", driver="GeoJSON")

    strad = shares[shares.groupby(["vintage", "precinct_key", "district_type"])["share"].transform("max") < STRADDLE]
    print(f"\nWrote {OUT}/  ({len(out):,} normalized rows)")
    print(f"  straddling precincts (<{STRADDLE:.0%} of adults in one district): "
          f"{strad.groupby(['vintage', 'district_type'])['precinct_key'].nunique().to_dict()}")
    print(f"  set aside: {len(set_aside)} rows ({set_aside['reason'].value_counts().to_dict()})")


if __name__ == "__main__":
    main()
