const SECTIONS = [
  {id:"core", label:"Core house rules"},
  {id:"questions", label:"Question semantics"},
  {id:"thresholds", label:"Data thresholds & filtering"},
  {id:"sharing", label:"Sharing & versioning"},
  {id:"gaps", label:"Known gaps & limitations"},
  {id:"attribution", label:"Attribution & data provenance"},
];

// Small, controlled vocabulary so the tag filter stays scannable rather
// than one chip per entry. Tags are cross-cutting (data source, mechanism,
// scope) - they deliberately don't just mirror the section list above.
const TAGS = ["google","swisstopo","osm","boundary","interrail","stations","clues","sharing","thresholds","units","rulebook","gaps","offline"];

const ASSUMPTIONS = [
  // --- Core house rules ---
  {id:"core-arbiter", section:"core", title:"Google Maps is the arbiter",
   body:"Stations and places come from Google Places, and every marker links to Google Maps so a dispute can be settled on the spot. Where Google has no data (boundaries, mountains, water) the layer is labelled in the interface as not Google-verified.",
   tags:["google"]},
  {id:"core-large-only", section:"core", title:"Built for Large games only",
   body:"Follows the official Large-game question pad. Small and Medium variants are not implemented.",
   tags:["rulebook"]},
  {id:"core-boundary", section:"core", title:"The Swiss border, per swisstopo not a smoothed guess",
   body:"Anything outside Switzerland does not exist for the game. The outline (SWISS_GEO) is built from official swisstopo CANTONS data plus OSM lake polygons, simplified to about 100 m, so it tracks the real border (the Rhine near Buchs SG, not a straight diagonal) and correctly excludes Campione d'Italia as an interior hole. Country membership for individual places and stations is still decided by Google's own address though, not by testing coordinates against this outline - the outline is only ever a guide, Google settles disputes.",
   tags:["swisstopo","osm","boundary","google"]},
  {id:"core-interrail", section:"core", title:"Excursion-only railways do not count",
   body:"This group plays with an Interrail pass, not a GA or Swiss Travel Pass. A station is excluded only if every line serving it is Interrail-excluded. Currently excluded: the Gornergrat, Jungfrau, Rigi, Pilatus, Brienz Rothorn and Furka-Bergstrecke cog/heritage railways, the Schynige Platte branch of Berner Oberland-Bahnen (route 68 only, not its ordinary regional service), the Sihltal-Zurich-Uetliberg-Bahn's Zurich S-Bahn services (S4, S10, night SN4), and Swiss Rail Traffic AG Glattbrugg's charter/freight EXT workings.",
   tags:["interrail","stations"]},
  {id:"core-interrail-nuance", section:"core", title:"Rigi and Pilatus are excluded either way",
   body:"Rigi Bahnen AG and Pilatusbahnen are discount-only (50%) under the GA/Swiss Travel Pass too, so they land in the same excursion bucket regardless of which pass standard is assumed. Vitznau was considered for a carve-out, since it is a real lakeside town normally reached by boat or PostBus, but was dropped with the rest of the Rigi group instead, since this project only tracks rail stations and has no boat or PostBus data to justify a rail-only exception.",
   tags:["interrail","stations"]},

  // --- Question semantics ---
  {id:"q-radar", section:"questions", title:"Radar: hit keeps the circle, miss cuts it",
   body:"Radar asks about the hider's location, not their hiding zone.",
   tags:["rulebook"]},
  {id:"q-thermo", section:"questions", title:"Thermometer is a half-plane, warned but never blocked",
   body:"A perpendicular bisector splits the map; hotter keeps the half toward the end point. Each thermometer question has a minimum distance the asker must have travelled for the answer to be valid (half/3/10/50 mi or 1/5/15/75 km); this is compared live against the actual straight-line distance between the two points. Falling short only warns, since the geometry is valid either way.",
   tags:["rulebook"]},
  {id:"q-matching", section:"questions", title:"Matching: Voronoi cell, or containment for admin areas",
   body:"Uses the Voronoi cell of the asker's nearest thing, or containment for canton and municipality.",
   tags:["rulebook"]},
  {id:"q-measuring", section:"questions", title:"Measuring: discs for places, bands for lines and borders",
   body:"A union of discs, radius equal to the asker's own distance, around every candidate place. Border, water, canton border, district border and high-speed rail line references use a band around the boundary instead.",
   tags:["rulebook"]},
  {id:"q-highspeed", section:"questions", title:"High-speed rail: highspeed=yes or maxspeed >= 200 km/h, by track segment",
   body:"Every OpenStreetMap railway track tagged highspeed=yes, or with a maxspeed of 200 km/h or more in either direction, counts - checked segment by segment rather than as a hand-picked list of named lines, since speed can change partway along a line (the Solothurn-Wanzwil line runs at 140 km/h from Solothurn to Subingen and only reaches 200 km/h after that, so only the faster stretch counts). Touching qualifying segments are merged into continuous lines for the measuring band.",
   tags:["thresholds"]},
  {id:"q-elevation", section:"questions", title:"Elevation uses a 1 km grid, rounded to the nearest 50 m",
   body:"The asker's own elevation is looked up from a swisstopo grid, rounded to the nearest 50 m per house ruling, then a contour polygon is built for everywhere at or above that elevation. This is the only clue type built on a raster grid rather than vector polygons or lines.",
   tags:["swisstopo","thresholds"]},
  {id:"q-tentacles", section:"questions", title:"Tentacles measure from the asker, not the named place",
   body:"The radius is measured from the asker, and only places inside that radius are candidates. Naming a place keeps the part of the asker's disc nearest that place; not in range removes the whole disc. Official radii: 1 mile (2 km) for museums, libraries, movie theatres and hospitals; 15 miles (25 km) for zoos, aquariums and amusement parks. Train stations are not a tentacle category.",
   tags:["thresholds"]},
  {id:"q-station", section:"questions", title:"Station identified is the strongest possible clue",
   body:"Not one of the five rulebook question types; built as an ordinary clue type instead so it gets sharing, editing and the viability filter for free. Its polygon uses whatever the hiding-zone radius is at the moment it is built, so it tracks the shared radius setting rather than being frozen independently of it.",
   tags:["clues"]},
  {id:"q-frozen-geometry", section:"questions", title:"A clue's geometry freezes the moment it is added",
   body:"Later data changes never silently rewrite an existing clue. Editing a clue (the pencil icon) repopulates the right tool's form and replaces that clue in place on the next commit, rather than appending a new one.",
   tags:["clues"]},
  {id:"q-units", section:"questions", title:"Imperial and metric are parallel rule sets, not conversions",
   body:"The Large-game question pad has two official value sets (10 mi radar and 15 km radar are different questions, not the same distance in two units). Toggling units never touches an existing clue: each clue's label is baked in at add time from whatever unit was active then, and stays that way regardless of later toggling.",
   tags:["units","clues"]},

  // --- Data thresholds & filtering ---
  {id:"t-min-reviews", section:"thresholds", title:"Minimum Google reviews: a live slider on top of a fixed per-category floor",
   body:"The Places tab's \"Minimum Google reviews\" slider is what you actually control: a single number, default 5, adjustable 0 to 50, applied the same way to every target-place category (not stations). It sits on top of a per-category floor baked into the shipped dataset when it was built and not adjustable in the app (hospital 50, airport 100, museum 10, park and amusement park 20, library, cinema and golf 5, zoo 10, aquarium 0, consulate 5). Airports that pass their review floor are additionally audited against Google Flights. Review count turned out to be the only strong signal for whether a place is the real thing, since type filtering alone barely helps (Google's primary type for a dental surgery is genuinely \"hospital\").",
   tags:["google","thresholds"]},
  {id:"t-elevation-peaks", section:"thresholds", title:"Mountain peaks are filtered to 2000 m and above",
   body:"Peaks below that elevation are dropped from the mountain layer entirely.",
   tags:["osm","thresholds"]},
  {id:"t-hiding-radius", section:"thresholds", title:"Default hiding-zone radius is 1 km",
   body:"Persisted in this browser between sessions, editable per game via the zone-radius selector.",
   tags:["thresholds"]},
  {id:"t-swissgeo-precision", section:"thresholds", title:"The Swiss outline is simplified to about 100 m",
   body:"Rebuilt from swisstopo CANTONS data plus OSM lake polygons at a 100 m simplify tolerance. The rebuild fills about 84 small stray gaps (6.04 km2 total) along the Bodensee shore, where the swisstopo canton edge and the OSM lake polygon disagree, since none of them are an intentional exclusion (only Campione d'Italia, at 2.49 km2, is). Final land area is about 41,288 km2.",
   tags:["swisstopo","osm","boundary","thresholds"]},
  {id:"t-districts-source", section:"thresholds", title:"Districts come from OpenStreetMap, not the federal boundary set",
   body:"swissBOUNDARIES3D's export used here does not carry the 2nd administrative division, so districts are sourced from OpenStreetMap instead. Some cantons have abolished districts entirely, which the game treats as a valid null answer.",
   tags:["osm","boundary"]},

  // --- Sharing & versioning ---
  {id:"s-hash-format", section:"sharing", title:"A shared map lives entirely in the URL hash",
   body:"The format is #v=3&z=<zone km>&r=<min reviews>&f=<stations>.<places>&c=<clue>~<clue>..., never the query string, so a shared link never touches a server.",
   tags:["sharing"]},
  {id:"s-fingerprint", section:"sharing", title:"The fingerprint flags a mismatched dataset",
   body:"The f value is a fingerprint of the sender's station and place counts; a mismatch against the recipient's own counts shows a prominent banner, since the two sides may then disagree on answers.",
   tags:["sharing"]},
  {id:"s-nearest-coord", section:"sharing", title:"Shared places resolve by coordinate, not by name",
   body:"A named tentacle place, or an identified station, resolves by nearest coordinate on replay, since a recipient's dataset may differ slightly from the sender's.",
   tags:["sharing"]},
  {id:"s-version-bump", section:"sharing", title:"SHARE_VERSION bumps whenever the wire format changes",
   body:"Currently 3, for the thermometer's minimum-distance question field and the station clue type. Old links just show a graceful \"this build does not understand that format\" banner rather than misparsing.",
   tags:["sharing"]},
  {id:"s-autosave", section:"sharing", title:"Clues auto-save to this browser between visits",
   body:"With no share hash in the URL, the current clue list is saved to and restored from this browser's local storage automatically, so closing and reopening the tab does not lose your progress.",
   tags:["sharing","clues","offline"]},

  // --- Known gaps & limitations ---
  {id:"g-airport-audit", section:"gaps", title:"Airports needed more than a review count",
   body:"Of the 17 review-count-proxy airport entries, 5 have flights displayed to or from the airport on Google Flights: Bern, Geneva, Sion, St. Gallen-Altenrhein and Zurich. Seasonal and charter flights count. The manual audit is persisted in the filter so rerunning it cannot restore the rejected fields. See data/airport-audit-report.txt for the full breakdown.",
   tags:["google","thresholds","gaps"]},
  {id:"g-coastline", section:"gaps", title:"Coastline and landmass return null answers",
   body:"Switzerland is landlocked (coastline) and one contiguous piece (landmass), so both count as automatically answered under the rulebook's own definitions. Documented, not implemented as a live check.",
   tags:["rulebook"]},
  {id:"g-sealevel", section:"gaps", title:"Sea level and altitude are implemented, unlike coastline and landmass",
   body:"The rulebook's warning that phone altitude readings are unreliable does not apply here, since the asker's elevation is looked up from the same grid as the hider's, never read off a device.",
   tags:["swisstopo"]},
  {id:"g-hospitals", section:"gaps", title:"Hospital coverage is slightly incomplete in a few city centres",
   body:"The Google Places sweep hit its subdivision floor in a handful of dense areas.",
   tags:["google"]},
  {id:"g-missing-stations", section:"gaps", title:"Three stations Google does not list",
   body:"Faulensee, Trübbach and Weite are absent under the strict Google-only rule.",
   tags:["google","stations"]},
  {id:"g-heritage-railways", section:"gaps", title:"Heritage and rack railways cannot be matched to transit lines",
   body:"Google often does not type termini like Pilatus Kulm, Brienzer Rothorn or the Furka steam line as train_station, so they are absent from the station list and cannot be matched against the GTFS feed. Accepted as a gap, since these lines typically need a supplement beyond a standard rail pass anyway.",
   tags:["google","stations"]},
  {id:"g-metro", section:"gaps", title:"Metro lines are not implemented",
   body:"The app holds no metro line geometry, so any question referencing a metro line has no data to check against.",
   tags:[]},

  // --- Attribution & data provenance ---
  {id:"a-stations", section:"attribution", title:"The station list blends two sources",
   body:"The Trainline EU open stations dataset (Open Database Licence) seeds the core list; live Google Places data then verifies and extends it, since the house rule is strict Google.",
   tags:["google"]},
  {id:"a-boundaries", section:"attribution", title:"Administrative boundaries come from two different official sources",
   body:"Cantons and municipalities come from swissBOUNDARIES3D (the official federal dataset) via the ch-municipalities project. Districts come from OpenStreetMap instead, since swissBOUNDARIES3D's export here does not carry that division.",
   tags:["swisstopo","osm","boundary"]},
  {id:"a-swisstopo-licence", section:"attribution", title:"swisstopo's elevation grid requires mandatory attribution",
   body:"The DHM25 elevation grid used for elevation questions carries a bespoke Geoinformation Act licence, not CC-BY, requiring a mandatory \"(c) swisstopo\" credit.",
   tags:["swisstopo"]},
  {id:"a-vendored", section:"attribution", title:"Leaflet and Turf.js are vendored locally, not loaded from a CDN",
   body:"Pinned versions ship in the vendor folder, so the map loads with no internet connection; a CDN fallback only kicks in if the local copy is missing entirely.",
   tags:["offline"]},
  {id:"a-highspeed-osm", section:"attribution", title:"The high-speed rail line list is traced from OpenStreetMap",
   body:"scripts/fetch_highspeed.py queries Overpass for railway tracks tagged highspeed=yes or maxspeed >= 200 km/h and merges touching ones into continuous lines, so the measuring band follows the real alignment - including tunnel curves - rather than a small number of hand-picked waypoints.",
   tags:["osm"]},
];

