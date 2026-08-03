# Scoping: live in-browser re-sweep of stations/places/OSM layers

Status: design only, nothing implemented yet. Lives on `feature/live-data-resweep`, does not touch `main`.

## Why this is a different feature from the one just removed

`main` just had its single-viewport "Load Google places for this view" button removed, because
it let one player's browser quietly drift onto different target-place data than everyone else's
mid-game. That principle - **every seeker works off the same committed `data/*.json`** - still
holds here. This feature is not a way for a player to refresh their own view; it is a way for
whoever is **setting up the app for a new region** (a country beyond Switzerland) to generate
that region's `stations.json` / `places-raw.json` / `osm-layers.json` from a browser, without
needing a local Python environment. The output is still reviewed and committed once, the same
as today's pipeline, so every player still ends up on one shared file. Think of it as a browser
front-end for `fetch_stations_google.py` / `fetch_places_google.py` / `fetch_osm_layers.py`, not
a new way to play the game.

Because of that framing, this tool belongs behind an "advanced / data setup" entry point kept
well away from the normal play panel, never something an ordinary seeker stumbles into.

## What can realistically port to the browser, and what can't

| Step | Today | In-browser feasibility |
|---|---|---|
| Station sweep (`fetch_stations_google.py`) | Python, adaptive grid | Yes - Places API (New) `searchNearby`/`searchText`, same as the removed feature, just walked exhaustively over a region instead of one viewport |
| Places sweep (`fetch_places_google.py`) | Python, adaptive grid, multi-category | Yes - same engine as stations, more categories and volume |
| Review-count filtering (`filter_places.py`) | Python, tunable `MIN_REVIEWS` dial | Keep this Python-only. It's re-run freely and for free against the raw sweep output; duplicating the threshold logic in JS would just create a second place for that dial to drift out of sync |
| OSM layers (`fetch_osm_layers.py`) | Python, Overpass API | Yes - Overpass is a plain HTTP API, no key needed, callable from a browser |
| Swiss outline repair (`fix_swiss_geo.py`) | Python + shapely/pyproj | No. Needs real polygon geometry libraries browsers don't have (turf.js doesn't cover this), and for a new country there is no boundary source baked in yet at all - out of scope for this tool. A new region needs its own outline decision made once, offline, same as Switzerland got |
| Private railway audit (`audit_private_railways.py`) | Python, cross-references a country-specific GTFS feed | No. Needs per-country knowledge of which operators are pass-excluded (this app's Interrail rule is Switzerland-specific); stays a manual research step per new region |
| Elevation grid | swisstopo-specific source | No, not via Google. A new country needs its own elevation source decided (Google Elevation API could plausibly join *this* sweep tool later, since it's also key-gated, but that's a separate addition, not part of v1) |
| High-speed line list | Hand-maintained | No, editorial by definition |

So the realistic scope of this feature is the three sweep-able layers: **stations, places, OSM
peaks/water**. Everything else remains an offline, per-region, human-reviewed step exactly as it
is today.

## Workflow

1. A maintainer/deployer opens the advanced data-setup view and pastes a Google API key (any
   restriction that permits the page's origin - same key constraints as the old in-app field,
   documented in `CLAUDE.md`).
2. They give the tool a region to sweep. For v1 this is a simple bounding box (or a pasted
   GeoJSON polygon), not a full administrative outline - avoids the chicken-and-egg problem of
   needing a Switzerland-quality boundary before you can even start sweeping a new country.
3. Before starting, the tool shows an estimate: approximate cell count for the chosen area and
   grid floor, therefore an approximate number of API calls and a rough cost figure, so the
   person knows what they're about to spend before committing minutes and money to it.
4. On start, the tool runs the same adaptive-subdivision loop as the Python scripts: sweep a
   cell, and if the 20-result cap is hit, split it into four and re-queue - reimplemented in JS
   since there's no shared Python/JS bridge in this buildless static site.
5. A progress panel shows: cells processed vs queued, running per-category counts, elapsed and
   estimated remaining time, and a scrolling log of any per-cell failures. Unlike the old
   feature (which aborted the whole loop on the first HTTP error), a single cell's failure is
   retried once, then skipped and logged - a transient error partway through a long sweep
   shouldn't discard everything collected before it.
6. A **Cancel** button stops before the next request and immediately offers to export whatever
   has been collected so far - a cancelled sweep is still useful, not wasted.
7. Throttling: a small delay between requests to stay under Google's QPS limits, and a
   `beforeunload` warning so the person doesn't lose an in-progress sweep by accidentally
   closing or reloading the tab. (Full resumability via IndexedDB is a phase-4 stretch, not v1 -
   see below.)
8. On completion (or cancellation), the tool offers `stations.json` / `places-raw.json` /
   `osm-layers.json` as browser downloads (`Blob` + `<a download>`) in the exact shape the
   existing scripts already produce, so the rest of the pipeline doesn't change: the maintainer
   still runs `filter_places.py` locally, still sanity-checks against Google Maps, still commits
   the results the same way as today.

## Suggested phasing

1. **Stations only.** Smallest schema, validates the sweep engine and progress UI end-to-end
   against a real Places API quota.
2. **Places**, multi-category, reusing the same engine - larger volume, exercises the
   review-count/rating fields.
3. **OSM layers** (peaks/water via Overpass) - no key, independent rate limit, can run standalone.
4. **Stretch**: resumable sweeps (persist the frontier queue and partial results to IndexedDB so
   a reload can continue rather than restart), and a live map showing swept vs. remaining cells
   during the run.

## Where the code should live

A separate tool, isolated from the player-facing `app.js` path - e.g. `tools/resweep.html` +
`tools/resweep.js` - rather than a hidden mode inside the main app, so there's no risk of it
ever shipping reachable to players. It can still reuse the existing `CATS`/`GTYPE`-style category
list and the Turf usage patterns already established in `app.js` for consistency.

## Open questions for whoever picks this up

- Bounding box vs pasted GeoJSON for the v1 region input - simplicity vs precision.
- Where the Places API cost estimate's per-call price assumption should live so it doesn't go
  stale if Google's pricing changes.
- Whether a first target expansion country is already decided, which would make "region input"
  concrete instead of generic.
