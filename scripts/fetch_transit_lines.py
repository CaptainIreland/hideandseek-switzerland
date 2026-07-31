#!/usr/bin/env python3
"""Build per-line station sequences from the official Swiss GTFS feed.

Usage, from the repository root:

    python scripts/fetch_transit_lines.py [--gtfs PATH] [--url URL]

Downloads the national GTFS timetable feed from data.opentransportdata.swiss
(about 200 MB) and extracts, for every rail line, the ordered list of
stations it stops at, matched to data/stations.json by name and then by
proximity. Writes data/transit-lines.json and data/transit-lines-report.txt.

This is for the "is the transit line you are on one that stops at my
station" question - not timetables, not full route geometry. In the app,
a line's clue region is the union of the hiding zones of the stations it
serves.

Adapted from a companion project's build_transit_data.py (Munich, GTFS ->
schematic tram/U-Bahn/bus route geometry for a small city play area). The
streaming approach for stop_times.txt carries over unchanged - that file
alone is about 2.5 GB uncompressed, so it is read row by row and never
extracted to disk. Everything else is different: Munich needed lat/lng
polylines clipped to a small zone; this needs named station sequences for
the whole country, matched against our own station list, with direction
collapsed out (which platform a line calls at does not change which
stations answer the yes/no question).

Rail only. GTFS Switzerland uses the extended route_type range 100-117
("Railway Service" and its subtypes: high speed, long distance, inter
regional, regional, S-Bahn, rack-and-pinion, tourist, sleeper, additional
rail) for every train operator. Tram is 900, metro is 401, bus is 700-715,
boat is 1000-1003, cable car is 1300s, funicular is 1400 - all excluded.
Widen RAIL_TYPES below if the group wants trams or the Lausanne metro
included later; that is a house-rule call, not a data one.

The feed's download URL is dated and changes twice a week, so DEFAULT_URL
below will eventually 404. To refresh it: open
https://data.opentransportdata.swiss/en/dataset/timetable-2026-gtfs2020,
open the newest GTFS_FP*.zip resource, and copy its download link, or pass
--url explicitly. --gtfs points at an already-downloaded zip and skips the
network entirely, for iterating on the matching logic without re-fetching
200 MB every run.

Free, no key. The raw zip is cached in a gitignored folder next to this
script's output (data/gtfs-cache/) - only the small derived
transit-lines.json is meant to be committed.
"""
import argparse
import csv
import io
import json
import math
import os
import sys
import time
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = BASE_DIR / "data" / "gtfs-cache"
STATIONS_PATH = BASE_DIR / "data" / "stations.json"
OUT_PATH = BASE_DIR / "data" / "transit-lines.json"
OUT_REPORT = BASE_DIR / "data" / "transit-lines-report.txt"

DEFAULT_URL = (
    "https://data.opentransportdata.swiss/dataset/3d2c18f9-9ef1-463f-a249-5c67604efd74"
    "/resource/940f970d-1ab6-4320-9c7e-f8dc5a2af48d/download/gtfs_fp2026_20260729.zip"
)

RAIL_TYPES = {str(t) for t in range(100, 118)}
MATCH_RADIUS_KM = 0.25  # proximity fallback when the name does not match exactly
MIN_LINE_STOPS = 2  # a "line" with fewer matched stations is not a usable clue


