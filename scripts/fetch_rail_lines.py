#!/usr/bin/env python3
"""Fetch the full Swiss passenger rail network's geometry from OpenStreetMap.

Usage, from the repository root:

    python scripts/fetch_rail_lines.py

Writes data/rail-lines.json, which the app loads automatically, and
data/rail-lines-report.txt, a human-readable audit trail. Free, no key.

This is a companion to fetch_highspeed.py, not a replacement: highspeed-
lines.json stays as the narrow, speed-qualified dataset the "measure to a
high-speed line" clue depends on, and this script produces a separate,
much larger "every line, not just the fast ones" dataset for the "which
rail lines currently run through the possible area" map layer.

data/transit-lines.json (GTFS-derived) was the first thing tried for that
layer, since it already carries agency/line-code identity - but the
official Swiss GTFS feed (data.opentransportdata.swiss) turns out to have
no shapes.txt and no shape_id column on trips.txt, so it has no route
geometry to give, only station-name sequences. OSM is the only source of
real track paths available here, at the cost of losing GTFS's named-line
identity: an OSM way only says what physical track it is, not which
timetabled line runs over it, so lines in this file are anonymous merged
chains (occasionally OSM's own railway=* name tag survives, in which case
it is kept), not "S3" or "IC1".

Reuses fetch_highspeed.py's Overpass-fetch, merge and RDP-simplify
machinery unchanged (see that file for why merging is topological, at
shared way endpoints, never by name). The only real difference is the
query: no highspeed=yes/maxspeed filter, and both railway=rail (standard
gauge) and railway=narrow_gauge, since Switzerland's narrow-gauge networks
(RhB, Matterhorn Gotthard Bahn, MOB, Zentralbahn, Appenzeller Bahnen, BOB's
main network) are ordinary Interrail-covered regional railways under house
rule 5 in CLAUDE.md, not excursion-only track.

Scope gap: house rule 5's excursion/charter-only exclusion list (Gornergrat,
Jungfrau, Rigi, Pilatus, Brienz Rothorn, Furka-Bergstrecke, the Schynige
Platte branch, and so on) was built by cross-referencing GTFS agency/route
data against data/stations.json (see scripts/audit_private_railways.py),
which only makes sense for point data. There is no equivalent cross-
reference here: an OSM way carries no GTFS route information, so this
script cannot tell a cog railway up to an excursion summit from an ordinary
regional line by its tags alone. Those excursion-only lines are included in
data/rail-lines.json, unlike the stations they serve. This is a visual aid,
not a new clue type or a change to station eligibility, so a heritage line
being drawn on the map is a minor inconsistency rather than a correctness
bug - accepted as a gap rather than chased by hand-listing excluded ways.
"""
import json
import os
import sys

