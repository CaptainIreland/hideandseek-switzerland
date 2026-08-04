#!/usr/bin/env python3
"""Flag stations without at least an hourly train, combined across every line, every day.

Usage, from the repository root:

    python scripts/audit_station_frequency.py [--gtfs PATH] [--url URL] [--dates YYYY-MM-DD,...]

One-off report, read-only w.r.t. data/stations.json and app.js - any removal
is a deliberate separate pass, one station at a time, matching the
precedent of scripts/audit_private_railways.py's house-rule-5 exclusions.

--dates checks exact calendar dates instead of a representative future week
- e.g. --dates 2026-08-06,2026-08-07,2026-08-08,2026-08-09 for a specific
game weekend. This is the more reliable mode when the dates are already
known: a single representative week can coincidentally land on a one-off
engineering closure (a whole corridor's stations flipping between "full
weekday, zero weekend" and the reverse is the signature of a rail-replacement
bus swap, not a real permanent gap - found by hand-tracing a flagged
station's raw GTFS calendar this way during development). Checking the
actual dates being played sidesteps that risk entirely: if there is a
closure on those dates, that is exactly what matters, not a statistical
abstraction. Without --dates, falls back to picking a representative week.

House rule: a station only counts as a valid hiding-zone/matching answer if
it gets a train (any line, combined) at least every 60 minutes, between
08:00 and 20:00, every day of the week including weekends - not just a
typical weekday. Overnight gaps (last train to first train) are ignored,
same as every station in the country.

Reuses fetch_transit_lines.py's GTFS download/cache and stop-matching
machinery, but has to read the GTFS zip itself: this needs stop_times.txt's
actual clock times, which data/transit-lines.json deliberately discards -
it only keeps each line's longest stop-name sequence, never trip counts or
timing (see that script's docstring). --gtfs points at an already-
downloaded zip and skips the network entirely; the cached zip from a
previous fetch_transit_lines.py run in data/gtfs-cache/ is reused
automatically if present, so this normally costs no fresh download.

Without --dates, dates are chosen dynamically from the feed's own
calendar.txt validity window rather than hardcoded, since the feed itself
is dated and changes twice a week (see fetch_transit_lines.py's DEFAULT_URL
comment): a Wednesday, Saturday and Sunday from a week starting at least 14
days after both today and the feed's own start date, and fully inside its
end date. Either way, using real calendar dates (not just weekday-pattern
matching against calendar.txt) means calendar_dates.txt's exceptions
(public holidays, one-off timetable changes, engineering closures) are
applied automatically rather than hand-avoided.

For each target date, every rail stop_times.txt row in [08:00, 20:00) is
kept and grouped by (station, date), combining every line that stops
there. A station's worst gap is the largest of: 08:00 to its first
departure that day, each consecutive gap between departures, and its last
departure to 20:00 - taken across every target date, since the rule (when
checking a representative week) applies every day, not just a typical
weekday. A date with zero departures counts as an infinite gap.
"""
import argparse
import sys
import time
import zipfile
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_transit_lines import (
    CACHE_DIR,
    DEFAULT_URL,
    RAIL_TYPES,
    build_matcher,
    csv_rows,
    dict_rows,
    download,
    load_our_stations,
)

BASE_DIR = Path(__file__).resolve().parent.parent
OUT_REPORT = BASE_DIR / "data" / "station-frequency-report.txt"

WINDOW_START = 8 * 60   # 08:00 in minutes-since-midnight
WINDOW_END = 20 * 60    # 20:00
MAX_GAP_MIN = 60
BORDERLINE_MARGIN = 10  # report gaps within +/-10 min of the 60 min threshold, for a human look

WEEKDAY_COLUMN = {
    0: "monday", 1: "tuesday", 2: "wednesday", 3: "thursday",
    4: "friday", 5: "saturday", 6: "sunday",
}


def parse_gtfs_date(s):
    return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))


def parse_time_to_minutes(hms):
    h, m, _s = hms.split(":")
    return int(h) * 60 + int(m)


