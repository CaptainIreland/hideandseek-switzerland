# Project context for Claude Code

An unofficial companion map for playing Jet Lag: The Game "Hide + Seek" across Switzerland. Seekers enter each answer the hider gives, and the map narrows to the area that still fits every clue.

## House rules that drive the design

1. **Google Maps is the arbiter.** Stations and places come from Google Places, and every marker links to Google Maps so a dispute can be settled on the spot. Where Google has no data (boundaries, mountains, water) the layer is labelled in the interface as not Google-verified.
2. **Built for Large games only**, following the official question pad. Small and Medium variants are not implemented.
3. **The map boundary rule.** Anything outside Switzerland does not exist for the game. Country membership is decided by Google's own address, not by testing coordinates against the outline. The outline is smoothed and is wrong within about a kilometre of the border in both directions, which once wrongly excluded Chiasso and wrongly included Konstanz.
4. **UK English, and no em dashes anywhere**, including code comments and interface text.

## Layout

- `index.html`, `styles.css`, `app.js` load in that order. No build step, no framework.
- `app.js` has large baked data literals near the top: `CANTONS`, `MUNICIPALITIES`, `TARGETS` (places), `STATIONS_GOOGLE`. The app works fully offline from these; the `data/` files override them when served.
- Leaflet draws, Turf.js does the geometry. Both are vendored in `vendor/` (pinned versions: Leaflet 1.9.4, Turf.js 6.5.0) so the app loads with no internet connection; `index.html` falls back to cdnjs only if the local copy is missing.
- `config.js` holds an optional Google key. Never commit a real key here. The in-app field stores it in localStorage instead.

## Data pipeline

Run from the repository root. Only the first two cost money.

```sh
python scripts/fetch_stations_google.py YOUR_KEY   # writes data/stations.json
python scripts/fetch_places_google.py YOUR_KEY     # writes data/places-raw.json
python scripts/filter_places.py                    # raw -> data/places.json, free, re-run freely
python scripts/fetch_osm_layers.py                 # writes data/osm-layers.json, free, no key
```

The sweep scripts walk Switzerland in adaptive square cells, subdividing wherever Google's 20-result cap is hit. A key used for scripts must have its application restriction set to None, because a key locked to a website rejects calls made outside a browser. Use a second key for that and keep it out of the repository.

`filter_places.py` is deliberately separate from the sweep so thresholds can be tuned without paying again. `MIN_REVIEWS` at the top of that file is the main dial. Review count turned out to be the only strong signal for whether a place is the real thing: Google's primary type for a dental surgery is genuinely `hospital`, so type filtering alone barely helped.

## Question semantics, taken from the rulebook

- **Radar**: hit keeps the circle, miss cuts it. Radar asks about the hider's location, not their hiding zone.
- **Thermometer**: half-plane on the perpendicular bisector, toward the end point when hotter.
- **Matching**: Voronoi cell of the asker's nearest thing, or containment for canton and municipality.
- **Measuring**: union of discs of radius equal to the asker's own distance, around every candidate. For border and water references it is a band around the boundary instead.
- **Tentacles**: the radius is measured **from the asker**, and only places inside that radius are candidates. Naming a place keeps the part of the asker's disc nearest that place. "Not in range" removes the whole disc. Official radii are one mile for museums, libraries, movie theatres and hospitals, and fifteen miles for zoos, aquariums and amusement parks. Train stations are not a tentacle category.

Clue geometry is frozen when a clue is added, so later data changes never silently rewrite an existing clue.

## Performance traps already hit

- Buffering detailed border lines by tens of kilometres took over three minutes. The canton border band instead erodes each canton and subtracts, which takes about a second. Do not reintroduce line buffering at scale.
- `turf.polygonToLine` returns a Feature for a Polygon but a FeatureCollection for a MultiPolygon. Handling only the first form silently dropped every canton with an exclave.
- The station viability filter recomputes after every clue and hides stations whose hiding zone no longer overlaps the possible area. Keep it bounding-box gated.

## Known gaps

- **Airports need a manual pass.** The rulebook counts an airport as commercial only if Google Flights shows flights to or from it. The current list of 17 is a review-count proxy and includes obvious non-airports.
- **Districts, the 2nd administrative division, are missing.** The federal dataset used here does not carry them.
- **Coastline, landmass and sea level** return null answers in Switzerland by the rulebook's own definitions. Documented, not implemented.
- **Hospital coverage is slightly incomplete in a few city centres**, where the sweep hit its subdivision floor.
- Three stations Google does not list (Faulensee, Trübbach, Weite) are absent under the strict rule.

## Testing

There is no test runner. Geometry changes were validated by evaluating `app.js` in Node with real `@turf/turf` and stub `document`/`L` objects, then asserting on areas, containment and timings. Area conservation is the strongest check available: clipping the same region with a clue and its inverse should sum to Switzerland's 41,408 km2 within a couple of percent.

Browser behaviour cannot be verified from a sandbox, so interface changes need a human to open the page. A CSS rule once made `hidden` ineffective on the tool forms and every form rendered at once, which no amount of static checking caught.