def download(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {url}\n  -> {dest}", flush=True)
    request = urllib.request.Request(url, headers={"User-Agent": "hideandseek-switzerland-fieldmap/1.0"})
    with urllib.request.urlopen(request, timeout=600) as response, open(dest, "wb") as out:
        total = int(response.headers.get("Content-Length", 0))
        read = 0
        chunk = response.read(1 << 20)
        while chunk:
            out.write(chunk)
            read += len(chunk)
            if total:
                print(f"\r  {read/1_048_576:,.0f} / {total/1_048_576:,.0f} MB", end="", flush=True)
            chunk = response.read(1 << 20)
    print()


def normalize(name):
    return " ".join(name.strip().casefold().split())


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def load_our_stations():
    stations = json.loads(STATIONS_PATH.read_text(encoding="utf-8"))
    by_name = {}
    for name, lat, lng in stations:
        by_name.setdefault(normalize(name), []).append((name, lat, lng))
    return stations, by_name


def build_matcher(stations, by_name):
    unmatched_counter = Counter()
    unmatched_pos = {}

    def match(name, lat, lng):
        key = normalize(name)
        candidates = by_name.get(key)
        if candidates:
            if len(candidates) == 1:
                return candidates[0][0]
            # Same name used twice in our own list: take the physically nearest.
            best = min(candidates, key=lambda c: haversine_km(lat, lng, c[1], c[2]))
            return best[0]
        if lat is not None and lng is not None:
            best_name, best_km = None, MATCH_RADIUS_KM
            for s_name, s_lat, s_lng in stations:
                km = haversine_km(lat, lng, s_lat, s_lng)
                if km < best_km:
                    best_km, best_name = km, s_name
            if best_name:
                return best_name
        unmatched_counter[name] += 1
        if lat is not None and lng is not None:
            unmatched_pos[name] = (lat, lng)
        return None

    def nearest_ch_km(lat, lng):
        return min(haversine_km(lat, lng, s_lat, s_lng) for _, s_lat, s_lng in stations)

    return match, unmatched_counter, unmatched_pos, nearest_ch_km


def dict_rows(archive, filename):
    with archive.open(filename) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
        yield from csv.DictReader(text)


def csv_rows(archive, filename):
    """Streams parsed CSV rows (as plain lists) without ever extracting the
    member to disk. Used for the two huge files instead of DictReader, which
    would otherwise build a dict per row for tens of millions of rows."""
    with archive.open(filename) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
        yield from csv.reader(text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gtfs", type=Path, help="Path to an already-downloaded GTFS zip, skips the download")
    parser.add_argument("--url", default=DEFAULT_URL, help="GTFS zip URL, only used without --gtfs")
    args = parser.parse_args()

    t0 = time.time()
    gtfs_path = args.gtfs
    if not gtfs_path:
        gtfs_path = CACHE_DIR / Path(args.url).name.split("?")[0]
        if not gtfs_path.exists():
            download(args.url, gtfs_path)
        else:
            print(f"Reusing cached {gtfs_path}")

    stations, by_name = load_our_stations()
    print(f"Loaded {len(stations)} of our own stations for matching.")

    with zipfile.ZipFile(gtfs_path) as archive:
        print("Reading agency.txt, routes.txt, stops.txt ...")
        agency_name = {}
        for row in dict_rows(archive, "agency.txt"):
            agency_name[row["agency_id"]] = row["agency_name"]

        routes = {}
        for row in dict_rows(archive, "routes.txt"):
            if row["route_type"] not in RAIL_TYPES:
                continue
            short_name = row["route_short_name"].strip()
            if not short_name:
                continue
            routes[row["route_id"]] = (row["agency_id"], short_name)
        print(f"  {len(routes)} rail routes (route_type 100-117) out of the full feed.")

        stop_name, stop_pos, stop_parent = {}, {}, {}
        for row in dict_rows(archive, "stops.txt"):
            sid = row["stop_id"]
            stop_name[sid] = row["stop_name"]
            stop_parent[sid] = row.get("parent_station") or ""
            try:
                stop_pos[sid] = (float(row["stop_lat"]), float(row["stop_lon"]))
            except (TypeError, ValueError):
                stop_pos[sid] = None

        def resolve_stop(sid):
            parent = stop_parent.get(sid)
            target = parent if parent and parent in stop_name else sid
            return stop_name.get(target, ""), stop_pos.get(target)

        print("Streaming trips.txt (rail routes only) ...")
        trip_line = {}  # trip_id -> (agency_id, short_name)
        header = None
        for fields in csv_rows(archive, "trips.txt"):
            if header is None:
                header = fields
                ri, ti = header.index("route_id"), header.index("trip_id")
                continue
            route = routes.get(fields[ri])
            if route:
                trip_line[fields[ti]] = route
        print(f"  {len(trip_line):,} rail trips kept.")

        print("Streaming stop_times.txt (about 2.5 GB uncompressed, this is the slow part) ...")
        best_stops = {}  # (agency_id, short_name) -> longest ordered [stop_id,...]
        current_trip, current_rows, finished = None, [], set()
        reorder_anomalies = 0
        row_count = 0
        header = None

        def flush():
            if current_trip is None or current_trip not in trip_line or not current_rows:
                return
            ordered = [sid for _, sid in sorted(current_rows, key=lambda x: x[0])]
            deduped = [ordered[0]] + [s for a, s in zip(ordered, ordered[1:]) if s != a]
            key = trip_line[current_trip]
            if len(deduped) > len(best_stops.get(key, [])):
                best_stops[key] = deduped

        for fields in csv_rows(archive, "stop_times.txt"):
            if header is None:
                header = fields
                ti = header.index("trip_id")
                si = header.index("stop_sequence")
                pi = header.index("stop_id")
                continue
            row_count += 1
            trip_id = fields[ti]
            if trip_id != current_trip:
                flush()
                if current_trip in finished:
                    reorder_anomalies += 1
                finished.add(current_trip)
                current_trip = trip_id
                current_rows = []
            current_rows.append((int(fields[si]), fields[pi]))
        flush()
        print(f"  {row_count:,} stop_times rows read, {len(best_stops)} candidate lines.")
        if reorder_anomalies:
            print(f"  WARNING: {reorder_anomalies} trip(s) had non-contiguous rows in stop_times.txt; "
                  f"only the first block of each was used.", file=sys.stderr)

    print("Matching stops to our own station list ...")
    match, unmatched_counter, unmatched_pos, nearest_ch_km = build_matcher(stations, by_name)
    output = []
    total_stops, total_matched = 0, 0
    short_lines = 0
    for (agency_id, short_name), stop_ids in best_stops.items():
        matched_names = []
        for sid in stop_ids:
            name, pos = resolve_stop(sid)
            total_stops += 1
            lat, lng = pos if pos else (None, None)
            m = match(name, lat, lng)
            if m:
                total_matched += 1
                if not matched_names or matched_names[-1] != m:
                    matched_names.append(m)
        if len(matched_names) < MIN_LINE_STOPS:
            short_lines += 1
            continue
        output.append({
            "agency": agency_name.get(agency_id, agency_id),
            "code": short_name,
            "stops": matched_names,
        })
    output.sort(key=lambda r: (r["agency"], r["code"]))

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({"lines": output}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    elapsed = time.time() - t0
    match_rate = (total_matched / total_stops * 100) if total_stops else 0
    top_unmatched = unmatched_counter.most_common(40)
    # Every unmatched name already survived the 250 m proximity fallback and
    # still found nothing, so most of these are genuinely foreign (French/
    # German/Italian stops on cross-border trains). Flag the exceptions: an
    # unmatched name whose nearest Swiss station is still fairly close is
    # more likely a real naming mismatch or a station missing from our own
    # list than a foreign stop, and is worth a human look.
    near_misses = []
    for name in unmatched_counter:
        lat, lng = unmatched_pos.get(name, (None, None))
        if lat is None:
            continue
        km = nearest_ch_km(lat, lng)
        if km < 15:
            near_misses.append((km, name, unmatched_counter[name]))
    near_misses.sort()

    report = [
        "=== SWISS RAIL TRANSIT LINES (GTFS) ===",
        f"Source zip: {gtfs_path.name}",
        f"Rail routes in feed (route_type 100-117): {len(routes)}",
        f"Rail trips kept: {len(trip_line):,}",
        f"Candidate lines (agency + line code, direction collapsed): {len(best_stops)}",
        f"Lines written (>= {MIN_LINE_STOPS} matched stations): {len(output)}",
        f"Lines dropped, too few matched stations: {short_lines}",
        f"Stop occurrences resolved from GTFS: {total_stops:,}",
        f"Matched to a station in data/stations.json: {total_matched:,} ({match_rate:.1f}%)",
        f"Proximity match radius used as a fallback: {MATCH_RADIUS_KM*1000:.0f} m",
        f"Elapsed: {elapsed/60:.1f} min",
        "",
        f"Unmatched names within 15 km of a Swiss station (worth checking by hand, "
        f"most likely candidates for a real naming mismatch or a station missing "
        f"from data/stations.json rather than a foreign stop) ({len(near_misses)}):",
    ]
    report += [f"  - {name} ({count}x, {km:.1f} km from nearest match)" for km, name, count in near_misses]
    report += [
        "",
        f"Most common unmatched GTFS stop names overall (dominated by genuinely "
        f"foreign stops on cross-border trains), top {len(top_unmatched)}:",
    ]
    report += [f"  - {name} ({count}x)" for name, count in top_unmatched]
    report.append("=== END ===")
    OUT_REPORT.write_text("\n".join(report) + "\n", encoding="utf-8")

    print(f"\nWrote {OUT_PATH} ({len(output)} lines)")
    print(f"Wrote {OUT_REPORT}")
    print(f"Match rate: {total_matched:,}/{total_stops:,} ({match_rate:.1f}%). Elapsed {elapsed/60:.1f} min.")


if __name__ == "__main__":
    main()
