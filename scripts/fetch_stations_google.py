#!/usr/bin/env python3
"""Build the strict, Google-only Swiss train station list.

Usage, from the repository root:

    python scripts/fetch_stations_google.py [YOUR_API_KEY]

If the key is not given as an argument, the script asks for it. The key needs
the Places API (application programming interface) (New) enabled, billing on,
and its application restriction set to None while running scripts (a key
restricted to websites rejects calls made outside a browser).

The script sweeps Switzerland in adaptive square cells: it asks Google for
train stations in each cell, and wherever Google's 20-result cap is hit, the
cell splits into four exact quadrants and is swept again, until every station
is captured. Quadrants partition perfectly, so dense cities cost the minimum
number of requests. It then:

1. keeps places Google types as train_station,
2. sets aside light-rail-only entries for a group ruling,
3. drops anything outside the Swiss outline,
4. audits the result against data/stations-core.json so any major station
   Google lacks is listed before it silently vanishes from the game,
5. writes data/stations.json (the pinned game list) and
   data/stations-google.json (full records with Google place identifiers).

Review the printed report, then commit both files.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import google_sweep

FIELD_MASK = ("places.id,places.displayName,places.location,places.types,"
              "places.addressComponents")
SEARCH_TYPES = ["train_station", "light_rail_station"]
# Narrow-gauge and rack railways sometimes carry only Google's light_rail type but
# are boardable trains for the game. Kept when the name matches; city trams are not.
KEEP_LIGHT_RAIL = (
    "appenzeller bahnen", "bernina", "rhb", "rhaetische", "matterhorn gotthard",
    "montreux", "mob", "zentralbahn", "wengernalp", "jungfrau", "gornergrat",
    "pilatus", "brienz rothorn", "furka", "schynige platte",
)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_PATH = os.path.join(BASE_DIR, "data", "stations-core.json")
OUT_SIMPLE = os.path.join(BASE_DIR, "data", "stations.json")
OUT_FULL = os.path.join(BASE_DIR, "data", "stations-google.json")
OUT_REPORT = os.path.join(BASE_DIR, "data", "stations-google-report.txt")
# Recovery snapshot only, overwritten every checkpoint and removed once the
# sweep finishes and the real outputs above are written - so a crash partway
# through does not lose the (already paid-for) API calls made so far.
OUT_PARTIAL = os.path.join(BASE_DIR, "data", "stations-google-partial.json")


def in_switzerland(place):
    """Use Google's own address for the country, not our simplified outline.

    The outline is a smoothed shape and is wrong within a kilometre or so of the
    border, in both directions. Google naming the country is both more accurate
    and consistent with the house rule that Google Maps is the arbiter.
    Returns None when Google gives no country, so the caller can fall back.
    """
    for component in place.get("addressComponents") or []:
        if "country" in (component.get("types") or []):
            short = (component.get("shortText") or "").strip().upper()
            long_name = (component.get("longText") or "").strip().lower()
            if short:
                return short == "CH"
            return long_name in ("switzerland", "schweiz", "suisse", "svizzera")
    return None


def write_partial(places, requests_made):
    """Recovery snapshot written every checkpoint during the sweep. Lets a crash
    mid-sweep be salvaged by re-reading this instead of losing every already
    paid-for request made so far."""
    try:
        os.makedirs(os.path.dirname(OUT_PARTIAL), exist_ok=True)
        with open(OUT_PARTIAL, "w", encoding="utf-8") as handle:
            json.dump({"requestsMade": requests_made, "places": list(places.values())},
                      handle, ensure_ascii=False, separators=(",", ":"))
    except OSError as error:
        print(f"  (could not write recovery snapshot: {error})", flush=True)


def partition(places):
    kept, light_rail, foreign, other = [], [], [], []
    disagreements = []
    for place in places.values():
        name = ((place.get("displayName") or {}).get("text") or "").strip()
        loc = place.get("location") or {}
        lat, lng = loc.get("latitude"), loc.get("longitude")
        if lat is None or lng is None:
            continue
        types = set(place.get("types") or [])
        record = {"id": place.get("id"), "name": name, "lat": round(lat, 6),
                  "lng": round(lng, 6), "types": sorted(types)}
        google_says = in_switzerland(place)
        outline_says = google_sweep.point_in_ch(lng, lat)
        swiss = outline_says if google_says is None else google_says
        if google_says is not None and google_says != outline_says:
            disagreements.append((name, "Google says in CH" if google_says else "Google says outside CH"))
        if not swiss:
            record["borderKm"] = round(google_sweep.ring_dist_km(lat, lng), 2)
            foreign.append(record)
        elif "train_station" in types:
            kept.append(record)
        elif "light_rail_station" in types:
            low = name.lower()
            if any(term in low for term in KEEP_LIGHT_RAIL):
                record["keptAsNarrowGauge"] = True
                kept.append(record)
            else:
                light_rail.append(record)
        else:
            other.append(record)
    for bucket in (kept, light_rail, foreign, other):
        bucket.sort(key=lambda r: r["name"].lower())
    globals()["LAST_DISAGREEMENTS"] = sorted(set(disagreements))
    return kept, light_rail, foreign, other


def audit_core(kept):
    if not os.path.exists(CORE_PATH):
        return None, []
    core = json.load(open(CORE_PATH, encoding="utf-8"))
    names = {r["name"].strip().lower() for r in kept}
    points = [(r["lat"], r["lng"]) for r in kept]
    matched, missing = 0, []
    for name, lat, lng in core:
        if name.strip().lower() in names:
            matched += 1
        elif any(google_sweep.dist_km((lat, lng), p) < 0.3 for p in points):
            matched += 1
        else:
            missing.append(name)
    return matched, sorted(missing)


def build_report(kept, light_rail, foreign, other, requests_made, top_level, warnings, matched, missing, core_total):
    lines = []
    lines.append("=== GOOGLE STATION SWEEP ===")
    ng = sum(1 for r in kept if r.get("keptAsNarrowGauge"))
    lines.append(f"Requests made: {requests_made} ({top_level} top-level tiles plus subdivisions)")
    lines.append(f"Unique Google places found: {len(kept) + len(light_rail) + len(foreign) + len(other)}")
    lines.append(f"  Kept, typed train_station: {len(kept) - ng}")
    lines.append(f"  Kept, narrow-gauge on the keep list: {ng}")
    lines.append(f"  Light-rail excluded as city tram: {len(light_rail)}")
    lines.append(f"  Outside the Swiss outline, dropped: {len(foreign)}")
    if other:
        lines.append(f"  Other types, dropped: {len(other)}")
    near = sorted([r for r in foreign if r.get("borderKm", 99) <= 1.5], key=lambda r: r["borderKm"])
    if near:
        lines.append(f"Dropped just outside the outline, within 1.5 km. Sanity-check these are truly foreign ({len(near)}):")
        for record in near[:25]:
            lines.append(f"  - {record['name']} ({record['borderKm']} km outside)")
    for warning in warnings:
        lines.append(f"WARNING: {warning}")
    if matched is None:
        lines.append("Core check skipped: data/stations-core.json not found.")
    else:
        lines.append(f"Core check: {matched} of {core_total} major stations matched")
        if missing:
            lines.append(f"MISSING from Google, these vanish from the game under strict mode ({len(missing)}):")
            for name in missing[:60]:
                lines.append(f"  - {name}")
        else:
            lines.append("Every core station is present in Google. Good sign.")
    if light_rail:
        lines.append("Light-rail-only entries, excluded, rule on these:")
        for record in light_rail[:40]:
            lines.append(f"  - {record['name']}")
    disagreements = globals().get("LAST_DISAGREEMENTS") or []
    if disagreements:
        lines.append(f"Border cases where Google overruled our outline ({len(disagreements)}), Google won:")
        for name, verdict in disagreements[:40]:
            lines.append(f"  - {name}: {verdict}")
    lines.append("=== END ===")
    return "\n".join(lines)


def main():
    key = sys.argv[1].strip() if len(sys.argv) > 1 else input("Paste your Google API key: ").strip()
    if not key:
        sys.exit("No key given.")
    print("Sweeping Switzerland for Google train stations. Expect a few minutes.")
    places, requests_made, top_level, warnings = google_sweep.sweep(
        key, SEARCH_TYPES, FIELD_MASK, on_progress=write_partial)
    kept, light_rail, foreign, other = partition(places)
    matched, missing = audit_core(kept)
    core_total = 0
    if os.path.exists(CORE_PATH):
        core_total = len(json.load(open(CORE_PATH, encoding="utf-8")))
    report = build_report(kept, light_rail, foreign, other, requests_made, top_level,
                          warnings, matched, missing, core_total)
    print("\n" + report + "\n")
    if len(kept) < 300:
        sys.exit(f"Only {len(kept)} stations kept, which looks wrong. Not writing.")
    os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)
    simple = sorted([[r["name"], r["lat"], r["lng"]] for r in kept], key=lambda s: s[0].lower())
    with open(OUT_SIMPLE, "w", encoding="utf-8") as handle:
        json.dump(simple, handle, ensure_ascii=False, separators=(",", ":"))
    with open(OUT_FULL, "w", encoding="utf-8") as handle:
        json.dump({"source": "Google Places API (New), searchNearby sweep",
                   "kept": kept, "lightRail": light_rail, "foreign": foreign, "other": other},
                  handle, ensure_ascii=False, separators=(",", ":"))
    with open(OUT_REPORT, "w", encoding="utf-8") as handle:
        handle.write(report + "\n")
    if os.path.exists(OUT_PARTIAL):
        os.remove(OUT_PARTIAL)
    print(f"Wrote {len(simple)} stations to {OUT_SIMPLE}, full records to {OUT_FULL}, report to {OUT_REPORT}")


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
