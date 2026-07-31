#!/usr/bin/env python3
"""Refresh the Swiss station list from OpenStreetMap and audit the result.

Usage, from the repository root:

    python3 scripts/fetch_stations.py [output_path]

Fetches every railway station and halt in Switzerland via the Overpass API
(application programming interface), applies the game's filters, audits the
result against the pinned core list in data/stations-core.json, prints the
audit, and writes data/stations.json. Review the audit before committing.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from google_sweep import dist_km

QUERY = (
    '[out:json][timeout:90];'
    'area["ISO3166-1"="CH"][admin_level=2]->.ch;'
    '(node["railway"~"^(station|halt)$"](area.ch);'
    'way["railway"~"^(station|halt)$"](area.ch););'
    'out center tags;'
)
ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": "hideandseek-switzerland-fieldmap/1.0 (Jet Lag fan project)",
}
EXCLUDE_STATION = {"subway", "funicular", "monorail"}
COUNT_WINDOW = (1500, 2300)  # Switzerland has roughly 1,800 railway stops
CORE_PATH = "data/stations-core.json"


def keep(tags):
    if tags.get("station") in EXCLUDE_STATION:
        return False
    if tags.get("railway") == "tram_stop":
        return False
    if tags.get("disused") == "yes" or tags.get("abandoned") == "yes" or tags.get("razed") == "yes":
        return False
    return True


def parse(data):
    by_name = {}
    out = []
    for element in data.get("elements", []):
        tags = element.get("tags") or {}
        if not keep(tags):
            continue
        lat = element.get("lat")
        lon = element.get("lon")
        if lat is None or lon is None:
            centre = element.get("center") or {}
            lat = centre.get("lat")
            lon = centre.get("lon")
        if lat is None or lon is None:
            continue
        name = (tags.get("name") or tags.get("name:de") or tags.get("name:fr")
                or tags.get("name:it") or "")
        key = name.strip().lower()
        kept = by_name.setdefault(key, [])
        if any(dist_km((lat, lon), p) < 0.3 for p in kept):
            continue
        kept.append((lat, lon))
        out.append([name, round(lat, 6), round(lon, 6)])
    return out


def fetch():
    body = urllib.parse.urlencode({"data": QUERY}).encode()
    for attempt in range(2):
        for url in ENDPOINTS:
            try:
                request = urllib.request.Request(url, data=body, headers=HEADERS)
                with urllib.request.urlopen(request, timeout=120) as response:
                    return json.load(response)
            except Exception as error:
                print(f"Endpoint failed ({url}): {error}", file=sys.stderr)
        if attempt == 0:
            print("All endpoints failed once. Waiting 15 seconds, then retrying.", file=sys.stderr)
            time.sleep(15)
    return None


def audit(stations, core):
    names = {s[0].strip().lower() for s in stations}
    points = [(s[1], s[2]) for s in stations]
    matched, missing = 0, []
    for name, lat, lon in core:
        if name.strip().lower() in names:
            matched += 1
        elif any(dist_km((lat, lon), p) < 0.3 for p in points):
            matched += 1
        else:
            missing.append(name)
    core_names = {c[0].strip().lower() for c in core}
    core_points = [(c[1], c[2]) for c in core]
    extra = [s for s in stations
             if s[0].strip().lower() not in core_names
             and not any(dist_km((s[1], s[2]), p) < 0.3 for p in core_points)]
    print("")
    print("=== STATION AUDIT ===")
    print(f"OpenStreetMap result: {len(stations)} stations and halts")
    lo, hi = COUNT_WINDOW
    if not (lo <= len(stations) <= hi):
        print(f"WARNING: outside the expected window of {lo} to {hi}. Investigate before committing.")
    print(f"Core coverage: {matched} of {len(core)} major stations matched")
    if missing:
        print(f"MISSING from OpenStreetMap result ({len(missing)}), investigate these:")
        for name in sorted(missing)[:50]:
            print(f"  - {name}")
    else:
        print("Every core station is present. Good sign.")
    print(f"Beyond the core: {len(extra)} additional stations and halts (expected, the core is only the major ones)")
    sample = sorted(s[0] for s in extra[:2000])[:15]
    print("Sample of additions:", ", ".join(sample))
    print("=== END AUDIT ===")
    print("")


def main():
    output_path = sys.argv[1] if len(sys.argv) > 1 else "data/stations.json"
    data = fetch()
    if not data:
        sys.exit("All Overpass endpoints failed. Try again in a few minutes.")
    stations = parse(data)
    core = []
    if os.path.exists(CORE_PATH):
        core = json.load(open(CORE_PATH, encoding="utf-8"))
    else:
        print(f"Note: {CORE_PATH} not found, skipping the audit.")
    if core:
        audit(stations, core)
    if len(stations) < COUNT_WINDOW[0]:
        sys.exit(f"Only {len(stations)} stations returned, which looks wrong. Not writing.")
    directory = os.path.dirname(output_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(stations, handle, ensure_ascii=False, separators=(",", ":"))
    print(f"Wrote {len(stations)} stations to {output_path}")


if __name__ == "__main__":
    main()
