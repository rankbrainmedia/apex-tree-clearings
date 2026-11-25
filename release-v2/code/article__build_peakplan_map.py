#!/usr/bin/env python3
"""build_peakplan_map.py: one still map for the article's Peak Plan 2055 section.

    ../apex-canopy/df-venv/bin/python build_peakplan_map.py

Draws, on the release's 10 m grid and inside Apex's planning jurisdiction only (the clearing detection exists nowhere else):
  (a) Wake County's 2020 tree canopy, light: the canopy share of each cell, the grid context_areas.csv counts as canopy_2020_acres;
  (b) cells cleared since July 2020, red: the cells behind cleared_since_mid2020_cell_acres;
  (c) forest inside approved cases that has not been cleared, blue: the cells behind forest_standing_now_in_approved_2020plus_acres
      (forest in 2020, no clearing event since, forest-like in Jul-Sep 2026, inside a conditional zoning case numbered 2020 or
      later that is approved). 23CZ13 is not in that case set (wake_tca.HEADLINE_OUT), so its ground is never blue;
  (d) the outlines of the Town's staff-draft Peak Plan 2055 context areas, labelled;
  (e) the outline of the planning jurisdiction.
The masks are rebuilt here exactly as ../entitlement/wake_tca.py report() builds them, from the same inputs, which are only read.
Writes out/img/peakplan-map.png (2400 px wide), out/img/peakplan-map-phone.png (1200 px wide, upright) and out/img/peakplan-map.json
(the acres drawn, by context area, beside the figures in context_areas.csv). Nothing here uploads or publishes.
"""
import json, os, sys
import numpy as np, pandas as pd, geopandas as gpd, shapely
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from matplotlib.colors import to_rgb
from matplotlib.patches import Patch, Rectangle
from matplotlib.lines import Line2D
from rasterio import features

HERE = os.path.dirname(os.path.abspath(__file__))
ENT = os.path.normpath(os.path.join(HERE, "..", "entitlement"))
sys.path.insert(0, ENT)
import wake_tca as W                                   # constants, loaders and the grid; importing runs nothing

OUT = os.path.join(HERE, "out", "img")
RED, BLUE, CANOPY, INK, LINE = "#a42528", "#2f6db5", "#c9d3c4", "#1c1c1c", "#3a3a3a"
PX, SHAPE, T10 = W.PX, W.SHAPE, W.T10
r1 = lambda v: round(float(v), 1)


