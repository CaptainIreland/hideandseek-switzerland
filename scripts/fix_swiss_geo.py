#!/usr/bin/env python3
"""Rebuild SWISS_GEO from official swisstopo canton data plus OSM lakes.

Usage, from the repository root (needs shapely + pyproj, not part of the
regular stdlib-only pipeline):

    pip install -r scripts/requirements.txt
    python scripts/fix_swiss_geo.py

Why this exists: SWISS_GEO (app.js line 1) is a 343-point Natural Earth
outline that every clue clips against (see compute() in app.js), while
CANTONS (app.js line 4) is the official swisstopo data (26 features) used
for canton questions. The two disagree by up to roughly a kilometre near
the border - a straight diagonal near Buchs SG instead of following the
Rhine - and the old outline wrongly includes Campione d'Italia.

Dissolving the cantons alone is nearly right but loses large lakes the
municipal boundaries don't cover (Zuerichsee, the Swiss side of Bodensee),
so this script unions the relevant OSM lake/river polygons from
data/osm-layers.json back in, clipped against the *current* (about to be
replaced) SWISS_GEO so only the Swiss-side portion of a shared lake or a
river that runs abroad survives. The result is simplified to about 100 m in
the Swiss projected CRS (EPSG:2056) and spliced back into app.js line 1.

Re-run this if data/osm-layers.json's water list changes.
"""
import json
import os
import sys

import shapely
from pyproj import Geod, Transformer
from shapely.geometry import Point, Polygon, MultiPolygon, shape
from shapely.ops import unary_union, transform as shapely_transform

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_JS = os.path.join(BASE_DIR, "app.js")
OSM_LAYERS = os.path.join(BASE_DIR, "data", "osm-layers.json")
REPORT = os.path.join(BASE_DIR, "data", "swiss-outline-report.txt")

SIMPLIFY_TOLERANCE_M = 100
COORD_PRECISION = 5
# swisstopo (CANTONS) and OSM (waters) are two independently digitized sources,
# so their shorelines don't align to the metre - unioning them raw leaves dozens
# of sliver gaps and a handful of genuinely tiny real lake islands (Ufenau,
# Brissago) as separate MultiPolygon pieces. A small morphological closing
# (dilate then erode) before the final simplify bridges sub-metre misalignment
# without materially changing the outline at our ~100 m target tolerance.
CLOSE_GAP_M = 20
MAX_DISCARD_KM2 = 10  # remaining islands/slivers after closing are a documented, negligible gap

LAKE_NAMES = ["Zürichsee", "Bodensee", "Vierwaldstättersee", "Lac de Neuchâtel", "Lago Maggiore"]

# Approximate real-world location of Campione d'Italia, used only to pick out
# its specific hole in the canton data by nearest-match (not itself used as a
# containment test point - the hole's own representative_point() is, below).
CAMPIONE_NEAR = Point(8.967, 45.973)

TEST_POINTS = [
    # name, lat, lng, expect_inside
    ("Vaduz", 47.1410, 9.5209, False),
    ("Schaan", 47.1662, 9.5099, False),
    ("Buchs SG station", 47.168415, 9.478637, True),
    ("Basel SBB", 47.547691, 7.582392, True),
]

WGS84_TO_LV95 = Transformer.from_crs("EPSG:4326", "EPSG:2056", always_xy=True)
LV95_TO_WGS84 = Transformer.from_crs("EPSG:2056", "EPSG:4326", always_xy=True)
GEOD = Geod(ellps="WGS84")


def read_app_js_literal(app_lines, line_index, prefix):
    line = app_lines[line_index]
    if not line.startswith(prefix):
        sys.exit(f"app.js line {line_index+1} does not start with {prefix!r} - layout changed, aborting.")
    body = line[len(prefix):].rstrip("\n")
    if not body.endswith(";"):
        sys.exit(f"app.js line {line_index+1} does not end with ';' - layout changed, aborting.")
    return json.loads(body[:-1])


