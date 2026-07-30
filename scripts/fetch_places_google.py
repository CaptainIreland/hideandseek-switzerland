#!/usr/bin/env python3
"""Sweep Switzerland for every place category the question cards use.

Usage, from the repository root:

    python scripts/fetch_places_google.py [YOUR_API_KEY] [category ...]

With no categories listed it sweeps them all. Named categories sweep only those,
which is useful for a cheap re-run of a single dense one:

    python scripts/fetch_places_google.py KEY park museum

It reuses the adaptive cell sweep from fetch_stations_google.py, so the same
subdivision, Swiss outline clipping, and 20-result cap handling apply. Results
are written to data/places-raw.json. Run scripts/filter_places.py afterwards to turn that
into data/places.json, the trimmed set the app actually loads.

The key needs Places API (application programming interface) (New) enabled,
billing on, and its application restriction set to None while running scripts.

Note on cost: dense categories, parks above all, need far more requests than
stations did. Sweep the ones you actually play with first and check your Google
Cloud billing page before doing the lot.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_stations_google as base

# Category name used inside the app, mapped to the Google place types to search.
CATEGORIES = {
    "museum": ["museum"],
    "library": ["library"],
    "cinema": ["movie_theater"],
    "hospital": ["hospital"],
    "zoo": ["zoo"],
    "aquarium": ["aquarium"],
    "themepark": ["amusement_park"],
    "golf": ["golf_course"],
    "park": ["park"],
    "airport": ["international_airport", "airport"],
    "consulate": ["embassy"],
}
FIELD_MASK = ("places.id,places.displayName,places.location,places.types,"
              "places.primaryType,places.rating,places.userRatingCount,"
              "places.addressComponents")

# The rulebook excludes some things Google returns even under the right primary
# type. Honorary consulates, driving ranges and miniature golf are named out.
# These are name tests, so treat them as a net rather than a guarantee.
NAME_EXCLUDE = {
    "consulate": ("honorary", "honorar", "honoraire", "onorario", "onorar"),
    "golf": ("driving range", "indoor", "minigolf", "mini-golf", "miniature"),
}
OUT_PATH = os.path.join(base.BASE_DIR, "data", "places-raw.json")
REPORT_PATH = os.path.join(base.BASE_DIR, "data", "places-report.txt")


def collect(key, category, types):
    """Sweep one category and return its rows plus a count of foreign drops."""
    base.SEARCH_TYPES = types
    base.FIELD_MASK = FIELD_MASK
    # Match on what a place primarily is. Matching any attached type pulls in
    # dental surgeries as hospitals and playgrounds as parks.
    base.USE_PRIMARY_TYPES = True
    banned = NAME_EXCLUDE.get(category, ())
    places, requests_made, top_level, warnings = base.sweep(key)
    rows, foreign, excluded = [], 0, 0
    seen = set()
    for place in places.values():
        name = ((place.get("displayName") or {}).get("text") or "").strip()
        loc = place.get("location") or {}
        lat, lng = loc.get("latitude"), loc.get("longitude")
        if not name or lat is None or lng is None:
            continue
        # Map boundary rule. Google's own address decides the country, with the
        # simplified outline only as a fallback when Google gives no country.
        verdict = base.in_switzerland(place)
        if verdict is None:
            verdict = base.point_in_ch(lng, lat)
        if not verdict:
            foreign += 1
            continue
        low = name.lower()
        if any(term in low for term in banned):
            excluded += 1
            continue
        key_xy = (low, round(lat, 4), round(lng, 4))
        if key_xy in seen:
            continue
        seen.add(key_xy)
        # The primary type is stored so the set can be re-filtered later without
        # paying for another sweep.
        # Store the full type list too. Google's primary type for a dental
        # surgery is genuinely "hospital", so the disqualifying signal lives in
        # the secondary types. Keeping them means any later re-filter is free.
        rows.append([name, round(lat, 6), round(lng, 6),
                     place.get("rating") or 0, place.get("userRatingCount") or 0,
                     place.get("primaryType") or "",
                     sorted(place.get("types") or [])])
    rows.sort(key=lambda r: r[0].lower())
    return rows, requests_made, foreign, warnings, excluded


def main():
    args = sys.argv[1:]
    key = args[0].strip() if args else input("Paste your Google API key: ").strip()
    if not key:
        sys.exit("No key given.")
    wanted = [a for a in args[1:] if a in CATEGORIES] or list(CATEGORIES)
    unknown = [a for a in args[1:] if a not in CATEGORIES]
    if unknown:
        print(f"Ignoring unknown categories: {', '.join(unknown)}")
        print(f"Valid categories: {', '.join(CATEGORIES)}")

    existing = {}
    if os.path.exists(OUT_PATH):
        try:
            existing = json.load(open(OUT_PATH, encoding="utf-8"))
        except Exception:
            existing = {}

    lines = ["=== GOOGLE PLACES SWEEP ==="]
    total_requests = 0
    for category in wanted:
        print(f"\nSweeping {category} ...", flush=True)
        rows, requests_made, foreign, warnings, excluded = collect(key, category, CATEGORIES[category])
        total_requests += requests_made
        existing[category] = rows
        lines.append(f"{category}: {len(rows)} kept, {foreign} outside Switzerland dropped, "
                     f"{excluded} excluded by rulebook name rules, {requests_made} requests")
        for warning in warnings:
            lines.append(f"  WARNING: {warning}")
        print(f"  {len(rows)} kept, {requests_made} requests")
        # Write after every category so a later failure never loses earlier work.
        os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
        with open(OUT_PATH, "w", encoding="utf-8") as handle:
            json.dump(existing, handle, ensure_ascii=False, separators=(",", ":"))

    lines.append(f"Total requests this run: {total_requests}")
    lines.append(f"Categories now in the file: {', '.join(sorted(existing))}")
    lines.append("=== END ===")
    report = "\n".join(lines)
    print("\n" + report)
    with open(REPORT_PATH, "w", encoding="utf-8") as handle:
        handle.write(report + "\n")
    print(f"\nWrote {OUT_PATH} and {REPORT_PATH}")


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
