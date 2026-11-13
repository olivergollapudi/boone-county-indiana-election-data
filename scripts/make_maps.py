#!/usr/bin/env python3
"""
make_maps.py - the static map set (PNGs for the README and for sharing).

Every number drawn comes straight from the published tables:
  * precinct colors  <- Results_Long (data/results_long_all.csv) and Turnout_Long
  * district trends  <- data/normalized/results_by_current_district.csv
  * shapes           <- source_geo/ (precincts) and data/normalized/current_districts.geojson
Every map carries a caption: source, election, method, and a one-line caveat.

Maps written to maps/:
  margin_president.png    precinct two-party margin, 2012 / 2016 / 2020 / 2024
  margin_governor.png     same, Governor
  margin_us_senate.png    same, U.S. Senate, 2010 - 2024
  trend_president.png     small multiples: each current district's margin over time
  trend_governor.png
  trend_us_senate.png
  swing_president_2016_2024.png   change in precinct margin, 2016 -> 2024
  swing_president_2012_2024.png   change in precinct margin over the whole period, 2012 -> 2024
  precinct_trends_president.png   every precinct's margin 2012 -> 2024, one small panel each
  turnout_2024_general.png        precinct turnout, 2024 general
  compare_<type>_<contest>.png    AS DRAWN vs NORMALIZED: each district number's margin
                                  using the lines in force at the time (as reported) vs
                                  today's lines - why old district results don't describe
                                  today's districts. <type> = in_house / in_senate / us_house;
                                  <contest> = president / us_senate.
  district_lines_in_house.png     how the Indiana House lines in Boone moved: 2002 map,
                                  2012 map, today's map
  captions.csv            the caption of every map (for alt text / README)

The as-drawn figures come from data/normalized/results_by_district_as_drawn.csv
(scripts/as_drawn.py), which assigns each precinct to the district printed on its own
ballot at the time - exact, no estimation.

Decisions (Phase 3): 2008 is left out until the OCR label fix lands; precinct detail
with today's Indiana House lines on top; margins labeled with party names spelled out;
diverging blue (Democratic) / red (Republican) with a neutral gray midpoint.

Two-party margin = (Republican - Democratic) / (Republican + Democratic) x 100, from the
candidates with party R and D. Third-party and write-in votes are not in the margin.

Run (from the repository root):
    python3 scripts/make_maps.py
"""
import csv, re

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.patches import Patch
import pandas as pd

from paths import DATA_DIR, ROOT
from provisional import is_provisional


def provisional_note(years):
    """Caption sentence naming any provisional (not yet certified) general elections shown."""
    ys = [y for y in years if is_provisional(f"{y}-GENERAL")]
    return f" {', '.join(ys)} results are provisional (not yet certified)." if ys else ""

GEO, NORM, OUT = ROOT / "source_geo", DATA_DIR / "normalized", ROOT / "maps"

# ---- contests and the elections each map covers (2008 deliberately excluded) -----------
CONTESTS = {
    "president": ("President", r"^PRESIDENT", ["2012", "2016", "2020", "2024"]),
    "governor":  ("Governor",  r"^GOVERNOR",  ["2012", "2016", "2020", "2024"]),
    "us_senate": ("U.S. Senate", r"^UNITED STATES SENATOR", ["2010", "2012", "2016", "2018", "2022", "2024"]),
    # midterm statewide office on every ballot every four years - the long-run comparison for
    # years with no President / Governor / U.S. Senate race (e.g. 2026)
    "secretary_of_state": ("Secretary of State", r"^SECRETARY OF STATE",
                           ["2010", "2014", "2018", "2022", "2026"]),
    # one congressional district covers all of Boone only under today's map (2022+);
    # before that Boone was split between Districts 4 and 5
    "us_house_4": ("U.S. House District 4", r"^(?:UNITED STATES|U\.?\s?S\.?)\s+REP\w*\.?\s+DISTRICT\s+4$",
                   ["2022", "2024", "2026"]),
}

# ---- colors (dataviz reference palette: diverging blue <-> red, gray midpoint) ----------
INK, INK_2, INK_3 = "#0b0b0b", "#52514e", "#8a8984"
SURFACE, NEUTRAL, NO_DATA = "#fcfcfb", "#f0efec", "#dddcd7"
# Each ramp passes the dataviz validator (--ordinal: one hue, monotone lightness, visible
# step gaps, lightest step >= 2:1 against the surface so the closest bins stay visible).
BLUE_ARM = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281"]   # light -> dark
RED_ARM  = ["#ee9b93", "#e8716c", "#e34948", "#bf3534", "#8f2222"]   # light -> dark
MARGIN_EDGES = [5, 10, 20, 30]          # points; bins 0-5, 5-10, 10-20, 20-30, 30+
SWING_EDGES = [2, 5, 10, 15]
TURNOUT_EDGES = [65, 70, 75, 80]        # bins: under 65, 65-70, 70-75, 75-80, 80+
TURNOUT_RAMP = ["#78bf9f", "#4ea585", "#2a8a68", "#156e4f", "#084a33"]  # one hue (green, not a party color)

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "text.color": INK,
                     "axes.edgecolor": INK_3, "axes.labelcolor": INK_2,
                     "xtick.color": INK_2, "ytick.color": INK_2,
                     "figure.facecolor": SURFACE, "axes.facecolor": SURFACE})

