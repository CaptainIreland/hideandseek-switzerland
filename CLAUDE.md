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
- **Tentacles**: the radius is measured **from the asker**, and only places inside that radius are candidates. Naming a place keeps the part of the asker's disc nearest that place. "Not in range" removes the whole disc. Official radii are one mile (2 km) for museums, libraries, movie theatres and hospitals, and fifteen miles (25 km) for zoos, aquariums and amusement parks. Train stations are not a tentacle category.
- **Station identified** is not one of the five rulebook questions; it is the strongest possible clue, built as an ordinary clue type (`buildStationClue()`) rather than a separate mode so it gets sharing, editing and the viability filter for free. Its polygon is a circle at the confirmed station using whatever the hiding-zone radius is *at the moment it is built* (add time, edit time, or replay time), not a value frozen into the share code, because the radius is meant to track the shared `z` setting rather than be independent of it.

Clue geometry is frozen when a clue is added, so later data changes never silently rewrite an existing clue. An existing clue can be edited (pencil icon in the clue list): `startEdit()` repopulates the right tool's form from `clue.share`, including restoring the unit it was created in, and sets `editingIndex` so the next commit replaces `clues[editingIndex]` in place instead of appending. Removing, cancelling or clearing all clues always resets `editingIndex` (adjusting it down, not just clearing it, when an earlier clue is removed while a later one is being edited), otherwise a later update silently writes into the wrong slot.

The "Me" buttons next to each Pick button reuse the existing `map.locate()` call and the `PICKS` coordinate mapping rather than calling `navigator.geolocation` directly, so they share the same accuracy ring and error handling as the corner locate control. A `mePending` flag records which field pair is waiting; the shared `locationfound` handler fills it and warns (but does not block) if the reported accuracy is worse than about 100 m, since a radar centre off by that much materially changes the possible area.

The dark mask always shows Switzerland as the play area, even before the first clue: with no clues it shades world-minus-Switzerland, and only switches to world-minus-possible-region once a clue exists (the red outline stays clue-only, since with none it would just retrace the border). `WORLD_MASK` is deliberately wide (roughly +/-179 longitude, +/-85 latitude) so the grey does not run out a few zoom levels out; keep it short of the antimeridian and the poles, since a polygon touching either makes Turf's boolean ops misbehave.

**Imperial and metric are parallel rule sets, not conversions.** The Large-game question pad has two official value sets (10 mi radar and 15 km radar are different cards, not the same distance in two units), all in `UNIT_TABLE` in `app.js`. The units toggle in the panel header (visible from both tabs) switches which card the preset buttons, the tentacle auto-fill and the hiding-zone selector show, and what unit typed distances and readouts use, but it never touches an existing clue: each clue's label is baked in at add time from whatever unit was active then (`clue.share.unit`), and stays that way regardless of later toggling, exactly like frozen geometry above. Internally every distance is a plain kilometre number (`toKm()`/`fromKm()` convert only at the form fields and the `fmtDist()`/`fmtArea()` readouts); `circle()` and `withinOf()` both take kilometres directly. Toggling units with clues already on the map shows a banner warning that existing clues keep the distances they were created with.

**Sharing a map state.** "Share this map" encodes the clue list into the URL hash (`#v=3&z=<zone km>&r=<min reviews>&f=<stations>.<places>&c=<clue>~<clue>...`), never the query string, so it never hits a server. The hash stores each clue's original inputs (coordinates to 5dp, distances as canonical kilometres) not its frozen geometry, and replay rebuilds every clue through the same `buildRadarClue()`/`buildThermoClue()`/etc. functions the "Add clue" buttons call, so a shared link always reflects whatever `clip()`/`circle()`/voronoi logic the recipient's build actually runs. Distance-bearing clues also carry the sender's creation unit, used only to keep the replayed label reading the way the sender saw it. A named tentacle place, or an identified station (`P|lat|lng`), resolves by nearest coordinate, not by name, since a recipient's dataset may differ slightly. `f` is a fingerprint (station count, place count); a mismatch against the recipient's own counts shows a prominent banner, since the two sides may then disagree on answers. Clues that fail to parse or whose category has no data are dropped and the drop count is reported, never silently shortened. Replay waits for `loadStations()`, `loadPlaces()` and `loadOsm()` to settle before touching the hash, since match/measure/tentacle clues and the fingerprint all depend on that data.

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
