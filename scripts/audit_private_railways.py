#!/usr/bin/env python3
"""Flag stations served only by a tourist/excursion cog railway.

Usage, from the repository root:

    python scripts/audit_private_railways.py

One-off, read-only report. It does not modify data/stations.json,
data/stations-google.json or app.js - any removal is a deliberate separate
pass, one station at a time, matching the precedent of commit a621ca3
("Remove 'Appenzeller Bahnen AG' - not a real station").

Motivation: data/stations.json has no operator or railway-type field, so it
currently includes stations such as Riffelberg that sit only on the
Gornergrat Bahn, a cog railway to Zermatt that needs a separate supplement
ticket and is not covered by this group's Interrail pass, the pass standard
confirmed on Issue #10. This is different from a legitimate regional
narrow-gauge operator (RhB, Matterhorn Gotthard Bahn, MOB, Zentralbahn,
Appenzeller Bahnen), which is ordinary scheduled public transport just run
by a non-SBB company and is Interrail-covered like the SBB network itself.

Interrail's coverage does not line up with the GA/Swiss Travel Pass a casual
reading of the rulebook might assume: Rigi Bahnen AG and Pilatusbahnen are
discount-only (50%) rather than covered either way, so they land in the same
excursion bucket regardless of which pass standard is used, but Zurich's
S-Bahn is a real divergence. SBB- and Thurbo-run S-Bahn lines there are
Interrail-covered, but the Sihltal-Zurich-Uetliberg-Bahn (SZU), a separate
agency, runs its own S4, S10 and night SN4 services that Interrail does not
accept even though GA/Swiss Travel Pass would. SZU is a single small
operator with no known Interrail-covered line, so unlike the Berner
Oberland-Bahnen carve-out above it is flagged whole-agency (code=None).
That is why SZU appears in EXCURSION_ROUTES below even though nothing else
about it resembles a mountain cog railway.

Classification reuses data/transit-lines.json (built by
fetch_transit_lines.py from the national GTFS feed), which already gives,
per line, an agency, a route code and the ordered list of matched station
names. A station is flagged only if every (agency, code) pair it appears
under belongs to EXCURSION_ROUTES below, i.e. no normal-fare line also
serves it. Classification keys on (agency, code), not agency name alone,
because some excursion lines share an agency with ordinary regional service
(Schynige Platte-Bahn is not its own GTFS agency, it is Berner
Oberland-Bahnen route 68, while the same agency also runs the ordinary R61/
R62 regional trains).

No network access, no GTFS re-fetch, no API key - pure local JSON
processing.
"""
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STATIONS_PATH = BASE_DIR / "data" / "stations.json"
STATIONS_GOOGLE_PATH = BASE_DIR / "data" / "stations-google.json"
TRANSIT_LINES_PATH = BASE_DIR / "data" / "transit-lines.json"
OUT_REPORT = BASE_DIR / "data" / "private-railway-report.txt"

# (agency, route code) pairs that are tourist/excursion cog railways: a
# separate supplement ticket, not covered by the GA or Swiss Travel Pass.
# code=None means every route under that agency counts (the agency runs
# nothing else). A tuple with a specific code carves out just that route
# from an agency that also runs ordinary regional service.
EXCURSION_ROUTES = {
    ("Gornergratbahn", None): "cog railway to Zermatt's summit stations, separate ticket",
    ("Jungfraubahn", None): "cog railway above Kleine Scheidegg to Jungfraujoch, separate ticket",
    ("Pilatusbahnen", None): "cog railway up Pilatus, separate ticket",
    ("Rigi Bahnen AG", None): "cog railway up Rigi, separate ticket",
    ("Brienz Rothorn Bahn AG", None): "steam/diesel cog railway up Brienzer Rothorn, separate ticket",
    ("Dampfbahn Furka-Bergstrecke", None): "seasonal heritage steam railway, separate ticket",
    ("Berner Oberland-Bahnen", "68"): "Schynige Platte cog line only, not the rest of BOB's ordinary regional service",
    ("Sihltal-Zürich-Uetliberg-Bahn", None): "Zurich S-Bahn services (S4, S10, night SN4) not accepted by Interrail, unlike the SBB/Thurbo-run S-Bahn lines",
    ("Swiss Rail Traffic AG Glattbrugg", None): "a freight/charter operator running special (EXT) trains, founded 2008 for special transport and smaller contracts, not a scheduled passenger service any pass covers",
}