captions = []


# ----------------------------------------------------------------------------- helpers
def key(name):
    """Same precinct-name normalization as normalize.py."""
    s = str(name).upper().strip()
    s = re.sub(r"\s*\(.*?\)\s*", " ", s)
    s = re.sub(r"([A-Z])(\d)", r"\1 \2", s)
    s = re.sub(r"\s+0*(\d+)\s*$", r" \1", s)
    return re.sub(r"\s+", " ", s).strip()


def party_label(m, unit="", lead="+"):
    if pd.isna(m): return "no votes"
    if abs(m) < 0.05: return "Even"
    side = "Republican" if m > 0 else "Democratic"
    return f"{side} {lead}{abs(m):.1f}{unit}"


def diverging(edges, low_word="Democratic", high_word="Republican", fmt="{}"):
    """Symmetric binned diverging scale. Returns (cmap, norm, legend handles)."""
    bounds = [-1000] + [-e for e in reversed(edges)] + [0] + edges + [1000]
    colors = list(reversed(BLUE_ARM)) + RED_ARM
    cmap, norm = ListedColormap(colors), BoundaryNorm(bounds, len(colors))
    labels, lo = [], [0] + edges
    for i, a in enumerate(lo):
        b = edges[i] if i < len(edges) else None
        labels.append(f"{fmt.format(a)}–{fmt.format(b)}" if b is not None else f"{fmt.format(a)}+")
    handles = ([Patch(fc=c, label=f"{high_word} {l}") for c, l in zip(reversed(RED_ARM), reversed(labels))] +
               [Patch(fc=c, label=f"{low_word} {l}") for c, l in zip(BLUE_ARM, labels)])
    return cmap, norm, handles


def load_results():
    files = ["results_long_all.csv"]          # 2008 (OCR) and the 2022 primary are not mapped
    r = pd.concat([pd.read_csv(DATA_DIR / f, dtype=str).fillna("") for f in files])
    r["election"] = r["source_file_id"].str.replace("-PRECINCT", "", regex=False)
    r["votes"] = pd.to_numeric(r["total"], errors="coerce")
    return r[r["granularity"] == "precinct"]


def contest_rows(results, year, pattern):
    el = results[results["election"] == f"{year}-GENERAL"]
    hit = el[el["office"].str.upper().str.contains(pattern, regex=True)]
    offices = hit["office"].unique()
    if len(offices) != 1:
        raise SystemExit(f"STOP: {year} {pattern}: expected one office, found {list(offices)}")
    return hit, offices[0]


def precinct_margins(rows):
    two = rows[rows["party"].isin(["R", "D"])]
    p = two.pivot_table(index="precinct_name", columns="party", values="votes", aggfunc="sum").fillna(0)
    p["margin"] = 100 * (p.get("R", 0) - p.get("D", 0)) / (p.get("R", 0) + p.get("D", 0))
    return p.reset_index()


def shapes_for(year):
    """Precinct shapes used for an election (same rule as normalize.py) + its caveat."""
    y = int(year)
    if y >= 2020: return "2024", "precinct shapes as of the election"
    if y >= 2012: return "2020", "precinct shapes assumed equal to 2020's (no map from that year)"
    return "2010", "2010 Census precinct shapes"


def precinct_layer(vintage):
    g = gpd.read_file(GEO / f"precincts_{vintage}.geojson").to_crs("EPSG:26916")
    g["pkey"] = g["precinct_name_raw"].map(key).str.replace(" WHITESTOWN$", "", regex=True)
    return g.dissolve(by="pkey", as_index=False)[["pkey", "geometry"]]


def house_lines():
    d = gpd.read_file(NORM / "current_districts.geojson").to_crs("EPSG:26916")
    return d[d["district_type"] == "in_house"]


def label_point(geom):
    """The point deepest inside a district's largest piece, so the label never sits on a
    border (a plain centroid can fall outside an irregular district)."""
    from shapely.ops import polylabel
    poly = max(getattr(geom, "geoms", [geom]), key=lambda g: g.area)
    return polylabel(poly, tolerance=10)


def plot_if_any(gdf, ax, **kw):
    if len(gdf): gdf.plot(ax=ax, **kw)


def draw_districts(ax, house):
    house.boundary.plot(ax=ax, color=INK, linewidth=1.4)
    for r in house.itertuples():
        pt = label_point(r.geometry)
        ax.annotate(f"House {r.district}", (pt.x, pt.y), ha="center", va="center", fontsize=8,
                    fontweight="bold", color=INK,
                    bbox=dict(boxstyle="round,pad=0.2", fc=SURFACE, ec="none", alpha=0.85))


def finish(fig, name, title, caption):
    import textwrap
    fig.suptitle(title, x=0.02, ha="left", fontsize=13, fontweight="bold", color=INK)
    # wrap to the figure's width (~15 characters per inch at 7.5 pt) so no line runs off the edge
    wrapped = textwrap.fill(caption, width=int(fig.get_figwidth() * 15))
    # hang the caption BELOW the figure area (y < 0); the tight save expands the canvas to
    # include it, so it can never collide with tick labels however many lines it wraps to
    fig.text(0.02, -0.01, wrapped, ha="left", va="top", fontsize=7.5, color=INK_2)
    OUT.mkdir(exist_ok=True)
    fig.savefig(OUT / f"{name}.png", dpi=170, facecolor=SURFACE, bbox_inches="tight", pad_inches=0.25)
    plt.close(fig)
    captions.append({"file": f"{name}.png", "title": title, "caption": caption})
    print(f"  maps/{name}.png")


