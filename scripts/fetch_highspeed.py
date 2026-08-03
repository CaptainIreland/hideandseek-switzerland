#!/usr/bin/env python3
"""Fetch high-speed rail line geometry from OpenStreetMap.

Usage, from the repository root:

    python scripts/fetch_highspeed.py

Writes data/highspeed-lines.json, which the app loads automatically, and
data/highspeed-report.txt, a human-readable audit trail. Free, no key.

This replaces a hand-maintained file that described five named lines as
2-3 straight waypoints each - fine for a rough "am I near this line"
answer, wrong for the measuring question, which buffers the exact geometry
by the asker's own distance. A straight chord through a tunnel that
actually curves puts that buffer several km off the real alignment.

The other problem with a hand-maintained list of named lines is that speed
is a property of track segments, not of named lines. The Solothurn-Wanzwil
line runs at 140 km/h from Solothurn to Subingen and only reaches 200 km/h
after that, so treating the whole named line as one high-speed entity was
wrong under any definition. This script queries OpenStreetMap way by way -
railway=rail ways tagged highspeed=yes, or with a maxspeed (including
direction-specific maxspeed:forward/maxspeed:backward, and semicolon-
separated multi-values) reaching RAIL_MIN_KMH - then merges touching
qualifying ways into continuous lines. A non-qualifying way in between
(like Solothurn-Subingen) is simply never fetched, so it breaks the chain
by construction rather than needing to be special-cased.

RAIL_MIN_KMH is the "official" threshold dial, same MIN_ELEVATION/
MIN_REVIEWS convention used elsewhere in scripts/: change it and re-run
for free, no fresh sweep needed since the query already fetches everything
tagged highspeed=yes or carrying any maxspeed tag with a 200-999 km/h
reading, wider than the default 200 km/h cut, so lowering the constant
alone is enough (raising it above what the query's regex prefilter allows
would need the query widened too).

Merging is topological (touching endpoints), never by name, since a named
line can span mixed-speed track - that is the exact bug being fixed. At a
genuine branch point (a Y-junction), first-match-wins chaining produces
two output lines that meet at a shared coordinate rather than one line
trying to represent a fork. That is correct, not a bug: a fork cannot be
one continuous line. Do not "fix" this by trying to force a single chain
through a branch.
"""
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(BASE_DIR, "data", "highspeed-lines.json")
REPORT_PATH = os.path.join(BASE_DIR, "data", "highspeed-report.txt")
STATIONS_PATH = os.path.join(BASE_DIR, "data", "stations.json")

RAIL_MIN_KMH = 200  # highspeed=yes always qualifies regardless of this value
EXCLUDED_SERVICE = {"siding", "yard", "spur", "crossover"}
RAIL_SIMPLIFY_DEGREES = 0.00007  # about 6-7 m, tight enough to keep real tunnel curvature
SHORT_LINE_KM = 0.5  # merged lines under this are flagged in the report, not dropped
FAR_FROM_STATION_KM = 5.0  # endpoint this far from any Swiss station may have crossed the border

ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": "hideandseek-switzerland-fieldmap/1.0 (Jet Lag fan project)",
}

# The regex prefilter is deliberately loose (any 3-digit 200-999 run anywhere
# in the tag value, unanchored so "200 km/h" and the "200" inside "160;200"
# both match) - it only trims the fetch, real qualification happens in
# Python via parse_maxspeed()/qualifies() below, since Overpass's (if:)/
# number() evaluator is a newer QL feature not guaranteed to behave
# identically across three independently-run mirrors.
HIGHSPEED_QUERY = (
    '[out:json][timeout:300];'
    'area["ISO3166-1"="CH"][admin_level=2]->.ch;'
    '('
    'way["railway"="rail"]["highspeed"="yes"](area.ch);'
    'way["railway"="rail"]["maxspeed"~"[2-9][0-9]{2}"](area.ch);'
    'way["railway"="rail"]["maxspeed:forward"~"[2-9][0-9]{2}"](area.ch);'
    'way["railway"="rail"]["maxspeed:backward"~"[2-9][0-9]{2}"](area.ch);'
    ');'
    'out geom;'
)