from fetch_highspeed import (
    ENDPOINTS,
    EXCLUDED_SERVICE,
    HEADERS,
    RAIL_SIMPLIFY_DEGREES,
    chain_name,
    chain_points,
    haversine_km,
    line_length_km,
    load_stations,
    merge_open_lines,
    nearest_station,
    raw_points,
    run,
    simplify,
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(BASE_DIR, "data", "rail-lines.json")
REPORT_PATH = os.path.join(BASE_DIR, "data", "rail-lines-report.txt")

SHORT_LINE_KM = 0.5  # merged lines under this are flagged in the report, not dropped
FAR_FROM_STATION_KM = 5.0  # endpoint this far from any Swiss station may have crossed the border

RAIL_NETWORK_QUERY = (
    '[out:json][timeout:400];'
    'area["ISO3166-1"="CH"][admin_level=2]->.ch;'
    '('
    'way["railway"="rail"](area.ch);'
    'way["railway"="narrow_gauge"](area.ch);'
    ');'
    'out geom;'
)


def parse_elements(data):
    segments = []
    seen_ids = set()
    excluded_service = 0
    for element in data.get("elements", []):
        if element.get("type") != "way":
            continue
        way_id = element.get("id")
        if way_id in seen_ids:
            continue
        tags = element.get("tags") or {}
        if tags.get("service") in EXCLUDED_SERVICE:
            excluded_service += 1
            continue
        points = raw_points(element.get("geometry") or [])
        if len(points) < 2:
            continue
        seen_ids.add(way_id)
        segments.append({
            "id": way_id,
            "points": points,
            "name": (tags.get("name") or "").strip(),
            "narrowGauge": tags.get("railway") == "narrow_gauge",
        })
    return segments, excluded_service


def build_lines(segments):
    chains = merge_open_lines(segments)
    lines = []
    for chain in chains:
        points = chain_points(chain)
        simplified = simplify(points, RAIL_SIMPLIFY_DEGREES)
        if len(simplified) < 2:
            simplified = points
        lines.append({
            "name": chain_name(chain),
            "gauge": "narrow" if all(seg["narrowGauge"] for seg in chain) else "standard",
            "lengthKm": round(line_length_km(points), 2),
            "wayCount": len(chain),
            "points": [[round(x, 5), round(y, 5)] for x, y in simplified],
        })
    lines.sort(key=lambda l: -l["lengthKm"])
    return lines


def write_report(lines, segment_count, excluded_service, stations):
    total_km = sum(l["lengthKm"] for l in lines)
    narrow_km = sum(l["lengthKm"] for l in lines if l["gauge"] == "narrow")
    report = [
        "=== SWISS RAIL NETWORK, ALL LINES (OpenStreetMap) ===",
        "Every railway=rail or railway=narrow_gauge way, merged at shared endpoints. "
        "No speed filter (contrast data/highspeed-lines.json) and no GTFS cross-reference "
        "(contrast data/transit-lines.json) - see this script's docstring for both gaps.",
        f"Qualifying ways fetched (pre-merge): {segment_count}",
        f"Excluded (service=siding/yard/spur/crossover): {excluded_service}",
        f"Merged lines: {len(lines)}",
        f"Total length: {total_km:.1f} km ({narrow_km:.1f} km narrow gauge)",
        "",
        "Lines (longest first), endpoints labelled with nearest station:",
    ]
    flagged_short = []
    flagged_far = []
    for line in lines:
        pts = line["points"]
        start_name, start_km = nearest_station(pts[0][1], pts[0][0], stations)
        end_name, end_km = nearest_station(pts[-1][1], pts[-1][0], stations)
        label = line["name"] or "(unnamed)"
        report.append(
            f"  - {label}: {line['lengthKm']:.1f} km, {line['wayCount']} ways, {line['gauge']} gauge, "
            f"nearest stations {start_name or '?'} ({start_km:.1f} km) / {end_name or '?'} ({end_km:.1f} km)"
        )
        if line["lengthKm"] < SHORT_LINE_KM or not line["name"]:
            flagged_short.append(f"{label} ({line['lengthKm']:.2f} km)")
        if (start_km and start_km > FAR_FROM_STATION_KM) or (end_km and end_km > FAR_FROM_STATION_KM):
            flagged_far.append(f"{label}: {start_km:.1f} km / {end_km:.1f} km from nearest station")
    if flagged_short:
        report += ["", f"Flagged for manual review, unnamed or under {SHORT_LINE_KM} km ({len(flagged_short)}):"]
        report += [f"  - {f}" for f in flagged_short]
    if flagged_far:
        report += ["", f"Flagged: an endpoint over {FAR_FROM_STATION_KM} km from any Swiss station, "
                        f"possibly crossed the border ({len(flagged_far)}):"]
        report += [f"  - {f}" for f in flagged_far]
    report.append("=== END ===")
    with open(REPORT_PATH, "w", encoding="utf-8") as handle:
        handle.write("\n".join(report) + "\n")


def main():
    print("Fetching the full Swiss rail network's geometry from OpenStreetMap.")
    data = run(RAIL_NETWORK_QUERY, "rail-network")
    if not data:
        sys.exit("Could not reach OpenStreetMap for the rail network. Try again shortly.")

    segments, excluded_service = parse_elements(data)
    print(f"  {len(segments)} qualifying ways (excluded {excluded_service} service)")
    if not segments:
        sys.exit("No qualifying rail ways found. Check the query.")

    lines = build_lines(segments)
    total_km = sum(l["lengthKm"] for l in lines)
    print(f"  merged into {len(lines)} lines, {total_km:.1f} km total")

    payload = {
        "source": "OpenStreetMap contributors, via scripts/fetch_rail_lines.py",
        "note": (
            "Not Google-verified (Google has no rail-line-path data). Every railway=rail or "
            "railway=narrow_gauge way, no speed threshold - contrast data/highspeed-lines.json, "
            "which only carries the speed-qualified subset for the measuring clue. Lines are "
            "anonymous merged OSM way chains, not matched to a GTFS agency/line code."
        ),
        "lines": lines,
    }
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
    size = os.path.getsize(OUT_PATH)
    print(f"\nWrote {OUT_PATH} ({size:,} bytes)")

    stations = load_stations()
    if not stations:
        print(f"  Warning: stations file not found, report will skip nearest-station labels.",
              file=sys.stderr)
    write_report(lines, len(segments), excluded_service, stations)
    print(f"Wrote {REPORT_PATH}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as error:
        if str(error):
            print(error)
    except Exception:
        import traceback
        traceback.print_exc()
    finally:
        try:
            input("\nPress Enter to close this window.")
        except EOFError:
            pass
