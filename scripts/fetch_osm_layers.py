#!/usr/bin/env python3
"""Fetch the layers Google does not provide: mountain peaks and water bodies.

Usage, from the repository root:

    python scripts/fetch_osm_layers.py

Writes data/osm-layers.json, which the app loads automatically. Everything from
this file is labelled in the interface as not Google-verified, because the house
rule makes Google Maps the arbiter and OpenStreetMap will sometimes disagree
with it. Treat these answers as a guide and settle disputes on Google Maps.

Peaks are filtered by elevation. The default keeps peaks at 2000 m and above,
which is roughly what a mapping app shows at a normal zoom. Change MIN_ELEVATION
below and re-run if your group wants a different bar.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(BASE_DIR, "data", "osm-layers.json")
MIN_ELEVATION = 2000  # metres
MIN_WATER_POINTS = 8  # ignore ponds mapped with a handful of nodes

ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": "hideandseek-switzerland-fieldmap/1.0 (Jet Lag fan project)",
}
PEAKS_QUERY = (
    '[out:json][timeout:180];'
    'area["ISO3166-1"="CH"][admin_level=2]->.ch;'
    'node["natural"="peak"]["name"](area.ch);'
    'out tags;'
)
WATER_QUERY = (
    '[out:json][timeout:300];'
    'area["ISO3166-1"="CH"][admin_level=2]->.ch;'
    '('
    'way["natural"="water"]["name"]["water"!="pond"](area.ch);'
    'relation["natural"="water"]["name"]["water"!="pond"](area.ch);'
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


def parse_peaks(data):
    out, seen = [], set()
    for element in data.get("elements", []):
        tags = element.get("tags") or {}
        name = (tags.get("name") or "").strip()
        lat, lon = element.get("lat"), element.get("lon")
        if not name or lat is None or lon is None:
            continue
        raw = (tags.get("ele") or "").replace(",", ".").split()[0:1]
        try:
            elevation = float(raw[0]) if raw else 0.0
        except ValueError:
            elevation = 0.0
        if elevation < MIN_ELEVATION:
            continue
        key = (name.lower(), round(lat, 3), round(lon, 3))
        if key in seen:
            continue
        seen.add(key)
        out.append([name, round(lat, 5), round(lon, 5), round(elevation)])
    out.sort(key=lambda r: -r[3])
    return out


def ring_from(geometry):
    ring = [[round(p["lon"], 4), round(p["lat"], 4)] for p in geometry if "lat" in p]
    if len(ring) < 4:
        return None
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring


def parse_water(data):
    out, seen = [], set()
    for element in data.get("elements", []):
        tags = element.get("tags") or {}
        name = (tags.get("name") or "").strip()
        if not name:
            continue
        rings = []
        if element.get("type") == "way":
            ring = ring_from(element.get("geometry") or [])
            if ring:
                rings.append(ring)
        else:
            for member in element.get("members") or []:
                if member.get("role") == "outer":
                    ring = ring_from(member.get("geometry") or [])
                    if ring:
                        rings.append(ring)
        rings = [r for r in rings if len(r) >= MIN_WATER_POINTS]
        if not rings:
            continue
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        out.append({"n": name, "r": rings})
    out.sort(key=lambda r: -sum(len(x) for x in r["r"]))
    return out


def main():
    print("Fetching mountain peaks and water bodies from OpenStreetMap.")
    peaks_raw = run(PEAKS_QUERY, "peaks")
    if not peaks_raw:
        sys.exit("Could not reach OpenStreetMap for peaks. Try again shortly.")
    peaks = parse_peaks(peaks_raw)
    print(f"  peaks: {len(peaks)} at or above {MIN_ELEVATION} m")

    water_raw = run(WATER_QUERY, "water")
    waters = parse_water(water_raw) if water_raw else []
    print(f"  water bodies: {len(waters)} named")
    if not waters:
        print("  Water fetch failed or returned nothing. Peaks will still be written.",
              file=sys.stderr)

    payload = {
        "source": "OpenStreetMap contributors",
        "note": "Not Google-verified. The house rule makes Google Maps the arbiter.",
        "minElevation": MIN_ELEVATION,
        "peaks": peaks,
        "waters": waters,
    }
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
    size = os.path.getsize(OUT_PATH) // 1024
    print(f"\nWrote {OUT_PATH} ({size} KB)")
    if peaks:
        print("Highest few:", ", ".join(f"{p[0]} ({p[3]} m)" for p in peaks[:5]))


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
