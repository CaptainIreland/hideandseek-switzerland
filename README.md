# Hide + Seek Switzerland field map

An unofficial, phone-friendly planning and deduction map for playing the Jet Lag: The Game Hide + Seek format across Switzerland.

## Run it

Use the deployed GitHub Pages site, or serve the folder locally with any static web server:

```sh
python3 -m http.server 4173
```

Then open http://localhost:4173. The location button needs HTTPS or localhost. Opening index.html straight from the file system mostly works too, but the bundled station file only loads over a server.

## What it does

- Every Swiss railway station and halt, each with a hiding zone ring (quarter, half, or one mile presets)
- Target places for tentacle-style questions (hospitals, museums, libraries, cinemas, zoos, aquariums, theme parks) with a minimum Google reviews filter
- A Narrow down tab: enter radar, thermometer, and within answers, and the map keeps only the area that fits every clue
- Live phone location with a GPS (Global Positioning System) accuracy ring
- A seven-day browser cache plus a bundled fallback set for weak field connections

## Ground truth

The group's arbiter is Google Maps. Under the strict house rule the station list itself is exactly Google's train station listings for Switzerland. Target places come from Google, with their live ratings and review counts, and the minimum-reviews filter uses Google review counts. Every marker, stations included, links straight to its spot on Google Maps for on-the-ground verification. Administrative boundaries (the country outline and cantons) only steer the canton question, since Google does not publish boundary data.

## Station data

House rule: strict Google. The station list is exactly what Google Maps lists as train stations in Switzerland, built with your Google API key:

```sh
python scripts/fetch_stations_google.py
```

The script sweeps the country in adaptive square cells, subdividing wherever Google's 20-result cap is hit, so dense cities are fully captured. It keeps places Google types as train_station, sets light-rail-only entries aside for a group ruling, drops anything outside the Swiss outline, and audits the result against `data/stations-core.json` so any major station Google lacks is listed before it silently vanishes from the game. Review the printed report, then commit `data/stations.json` and `data/stations-google.json`.

## Question coverage

Built for Large games, following the official question pad. Radar, thermometer, matching (canton or nearest station), measuring, and tentacles are all implemented. Tentacle radii and categories follow the rulebook: one mile for museums, libraries, movie theatres and hospitals, fifteen miles for zoos, aquariums and amusement parks. The tentacle radius is measured from the asker, and only places inside that radius are candidates.

Metro lines are not implemented, since the app holds no metro line geometry.

## Place data

Stations come from `scripts/fetch_stations_google.py`. Every other place category comes from `scripts/fetch_places_google.py`, which sweeps the country the same way and writes `data/places.json`:

```sh
python scripts/fetch_places_google.py YOUR_KEY
python scripts/fetch_places_google.py YOUR_KEY park museum
```

Both scripts ask Google which country a place is in and use that answer, rather than testing coordinates against a simplified outline. The outline is smoothed and is unreliable within about a kilometre of the border, in both directions.

## Layers that are not from Google

The house rule makes Google Maps the arbiter, but Google does not publish boundaries, mountains or water bodies. Those layers come from elsewhere and are labelled in the interface as not Google-verified. Settle any dispute on Google Maps.

- Cantons (1st administrative division) and municipalities (3rd) come from swissBOUNDARIES3D, the official federal dataset, via the ch-municipalities project
- Mountain peaks and named water bodies come from OpenStreetMap:

```sh
python scripts/fetch_osm_layers.py
```

That writes `data/osm-layers.json` and switches on the mountain and water questions, which stay greyed out until it exists. Peaks are filtered to 2000 m and above by default; change MIN_ELEVATION in the script to move that bar.

Districts (2nd administrative division) are not implemented, since the federal dataset used here does not carry them.

## Questions with no answer in Switzerland

Under the rulebook's own definitions these return a null answer, which counts as an answered question:

- Coastline, since Switzerland is landlocked
- Landmass, since the whole country is one piece, so the answer is always a match
- Sea level, which needs elevation data the app does not hold

## For people helping test

You do not need a Google key. Every dataset the game uses is committed to this repository, so the site works as soon as it loads. Open the published link, report anything odd in the Issues tab, and include what you asked and what the map did.

The key is only needed to regenerate the datasets, which is a maintainer job. If you are regenerating them, use a second key with no application restriction, because a key locked to a website will refuse requests made from a script. Keep that second key out of the repository.

## Roadmap

1. Done: the Large-game question engine, Google-sourced stations and places, official boundaries, and the viability filter
2. Next: confirm which airports are commercial via Google Flights, then publish to GitHub Pages
3. Later: shareable game state in the URL, and Swiss transit overlays

## Data and attribution

- Stations and base map: [OpenStreetMap contributors](https://www.openstreetmap.org/copyright)
- Core station list: derived from the [Trainline EU stations dataset](https://github.com/trainline-eu/stations), Open Database Licence
- Target place details (names, ratings, review counts): Google
- Map rendering: [Leaflet](https://leafletjs.com). Geometry: [Turf.js](https://turfjs.org)
- Inspired by a friend's Munich Zone M field map and by [taibeled/JetLagHideAndSeek](https://github.com/taibeled/JetLagHideAndSeek)

This is an unofficial fan project and is not affiliated with Jet Lag: The Game, Wendover Productions, or Nebula.