def masks():
    """The grids of wake_tca.report(), sections 'grids', 'geographies' and 'cases', unchanged."""
    b = np.load(os.path.join(W.AC, "s2", "cache", "baseline.npz"))
    inb = b["inb"]
    D = np.load(os.path.join(W.PRE, "detect_2017.npz"))
    DET_Q = json.load(open(os.path.join(W.PRE, "detect_2017.json")))["det_quarters"]
    i0 = DET_Q.index(W.SINCE_Q)
    fe, ke, now = D["first_event"], D["kept_event"], D["state_now"]
    since = ke & (fe >= i0)
    Z = np.load(W.rasters())
    f20 = Z["frac2020"]
    n20 = np.load(os.path.join(W.PRE, "naip", "canopy_2020.npz"))["frac"]
    proj = W.burn(W.load("wake_project_boundary").geometry).astype(bool)
    can20 = np.where(proj, f20, np.nan_to_num(n20, nan=0.0)).astype(np.float32)
    F20 = can20 >= W.FOREST_FRAC
    standing = F20 & ~(fe >= i0) & (now == 0)
    corp_g, etj_g = W.load("apex_corporate_limits").geometry.union_all(), W.load("apex_etj").geometry.union_all()
    corp = W.burn([corp_g]).astype(bool)
    pj = corp | (W.burn([etj_g]).astype(bool) & ~corp)
    PJ_G = shapely.union_all([corp_g, etj_g])
    # cases
    ms = lambda s: pd.to_datetime(s, unit="ms", errors="coerce") if "datetime" not in str(s.dtype) else s.dt.tz_localize(None)
    rz = gpd.read_file(os.path.join(ENT, "inputs", "town_rezoning_2026-11-24.geojson")).to_crs(32617)
    rz["geometry"] = shapely.make_valid(rz.geometry.values)
    rz["case"] = rz.Petition.str.strip().str.upper()
    rz = rz.set_index("case", drop=False)
    zn = gpd.read_file(os.path.join(ENT, "inputs", "town_zoning_2026-11-24.geojson")).to_crs(32617)
    zn["geometry"] = shapely.make_valid(zn.geometry.values)
    zn["case"] = zn.CASE_NUMBE.fillna("").str.strip().str.upper()
    names = sorted({c for c in list(zn.case) + list(rz.index) if W.parse_case(c)[1] == "CZ" and (W.parse_case(c)[0] or 0) >= 2020} | set(rz.index[rz.Status == "Proposed"]))
    cmask, era = {}, {}
    for c in names:
        yr = W.parse_case(c)[0]
        r = rz.loc[c] if c in rz.index else None
        cur = zn[zn.case == c]
        geom = r.geometry if r is not None else cur.geometry.union_all()
        status = W.MANUAL_STATUS.get(c) or (r.Status if r is not None else "on zoning map")
        group = "pending" if status == "Proposed" else "approved" if status in ("Approved", "on zoning map") else "not counted"
        if group == "approved" and yr < 2020:
            group = "not counted"
        era[c] = ("2022 or later" if yr >= 2022 else "2020-2021") if group == "approved" else group
        cmask[c] = W.burn([geom]).astype(bool) & inb
    approved = [c for c in names if era[c] in ("2022 or later", "2020-2021")]
    um = lambda cs: np.any([cmask[c] for c in cs], axis=0) if cs else np.zeros(SHAPE, bool)
    M20 = um([c for c in approved if c not in W.HEADLINE_OUT])
    M20c = um(approved)                                  # with 23CZ13, to report what leaving it out removed
    ca = W.load("apex_context_areas_2055")
    calab = features.rasterize([(g, i + 1) for i, g in enumerate(ca.geometry)], out_shape=SHAPE, transform=T10, fill=0, dtype="int32")
    return dict(inb=inb, since=since & inb & pj, blue=standing & M20 & pj & inb, blue_c=standing & M20c & pj & inb, can20=can20, pj=pj, PJ_G=PJ_G, ca=ca, calab=calab,
                n_cases=len([c for c in approved if c not in W.HEADLINE_OUT]), has_23=("23CZ13" in approved))


def rgba(mask, colour, alpha=1.0):
    im = np.zeros(mask.shape + (4,), np.float32)
    im[..., :3] = to_rgb(colour)
    im[..., 3] = mask * alpha
    return im


WRAP = {"Transit-Oriented Development": "Transit-Oriented\nDevelopment"}
SECOND_MIN_AC = 600          # a separate piece of an area this large, inside the jurisdiction, gets a smaller second label