SOURCE = "Source: Boone County Clerk precinct results (Results_Long), github.com/olivergollapudi/boone-county-indiana-election-data."
MARGIN_METHOD = "Margin = (Republican − Democratic) ÷ (Republican + Democratic) votes."


# ----------------------------------------------------------------------------- maps
def margin_maps(results, house):
    cmap, norm, handles = diverging(MARGIN_EDGES)
    for slug, (label, pattern, years) in CONTESTS.items():
        n = len(years)
        cols = 3 if n > 4 else 2
        rows_ = (n + cols - 1) // cols
        # size each panel to Boone County's own width:height so the map fills its panel, and
        # let constrained layout place panel titles / legend (fixed spacing made them collide)
        minx, miny, maxx, maxy = house.total_bounds
        aspect = (maxx - minx) / (maxy - miny)
        pw = 4.2                                              # panel width, inches
        fig, axes = plt.subplots(rows_, cols, layout="constrained",
                                 figsize=(pw * cols + 2.4, rows_ * (pw / aspect + 0.45) + 0.6))
        axes = axes.ravel()
        assumed = []
        for ax, year in zip(axes, years):
            rows, office = contest_rows(results, year, pattern)
            m = precinct_margins(rows)
            m["pkey"] = m["precinct_name"].map(key).replace({"WORTH 1": "WORTH"} if year < "2012" else {})
            vintage, basis = shapes_for(year)
            if "assumed" in basis: assumed.append(year)
            g = precinct_layer(vintage).merge(m, on="pkey", how="left")
            plot_if_any(g[g["margin"].isna()], ax, color=NO_DATA, edgecolor=SURFACE, linewidth=0.4)
            plot_if_any(g[g["margin"].notna()], ax, column="margin", cmap=cmap, norm=norm,
                        edgecolor=SURFACE, linewidth=0.4)
            draw_districts(ax, house)
            R, D = rows[rows.party == "R"]["votes"].sum(), rows[rows.party == "D"]["votes"].sum()
            ax.set_title(f"{year}  ·  county: {party_label(100 * (R - D) / (R + D))}",
                         loc="left", fontsize=10, color=INK)
            ax.set_axis_off()
        for ax in axes[n:]: ax.set_axis_off()
        fig.legend(handles=handles, loc="outside right center", frameon=False, fontsize=8,
                   title="Two-party margin (points)", title_fontsize=8.5)
        caveat = ((f"Caveat: {', '.join(assumed)} use precinct shapes assumed equal to 2020's; "
                   if assumed else "Caveat: ") + "lines show today's Indiana House districts; 2008 omitted (scanned data under review)."
                  + provisional_note(years))
        finish(fig, f"margin_{slug}", f"{label}: two-party margin by precinct, Boone County",
               f"{SOURCE} Elections: {', '.join(y + ' general' for y in years)}. "
               f"Method: {MARGIN_METHOD} Each precinct colored by its own reported result. {caveat}")


