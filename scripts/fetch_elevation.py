#!/usr/bin/env python3
"""Build a coarse elevation grid for the sea-level/altitude measuring question.

Usage, from the repository root:

    python scripts/fetch_elevation.py

Downloads swisstopo's DHM25/200m digital height model (free, no key, about
43 MB) and writes data/elevation.json: a downsampled grid (roughly 1 km
spacing, elevation rounded to the nearest 50 m per the group's ruling) of
[lat, lng, elevation] points, kept in strict row-major grid order so the app
can feed it straight to turf.isobands to build a "higher/lower than the
asker" contour region without re-gridding at runtime.

Source: swisstopo DHM25/200m (https://www.swisstopo.admin.ch/en/height-model-dhm25-200m),
Swiss federal open geodata. Free to use, distribute and use commercially;
mandatory attribution ("(c) swisstopo") under the Geoinformation Act - not
CC-BY, a bespoke federal licence. See data/elevation-licence.txt (extracted
from the archive) for the full text.

The grid is in the Swiss LV03 projection, not lat/lng. Converted with
swisstopo's own published approximate formula (precision on the order of
1-2 m, entirely adequate for a 1 km grid), not a hand-rolled projection -
see CHtoWGSlat/CHtoWGSlng below, ported from swisstopo's own reference
script (https://github.com/ValentinMinder/Swisstopo-WGS84-LV03, MIT
licence, copyright Federal Office of Topography swisstopo).
"""
import io
import json
import os
import sys
import urllib.request
import zipfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(BASE_DIR, "data", "elevation-cache")
OUT_PATH = os.path.join(BASE_DIR, "data", "elevation.json")
OUT_LICENCE = os.path.join(BASE_DIR, "data", "elevation-licence.txt")

URL = "https://data.geo.admin.ch/ch.swisstopo.digitales-hoehenmodell_25/data.zip"
DOWNSAMPLE = 5  # 200 m native grid * 5 = 1 km spacing
ROUND_TO_M = 50  # group's ruling: nearest 50 m


def chtowgs_lat(y, x):
    y_aux = (y - 600000) / 1000000
    x_aux = (x - 200000) / 1000000
    lat = (16.9023892 + (3.238272 * x_aux)) \
        - (0.270978 * y_aux ** 2) \
        - (0.002528 * x_aux ** 2) \
        - (0.0447 * y_aux ** 2 * x_aux) \
        - (0.0140 * x_aux ** 3)
    return (lat * 100) / 36


def chtowgs_lng(y, x):
    y_aux = (y - 600000) / 1000000
    x_aux = (x - 200000) / 1000000
    lng = (2.6779094 + (4.728982 * y_aux)
           + (0.791484 * y_aux * x_aux)
           + (0.1306 * y_aux * x_aux ** 2)) \
        - (0.0436 * y_aux ** 3)
    return (lng * 100) / 36


def download(url, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    print(f"Downloading {url}\n  -> {dest}", flush=True)
    request = urllib.request.Request(url, headers={"User-Agent": "hideandseek-switzerland-fieldmap/1.0"})
    with urllib.request.urlopen(request, timeout=180) as response, open(dest, "wb") as out:
        out.write(response.read())


def parse_asc(text):
    lines = text.splitlines()
    header = {}
    i = 0
    while i < len(lines):
        parts = lines[i].split()
        if len(parts) == 2 and parts[0].upper() in (
            "NCOLS", "NROWS", "XLLCORNER", "YLLCORNER", "CELLSIZE", "NODATA_VALUE"
        ):
            header[parts[0].upper()] = float(parts[1])
            i += 1
        else:
            break
    ncols, nrows = int(header["NCOLS"]), int(header["NROWS"])
    xll, yll, cell = header["XLLCORNER"], header["YLLCORNER"], header["CELLSIZE"]
    nodata = header["NODATA_VALUE"]
    # Rows wrap across many physical lines (20 values per line in this file),
    # not one row per line, so read the remaining text as one flat token
    # stream and reshape it, rather than trusting line boundaries.
    tokens = " ".join(lines[i:]).split()
    expected = ncols * nrows
    if len(tokens) < expected:
        raise ValueError(f"Expected {expected} grid values, found {len(tokens)}")
    values = [float(v) for v in tokens[:expected]]
    rows = [values[r * ncols:(r + 1) * ncols] for r in range(nrows)]
    return ncols, nrows, xll, yll, cell, nodata, rows


def main():
    dest = os.path.join(CACHE_DIR, "dhm25_200m.zip")
    if not os.path.exists(dest):
        download(URL, dest)
    else:
        print(f"Reusing cached {dest}")

    with zipfile.ZipFile(dest) as z:
        with z.open("DHM200.asc") as f:
            text = io.TextIOWrapper(f, encoding="ascii").read()
        licence_text = z.read("license.txt").decode("utf-8", errors="replace")

    ncols, nrows, xll, yll, cell, nodata, rows = parse_asc(text)
    print(f"Parsed grid: {ncols} x {nrows} at {cell:.0f} m spacing")

    out_rows, out_cols = 0, 0
    grid = []
    kept = 0
    total = 0
    for r in range(0, nrows, DOWNSAMPLE):
        row_vals = rows[r]
        out_row = []
        for c in range(0, ncols, DOWNSAMPLE):
            total += 1
            v = row_vals[c]
            # Every cell keeps a coordinate, valid or not - turf.isobands
            # needs a complete rectangular grid (nulls for the elevation
            # value are fine, a missing point is not), since it infers row/
            # column structure from the point collection itself.
            x = xll + (c + 0.5) * cell
            y = yll + (nrows - 1 - r + 0.5) * cell
            lat = chtowgs_lat(x, y)
            lng = chtowgs_lng(x, y)
            if v == nodata:
                out_row.append([round(lat, 5), round(lng, 5), None])
                continue
            elev = round(v / ROUND_TO_M) * ROUND_TO_M
            out_row.append([round(lat, 5), round(lng, 5), elev])
            kept += 1
        grid.append(out_row)
        out_rows += 1
    out_cols = len(grid[0]) if grid else 0
    print(f"Downsampled to {out_cols} x {out_rows} ({kept:,} of {total:,} cells have data)")

    payload = {
        "source": "swisstopo DHM25/200m",
        "licence": "(c) swisstopo - mandatory attribution, free to use/distribute/commercial use, Geoinformation Act SR 510.62",
        "roundedToM": ROUND_TO_M,
        "spacingKm": DOWNSAMPLE * cell / 1000,
        "ncols": out_cols,
        "nrows": out_rows,
        "grid": grid,
    }
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
    size_kb = os.path.getsize(OUT_PATH) / 1024
    print(f"Wrote {OUT_PATH} ({size_kb:.0f} KB)")

    with open(OUT_LICENCE, "w", encoding="utf-8") as handle:
        handle.write(licence_text)
    print(f"Wrote {OUT_LICENCE}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