def run(query, label):
    body = urllib.parse.urlencode({"data": query}).encode()
    for attempt in range(2):
        for url in ENDPOINTS:
            try:
                print(f"  {label}: asking {url.split('/')[2]} ...", flush=True)
                request = urllib.request.Request(url, data=body, headers=HEADERS)
                with urllib.request.urlopen(request, timeout=300) as response:
                    return json.load(response)
            except Exception as error:
                print(f"    failed: {error}", file=sys.stderr)
        if attempt == 0:
            print("  All endpoints failed once. Waiting 20 seconds.", file=sys.stderr)
            time.sleep(20)
    return None


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def simplify(points, epsilon):
    """Ramer-Douglas-Peucker, iterative so a long line cannot blow the stack."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        start, end = stack.pop()
        if end <= start + 1:
            continue
        x1, y1 = points[start]
        x2, y2 = points[end]
        dx, dy = x2 - x1, y2 - y1
        denom = (dx * dx + dy * dy) ** 0.5
        worst, index = 0.0, start
        for i in range(start + 1, end):
            x, y = points[i]
            if denom == 0:
                dist = ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
            else:
                dist = abs(dy * x - dx * y + x2 * y1 - y2 * x1) / denom
            if dist > worst:
                worst, index = dist, i
        if worst > epsilon:
            keep[index] = True
            stack.append((start, index))
            stack.append((index, end))
    return [p for p, k in zip(points, keep) if k]


def raw_points(geometry):
    return [[p["lon"], p["lat"]] for p in geometry if "lat" in p]


def parse_maxspeed(tags):
    candidates = []
    for key in ("maxspeed", "maxspeed:forward", "maxspeed:backward"):
        raw = tags.get(key)
        if not raw:
            continue
        for chunk in re.split(r"[;,]", raw):
            m = re.match(r"\s*(\d+(?:\.\d+)?)\s*(mph)?", chunk)
            if not m:
                continue
            value = float(m.group(1))
            if m.group(2) == "mph":
                value *= 1.60934
            candidates.append(value)
    return max(candidates) if candidates else None


def qualifies(tags, speed):
    if tags.get("service") in EXCLUDED_SERVICE:
        return False
    return tags.get("highspeed") == "yes" or (speed is not None and speed >= RAIL_MIN_KMH)


def line_length_km(points):
    return sum(
        haversine_km(points[i][1], points[i][0], points[i + 1][1], points[i + 1][0])
        for i in range(len(points) - 1)
    )


def parse_elements(data):
    segments = []
    seen_ids = set()
    excluded_service = 0
    excluded_speed = 0
    for element in data.get("elements", []):
        if element.get("type") != "way":
            continue
        way_id = element.get("id")
        if way_id in seen_ids:
            continue
        tags = element.get("tags") or {}
        speed = parse_maxspeed(tags)
        if tags.get("service") in EXCLUDED_SERVICE:
            excluded_service += 1
            continue
        if not qualifies(tags, speed):
            excluded_speed += 1
            continue
        points = raw_points(element.get("geometry") or [])
        if len(points) < 2:
            continue
        seen_ids.add(way_id)
        segments.append({
            "id": way_id,
            "points": points,
            "name": (tags.get("name") or "").strip(),
            "maxspeed": speed,
            "highspeed": tags.get("highspeed") == "yes",
        })
    return segments, excluded_service, excluded_speed


def reversed_seg(seg):
    return {**seg, "points": list(reversed(seg["points"]))}


def merge_open_lines(segments):
    """Chain way segments that share endpoints into continuous open lines.

    Adapted from fetch_osm_layers.py's stitch_rings(), which chains water-
    polygon boundary ways the same way but then forces closure into a ring.
    A railway has two distinct ends, so that closing step is removed here -
    a chain simply stops growing once no remaining segment matches either
    end, and is emitted open.
    """
    remaining = list(segments)
    chains = []
    while remaining:
        chain = [remaining.pop(0)]
        progressed = True
        while progressed:
            progressed = False
            head, tail = chain[0]["points"][0], chain[-1]["points"][-1]
            for i, seg in enumerate(remaining):
                p = seg["points"]
                if p[0] == tail:
                    chain.append(seg)
                elif p[-1] == tail:
                    chain.append(reversed_seg(seg))
                elif p[-1] == head:
                    chain.insert(0, seg)
                elif p[0] == head:
                    chain.insert(0, reversed_seg(seg))
                else:
                    continue
                remaining.pop(i)
                progressed = True
                break
        chains.append(chain)
    return chains


def chain_points(chain):
    points = list(chain[0]["points"])
    for seg in chain[1:]:
        points.extend(seg["points"][1:])
    return points


def chain_name(chain):
    named = [(seg["name"], line_length_km(seg["points"])) for seg in chain if seg["name"]]
    if not named:
        return None
    best_len = max(length for _, length in named)
    candidates = sorted(name for name, length in named if length == best_len)
    return candidates[0]


def build_lines(segments):
    chains = merge_open_lines(segments)
    lines = []
    for chain in chains:
        points = chain_points(chain)
        simplified = simplify(points, RAIL_SIMPLIFY_DEGREES)
        if len(simplified) < 2:
            simplified = points
        speeds = [seg["maxspeed"] for seg in chain if seg["maxspeed"] is not None]
        max_kmh = max(speeds) if speeds else None
        min_kmh = min(speeds) if speeds else None
        lines.append({
            "name": chain_name(chain),
            "category": "purpose-built" if any(seg["highspeed"] for seg in chain) else "upgraded",
            "maxKmh": int(round(max_kmh)) if max_kmh is not None else None,
            "minKmh": int(round(min_kmh)) if min_kmh is not None else None,
            "lengthKm": round(line_length_km(points), 2),
            "wayCount": len(chain),
            "points": [[round(x, 5), round(y, 5)] for x, y in simplified],
        })
    lines.sort(key=lambda l: -l["lengthKm"])
    return lines


def load_stations():
    if not os.path.exists(STATIONS_PATH):
        return []
    with open(STATIONS_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def nearest_station(lat, lng, stations):
    if not stations:
        return None, None
    name, s_lat, s_lng = min(stations, key=lambda s: haversine_km(lat, lng, s[1], s[2]))
    return name, haversine_km(lat, lng, s_lat, s_lng)


def write_report(lines, segment_count, excluded_service, excluded_speed, stations):
    total_km = sum(l["lengthKm"] for l in lines)
    report = [
        "=== HIGH-SPEED RAIL (OpenStreetMap) ===",
        f"Threshold: highspeed=yes OR maxspeed >= {RAIL_MIN_KMH} km/h, applied per OSM way before merging.",
        f"Qualifying ways fetched (pre-merge): {segment_count}",
        f"Excluded (service=siding/yard/spur/crossover): {excluded_service}",
        f"Excluded (maxspeed present but below threshold, no highspeed=yes): {excluded_speed}",
        f"Merged lines: {len(lines)}",
        f"Total length: {total_km:.1f} km",
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
        if line["maxKmh"] is None:
            speed_txt = "speed unknown (highspeed=yes)"
        elif line["minKmh"] != line["maxKmh"]:
            speed_txt = f"{line['minKmh']}-{line['maxKmh']} km/h"
        else:
            speed_txt = f"{line['maxKmh']} km/h"
        report.append(
            f"  - {label}: {line['lengthKm']:.1f} km, {line['wayCount']} ways, {speed_txt}, "
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
    print("Fetching high-speed rail geometry from OpenStreetMap.")
    data = run(HIGHSPEED_QUERY, "highspeed")
    if not data:
        sys.exit("Could not reach OpenStreetMap for high-speed rail. Try again shortly.")

    segments, excluded_service, excluded_speed = parse_elements(data)
    print(f"  {len(segments)} qualifying ways "
          f"(excluded {excluded_service} service, {excluded_speed} below threshold)")
    if not segments:
        sys.exit("No qualifying rail ways found. Check the query or RAIL_MIN_KMH.")

    lines = build_lines(segments)
    total_km = sum(l["lengthKm"] for l in lines)
    print(f"  merged into {len(lines)} lines, {total_km:.1f} km total")

    payload = {
        "source": "OpenStreetMap contributors, via scripts/fetch_highspeed.py",
        "note": (
            "Not Google-verified (Google has no rail-line-path data). Threshold: highspeed=yes or "
            f"maxspeed>={RAIL_MIN_KMH} km/h, applied per OSM way before merging, so status can change "
            "mid-corridor (Solothurn-Subingen at 140 km/h is excluded while Subingen-Wanzwil at 200 km/h "
            "is kept as its own line) instead of one hand-picked corridor spanning mixed-speed track."
        ),
        "thresholdKmh": RAIL_MIN_KMH,
        "lines": lines,
    }
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
    size = os.path.getsize(OUT_PATH)
    print(f"\nWrote {OUT_PATH} ({size:,} bytes)")

    stations = load_stations()
    if not stations:
        print(f"  Warning: {STATIONS_PATH} not found, report will skip nearest-station labels.",
              file=sys.stderr)
    write_report(lines, len(segments), excluded_service, excluded_speed, stations)
    print(f"Wrote {REPORT_PATH}")

    if lines:
        print("\nLongest lines:")
        for line in lines[:8]:
            print(f"  {line['name'] or '(unnamed)'}: {line['lengthKm']:.1f} km, {line['maxKmh']} km/h")


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