# Stations that would auto-flag from rail data alone but are known to have
# normal-fare access by a non-rail mode, so the rail-only heuristic can't
# see their real situation. Empty for now: Vitznau used to sit here (a real
# lakeside town normally reached by boat or PostBus, with only the excursion
# Rigi cog railway touching it by rail), but Issue #10 settled on dropping it
# with the rest of the Rigi Bahnen AG group rather than carving it out, since
# this project only tracks rail stations and has no boat/PostBus data to
# justify keeping a rail-only entry alive on a non-rail argument.
MANUAL_EXCEPTIONS = {}

# Already documented in CLAUDE.md's known gaps and data/transit-lines-report.txt
# as missing from data/stations.json because Google does not type their
# termini as train_station. Checked here to confirm the gap has not silently
# closed, not because we expect a hit.
KNOWN_GAP_NAMES = [
    "Pilatus Kulm",
    "Brienzer Rothorn",
    "Muttbach-Belvédère",
    "Gletsch",
    "Tiefenbach DFB",
]


def excursion_key(agency, code):
    if (agency, code) in EXCURSION_ROUTES:
        return (agency, code)
    if (agency, None) in EXCURSION_ROUTES:
        return (agency, None)
    return None


def main():
    stations = json.loads(STATIONS_PATH.read_text(encoding="utf-8"))
    station_names = {name for name, _, _ in stations}
    station_coords = {name: (lat, lng) for name, lat, lng in stations}
    print(f"Loaded {len(stations)} stations from {STATIONS_PATH.relative_to(BASE_DIR)}.")

    lines = json.loads(TRANSIT_LINES_PATH.read_text(encoding="utf-8"))["lines"]
    print(f"Loaded {len(lines)} transit lines from {TRANSIT_LINES_PATH.relative_to(BASE_DIR)}.")

    # Only consider stops that are still real stations: once a removal pass has run,
    # transit-lines.json keeps naming stations that data/stations.json no longer has
    # (it is only refreshed by a separate, paid fetch_transit_lines.py re-run), and
    # that is expected steady state afterwards, not a matching error to investigate.
    station_routes = {}  # name -> list of (agency, code)
    for line in lines:
        agency, code = line["agency"], line["code"]
        for stop in line["stops"]:
            if stop in station_names:
                station_routes.setdefault(stop, []).append((agency, code))

    flagged = {}       # name -> set of excursion keys serving it
    mixed = {}         # name -> (excursion keys, normal (agency, code) pairs)
    for name, pairs in station_routes.items():
        exc_keys = set()
        normal_pairs = []
        for agency, code in pairs:
            key = excursion_key(agency, code)
            if key:
                exc_keys.add(key)
            else:
                normal_pairs.append((agency, code))
        if not exc_keys:
            continue
        if normal_pairs:
            mixed[name] = (exc_keys, sorted(set(normal_pairs)))
        else:
            flagged[name] = exc_keys

    manual_exceptions = {}
    for name in list(flagged):
        if name in MANUAL_EXCEPTIONS:
            manual_exceptions[name] = flagged.pop(name)

    # Every flagged/mixed/exception name should already be a literal entry
    # in data/stations.json, since transit-lines.json's stops are matched
    # against it by construction. Assert rather than assume.
    for name in list(flagged) + list(mixed) + list(manual_exceptions):
        assert name in station_names, (
            f"{name!r} came from transit-lines.json but is not in "
            f"data/stations.json - matching invariant broken, investigate "
            f"before trusting this report."
        )

    gap_hits = [name for name in KNOWN_GAP_NAMES if name in station_names]

    google_data = json.loads(STATIONS_GOOGLE_PATH.read_text(encoding="utf-8"))
    berninaplatz_kept = [r for r in google_data["kept"] if r["name"] == "Berninaplatz"]
    berninaplatz_in_stations = "Berninaplatz" in station_names

    goldau_a4_present = "Goldau A4" in station_names

    def group_by_operator(names_dict):
        groups = {}
        for name, exc_keys in names_dict.items():
            for agency, code in exc_keys:
                groups.setdefault((agency, code), []).append(name)
        return groups

    flagged_groups = group_by_operator(flagged)

    report = ["=== PRIVATE / EXCURSION RAILWAY AUDIT ===", ""]
    report.append(f"Stations checked: {len(stations)}")
    report.append(f"Flagged (excursion-only): {len(flagged)}")
    report.append(f"Not flagged, mixed/interchange with a normal-fare line: {len(mixed)}")
    report.append(f"Manual exceptions (rail-only heuristic blind spot): {len(manual_exceptions)}")
    report.append(f"Known-gap names still absent from data/stations.json: {len(KNOWN_GAP_NAMES) - len(gap_hits)} of {len(KNOWN_GAP_NAMES)}")
    report.append("")

    report.append("--- FLAGGED: excursion/tourist-only, separate supplement required ---")
    for (agency, code), reason in EXCURSION_ROUTES.items():
        names = sorted(flagged_groups.get((agency, code), []))
        if not names:
            continue
        label = agency if code is None else f"{agency} route {code}"
        report.append(f"\n{label} - {reason} ({len(names)} stations):")
        for name in names:
            lat, lng = station_coords[name]
            report.append(f"  - {name} ({lat}, {lng})")
    report.append("")

    report.append("--- NOT FLAGGED: mixed/interchange, transparency only ---")
    report.append("These also carry at least one normal-fare line, so they are left alone:")
    for name in sorted(mixed):
        exc_keys, normal_pairs = mixed[name]
        lat, lng = station_coords[name]
        normal_desc = ", ".join(f"{a} {c}" for a, c in normal_pairs)
        report.append(f"  - {name} ({lat}, {lng}) - normal-fare line(s): {normal_desc}")
    report.append("")

    report.append("--- MANUAL EXCEPTION ---")
    for name, exc_keys in manual_exceptions.items():
        lat, lng = station_coords[name]
        report.append(f"  - {name} ({lat}, {lng}): {MANUAL_EXCEPTIONS[name]}")
    report.append("")

    report.append("--- KNOWN GAPS: already documented in CLAUDE.md, nothing new ---")
    report.append("Excursion-line termini Google does not type as train_station, so they")
    report.append("are absent from data/stations.json. See data/transit-lines-report.txt.")
    for name in KNOWN_GAP_NAMES:
        status = "UNEXPECTEDLY PRESENT" if name in gap_hits else "confirmed absent"
        report.append(f"  - {name}: {status}")
    report.append("")

    report.append("--- ASIDES ---")
    if berninaplatz_kept:
        report.append(
            "  - Berninaplatz: flagged keptAsNarrowGauge=true in "
            "data/stations-google.json (a Zurich VBZ tram stop, a false-positive "
            "substring match on \"bernina\" in fetch_stations_google.py's "
            "KEEP_LIGHT_RAIL list). "
            + ("It DID reach data/stations.json - needs a look."
               if berninaplatz_in_stations
               else "It did not reach data/stations.json, so no action needed.")
        )
    if goldau_a4_present:
        lat, lng = station_coords["Goldau A4"]
        report.append(
            f"  - Goldau A4 ({lat}, {lng}): a genuine Rigi Bahnen AG park-and-ride "
            f"stop, just an odd Google Places name worth a mention."
        )
    report.append("")
    report.append("=== END ===")

    OUT_REPORT.write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_REPORT.relative_to(BASE_DIR)} "
          f"({len(flagged)} flagged, {len(mixed)} mixed, {len(manual_exceptions)} manual exception(s)).")


if __name__ == "__main__":
    main()