def place_labels(G, mpp, big_px, small_px):
    """One large label on the largest piece of each context area inside the jurisdiction, and a smaller one on any other piece of
    SECOND_MIN_AC or more. Each sits where its box covers the fewest red and blue cells and stays inside its piece as far as it can."""
    busy = (G["since"] | G["blue"]).astype(np.float32)
    ii = np.pad(busy, ((1, 0), (1, 0))).cumsum(0).cumsum(1)

    def cells(x, y, w, h):
        c0, c1 = int((x - w / 2 - W.X0) // 10), int((x + w / 2 - W.X0) // 10)
        r0, r1_ = int((W.Y1 - (y + h / 2)) // 10), int((W.Y1 - (y - h / 2)) // 10)
        c0, c1, r0, r1_ = max(c0, 0), min(c1, SHAPE[1]), max(r0, 0), min(r1_, SHAPE[0])
        return float(ii[r1_, c1] - ii[r0, c1] - ii[r1_, c0] + ii[r0, c0])

    out, taken = [], []
    todo = []
    for _, r in G["ca"].iterrows():
        g = r.geometry.intersection(G["PJ_G"])
        parts = sorted([p for p in getattr(g, "geoms", [g]) if p.geom_type == "Polygon"], key=lambda p: -p.area)
        todo.append((r.Name, parts[0], True))
        todo += [(r.Name, p, False) for p in parts[1:] if p.area / W.M2_AC >= SECOND_MIN_AC]
    for name, part, main in sorted(todo, key=lambda t: (not t[2], -t[1].area)):
        text = WRAP.get(name, name) if main or name in WRAP else name
        px = big_px if main else small_px
        lines = text.split("\n")
        w, h = 0.62 * px * max(len(l) for l in lines) * mpp, 1.12 * px * len(lines) * mpp
        bx0, by0, bx1, by1 = part.bounds
        best = None
        for x in np.arange(bx0 + w / 2, bx1 - w / 2 + 1, 150) if bx1 - bx0 > w else [(bx0 + bx1) / 2]:
            for y in np.arange(by0 + h / 2, by1 - h / 2 + 1, 150) if by1 - by0 > h else [(by0 + by1) / 2]:
                box = shapely.box(x - w / 2, y - h / 2, x + w / 2, y + h / 2)
                if not part.contains(shapely.Point(x, y)) or any(box.buffer(250).intersects(t) for t in taken):
                    continue
                outside = 1 - box.intersection(part).area / box.area
                cost = 4 * cells(x, y, w, h) / (w * h / 100) + 1.5 * outside + 0.00002 * shapely.Point(x, y).distance(part.centroid)
                if best is None or cost < best[0]:
                    best = (cost, x, y, box)
        if best is None:
            rp = part.representative_point(); best = (0, rp.x, rp.y, shapely.box(rp.x - w / 2, rp.y - h / 2, rp.x + w / 2, rp.y + h / 2))
        taken.append(best[3])
        out.append(dict(name=name, text=text, x=best[1], y=best[2], main=main, acres_of_piece=round(part.area / W.M2_AC)))
    return out


def draw(G, fn, px_w):
    """The same layout at any width: every size is set in pixels of a 1200-px-wide file and scaled."""
    k = px_w / 1200
    dpi = 100 * k                                         # so a font size in points equals its height in px at 1200 wide, times 100/72
    x0, y0, x1, y1 = G["PJ_G"].bounds
    pad = 450
    x0, x1, y0, y1 = x0 - pad, x1 + pad, y0 - pad, y1 + pad
    mpp = (x1 - x0) / 1200                                # metres per px at 1200 wide
    map_h, head, foot = 1200 * (y1 - y0) / (x1 - x0), 140, 250
    fig_h = map_h + head + foot
    pt = lambda px: px * 72 / 100                         # px (at 1200 wide) to points
    fig = plt.figure(figsize=(12, fig_h / 100), dpi=dpi, facecolor="white")
    ax = fig.add_axes([0, foot / fig_h, 1, map_h / fig_h])
    ext = (W.X0, W.X1, W.Y0, W.Y1)
    ax.imshow(rgba(np.clip(G["can20"], 0, 1) * G["pj"], CANOPY), extent=ext, interpolation="bilinear", zorder=1)
    ax.imshow(rgba(G["blue"], BLUE), extent=ext, interpolation="nearest", zorder=2)
    ax.imshow(rgba(G["since"], RED), extent=ext, interpolation="nearest", zorder=3)
    gpd.GeoSeries([G["PJ_G"]]).boundary.plot(ax=ax, color="#9a9a9a", linewidth=0.7, zorder=4)
    G["ca"].boundary.plot(ax=ax, color=LINE, linewidth=1.6, zorder=5)
    BIG, SMALL = 30, 22
    labels = place_labels(G, mpp, BIG, SMALL)
    for l in labels:
        ax.text(l["x"], l["y"], l["text"], fontsize=pt(BIG if l["main"] else SMALL), fontweight="bold", color=INK if l["main"] else "#3f3f3f", ha="center", va="center", linespacing=1.18, zorder=7,
                path_effects=[pe.withStroke(linewidth=5.5 if l["main"] else 4.5, foreground="white")])
    ax.text(x0 + 0.49 * (x1 - x0), y0 + 0.07 * (y1 - y0), "The Rural area continues outside the planning area.\nNothing is drawn there: the count stops at its edge.",
            fontsize=pt(18), color="#555555", ha="center", va="center", linespacing=1.3, zorder=7, path_effects=[pe.withStroke(linewidth=3.5, foreground="white")])
    mi = 1609.344                                          # scale bar, bottom right: 2 miles
    sx, sy = x1 - 900 - 2 * mi, y0 + 1500
    ax.add_patch(Rectangle((sx, sy), mi, 120, facecolor=INK, edgecolor=INK, linewidth=0.8, zorder=8))
    ax.add_patch(Rectangle((sx + mi, sy), mi, 120, facecolor="white", edgecolor=INK, linewidth=0.8, zorder=8))
    for j, lab in ((0, "0"), (1, "1"), (2, "2 miles")):
        ax.text(sx + j * mi, sy + 230, lab, fontsize=pt(20), color=INK, ha="center", va="bottom", zorder=8)
    nx, ny = x1 - 800, y1 - 1500                           # north arrow, top right
    ax.annotate("", xy=(nx, ny + 900), xytext=(nx, ny), arrowprops=dict(arrowstyle="-|>", color=INK, lw=1.8, mutation_scale=16), zorder=8)
    ax.text(nx, ny - 120, "N", fontsize=pt(22), fontweight="bold", color=INK, ha="center", va="top", zorder=8)
    ax.set_xlim(x0, x1); ax.set_ylim(y0, y1); ax.set_axis_off()
    fig.text(28 / 1200, 1 - 50 / fig_h, "Peak Plan 2055 draft areas, tree canopy and clearing", fontsize=pt(30), fontweight="bold", color=INK, ha="left", va="center")
    fig.text(28 / 1200, 1 - 100 / fig_h, "Apex's planning area. Canopy as Wake County mapped it in 2020.", fontsize=pt(22), color="#444444", ha="left", va="center")
    handles = [Patch(facecolor=CANOPY, edgecolor="#9aa694", linewidth=0.6, label="Tree canopy in 2020 (Wake County)"),
               Patch(facecolor=RED, edgecolor="none", label="Forest cleared since July 2020"),
               Patch(facecolor=BLUE, edgecolor="none", label="Forest inside approved rezonings, not cleared"),
               Line2D([0], [0], color=LINE, linewidth=2.4, label="Peak Plan 2055 context area (Town staff draft)")]
    lax = fig.add_axes([0, 0, 1, foot / fig_h]); lax.set_axis_off()
    lax.legend(handles=handles, loc="center left", bbox_to_anchor=(14 / 1200, 0.52), ncol=1, frameon=False, fontsize=pt(23), handlelength=1.5, handleheight=1.1, labelspacing=0.5, borderaxespad=0.2, labelcolor=INK)
    fig.savefig(fn, dpi=dpi, facecolor="white")
    plt.close(fig)
    return labels


def main():
    G = masks()
    names = list(G["ca"].Name)
    CA = pd.read_csv(os.path.join(ENT, "out_wake_tca", "context_areas.csv")).set_index("area")
    rows = {}
    for i, n in enumerate(names + ["All four"]):
        m = (G["calab"] == i + 1) if n != "All four" else (G["calab"] > 0)
        rows[n] = dict(red_cells_acres_drawn=r1((G["since"] & m).sum() * PX), csv_cleared_since_mid2020_cell_acres=float(CA.loc[n, "cleared_since_mid2020_cell_acres"]),
                       blue_cells_acres_drawn=r1((G["blue"] & m).sum() * PX), csv_forest_standing_now_in_approved_2020plus_acres=float(CA.loc[n, "forest_standing_now_in_approved_2020plus_acres"]),
                       blue_if_23CZ13_were_included_acres=r1((G["blue_c"] & m).sum() * PX),
                       canopy_2020_acres_drawn=r1(float(G["can20"][m & G["pj"] & G["inb"]].sum()) * PX), csv_canopy_2020_acres=float(CA.loc[n, "canopy_2020_acres"]))
    S = json.load(open(os.path.join(ENT, "out_wake_tca", "layers", "SOURCES.json")))
    src = lambda k: {a: S[k].get(a) for a in ("url", "pulled", "layer_last_edit", "file")}
    meta = dict(
        files=["peakplan-map.png", "peakplan-map-phone.png"], colours=dict(canopy=CANOPY, cleared=RED, not_cleared_in_approved_cases=BLUE, outlines=LINE),
        whole_jurisdiction=dict(red_cells_acres_drawn=r1(G["since"].sum() * PX), blue_cells_acres_drawn=r1(G["blue"].sum() * PX), blue_if_23CZ13_were_included_acres=r1(G["blue_c"].sum() * PX),
                                red_and_blue_overlap_cells=int((G["since"] & G["blue"]).sum()),
                                note="context_areas.csv 'All four' covers the jurisdiction less a few cells in no context area; canopy_estimate_by_geography.csv 'Planning jurisdiction (Town layers)' has cleared_since_mid2020_cell_acres 1615.7"),
        by_context_area=rows,
        blue_layer=dict(matches_csv_column="forest_standing_now_in_approved_2020plus_acres",
                        definition="10 m cells that are forest on the County's 2020 map (at least half canopy), have no clearing event since July 2020, read as forest-like in Jul-Sep 2026, and lie inside a conditional zoning case numbered 2020 or later that the Town lists as approved (or that is on the zoning map)",
                        approved_cases_in_the_mask=G["n_cases"],
                        case_23CZ13=dict(excluded=True, how="wake_tca.HEADLINE_OUT = {'23CZ13'}; M20 is built from the approved cases without it", in_the_approved_list_before_exclusion=G["has_23"],
                                         acres_removed_from_blue=r1((G["blue_c"] & ~G["blue"]).sum() * PX),
                                         note="ground of 23CZ13 that also lies inside another approved case stays blue through that case; the figure above is what leaving 23CZ13 out actually removed"),
                        not_the_same_as="the article's 1,562 acres 'not yet cleared' (79 cases approved on or after 2019-12-03, forest at approval less cleared since, from the 2017 forest map). This layer uses case numbers 2020 or later, the County's 2020 canopy and a forest-like-now test."),
        red_layer=dict(matches_csv_column="cleared_since_mid2020_cell_acres", definition="10 m cells in patches of an acre or more whose first clearing event was detected in Jul-Sep 2020 or later (event rule, 2017-2026 series), through October 24, 2026"),
        canopy_layer=dict(matches_csv_column="canopy_2020_acres", definition="share of each 10 m cell under tree canopy on Wake County's 2020 land cover (1 m), drawn light in proportion to the share; outside the County's study area (about 250 acres on the Chatham side) NAIP 2020 by the release's recipe, as in wake_tca.py"),
        extent_note="The data layers are drawn inside Apex's planning jurisdiction only (town limits plus ETJ, Town layers pulled 2026-11-24). The Rural context area extends well outside it (8,376 acres in all, 1,636 inside); its outline is drawn to the edge of the frame and nothing is drawn under it outside the jurisdiction.",
        sources=dict(context_areas=src("apex_context_areas_2055"), corporate_limits=src("apex_corporate_limits"), etj=src("apex_etj"), county_study_area=src("wake_project_boundary"),
                     county_canopy_2020="Wake County 2020 land cover, 1 m (cache/wake_canopy_2020_1m_apex.tif, aggregated to 10 m in cache/wake_canopy_10m.npz by wake_tca.py rasters(), pulled 2026-11-24)",
                     clearings="apex-canopy/prerezoning_cache/detect_2017.npz (Sentinel-2, 2017-2026 series)", cases="entitlement/inputs/town_rezoning_2026-11-24.geojson and town_zoning_2026-11-24.geojson (Town of Apex, pulled 2026-11-24)"))
    json.dump(meta, open(os.path.join(OUT, "peakplan-map.json"), "w"), indent=1)
    labels = draw(G, os.path.join(OUT, "peakplan-map.png"), 2400)
    draw(G, os.path.join(OUT, "peakplan-map-phone.png"), 1200)
    meta["labels"] = [dict(l, x=round(l["x"]), y=round(l["y"])) for l in labels]
    json.dump(meta, open(os.path.join(OUT, "peakplan-map.json"), "w"), indent=1)
    for n, r in rows.items():
        print(f"{n:<30} red {r['red_cells_acres_drawn']:>8} (csv {r['csv_cleared_since_mid2020_cell_acres']:>8}) | blue {r['blue_cells_acres_drawn']:>8} (csv {r['csv_forest_standing_now_in_approved_2020plus_acres']:>8}) | with 23CZ13 {r['blue_if_23CZ13_were_included_acres']}")
    print("jurisdiction: red", meta["whole_jurisdiction"]["red_cells_acres_drawn"], "blue", meta["whole_jurisdiction"]["blue_cells_acres_drawn"], "| 23CZ13 removed", meta["blue_layer"]["case_23CZ13"]["acres_removed_from_blue"], "| approved cases", G["n_cases"])


if __name__ == "__main__":
    main()