def fmt(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def feed_validity(archive):
    starts, ends = [], []
    for row in dict_rows(archive, "calendar.txt"):
        starts.append(parse_gtfs_date(row["start_date"]))
        ends.append(parse_gtfs_date(row["end_date"]))
    return min(starts), max(ends)


def parse_explicit_dates(s):
    """'2026-08-06,2026-08-07' -> {"2026-08-06": date(2026,8,6), ...}, in the
    order given, so the report lists them in the order the group plays."""
    dates = {}
    for part in s.split(","):
        part = part.strip()
        if part:
            dates[part] = date.fromisoformat(part)
    return dates


def pick_representative_dates(archive):
    """A Wednesday, Saturday and Sunday from a week comfortably inside the
    feed's validity window - at least 14 days out from both today and the
    feed's own start, so as not to land on the edge of a schedule change."""
    feed_start, feed_end = feed_validity(archive)
    earliest = max(date.today(), feed_start) + timedelta(days=14)
    wednesday = earliest + timedelta(days=(2 - earliest.weekday()) % 7)
    saturday = wednesday + timedelta(days=3)
    sunday = wednesday + timedelta(days=4)
    if sunday > feed_end:
        raise SystemExit(
            f"Feed only valid to {feed_end}, not enough room for a representative "
            f"week starting {wednesday}. Refresh the GTFS feed (see "
            f"fetch_transit_lines.py's DEFAULT_URL comment) and re-run."
        )
    return {"weekday": wednesday, "saturday": saturday, "sunday": sunday}, feed_start, feed_end


def active_service_ids(archive, target_dates):
    """target_dates: {day_type: date}. Returns {day_type: set(service_id)}."""
    active = {day: set() for day in target_dates}
    for row in dict_rows(archive, "calendar.txt"):
        start, end = parse_gtfs_date(row["start_date"]), parse_gtfs_date(row["end_date"])
        for day, target in target_dates.items():
            if start <= target <= end and row[WEEKDAY_COLUMN[target.weekday()]] == "1":
                active[day].add(row["service_id"])

    try:
        exception_rows = list(dict_rows(archive, "calendar_dates.txt"))
    except KeyError:
        exception_rows = []
    for row in exception_rows:
        d = parse_gtfs_date(row["date"])
        for day, target in target_dates.items():
            if d == target:
                if row["exception_type"] == "1":
                    active[day].add(row["service_id"])
                elif row["exception_type"] == "2":
                    active[day].discard(row["service_id"])
    return active


def rail_route_ids(archive):
    return {row["route_id"] for row in dict_rows(archive, "routes.txt") if row["route_type"] in RAIL_TYPES}


def stream_trip_buckets(archive, active, route_ids):
    """Rail trips only, tagged with whichever day types their service_id is active for."""
    trip_days = {}
    header = None
    for fields in csv_rows(archive, "trips.txt"):
        if header is None:
            header = fields
            ri, ti, si = header.index("route_id"), header.index("trip_id"), header.index("service_id")
            continue
        if fields[ri] not in route_ids:
            continue
        service_id = fields[si]
        days = {day for day, ids in active.items() if service_id in ids}
        if days:
            trip_days[fields[ti]] = days
    return trip_days


def stream_departures(archive, trip_days):
    """Returns {(stop_id, day_type): [minutes-since-midnight, ...]} for rows
    inside the 08:00-20:00 window, keyed by raw GTFS stop_id (not yet
    resolved to one of our own station names)."""
    times = defaultdict(list)
    header = None
    for fields in csv_rows(archive, "stop_times.txt"):
        if header is None:
            header = fields
            ti = header.index("trip_id")
            pi = header.index("stop_id")
            ai = header.index("arrival_time")
            di = header.index("departure_time")
            continue
        days = trip_days.get(fields[ti])
        if not days:
            continue
        raw_time = fields[ai] or fields[di]
        if not raw_time:
            continue
        minutes = parse_time_to_minutes(raw_time)
        if minutes < WINDOW_START or minutes >= WINDOW_END:
            continue
        stop_id = fields[pi]
        for day in days:
            times[(stop_id, day)].append(minutes)
    return times


def resolve_and_match(archive, times, match):
    stop_name, stop_pos, stop_parent = {}, {}, {}
    for row in dict_rows(archive, "stops.txt"):
        sid = row["stop_id"]
        stop_name[sid] = row["stop_name"]
        stop_parent[sid] = row.get("parent_station") or ""
        try:
            stop_pos[sid] = (float(row["stop_lat"]), float(row["stop_lon"]))
        except (TypeError, ValueError):
            stop_pos[sid] = None

    def resolve(sid):
        parent = stop_parent.get(sid)
        target = parent if parent and parent in stop_name else sid
        return stop_name.get(target, ""), stop_pos.get(target)

    station_times = defaultdict(list)  # (station name, day) -> [minutes]
    unmatched = Counter()
    unmatched_pos = {}
    for (stop_id, day), minutes_list in times.items():
        name, pos = resolve(stop_id)
        lat, lng = pos if pos else (None, None)
        m = match(name, lat, lng)
        if m:
            station_times[(m, day)].extend(minutes_list)
        else:
            unmatched[name] += len(minutes_list)
            if lat is not None:
                unmatched_pos[name] = (lat, lng)
    return station_times, unmatched, unmatched_pos


def compute_gaps(station_names, station_times, day_order):
    """name -> {"worst": minutes, "worst_day": day, "worst_desc": str, "per_day": {day: (gap, desc, count)}}"""
    results = {}
    for name in station_names:
        per_day = {}
        worst, worst_day, worst_desc = -1, None, None
        for day in day_order:
            mins = sorted(station_times.get((name, day), []))
            if not mins:
                gap, desc = 24 * 60, "no departures found in the 08:00-20:00 window"
            else:
                edges = [mins[0] - WINDOW_START]
                edges += [b - a for a, b in zip(mins, mins[1:])]
                edges += [WINDOW_END - mins[-1]]
                gap = max(edges)
                idx = edges.index(gap)
                if idx == 0:
                    desc = f"08:00 to first train at {fmt(mins[0])}"
                elif idx == len(edges) - 1:
                    desc = f"last train at {fmt(mins[-1])} to 20:00"
                else:
                    desc = f"{fmt(mins[idx - 1])} to {fmt(mins[idx])}"
            per_day[day] = (gap, desc, len(mins))
            if gap > worst:
                worst, worst_day, worst_desc = gap, day, desc
        results[name] = {"worst": worst, "worst_day": worst_day, "worst_desc": worst_desc, "per_day": per_day}
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gtfs", type=Path, help="Path to an already-downloaded GTFS zip, skips the download")
    parser.add_argument("--url", default=DEFAULT_URL, help="GTFS zip URL, only used without --gtfs")
    parser.add_argument("--dates", help="Comma-separated YYYY-MM-DD dates to check exactly, instead of a representative future week")
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
    station_names = [name for name, _, _ in stations]
    station_coords = {name: (lat, lng) for name, lat, lng in stations}
    print(f"Loaded {len(stations)} of our own stations.")

    with zipfile.ZipFile(gtfs_path) as archive:
        if args.dates:
            target_dates = parse_explicit_dates(args.dates)
            feed_start, feed_end = feed_validity(archive)
            for day, d in target_dates.items():
                if not (feed_start <= d <= feed_end):
                    raise SystemExit(
                        f"{d} ({day}) is outside the feed's validity window "
                        f"({feed_start} to {feed_end}). Refresh the GTFS feed (see "
                        f"fetch_transit_lines.py's DEFAULT_URL comment) and re-run."
                    )
        else:
            print("Picking representative dates from calendar.txt ...")
            target_dates, feed_start, feed_end = pick_representative_dates(archive)
        day_order = list(target_dates.keys())
        print("Dates checked:")
        for day, d in target_dates.items():
            print(f"  {day}: {d} ({d.strftime('%A')})")

        print("Resolving active service_ids for those dates ...")
        active = active_service_ids(archive, target_dates)
        for day, ids in active.items():
            print(f"  {day}: {len(ids)} active services")

        print("Reading routes.txt (rail only) ...")
        route_ids = rail_route_ids(archive)
        print(f"  {len(route_ids)} rail routes.")

        print("Streaming trips.txt ...")
        trip_days = stream_trip_buckets(archive, active, route_ids)
        print(f"  {len(trip_days):,} rail trips kept across the {len(target_dates)} target dates.")

        print("Streaming stop_times.txt (about 2.5 GB uncompressed, this is the slow part) ...")
        times = stream_departures(archive, trip_days)
        total_rows = sum(len(v) for v in times.values())
        print(f"  {total_rows:,} stop_times rows kept inside the 08:00-20:00 window.")

        print("Matching GTFS stops to our own station list ...")
        match, unmatched_counter, unmatched_pos, nearest_ch_km = build_matcher(stations, by_name)
        station_times, unmatched, unmatched_pos_local = resolve_and_match(archive, times, match)

    print("Computing worst gaps ...")
    results = compute_gaps(station_names, station_times, day_order)

    flagged = {n: r for n, r in results.items() if r["worst"] > MAX_GAP_MIN}
    borderline = {
        n: r for n, r in results.items()
        if MAX_GAP_MIN - BORDERLINE_MARGIN <= r["worst"] <= MAX_GAP_MIN + BORDERLINE_MARGIN
    }
    no_data_any_day = {
        n: r for n, r in results.items()
        if all(r["per_day"][d][2] == 0 for d in day_order)
    }

    near_misses = []
    for name, count in unmatched.items():
        lat, lng = unmatched_pos_local.get(name, (None, None))
        if lat is None:
            continue
        km = nearest_ch_km(lat, lng)
        if km < 15:
            near_misses.append((km, name, count))
    near_misses.sort()

    elapsed = time.time() - t0

    report = ["=== STATION FREQUENCY AUDIT (>= 1 train per 60 min, 08:00-20:00) ===", ""]
    report.append(f"Source zip: {gtfs_path.name}")
    report.append(f"Feed valid: {feed_start} to {feed_end}")
    report.append("Dates checked:")
    for day, d in target_dates.items():
        report.append(f"  {day}: {d} ({d.strftime('%A')})")
    report.append("")
    report.append(f"Stations checked: {len(station_names)}")
    report.append(f"Flagged (worst gap > {MAX_GAP_MIN} min on at least one checked date): {len(flagged)}")
    report.append(f"Borderline (worst gap within {BORDERLINE_MARGIN} min of the {MAX_GAP_MIN} min threshold): {len(borderline)}")
    report.append(f"No departures matched on any checked date (check for a name-matching gap before trusting): {len(no_data_any_day)}")
    report.append(f"Elapsed: {elapsed/60:.1f} min")
    report.append("")

    report.append(f"--- FLAGGED: worst gap exceeds {MAX_GAP_MIN} minutes on at least one checked date, combined across every line ---")
    for name in sorted(flagged, key=lambda n: -flagged[n]["worst"]):
        r = flagged[name]
        lat, lng = station_coords[name]
        report.append(f"\n  {name} ({lat}, {lng}) - worst gap {r['worst']} min on {r['worst_day']}: {r['worst_desc']}")
        for day in day_order:
            gap, desc, count = r["per_day"][day]
            report.append(f"    {day}: {count} trains in window, worst gap {gap} min ({desc})")
    report.append("")

    report.append(f"--- BORDERLINE: worst gap within {BORDERLINE_MARGIN} min of the {MAX_GAP_MIN} min threshold, worth a human look ---")
    for name in sorted(borderline, key=lambda n: borderline[n]["worst"]):
        r = borderline[name]
        lat, lng = station_coords[name]
        flag_word = "FLAGGED" if r["worst"] > MAX_GAP_MIN else "not flagged"
        report.append(f"  - {name} ({lat}, {lng}) - worst gap {r['worst']} min on {r['worst_day']} ({flag_word}): {r['worst_desc']}")
    report.append("")

    report.append("--- NO DEPARTURES MATCHED ON ANY CHECKED DATE: likely a name-matching gap, not a real 12-hour service gap ---")
    report.append("Check these by hand against the GTFS feed before treating them as a genuine low-frequency station:")
    for name in sorted(no_data_any_day):
        lat, lng = station_coords[name]
        report.append(f"  - {name} ({lat}, {lng})")
    report.append("")

    report.append("--- UNMATCHED GTFS STOP NAMES WITHIN 15 KM OF A SWISS STATION (possible naming mismatch) ---")
    report += [f"  - {name} ({count}x, {km:.1f} km from nearest match)" for km, name, count in near_misses]
    report.append("")
    report.append("=== END ===")

    OUT_REPORT.write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"\nWrote {OUT_REPORT.relative_to(BASE_DIR)} "
          f"({len(flagged)} flagged, {len(borderline)} borderline, {len(no_data_any_day)} with no matched data). "
          f"Elapsed {elapsed/60:.1f} min.")


if __name__ == "__main__":
    main()