(function(){
  const state = {q:"", sections:new Set(), tags:new Set()};

  const searchEl = document.getElementById("assum-search");
  const sectionChipsEl = document.getElementById("section-chips");
  const tagChipsEl = document.getElementById("tag-chips");
  const contentEl = document.getElementById("assum-content");
  const emptyEl = document.getElementById("assum-empty");

  function chip(container, id, label, set){
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    b.setAttribute("aria-pressed", "false");
    b.addEventListener("click", () => {
      if (set.has(id)) { set.delete(id); b.classList.remove("on"); b.setAttribute("aria-pressed","false"); }
      else { set.add(id); b.classList.add("on"); b.setAttribute("aria-pressed","true"); }
      render();
    });
    container.appendChild(b);
  }

  SECTIONS.forEach(s => chip(sectionChipsEl, s.id, s.label, state.sections));
  TAGS.forEach(t => chip(tagChipsEl, t, t, state.tags));

  let debounceTimer = null;
  searchEl.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      state.q = searchEl.value.trim().toLowerCase();
      render();
    }, 120);
  });

  function matches(item){
    if (state.sections.size && !state.sections.has(item.section)) return false;
    if (state.tags.size && !item.tags.some(t => state.tags.has(t))) return false;
    if (state.q){
      const hay = (item.title + " " + item.body + " " + item.tags.join(" ")).toLowerCase();
      if (!hay.includes(state.q)) return false;
    }
    return true;
  }

  function render(){
    contentEl.innerHTML = "";
    let shown = 0;
    SECTIONS.forEach(sec => {
      const items = ASSUMPTIONS.filter(a => a.section === sec.id && matches(a));
      if (!items.length) return;
      shown += items.length;

      const wrap = document.createElement("div");
      wrap.className = "assum-section";

      const h = document.createElement("p");
      h.className = "section-label";
      h.textContent = sec.label;
      wrap.appendChild(h);

      const grid = document.createElement("div");
      grid.className = "assum-grid";
      items.forEach(item => {
        const card = document.createElement("article");
        card.className = "assum-card" + (item.section === "gaps" ? " gap-note" : "");
        card.id = item.id;

        const h3 = document.createElement("h3");
        h3.textContent = item.title;
        card.appendChild(h3);

        const p = document.createElement("p");
        p.textContent = item.body;
        card.appendChild(p);

        const tagRow = document.createElement("div");
        tagRow.className = "tag-row";
        item.tags.forEach(t => {
          const s = document.createElement("span");
          s.className = "tag";
          s.textContent = t;
          tagRow.appendChild(s);
        });
        card.appendChild(tagRow);

        grid.appendChild(card);
      });
      wrap.appendChild(grid);
      contentEl.appendChild(wrap);
    });
    emptyEl.hidden = shown > 0;
  }

  render();

  // Deep link support: /assumptions.html#core-interrail scrolls straight
  // to that card once the filterable content has rendered.
  if (location.hash.length > 1){
    const target = document.getElementById(location.hash.slice(1));
    if (target) target.scrollIntoView({block:"start"});
  }
})();