def repair(geom):
    if geom.is_empty or geom.is_valid:
        return geom
    fixed = shapely.make_valid(geom)
    if fixed.geom_type == "GeometryCollection":
        polys = [g for g in fixed.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
        fixed = unary_union(polys) if polys else Polygon()
    return fixed


def geodesic_area_km2(geom):
    if geom.is_empty:
        return 0.0
    area_m2, _ = GEOD.geometry_area_perimeter(geom)
    return abs(area_m2) / 1e6


def collect_holes(geom):
    parts = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
    return [Polygon(ring) for part in parts for ring in part.interiors]


def exteriors_only(geom):
    parts = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
    return unary_union([Polygon(part.exterior) for part in parts])


def as_single_polygon(geom, label):
    geom = repair(geom)
    if isinstance(geom, Polygon):
        return geom
    if isinstance(geom, MultiPolygon):
        polys = sorted(geom.geoms, key=lambda g: g.area, reverse=True)
        main = polys[0]
        discarded_km2 = sum(geodesic_area_km2(p) for p in polys[1:])
        if discarded_km2 > MAX_DISCARD_KM2:
            sys.exit(
                f"{label}: union/simplify produced a MultiPolygon and discarding the "
                f"smaller pieces would drop {discarded_km2:.3f} km^2 (> {MAX_DISCARD_KM2} km^2 limit). "
                f"Refusing to silently ship a shrunk outline - investigate manually."
            )
        print(f"  ({label}: discarded {len(polys)-1} sliver piece(s) totalling {discarded_km2:.4f} km^2)")
        return main
    sys.exit(f"{label}: unexpected geometry type {geom.geom_type!r} after union/simplify.")


def polygon_from_ring(ring):
    if len(ring) < 4:
        return None
    poly = repair(Polygon(ring))
    return None if poly.is_empty else poly


def water_geometry(entry):
    parts = []
    for ring in entry.get("r", []):
        poly = polygon_from_ring(ring)
        if poly is not None:
            parts.append(poly)
    return unary_union(parts) if parts else None


def to_lv95(geom):
    return shapely_transform(lambda x, y: WGS84_TO_LV95.transform(x, y), geom)


def to_wgs84(geom):
    return shapely_transform(lambda x, y: LV95_TO_WGS84.transform(x, y), geom)


def round_ring(ring):
    return [[round(x, COORD_PRECISION), round(y, COORD_PRECISION)] for x, y in ring]


def polygon_to_geojson(poly):
    exterior = round_ring(list(poly.exterior.coords))
    interiors = [round_ring(list(r.coords)) for r in poly.interiors]
    return {"type": "Polygon", "coordinates": [exterior] + interiors}


def main():
    report_lines = []

    def log(msg):
        print(msg)
        report_lines.append(msg)

    def finish(ok):
        with open(REPORT, "w", encoding="utf-8") as f:
            f.write("\n".join(report_lines) + "\n")
        log(f"Report written to {REPORT}")
        if not ok:
            sys.exit(1)

    log("Rebuilding SWISS_GEO from CANTONS + OSM lakes")

    with open(APP_JS, encoding="utf-8") as f:
        app_lines = f.readlines()
    swiss_geo = read_app_js_literal(app_lines, 0, "const SWISS_GEO = ")
    cantons = read_app_js_literal(app_lines, 3, "const CANTONS = ")
    with open(OSM_LAYERS, encoding="utf-8") as f:
        osm = json.load(f)
    waters = osm.get("waters", [])

    old_swiss = repair(shape(swiss_geo))
    old_points = len(swiss_geo["coordinates"][0])
    old_area_km2 = geodesic_area_km2(old_swiss)
    log(f"Old SWISS_GEO: {old_points} points, {old_area_km2:.0f} km^2")

    canton_geoms = [repair(shape(f["geometry"])) for f in cantons["features"]]
    canton_points = sum(
        len(f["geometry"]["coordinates"][0]) if f["geometry"]["type"] == "Polygon"
        else sum(len(part[0]) for part in f["geometry"]["coordinates"])
        for f in cantons["features"]
    )
    dissolved = repair(unary_union(canton_geoms))
    dissolved_area_km2 = geodesic_area_km2(dissolved)
    dissolved_parts = 1 if isinstance(dissolved, Polygon) else len(dissolved.geoms)
    log(f"CANTONS: 26 features, {canton_points} points, dissolved area {dissolved_area_km2:.0f} km^2 "
        f"({dissolved_parts} part(s) - lakes not in canton data can split shorelines apart; "
        f"expected to reconnect once water is unioned back in)")

    # Holes in the dissolved cantons are overwhelmingly small lakes/ponds that
    # happen to sit fully inside one canton rather than splitting two apart -
    # those should just fill back in as ordinary in-bounds area (there are
    # ~289 of them; a "not covered by named water" heuristic still let
    # through ~180 spurious ones - unlabeled ponds/reservoirs OSM doesn't
    # carry - so it's not a reliable way to isolate the one hole that matters).
    # The only genuine foreign exclave is Campione d'Italia, so find its hole
    # by location instead of by a generic rule, and protect only that one.
    all_holes = collect_holes(dissolved)
    dissolved_filled = repair(exteriors_only(dissolved))

    by_name = {}
    for entry in waters:
        geom = water_geometry(entry)
        if geom is not None:
            by_name.setdefault(entry["n"], []).append(geom)

    clipped_waters = []
    lake_areas = {}
    for name, geoms in by_name.items():
        merged = repair(unary_union(geoms))
        clipped = repair(merged.intersection(old_swiss))
        if clipped.is_empty:
            continue
        clipped_waters.append(clipped)
        if name in LAKE_NAMES:
            lake_areas[name] = geodesic_area_km2(clipped)

    log(f"Water entries clipped against old outline: {len(clipped_waters)} (of {len(by_name)} named)")
    for name in LAKE_NAMES:
        if name in lake_areas:
            log(f"  {name}: {lake_areas[name]:.1f} km^2 (Swiss-side, clipped)")
        else:
            log(f"  {name}: NOT FOUND in clipped water set - check data/osm-layers.json")

    foreign_holes = []
    if all_holes:
        nearest = min(all_holes, key=lambda h: h.distance(CAMPIONE_NEAR))
        nearest_dist_deg = nearest.distance(CAMPIONE_NEAR)
        nearest_area_km2 = geodesic_area_km2(nearest)
        if nearest_dist_deg < 0.05 and 0.3 <= nearest_area_km2 <= 5:
            foreign_holes = [nearest]
            log(f"Campione d'Italia hole located: {nearest_area_km2:.2f} km^2, "
                f"centroid {nearest.centroid.y:.4f},{nearest.centroid.x:.4f}")
        else:
            log(f"WARNING: no plausible Campione d'Italia hole found near "
                f"{CAMPIONE_NEAR.y:.4f},{CAMPIONE_NEAR.x:.4f} (nearest candidate: "
                f"{nearest_area_km2:.2f} km^2, {nearest_dist_deg:.4f} deg away) - check CANTONS data.")

    raw_combined = repair(unary_union([dissolved_filled] + clipped_waters))
    raw_area_km2 = geodesic_area_km2(raw_combined)
    raw_parts = 1 if isinstance(raw_combined, Polygon) else len(raw_combined.geoms)
    log(f"Combined (pre-closing, holes filled) area: {raw_area_km2:.0f} km^2 ({raw_parts} part(s))")

    combined_lv95 = to_lv95(raw_combined)
    closed_lv95 = repair(combined_lv95.buffer(CLOSE_GAP_M).buffer(-CLOSE_GAP_M))
    simplified_lv95 = closed_lv95.simplify(SIMPLIFY_TOLERANCE_M, preserve_topology=True)
    filled_simplified = as_single_polygon(to_wgs84(simplified_lv95), "post-closing-and-simplify")
    if not filled_simplified.is_valid:
        filled_simplified = as_single_polygon(repair(filled_simplified), "post-simplify-repaired")

    # dissolved_filled and clipped_waters are both hole-free by construction, so
    # any hole surviving here is a gap between the two datasets that the
    # closing step above was too conservative to bridge (found in practice
    # along part of the Bodensee shore, near the diplomatically undefined
    # Swiss/German/Austrian line in the lake - real dataset disagreement, not
    # a sliver, so no reasonable closing radius fixes it without also
    # coarsening the outline well past the ~100 m target elsewhere). None of
    # these gaps are intentional exclusions - Campione d'Italia is the only
    # deliberate hole, carved back in explicitly right below - so force every
    # other hole shut before that carve.
    stray_holes = len(filled_simplified.interiors)
    if stray_holes:
        stray_area_km2 = sum(geodesic_area_km2(Polygon(r)) for r in filled_simplified.interiors)
        log(f"Filling {stray_holes} stray gap(s) ({stray_area_km2:.2f} km^2) between the canton and "
            f"water datasets that the closing step didn't bridge - not intentional exclusions")
        filled_simplified = Polygon(filled_simplified.exterior)

    if foreign_holes:
        holes_lv95 = to_lv95(repair(unary_union(foreign_holes)))
        holes_simplified = to_wgs84(holes_lv95.simplify(SIMPLIFY_TOLERANCE_M, preserve_topology=True))
        simplified = as_single_polygon(repair(filled_simplified.difference(holes_simplified)), "post-hole-carve")
    else:
        simplified = filled_simplified

    new_points = len(simplified.exterior.coords) + sum(len(r.coords) for r in simplified.interiors)
    new_area_km2 = geodesic_area_km2(simplified)
    log(f"New SWISS_GEO: {new_points} points ({len(simplified.interiors)} hole(s)), {new_area_km2:.0f} km^2")

    log("")
    log("Containment checks (post-simplify):")
    all_ok = True

    if foreign_holes:
        campione_hole = foreign_holes[0]
        rep = campione_hole.representative_point()
        inside = simplified.covers(rep)
        ok = not inside
        all_ok = all_ok and ok
        log(f"  Campione d'Italia ({geodesic_area_km2(campione_hole):.2f} km^2, "
            f"representative point {rep.y:.5f},{rep.x:.5f}): {'inside' if inside else 'outside'} - "
            f"{'OK' if ok else 'FAIL (expected outside)'}")
    else:
        log("  Campione d'Italia: FAIL (no foreign holes survived - hole detection found nothing)")
        all_ok = False

    for lake_name in LAKE_NAMES:
        if lake_name not in by_name:
            log(f"  {lake_name}: SKIP (not in data/osm-layers.json)")
            all_ok = False
            continue
        merged = repair(unary_union(by_name[lake_name]))
        clipped = repair(merged.intersection(old_swiss))
        if clipped.is_empty:
            log(f"  {lake_name}: SKIP (empty after clip)")
            all_ok = False
            continue
        rep = clipped.representative_point()
        inside = simplified.covers(rep)
        all_ok = all_ok and inside
        log(f"  {lake_name} representative point ({rep.y:.5f},{rep.x:.5f}): "
            f"{'inside' if inside else 'OUTSIDE'} - {'OK' if inside else 'FAIL (expected inside)'}")

    for name, lat, lng, expect_inside in TEST_POINTS:
        pt = Point(lng, lat)
        inside = simplified.covers(pt)
        ok = inside == expect_inside
        all_ok = all_ok and ok
        expect_word = "inside" if expect_inside else "outside"
        actual_word = "inside" if inside else "outside"
        status = "OK" if ok else f"FAIL (expected {expect_word})"
        log(f"  {name} ({lat},{lng}): {actual_word} - {status}")

    area_ok = abs(new_area_km2 - 41285) < 300
    all_ok = all_ok and area_ok
    log("")
    log(f"Area check: {new_area_km2:.0f} km^2 (target ~41,285 km^2, {'OK' if area_ok else 'CHECK'})")

    if not all_ok:
        log("")
        log("FAILED one or more checks - not writing app.js. Investigate before re-running.")
        finish(False)
        return

    new_geojson = polygon_to_geojson(simplified)
    new_literal = "const SWISS_GEO = " + json.dumps(new_geojson, separators=(",", ":")) + ";\n"
    app_lines[0] = new_literal
    with open(APP_JS, "w", encoding="utf-8", newline="") as f:
        f.writelines(app_lines)
    log("")
    log(f"Wrote new SWISS_GEO to {APP_JS} (line 1 only, {old_points} -> {new_points} points, "
        f"{old_area_km2:.0f} -> {new_area_km2:.0f} km^2).")
    finish(True)


if __name__ == "__main__":
    main()