def trend_maps():
    n = pd.read_csv(NORM / "results_by_current_district.csv", dtype={"district": str})
    n = n[(n["district_type"].isin(["in_house", "in_senate", "us_house"])) & n["party"].isin(["R", "D"])]
    panels = [("in_house", d) for d in ["24", "25", "28", "41"]] + [("in_senate", d) for d in ["7", "29"]] + [("us_house", "4")]
    names = {"in_house": "Indiana House", "in_senate": "Indiana Senate", "us_house": "U.S. House"}
    for slug, (label, pattern, years) in CONTESTS.items():
        sel = n[n["office"].str.upper().str.contains(pattern, regex=True) &
                n["election"].isin([f"{y}-GENERAL" for y in years])]
        piv = sel.pivot_table(index=["district_type", "district", "election"], columns="party",
                              values="votes", aggfunc="sum").reset_index()
        piv["margin"] = 100 * (piv["R"] - piv["D"]) / (piv["R"] + piv["D"])
        piv["year"] = piv["election"].str[:4].astype(int)
        lim = max(10, (abs(piv["margin"]).max() // 10 + 1) * 10)
        fig, axes = plt.subplots(2, 4, figsize=(13, 6.4), sharex=True, sharey=True)
        axes = axes.ravel()
        for ax, (dt, d) in zip(axes, panels):
            s = piv[(piv.district_type == dt) & (piv.district == d)].sort_values("year")
            ax.axhspan(0, lim, color="#fbeceb", zorder=0)        # Republican side, very light
            ax.axhspan(-lim, 0, color="#e9f1fb", zorder=0)       # Democratic side, very light
            ax.axhline(0, color=INK_3, linewidth=0.8)
            ax.plot(s["year"], s["margin"], color=INK, linewidth=2, marker="o", markersize=5,
                    markeredgecolor=SURFACE, markeredgewidth=1.5, zorder=3)
            if len(s):          # direct label on the latest point, on the side AWAY from the line
                last = s.iloc[-1]
                falling = len(s) > 1 and last["margin"] < s.iloc[-2]["margin"]
                ax.annotate(party_label(last["margin"]), (last["year"], last["margin"]),
                            textcoords="offset points", xytext=(4, -10 if falling else 9),
                            ha="right", va="top" if falling else "bottom", fontsize=7.5, color=INK,
                            bbox=dict(boxstyle="round,pad=0.15", fc=SURFACE, ec="none", alpha=0.8))
            ax.set_xlim(int(years[0]) - 1, int(years[-1]) + 1)
            ax.set_title(f"{names[dt]} {d}", loc="left", fontsize=9.5, color=INK)
            ax.set_ylim(-lim, lim); ax.grid(axis="y", color="#e6e5e1", linewidth=0.6)
            ax.set_xticks([int(y) for y in years]); ax.tick_params(labelsize=7.5)
            for sp in ("top", "right"): ax.spines[sp].set_visible(False)
        axes[-1].set_axis_off()
        axes[-1].text(0.02, 0.62, "Above the line: Republican margin\nBelow the line: Democratic margin\n\n"
                      "Each panel: only the part of the\ndistrict inside Boone County.",
                      transform=axes[-1].transAxes, fontsize=8.5, color=INK_2, va="top")
        ticks = [-lim, -lim / 2, 0, lim / 2, lim]
        axes[0].set_yticks(ticks)
        axes[0].set_yticklabels([("Dem +" if t < 0 else "Rep +" if t > 0 else "") + f"{abs(t):.0f}" if t else "Even" for t in ticks])
        fig.subplots_adjust(left=0.07, right=0.98, top=0.86, bottom=0.17, wspace=0.12, hspace=0.35)
        finish(fig, f"trend_{slug}", f"{label}: how today's districts voted, Boone County portion",
               f"Source: data/normalized/results_by_current_district.csv (Boone County Clerk results re-expressed on "
               f"2021-enacted districts). Elections: {', '.join(years)} general. Method: {MARGIN_METHOD} "
               f"Old precincts allocated to today's districts by Census voting-age population (METHODOLOGY.md §7). "
               + (f"Caveat: {', '.join(y for y in years if 2012 <= int(y) <= 2018)} assume 2020 precinct shapes; "
                  if any(2012 <= int(y) <= 2018 for y in years) else "Caveat: ")
               + "2008 omitted (scanned data under review)." + provisional_note(years))


def swing_map(results, house, y0="2016", y1="2024", edges=SWING_EDGES, contest="president"):
    """Change in each precinct's margin for one contest from y0 to y1 (both on today's 53
    precinct names)."""
    label, pattern, _ = CONTESTS[contest]
    cmap, norm, handles = diverging(edges, "Toward Democratic", "Toward Republican")
    a, _ = contest_rows(results, y0, pattern)
    b, _ = contest_rows(results, y1, pattern)
    ma, mb = precinct_margins(a), precinct_margins(b)
    for m in (ma, mb): m["pkey"] = m["precinct_name"].map(key)
    sw = mb[["pkey", "margin"]].merge(ma[["pkey", "margin"]], on="pkey", suffixes=("_1", "_0"))
    sw["swing"] = sw["margin_1"] - sw["margin_0"]
    g = precinct_layer("2024").merge(sw, on="pkey", how="left")
    fig, ax = plt.subplots(figsize=(9, 6.2))
    plot_if_any(g[g["swing"].isna()], ax, color=NO_DATA, edgecolor=SURFACE, linewidth=0.4)
    plot_if_any(g[g["swing"].notna()], ax, column="swing", cmap=cmap, norm=norm, edgecolor=SURFACE, linewidth=0.4)
    draw_districts(ax, house); ax.set_axis_off()
    ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(1.0, 1.0), frameon=False, fontsize=8,
              title="Change in margin (points)", title_fontsize=8.5)
    fig.subplots_adjust(left=0.01, right=0.74, top=0.93, bottom=0.02)
    shapes = (f"{y0} precinct shapes assumed equal to today's (same 53 names); " if int(y0) < 2020 else "")
    finish(fig, f"swing_{contest}_{y0}_{y1}", f"{label}: change in two-party margin by precinct, {y0} → {y1}",
           f"{SOURCE} Elections: {y0} and {y1} general. Method: {y1} margin minus {y0} margin. {MARGIN_METHOD} "
           f"Caveat: {shapes}the {y0} and {y1} candidates differ." + provisional_note([y0, y1]))


def precinct_trends(results, house):
    """One small panel per precinct: its President margin 2012 -> 2024, grouped by current
    Indiana House district, with the total shift over the period written in each panel."""
    _, pattern, years = CONTESTS["president"]
    m = []
    for y in years:
        rows, _ = contest_rows(results, y, pattern)
        pm = precinct_margins(rows).assign(year=int(y))
        pm["pkey"] = pm["precinct_name"].map(key)
        m.append(pm[["pkey", "year", "margin"]])
    m = pd.concat(m)
    p24 = gpd.read_file(GEO / "precincts_2024.geojson")
    p24["pkey"] = p24["precinct_name_raw"].map(key)
    order = p24.sort_values(["in_house", "pkey"], key=lambda s: s.map(
        lambda v: (int(v) if str(v).isdigit() else v)))[["pkey", "in_house", "precinct_name_raw"]]
    lim = (abs(m["margin"]).max() // 10 + 1) * 10
    cols = 9
    rows_ = -(-len(order) // cols)
    fig, axes = plt.subplots(rows_, cols, figsize=(1.75 * cols, 1.45 * rows_ + 0.5), sharex=True, sharey=True)
    axes = axes.ravel()
    for ax, r in zip(axes, order.itertuples()):
        s = m[m.pkey == r.pkey].sort_values("year")
        ax.axhspan(0, lim, color="#fbeceb", zorder=0); ax.axhspan(-lim, 0, color="#e9f1fb", zorder=0)
        ax.axhline(0, color=INK_3, linewidth=0.6)
        ax.plot(s["year"], s["margin"], color=INK, linewidth=1.6, marker="o", markersize=2.8, zorder=3)
        ax.set_ylim(-lim, lim); ax.set_xlim(2010.5, 2025.5)
        ax.set_xticks([2012, 2024]); ax.set_yticks([])
        ax.tick_params(labelsize=6.5, length=2)
        for sp in ("top", "right", "left"): ax.spines[sp].set_visible(False)
        name = r.precinct_name_raw.title().replace(" 0", " ")
        ax.set_title(f"{name}  ·  H{r.in_house}", loc="left", fontsize=7, color=INK, pad=2)
        if len(s) >= 2:
            shift = s.iloc[-1]["margin"] - s.iloc[0]["margin"]
            text = ("no net change" if abs(shift) < 0.5 else
                    f"{abs(shift):.0f} pts toward {'Dem' if shift < 0 else 'Rep'}")
            ax.text(0.03, 0.06, text, transform=ax.transAxes, fontsize=6.3, color=INK_2)
    for ax in axes[len(order):]: ax.set_axis_off()
    fig.subplots_adjust(left=0.01, right=0.99, top=0.93, bottom=0.04, wspace=0.08, hspace=0.75)
    finish(fig, "precinct_trends_president",
           "President: every precinct's two-party margin, 2012 → 2024 (grouped by today's Indiana House district)",
           f"{SOURCE} Elections: 2012, 2016, 2020, 2024 general. Method: {MARGIN_METHOD} Each panel: one "
           f"precinct (H = today's Indiana House district); shaded red above the line = Republican margin, blue "
           f"below = Democratic; scale ±{lim:.0f} points in every panel; text = total shift 2012→2024. "
           f"Caveat: 2012 and 2016 precinct shapes assumed equal to today's (same 53 names).")


def turnout_map(house, year="2024", edges=TURNOUT_EDGES):
    """Precinct turnout for one general election. Bins are per year (`edges`, 4 cut points
    -> 5 bins): presidential-year turnout runs ~20 points above midterm turnout, so one fixed
    set of bins would put nearly every precinct in a single bin in one or the other."""
    t = pd.read_csv(DATA_DIR / "turnout_long.csv", dtype=str)
    t = t[(t["source_file_id"] == f"{year}-GENERAL-PRECINCT") & (t["granularity"] == "precinct")].copy()
    t["pct"] = 100 * t["public_count"].astype(float) / t["registered_voters"].astype(float)
    t["pkey"] = t["precinct_name"].map(key)
    g = precinct_layer("2024").merge(t[["pkey", "pct"]], on="pkey", how="left")
    bounds = [0] + list(edges) + [100]
    cmap, norm = ListedColormap(TURNOUT_RAMP), BoundaryNorm(bounds, len(TURNOUT_RAMP))
    fig, ax = plt.subplots(figsize=(9, 6.2))
    g.plot(ax=ax, column="pct", cmap=cmap, norm=norm, edgecolor=SURFACE, linewidth=0.4,
           missing_kwds={"color": NO_DATA})
    draw_districts(ax, house); ax.set_axis_off()
    labels = [f"under {edges[0]}%"] + [f"{a}–{b}%" for a, b in zip(edges, edges[1:])] + [f"{edges[-1]}%+"]
    ax.legend(handles=[Patch(fc=c, label=l) for c, l in zip(reversed(TURNOUT_RAMP), reversed(labels))],
              loc="upper left", bbox_to_anchor=(1.0, 1.0), frameon=False, fontsize=8,
              title="Ballots cast ÷ registered", title_fontsize=8.5)
    county = 100 * t["public_count"].astype(float).sum() / t["registered_voters"].astype(float).sum()
    fig.subplots_adjust(left=0.01, right=0.76, top=0.93, bottom=0.02)
    finish(fig, f"turnout_{year}_general", f"Turnout by precinct, {year} general (county: {county:.1f}%)",
           f"Source: Boone County Clerk precinct reports (Turnout_Long). Election: {year} general. "
           "Method: ballots cast (public count) ÷ registered voters, as printed per precinct. "
           "Caveat: registered-voter counts are as printed in each precinct report, not adjusted in any way."
           + provisional_note([year]))


# ----------------------------------------------------------------------------- 2022 vs 2026
MIDTERM_OFFICES = [   # on every Boone ballot in both 2022 and 2026, contested by both parties
    ("Secretary of State", r"^SECRETARY OF STATE"),
    ("Auditor of State / State Comptroller", r"AUDITOR OF STATE|COMPTROLLER"),
    ("Treasurer of State", r"^TREASURER OF STATE"),
    ("U.S. House District 4", None),           # pattern filled from CONTESTS below
]


def office_shift_chart(results, y0="2022", y1="2026"):
    """Dumbbell chart: each statewide office's two-party margin in y0 (hollow gray) and y1
    (solid ink), for Boone County and for each of today's legislative districts. Both years
    use today's precincts and lines, so the districts are exact (no estimation)."""
    offices = [(l, p or CONTESTS["us_house_4"][1]) for l, p in MIDTERM_OFFICES]
    norm_ = pd.read_csv(NORM / "results_by_current_district.csv", dtype={"district": str})
    rows = [("county", None, "Boone County (all)")] + \
           [("in_house", d, f"Indiana House {d}") for d in ["24", "25", "28", "41"]] + \
           [("in_senate", d, f"Indiana Senate {d}") for d in ["7", "29"]]
    vals = {}
    for label, pattern in offices:
        dm = district_margins(norm_, pattern, [y0, y1]).set_index(["district_type", "district", "year"])["margin"]
        for y in (y0, y1):
            r_, _ = contest_rows(results, y, pattern)
            R, D = r_[r_.party == "R"]["votes"].sum(), r_[r_.party == "D"]["votes"].sum()
            vals[(label, "county", None, y)] = 100 * (R - D) / (R + D)
            for dt, d, _ in rows[1:]:
                vals[(label, dt, d, y)] = dm.get((dt, d, int(y)))
    lim = (max(abs(v) for v in vals.values() if v is not None) // 10 + 1) * 10
    fig, axes = plt.subplots(1, len(offices), figsize=(3.6 * len(offices) + 1.6, 4.4), sharey=True)
    ypos = list(range(len(rows)))[::-1]
    for ax, (label, _) in zip(axes, offices):
        ax.axvspan(0, lim, color="#fbeceb", zorder=0); ax.axvspan(-lim, 0, color="#e9f1fb", zorder=0)
        ax.axvline(0, color=INK_3, linewidth=0.8)
        for y_, (dt, d, _) in zip(ypos, rows):
            a, b = vals[(label, dt, d, y0)], vals[(label, dt, d, y1)]
            ax.plot([a, b], [y_, y_], color=INK_3, linewidth=2, zorder=2)
            ax.plot(a, y_, "o", markersize=7, markerfacecolor=SURFACE, markeredgecolor=INK_3,
                    markeredgewidth=1.6, zorder=3)
            ax.plot(b, y_, "o", markersize=7, markerfacecolor=INK, markeredgecolor=SURFACE,
                    markeredgewidth=1.2, zorder=4)
        ax.set_title(label, loc="left", fontsize=9.5, color=INK)
        ax.set_xlim(-lim, lim)
        ticks = [-lim / 2, 0, lim / 2]      # inner ticks only: edge labels collide across panels
        ax.set_xticks(ticks)
        ax.set_xticklabels([("Dem +" if t < 0 else "Rep +") + f"{abs(t):.0f}" if t else "Even" for t in ticks],
                           fontsize=7.5)
        ax.grid(axis="x", color="#e6e5e1", linewidth=0.6)
        for sp in ("top", "right", "left"): ax.spines[sp].set_visible(False)
        ax.tick_params(axis="y", length=0)
    axes[0].set_yticks(ypos); axes[0].set_yticklabels([r[2] for r in rows], fontsize=8.5)
    fig.legend(handles=[plt.Line2D([], [], marker="o", linestyle="", markersize=7, markerfacecolor=SURFACE,
                                   markeredgecolor=INK_3, markeredgewidth=1.6, label=f"{y0}"),
                        plt.Line2D([], [], marker="o", linestyle="", markersize=7, markerfacecolor=INK,
                                   markeredgecolor=SURFACE, label=f"{y1}")],
               loc="upper left", ncol=2, frameon=False, fontsize=8.5, bbox_to_anchor=(0.015, 0.92))
    fig.subplots_adjust(left=0.13, right=0.99, top=0.74, bottom=0.12, wspace=0.08)
    finish(fig, f"statewide_offices_{y0}_{y1}",
           f"Statewide offices on the {y0} and {y1} ballots: two-party margin by today's district",
           f"Source: Boone County Clerk results (Results_Long) and data/normalized/results_by_current_district.csv. "
           f"Elections: {y0} and {y1} general. Method: {MARGIN_METHOD} Both years are on today's precincts and "
           f"district lines, so district figures are exact sums of whole precincts. Caveat: Boone County portion "
           f"of each district only; the candidates differ between years." + provisional_note([y0, y1]))


# ----------------------------------------------------------------------------- comparison
DT_NAMES = {"in_house": "Indiana House", "in_senate": "Indiana Senate", "us_house": "U.S. House"}
AS_DRAWN_INK = "#8a8984"      # gray, dashed: the context series; today's lines are the point


def district_margins(df, pattern, years):
    sel = df[df["office"].str.upper().str.contains(pattern, regex=True) & df["party"].isin(["R", "D"]) &
             df["election"].isin([f"{y}-GENERAL" for y in years])]
    p = sel.pivot_table(index=["district_type", "district", "election"], columns="party",
                        values="votes", aggfunc="sum").reset_index()
    p["margin"] = 100 * (p["R"] - p["D"]) / (p["R"] + p["D"])
    p["year"] = p["election"].str[:4].astype(int)
    return p


# (first general-election year under the map, first year of the NEXT map) - contiguous, no gaps
MAP_ERAS = [(2002, 2012, "2002 map"), (2012, 2022, "2012 map"), (2022, 2100, "today's map")]
# Results_Long's own era tag -> first general-election year under that map
ERA_START = {"2001-2010 map": 2002, "2011-2020 map": 2012, "2021-present map": 2022}


def as_drawn_segments(sd):
    """The as-drawn series split by map era, keeping only eras BEFORE today's map (from 2022
    the as-drawn and normalized series are identical) with at least two results - a single
    result under a map is not a trend and is not drawn."""
    segs = []
    for start, end, _ in MAP_ERAS[:-1]:
        seg = sd[(sd["year"] >= start) & (sd["year"] < end)]
        if len(seg) >= 2:
            segs.append(seg)
    return segs


def compare_charts():
    norm_ = pd.read_csv(NORM / "results_by_current_district.csv", dtype={"district": str})
    drawn = pd.read_csv(NORM / "results_by_district_as_drawn.csv", dtype={"district": str})
    # first map era in which each district number appeared in Boone (from ANY election's
    # ballots), using Results_Long's own era tag rather than guessing from the year
    seen = drawn[drawn["election"].str[:4].astype(int) >= 2010]     # 2008 is not mapped
    first_seen = (seen.assign(start=seen["redistricting_era"].map(ERA_START))
                      .groupby(["district_type", "district"])["start"].min().to_dict())
    for slug in ("president", "us_senate"):
        label, pattern, years = CONTESTS[slug]
        n, d = district_margins(norm_, pattern, years), district_margins(drawn, pattern, years)
        for dt, dname in DT_NAMES.items():
            today = sorted(n[n.district_type == dt]["district"].unique(), key=int)
            past_all = sorted(set(d[d.district_type == dt]["district"]) - set(today), key=int)
            # a retired district number gets a panel only if it has a trend to show (an era with
            # >= 2 results); the rest are named in the caption instead of drawn as a lone dot
            def segs_of(x):
                return as_drawn_segments(d[(d.district_type == dt) & (d.district == x)].sort_values("year"))
            past_only = [x for x in past_all if segs_of(x)]
            dropped = [x for x in past_all if x not in past_only]
            panels = today + past_only
            lim = max(10, (max(abs(n["margin"]).max(), abs(d["margin"]).max()) // 10 + 1) * 10)
            cols = min(4, len(panels))
            rows_ = (len(panels) + cols - 1) // cols
            fig, axes = plt.subplots(rows_, cols, figsize=(3.4 * cols + 0.6, 3.1 * rows_ + 1.2),
                                     sharex=True, sharey=True, squeeze=False)
            axes = axes.ravel()
            for ax, dist in zip(axes, panels):
                ax.axhspan(0, lim, color="#fbeceb", zorder=0); ax.axhspan(-lim, 0, color="#e9f1fb", zorder=0)
                ax.axhline(0, color=INK_3, linewidth=0.8)
                sd = d[(d.district_type == dt) & (d.district == dist)].sort_values("year")
                sn = n[(n.district_type == dt) & (n.district == dist)].sort_values("year")
                # map changes: thin dotted separators; the as-drawn line is BROKEN at each one,
                # because the same number under a new map is a different place
                for start, _, _ in MAP_ERAS[1:]:
                    if int(years[0]) < start <= int(years[-1]):
                        ax.axvline(start - 1, color=INK_3, linewidth=0.8, linestyle=":", zorder=1)
                for seg in as_drawn_segments(sd):
                    ax.plot(seg["year"], seg["margin"], color=AS_DRAWN_INK, linewidth=2, linestyle=(0, (4, 2)),
                            marker="s", markersize=5, markeredgecolor=SURFACE, markeredgewidth=1.2, zorder=2)
                if len(sn):
                    ax.plot(sn["year"], sn["margin"], color=INK, linewidth=2, marker="o", markersize=5,
                            markeredgecolor=SURFACE, markeredgewidth=1.2, zorder=3)
                if dist in past_only:
                    note = "not a Boone district today"
                elif first_seen.get((dt, dist), 9999) > 2002:
                    note = f"number used in Boone only since {first_seen.get((dt, dist))}"
                else:
                    note = ""
                ax.set_title(f"{dname} {dist}", loc="left", fontsize=9.5, color=INK)
                if note:
                    ax.text(0.02, 0.04, note, transform=ax.transAxes, fontsize=7.5, color=INK_2, style="italic",
                            zorder=5, bbox=dict(boxstyle="round,pad=0.2", fc="#e9f1fb", ec="none"))
                ax.set_ylim(-lim, lim); ax.set_xlim(int(years[0]) - 1, int(years[-1]) + 1)
                ax.set_xticks([int(y) for y in years]); ax.tick_params(labelsize=7.5)
                ax.grid(axis="y", color="#e6e5e1", linewidth=0.6)
                for sp in ("top", "right"): ax.spines[sp].set_visible(False)
            for ax in axes[len(panels):]: ax.set_axis_off()
            ticks = [-lim, 0, lim]
            axes[0].set_yticks(ticks)
            axes[0].set_yticklabels([f"Dem +{lim:.0f}", "Even", f"Rep +{lim:.0f}"])
            fig.legend(handles=[plt.Line2D([], [], color=INK, linewidth=2, marker="o", label="Today's lines (normalized)"),
                                plt.Line2D([], [], color=AS_DRAWN_INK, linewidth=2, linestyle=(0, (4, 2)), marker="s",
                                           label="Lines in force at the time (as reported)")],
                       loc="upper left", ncol=2, frameon=False, fontsize=8.5,
                       bbox_to_anchor=(0.015, 0.93 if rows_ == 1 else 0.955))   # own row under the title
            fig.subplots_adjust(left=0.08, right=0.98, top=0.76 if rows_ == 1 else 0.86, bottom=0.1 if rows_ == 1 else 0.06,
                                wspace=0.12, hspace=0.4)
            finish(fig, f"compare_{dt}_{slug}",
                   f"{label} margin by {dname} district: today's lines vs the lines at the time",
                   f"Source: data/normalized/results_by_current_district.csv and results_by_district_as_drawn.csv "
                   f"(Boone County Clerk results). Elections: {', '.join(years)} general. Method: {MARGIN_METHOD} "
                   f"Solid = precincts re-expressed on 2021-enacted lines; dashed = precincts in that district number "
                   f"at the time, read from each precinct's own ballot; dotted verticals mark new maps (dashed line "
                   f"breaks there); from 2022 the two coincide, so only earlier maps are drawn dashed; a single "
                   f"result under a map is not drawn. "
                   + ("Not shown (only one result, no trend): " + "; ".join(
                          f"{dname} {x} ({int(d[(d.district_type == dt) & (d.district == x)]['year'].min())})"
                          for x in dropped) + ". " if dropped else "")
                   + "Caveat: Boone County portion only; a shared district number does not mean the same place.")


DISTRICT_SLOTS = ["#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6"]   # categorical slots 2-7


def district_lines_map():
    a = pd.read_csv(NORM / "precinct_district_as_drawn.csv", dtype=str)
    a = a[a["district_type"] == "in_house"]
    eras = [("2001-2010 map", "2010", "Lines used 2002–2011"),
            ("2011-2020 map", "2020", "Lines used 2012–2020"),
            ("2021-present map", "2024", "Today's lines (2022–)")]
    numbers = sorted(a["district"].unique(), key=int)
    color = {n: DISTRICT_SLOTS[i % len(DISTRICT_SLOTS)] for i, n in enumerate(numbers)}   # fixed per number
    fig, axes = plt.subplots(1, 3, figsize=(15, 5.2))
    for ax, (era, vintage, title) in zip(axes, eras):
        g = precinct_layer(vintage).merge(a[a.era == era][["precinct_key", "district"]],
                                          left_on="pkey", right_on="precinct_key", how="left")
        plot_if_any(g[g["district"].isna()], ax, color=NO_DATA, edgecolor=SURFACE, linewidth=0.3)
        dd = g[g["district"].notna()].dissolve(by="district", as_index=False)
        for r in dd.itertuples():
            gpd.GeoSeries([r.geometry], crs=g.crs).plot(ax=ax, color=color[r.district], edgecolor=SURFACE, linewidth=1.2)
            pt = label_point(r.geometry)
            ax.annotate(f"House {r.district}", (pt.x, pt.y), ha="center", va="center", fontsize=8.5,
                        fontweight="bold", color=INK, bbox=dict(boxstyle="round,pad=0.2", fc=SURFACE, ec="none", alpha=0.9))
        ax.set_title(title, loc="left", fontsize=10.5, color=INK); ax.set_axis_off()
    fig.subplots_adjust(left=0.01, right=0.99, top=0.86, bottom=0.12, wspace=0.03)
    finish(fig, "district_lines_in_house", "Indiana House districts in Boone County under three maps",
           "Source: each precinct's district as printed on its own ballot (data/normalized/precinct_district_as_drawn.csv); "
           "precinct shapes from IndianaMap. Method: precincts dissolved by the district shown on their ballots in each "
           "map era; a number keeps one color across panels. Caveat: 2002–2011 and 2012–2020 drawn on 2010 and 2020 "
           "precinct shapes, the closest maps available.")


def main():
    print("Maps:")
    results, house = load_results(), house_lines()
    margin_maps(results, house)
    trend_maps()
    swing_map(results, house)                                        # recent: 2016 -> 2024
    swing_map(results, house, "2012", "2024", edges=[5, 10, 20, 30])   # whole period
    swing_map(results, house, "2022", "2026", contest="secretary_of_state")   # midterm to midterm
    precinct_trends(results, house)
    turnout_map(house)                                             # 2024 general
    turnout_map(house, "2026", edges=[40, 45, 50, 55])             # midterm: ~20 pts lower
    office_shift_chart(results)
    compare_charts()
    district_lines_map()
    with open(OUT / "captions.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["file", "title", "caption"]); w.writeheader(); w.writerows(captions)
    print(f"  maps/captions.csv ({len(captions)} captions)")


if __name__ == "__main__":
    main()
