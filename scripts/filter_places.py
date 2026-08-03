#!/usr/bin/env python3
"""Turn the raw Google sweep into the trimmed set the game actually uses.

Usage, from the repository root:

    python scripts/filter_places.py            # apply the rules
    python scripts/filter_places.py --loose     # keep medical practices as hospitals
    python scripts/filter_places.py --min 10    # also require 10 or more reviews

Reads data/places-raw.json and writes data/places.json. This runs entirely on
already-downloaded data, so it costs nothing and can be re-run as often as you
like while tuning. If a rule looks wrong, change EXCLUDE_TYPES below and run it
again rather than paying for another sweep.

Why this exists: Google's primary type for a dental surgery is genuinely
"hospital", and for a playground it is "park". The disqualifying signal sits in
the secondary types, which the sweep now stores.
"""
import json
import os
import sys
from collections import Counter

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_PATH = os.path.join(BASE_DIR, "data", "places-raw.json")
OUT_PATH = os.path.join(BASE_DIR, "data", "places.json")
REPORT_PATH = os.path.join(BASE_DIR, "data", "places-filter-report.txt")

# Secondary types that disqualify a place from counting as the category.
EXCLUDE_TYPES = {
    "hospital": {
        "dentist", "beauty_salon", "spa", "veterinary_care", "pharmacy",
        "drugstore", "massage", "physiotherapist", "chiropractor",
        "skin_care_clinic", "nursing_home", "assisted_living_facility",
        "wellness_center", "hair_salon", "gym", "psychologist",
    },
    "museum": {"store", "shopping_mall", "restaurant", "bar", "cafe",
               "hotel", "lodging", "book_store"},
    "library": {"book_store", "store", "shopping_mall"},
    "cinema": {"store", "shopping_mall", "restaurant", "bar"},
    "park": {"parking", "rest_stop", "truck_stop", "campground", "playground",
             "dog_park", "restaurant", "cafe", "hotel", "lodging"},
    "zoo": {"farm", "pet_store", "store", "restaurant", "cafe", "lodging",
            "hotel", "farmstay"},
    "themepark": {"gym", "sports_complex", "store", "restaurant",
                  "hotel", "lodging", "spa"},
    "golf": {"store", "travel_agency", "restaurant", "bar", "hotel", "lodging",
             "gym", "miniature_golf_course"},
    "airport": {"restaurant", "hotel", "lodging", "travel_agency", "store",
                "taxi_stand", "tourist_attraction", "sports_complex"},
    "consulate": {"art_gallery", "store", "restaurant", "travel_agency"},
    "aquarium": {"pet_store", "store", "restaurant"},
}
# Only applied without --loose. A working hospital is often tagged "doctor" too,
# so this is the aggressive half of the rule and is reported separately.
# Google's own review counts are the only strong signal for whether a place is
# the real thing or a one-room practice. The thresholds below were chosen from
# the actual Swiss distributions so each category lands at a plausible size.
# These are the main dial: raise one to tighten, lower it to widen.
MIN_REVIEWS = {
    "hospital": 50, "museum": 10, "library": 5, "cinema": 5, "park": 20,
    "zoo": 10, "aquarium": 0, "themepark": 20, "golf": 5,
    "airport": 100, "consulate": 5,
}
# WARNING: airport's threshold is only a proxy. data/places.json's committed
# airport list was additionally hand-curated against Google Flights (see
# data/airport-audit-report.txt) to drop general aviation/military/charter
# fields this review-count filter alone cannot tell apart. Re-running this
# script regenerates the full review-count-proxy list from data/places-raw.json
# and silently discards that manual curation, even with no fresh sweep - redo
# the Google Flights check before committing data/places.json again.
# Only applied with --strict-medical. Some genuine hospitals carry these tags,
# so the review threshold usually does this job better.
MEDICAL_PRACTICE = {"hospital": {"doctor", "medical_clinic", "medical_lab"}}


def main():
    args = sys.argv[1:]
    loose = "--loose" in args
    strict_medical = "--strict-medical" in args
    override = None
    if "--min" in args:
        try:
            override = int(args[args.index("--min") + 1])
        except (IndexError, ValueError):
            sys.exit("--min needs a number, for example: --min 10")

    if not os.path.exists(RAW_PATH):
        sys.exit(f"No raw sweep found at {RAW_PATH}. Run fetch_places_google.py first.")
    raw = json.load(open(RAW_PATH, encoding="utf-8"))

    out, lines = {}, ["=== PLACE FILTER ==="]
    lines.append(f"Mode: {'loose, all review thresholds off' if loose else 'per-category thresholds'}"
                 f"{f', overridden to {override} everywhere' if override is not None else ''}"
                 f"{', medical practices excluded' if strict_medical else ''}")
    lines.append(f"{'category':11s} {'raw':>6s} {'kept':>6s} {'type':>6s} {'medical':>8s} {'reviews':>8s}")
    for category, rows in sorted(raw.items()):
        banned = EXCLUDE_TYPES.get(category, set())
        medical = MEDICAL_PRACTICE.get(category, set()) if strict_medical else set()
        if loose:
            min_reviews = 0
        elif override is not None:
            min_reviews = override
        else:
            min_reviews = MIN_REVIEWS.get(category, 0)
        kept, by_type, by_medical, by_reviews = [], 0, 0, 0
        reasons = Counter()
        for row in rows:
            types = set(row[6]) if len(row) > 6 and row[6] else set()
            hit = types & banned
            if hit:
                by_type += 1
                reasons.update(hit)
                continue
            if types & medical:
                by_medical += 1
                continue
            if min_reviews and (row[4] or 0) < min_reviews:
                by_reviews += 1
                continue
            kept.append([row[0], row[1], row[2], row[3], row[4]])
        out[category] = kept
        lines.append(f"{category:11s} {len(rows):6d} {len(kept):6d} {by_type:6d} "
                     f"{by_medical:8d} {by_reviews:8d}  (min {min_reviews})")
        if reasons:
            top = ", ".join(f"{t} ({n})" for t, n in reasons.most_common(4))
            lines.append(f"            excluded mostly by: {top}")

    lines.append("Columns: raw, kept, then dropped by secondary type, "
                 "by medical practice rule, by review count.")
    lines.append("Airports need a manual pass: the rulebook counts an airport as "
                 "commercial only if Google Flights shows flights to or from it.")
    lines.append("=== END ===")
    report = "\n".join(lines)
    print("\n" + report)

    with open(OUT_PATH, "w", encoding="utf-8") as handle:
        json.dump(out, handle, ensure_ascii=False, separators=(",", ":"))
    with open(REPORT_PATH, "w", encoding="utf-8") as handle:
        handle.write(report + "\n")
    total = sum(len(v) for v in out.values())
    print(f"\nWrote {total} places to {OUT_PATH}")


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
