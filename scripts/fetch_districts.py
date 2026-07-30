#!/usr/bin/env python3
"""Fetch Swiss districts, the 2nd administrative division, from OpenStreetMap.

Usage, from the repository root:

    python scripts/fetch_districts.py

Writes data/districts.json, which the app loads automatically. Like the other
OSM layers this is labelled in the interface as not Google-verified, because
the house rule makes Google Maps the arbiter and OpenStreetMap will sometimes
disagree with it.

Districts are OSM admin_level=6 boundary relations. Some cantons have
abolished districts as an administrative layer; those cantons simply have no
admin_level=6 relations, which shows up as a canton with zero districts in
the printed report rather than being assumed in code.

Free, no key required.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(BASE_DIR, "data", "districts.json")
OUT_REPORT = os.path.join(BASE_DIR, "data", "districts-report.txt")
SIMPLIFY_DEGREES = 0.0006  # about 60 m, finer than the water layer since districts are smaller
MIN_EXTENT_DEGREES = 0.002

ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": "hideandseek-switzerland-fieldmap/1.0 (Jet Lag fan project)",
}
DISTRICTS_QUERY = (
    '[out:json][timeout:180];'
    'area["ISO3166-1"="CH"][admin_level=2]->.ch;'
    'relation["admin_level"="6"]["boundary"="administrative"](area.ch);'
    'out geom;'
)

# Administrative boundary relations share their edge ways with the neighbouring
# country's relations, which fools Overpass's area filter into returning French,
# German, Italian and Austrian districts alongside the Swiss ones. There is no
# Google address to check here (unlike fetch_stations_google.py), so this reuses
# the same outline that script falls back on: about 100 m tolerance, [lng, lat].
CH_RING = [[6.09361,46.27309],[6.10074,46.30141],[6.10405,46.30922],[6.1364,46.35934],[6.13506,46.3704],[6.12286,46.38554],[6.10818,46.3965],[6.05424,46.41942],[6.06571,46.42701],[6.06757,46.4336],[6.06478,46.45107],[6.06023,46.4599],[6.06023,46.46502],[6.06416,46.47112],[6.07552,46.47959],[6.11036,46.52083],[6.1457,46.55163],[6.12152,46.57028],[6.11842,46.58346],[6.13185,46.59561],[6.26631,46.68036],[6.33794,46.70741],[6.34786,46.71317],[6.37422,46.73361],[6.40739,46.7457],[6.41793,46.7511],[6.4292,46.76082],[6.43302,46.76911],[6.43261,46.78598],[6.4199,46.79653],[6.41711,46.80216],[6.43426,46.83955],[6.44677,46.85771],[6.44842,46.87156],[6.44522,46.88262],[6.43189,46.90003],[6.42775,46.90908],[6.44264,46.94416],[6.49111,46.96339],[6.5987,46.98654],[6.66541,47.02129],[6.68825,47.04385],[6.67626,47.0624],[6.6897,47.07829],[6.69911,47.08462],[6.72422,47.09077],[6.72794,47.09713],[6.74603,47.10395],[6.74479,47.12105],[6.77476,47.12818],[6.84028,47.16953],[6.8593,47.19092],[6.88834,47.21131],[6.95625,47.24523],[6.95222,47.27004],[6.95862,47.29055],[6.97743,47.30373],[6.9919,47.30595],[7.00648,47.31936],[7.03655,47.32952],[7.0443,47.3405],[7.03386,47.35065],[7.004,47.36814],[6.9856,47.36212],[6.86664,47.35417],[6.8716,47.36695],[6.884,47.38259],[6.89878,47.39571],[6.92452,47.406],[6.92607,47.42486],[6.95232,47.42884],[6.96855,47.43519],[6.98343,47.4438],[6.99097,47.45222],[6.98612,47.46413],[6.97578,47.47796],[6.9733,47.48909],[6.9919,47.49294],[7.00079,47.49767],[7.00978,47.49925],[7.01888,47.49767],[7.02797,47.49294],[7.05391,47.49038],[7.10373,47.49627],[7.1273,47.49294],[7.14032,47.48785],[7.15365,47.4864],[7.18083,47.48826],[7.16264,47.4599],[7.16833,47.44356],[7.19003,47.43473],[7.21938,47.42848],[7.23034,47.41902],[7.23809,47.4168],[7.28263,47.42889],[7.30909,47.43266],[7.37855,47.43065],[7.40635,47.43824],[7.42609,47.45576],[7.42929,47.46511],[7.42764,47.47075],[7.41441,47.48403],[7.41431,47.49018],[7.42599,47.4925],[7.44149,47.48883],[7.45451,47.4832],[7.46743,47.48191],[7.48448,47.49294],[7.48593,47.49839],[7.47776,47.5077],[7.4756,47.51173],[7.47694,47.51488],[7.48273,47.517],[7.49306,47.5155],[7.50112,47.51731],[7.50546,47.52302],[7.50515,47.53302],[7.50174,47.53296],[7.48273,47.54227],[7.52634,47.56645],[7.55032,47.57549],[7.58603,47.58462],[7.63703,47.59498],[7.65967,47.59658],[7.64654,47.57154],[7.63589,47.56459],[7.60975,47.56475],[7.66142,47.54625],[7.68344,47.54426],[7.76674,47.55596],[7.78555,47.5632],[7.80147,47.57609],[7.81966,47.59534],[7.83371,47.59048],[7.8982,47.58785],[7.9043,47.58356],[7.90947,47.5648],[7.91216,47.56056],[8.04228,47.56056],[8.08724,47.56738],[8.09695,47.57185],[8.10543,47.58126],[8.1139,47.58785],[8.14377,47.60007],[8.16207,47.60376],[8.17385,47.61353],[8.17901,47.6158],[8.23297,47.62195],[8.25105,47.622],[8.27699,47.61663],[8.28857,47.6158],[8.29394,47.61146],[8.30635,47.59219],[8.31616,47.58785],[8.35409,47.58102],[8.41807,47.58077],[8.44887,47.58428],[8.45011,47.58903],[8.46179,47.60614],[8.49238,47.61983],[8.52235,47.6219],[8.53775,47.61213],[8.54964,47.59859],[8.5607,47.5894],[8.57413,47.59244],[8.58064,47.60017],[8.5825,47.62159],[8.57806,47.63348],[8.58033,47.639],[8.58395,47.64112],[8.59356,47.64257],[8.59511,47.63482],[8.60162,47.6326],[8.60731,47.65629],[8.56824,47.66293],[8.51967,47.65735],[8.47605,47.6404],[8.45827,47.63988],[8.4376,47.64784],[8.41197,47.66105],[8.3913,47.66546],[8.39771,47.67629],[8.39523,47.68482],[8.39099,47.69213],[8.39213,47.69952],[8.40195,47.70709],[8.42727,47.71647],[8.43791,47.72319],[8.44546,47.74318],[8.45011,47.75047],[8.46365,47.76391],[8.4715,47.76706],[8.48267,47.76685],[8.53651,47.77409],[8.5516,47.77925],[8.5423,47.79502],[8.55822,47.80117],[8.58312,47.80024],[8.60162,47.7946],[8.60411,47.7744],[8.60762,47.76225],[8.61744,47.75732],[8.62984,47.7628],[8.63501,47.7846],[8.6441,47.79101],[8.65702,47.78812],[8.68193,47.75874],[8.69227,47.75716],[8.70332,47.75871],[8.71314,47.75742],[8.71976,47.74732],[8.70374,47.73003],[8.70043,47.7235],[8.70467,47.71533],[8.71262,47.70869],[8.71707,47.69456],[8.76988,47.69507],[8.76172,47.70125],[8.77071,47.72086],[8.79758,47.72003],[8.83024,47.70719],[8.85608,47.69068],[8.83768,47.68779],[8.83779,47.68084],[8.85267,47.67079],[8.88171,47.65614],[8.9062,47.65179],[8.94538,47.6543],[8.98176,47.66216],[8.99767,47.67383],[9.01659,47.6789],[9.1281,47.67043],[9.1834,47.67043],[9.19694,47.65614],[9.23435,47.65616],[9.27321,47.65009],[9.54748,47.53455],[9.55495,47.5109],[9.58451,47.48072],[9.62172,47.4692],[9.65035,47.45209],[9.64952,47.40972],[9.6398,47.39452],[9.60105,47.36127],[9.5874,47.32781],[9.5533,47.29985],[9.50462,47.24373],[9.48736,47.21001],[9.48498,47.17635],[9.49263,47.15981],[9.50348,47.14539],[9.51185,47.12937],[9.51237,47.10803],[9.50286,47.0947],[9.48757,47.08395],[9.47589,47.07323],[9.47702,47.0639],[9.49955,47.05935],[9.56064,47.0524],[9.5812,47.05687],[9.59991,47.05349],[9.65231,47.05793],[9.66905,47.0562],[9.85798,47.01548],[9.85633,47.00408],[9.86057,47.0016],[9.86677,47.00194],[9.87059,46.99884],[9.87059,46.99295],[9.86646,46.98339],[9.86398,46.95992],[9.86077,46.94915],[9.86243,46.93977],[9.87514,46.92742],[9.89994,46.9144],[10.00691,46.89076],[10.04557,46.86556],[10.0681,46.85662],[10.1113,46.84712],[10.13197,46.84657],[10.15781,46.85161],[10.20142,46.86683],[10.21166,46.87704],[10.21517,46.89311],[10.21992,46.90577],[10.23512,46.92331],[10.25134,46.92538],[10.27077,46.92189],[10.29568,46.92269],[10.2962,46.94137],[10.31367,46.96432],[10.33888,46.98411],[10.36792,46.99551],[10.37898,46.99551],[10.38436,46.99315],[10.39469,46.9854],[10.41557,46.96241],[10.44957,46.94391],[10.45846,46.93662],[10.46384,46.91975],[10.45143,46.88577],[10.45381,46.86443],[10.44854,46.83223],[10.44492,46.82324],[10.43903,46.81688],[10.41722,46.79885],[10.41909,46.78397],[10.42622,46.76942],[10.4287,46.75565],[10.4166,46.74301],[10.39965,46.73555],[10.39562,46.7264],[10.39655,46.715],[10.39438,46.70082],[10.38477,46.68901],[10.37392,46.68191],[10.36917,46.6724],[10.37754,46.65328],[10.39562,46.63881],[10.4382,46.63566],[10.45908,46.62356],[10.46663,46.60429],[10.4659,46.57848],[10.45795,46.5537],[10.44399,46.53773],[10.42591,46.53533],[10.35428,46.54832],[10.31945,46.54605],[10.30664,46.5475],[10.29537,46.55109],[10.27594,46.56553],[10.2347,46.5753],[10.23026,46.58615],[10.23574,46.60669],[10.23377,46.61798],[10.21786,46.62697],[10.19212,46.62682],[10.09745,46.60804],[10.08784,46.60439],[10.0835,46.597],[10.0712,46.56439],[10.06293,46.55675],[10.04133,46.54186],[10.03275,46.53298],[10.0312,46.50383],[10.02686,46.49318],[10.0281,46.48393],[10.03048,46.47667],[10.03533,46.47107],[10.04402,46.46698],[10.02634,46.44626],[10.04205,46.43272],[10.07141,46.42482],[10.11616,46.41882],[10.13342,46.41402],[10.14076,46.4029],[10.13321,46.3811],[10.12598,46.37438],[10.105,46.36136],[10.09745,46.35164],[10.09239,46.3381],[10.09177,46.32896],[10.0958,46.32053],[10.10489,46.30937],[10.14613,46.28028],[10.15894,46.26245],[10.14582,46.24333],[10.11791,46.23113],[10.07575,46.22002],[10.04267,46.22049],[10.04185,46.24307],[10.03172,46.26007],[9.99224,46.28436],[9.97756,46.2981],[9.97105,46.32002],[9.97064,46.33981],[9.96402,46.35609],[9.93901,46.36745],[9.91844,46.37115],[9.89901,46.37216],[9.8554,46.36696],[9.78884,46.3433],[9.76806,46.33862],[9.75525,46.34053],[9.73086,46.35071],[9.72011,46.35089],[9.70926,46.34239],[9.70729,46.33097],[9.70843,46.31175],[9.69313,46.29707],[9.67432,46.2918],[9.5597,46.29273],[9.53645,46.29862],[9.51526,46.3086],[9.50255,46.32074],[9.4826,46.35681],[9.47372,46.36187],[9.4516,46.37038],[9.44436,46.37528],[9.4424,46.38089],[9.44385,46.39614],[9.43785,46.49205],[9.43465,46.49833],[9.42679,46.49711],[9.41067,46.48889],[9.40385,46.48251],[9.39548,46.46941],[9.38463,46.46642],[9.37708,46.46869],[9.35155,46.48548],[9.35083,46.49786],[9.33099,46.5015],[9.28231,46.49737],[9.26319,46.48512],[9.24582,46.46104],[9.23797,46.43655],[9.24758,46.42303],[9.26091,46.41665],[9.26288,46.40663],[9.26029,46.39402],[9.2604,46.37973],[9.27383,46.34425],[9.27518,46.33138],[9.26897,46.30937],[9.23972,46.267],[9.22483,46.23119],[9.21575,46.22106],[9.20417,46.21356],[9.18133,46.20405],[9.1711,46.18261],[9.16324,46.17227],[9.09059,46.13817],[9.07209,46.11889],[9.06816,46.10597],[9.07033,46.08344],[9.06713,46.07114],[9.05917,46.06179],[9.04966,46.05791],[9.02775,46.05311],[9.00212,46.03931],[8.99778,46.02794],[9.01555,45.99311],[8.98269,45.97198],[8.98052,45.9695],[8.98052,45.96438],[8.99343,45.95425],[9.0017,45.93606],[9.0108,45.92665],[9.02051,45.92278],[9.04232,45.91973],[9.05173,45.91555],[9.0631,45.89896],[9.05927,45.88195],[9.03436,45.84811],[9.00243,45.82072],[8.97235,45.82465],[8.93959,45.83483],[8.9,45.8264],[8.90372,45.8418],[8.90972,45.85369],[8.91375,45.86609],[8.9121,45.8834],[8.90652,45.89648],[8.89814,45.90955],[8.88078,45.9311],[8.87096,45.94707],[8.86445,45.95342],[8.85773,45.95709],[8.80037,45.97854],[8.78508,45.98231],[8.76792,45.98309],[8.79097,46.01869],[8.8196,46.04293],[8.83437,46.06639],[8.80895,46.08975],[8.79386,46.09342],[8.76317,46.0929],[8.74714,46.09445],[8.7395,46.09807],[8.73216,46.10742],[8.72389,46.10954],[8.69505,46.09517],[8.67749,46.09579],[8.63087,46.11471],[8.60183,46.12282],[8.53868,46.18762],[8.51026,46.20788],[8.45652,46.22483],[8.43812,46.23537],[8.42717,46.25144],[8.42324,46.27583],[8.42665,46.30157],[8.44287,46.35337],[8.44628,46.38218],[8.44577,46.41236],[8.44163,46.43494],[8.42789,46.44869],[8.39916,46.45218],[8.34345,46.44389],[8.31627,46.43365],[8.29498,46.41805],[8.2866,46.40536],[8.29043,46.40112],[8.29704,46.39763],[8.29746,46.38751],[8.29146,46.37836],[8.28154,46.37012],[8.27007,46.36404],[8.24175,46.35412],[8.19255,46.30916],[8.17188,46.29919],[8.12847,46.29247],[8.10687,46.28555],[8.08734,46.2718],[8.07732,46.26203],[8.07308,46.25361],[8.07659,46.24974],[8.09995,46.23563],[8.12951,46.19604],[8.1323,46.15935],[8.11059,46.12695],[8.06688,46.1006],[8.05602,46.09807],[8.03535,46.09652],[8.02533,46.09114],[8.0182,46.08086],[8.01603,46.06938],[8.01592,46.05817],[8.01065,46.0297],[7.99835,46.01063],[7.98585,45.99931],[7.97872,45.99518],[7.9691,45.99311],[7.8982,45.98195],[7.88378,45.97387],[7.87292,45.95938],[7.8702,45.94037],[7.84962,45.93971],[7.84529,45.92779],[7.84612,45.92257],[7.84374,45.91921],[7.83123,45.91446],[7.80756,45.91849],[7.78007,45.91813],[7.73201,45.93038],[7.70628,45.92572],[7.69398,45.92867],[7.67372,45.95032],[7.65874,45.96004],[7.64303,45.96634],[7.54112,45.98412],[7.52438,45.97807],[7.50371,45.95673],[7.48273,45.95487],[7.45296,45.94588],[7.39384,45.9157],[7.3618,45.90785],[7.28667,45.91343],[7.27354,45.91027],[7.24543,45.89813],[7.18373,45.88046],[7.15355,45.87653],[7.12089,45.87612],[7.09019,45.88051],[7.06694,45.89022],[7.02208,45.92526],[7.01516,45.93332],[7.00276,45.96169],[6.99128,45.98247],[6.98767,45.99311],[6.98281,45.99538],[6.91511,46.04861],[6.89238,46.05559],[6.884,46.05321],[6.86922,46.04406],[6.85971,46.04499],[6.85093,46.04964],[6.85196,46.06468],[6.85341,46.06567],[6.8531,46.0761],[6.85134,46.08602],[6.84855,46.08504],[6.86819,46.10468],[6.86922,46.11233],[6.85393,46.12261],[6.77435,46.13481],[6.76566,46.1516],[6.77486,46.18586],[6.79223,46.22168],[6.82768,46.26948],[6.80494,46.29661],[6.76949,46.32268],[6.75037,46.34552],[6.75574,46.35707],[6.7821,46.37846],[6.78923,46.3952],[6.78706,46.41417],[6.77772,46.42411],[6.76267,46.42926],[6.61368,46.4559],[6.54702,46.45737],[6.48294,46.44859],[6.39768,46.40818],[6.36522,46.40244],[6.33236,46.40138],[6.30156,46.39448],[6.2691,46.37503],[6.2195,46.32911],[6.21412,46.31547],[6.22745,46.28849],[6.22797,46.28446],[6.23758,46.26793],[6.24182,46.26369],[6.25226,46.25992],[6.269,46.26524],[6.27603,46.26312],[6.2812,46.24007],[6.25536,46.22111],[6.19138,46.1917],[6.14033,46.15021],[6.10787,46.13863],[6.07387,46.14917],[6.02829,46.14793],[5.98292,46.14044],[5.95884,46.13047],[5.97982,46.16225],[5.98292,46.17083],[5.96525,46.18623],[5.95481,46.19992],[5.95853,46.21196],[5.98292,46.22271],[6.04287,46.24307],[6.06188,46.24116],[6.08969,46.24638],[6.09403,46.25304],[6.09361,46.27309]]


def point_in_ch(lng, lat):
    inside = False
    previous = CH_RING[-1]
    for current in CH_RING:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > lat) != (y2 > lat):
            boundary = (x2 - x1) * (lat - y1) / (y2 - y1) + x1
            if lng < boundary:
                inside = not inside
        previous = current
    return inside


def run(query, label):
    body = urllib.parse.urlencode({"data": query}).encode()
    for attempt in range(2):
        for url in ENDPOINTS:
            try:
                print(f"  {label}: asking {url.split('/')[2]} ...", flush=True)
                request = urllib.request.Request(url, data=body, headers=HEADERS)
                with urllib.request.urlopen(request, timeout=300) as response:
                    return json.load(response)
            except Exception as error:
                print(f"    failed: {error}", file=sys.stderr)
        if attempt == 0:
            print("  All endpoints failed once. Waiting 20 seconds.", file=sys.stderr)
            time.sleep(20)
    return None


def simplify(points, epsilon):
    """Ramer-Douglas-Peucker, iterative so a large ring cannot blow the stack."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        start, end = stack.pop()
        if end <= start + 1:
            continue
        x1, y1 = points[start]
        x2, y2 = points[end]
        dx, dy = x2 - x1, y2 - y1
        denom = (dx * dx + dy * dy) ** 0.5
        worst, index = 0.0, start
        for i in range(start + 1, end):
            x, y = points[i]
            if denom == 0:
                dist = ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
            else:
                dist = abs(dy * x - dx * y + x2 * y1 - y2 * x1) / denom
            if dist > worst:
                worst, index = dist, i
        if worst > epsilon:
            keep[index] = True
            stack.append((start, index))
            stack.append((index, end))
    return [p for p, k in zip(points, keep) if k]


def extent(ring):
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return max(max(xs) - min(xs), max(ys) - min(ys))


def way_points(member):
    return [(round(p["lon"], 7), round(p["lat"], 7)) for p in member.get("geometry") or [] if "lat" in p]


def assemble_rings(way_pointlists):
    """Administrative boundary relations split their outer ring into dozens of
    shared-edge ways (each border segment is one way, shared with the
    neighbouring relation). Overpass's "out geom" gives each way's raw point
    list, not a joined ring, so ways have to be chained end to end here by
    matching shared endpoints, flipping direction as needed. Segments that
    never close back on themselves are dropped rather than guessed shut,
    since a false closure would silently invent a boundary."""
    ways = [list(w) for w in way_pointlists if len(w) >= 2]
    rings = []
    used = [False] * len(ways)
    for start_i in range(len(ways)):
        if used[start_i]:
            continue
        used[start_i] = True
        ring = list(ways[start_i])
        progress = True
        while progress and ring[0] != ring[-1]:
            progress = False
            for j in range(len(ways)):
                if used[j]:
                    continue
                w = ways[j]
                if w[0] == ring[-1]:
                    ring.extend(w[1:]); used[j] = True; progress = True; break
                if w[-1] == ring[-1]:
                    ring.extend(list(reversed(w))[1:]); used[j] = True; progress = True; break
                if w[-1] == ring[0]:
                    ring = w[:-1] + ring; used[j] = True; progress = True; break
                if w[0] == ring[0]:
                    ring = list(reversed(w))[:-1] + ring; used[j] = True; progress = True; break
        if ring[0] == ring[-1]:
            rings.append(ring)
    return rings


def ring_centroid(ring):
    xs = [p[0] for p in ring[:-1]]
    ys = [p[1] for p in ring[:-1]]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def parse_districts(data):
    out, seen_id = [], set()
    skipped_unclosed = []
    dropped_foreign = []
    for element in data.get("elements", []):
        if element.get("type") != "relation":
            continue
        rel_id = element.get("id")
        if rel_id in seen_id:
            continue
        seen_id.add(rel_id)
        tags = element.get("tags") or {}
        name = (tags.get("name") or "").strip()
        if not name:
            continue
        outer_ways = [way_points(m) for m in (element.get("members") or []) if m.get("role") == "outer"]
        rings = assemble_rings(outer_ways)
        if not rings:
            skipped_unclosed.append(name)
            continue
        # Overpass's area filter leaks neighbouring-country relations that
        # share a border way with a Swiss one (see CH_RING comment above).
        # Test the largest assembled ring, since a real Swiss district's main
        # body will not be a small border sliver.
        main_ring = max(rings, key=len)
        cx, cy = ring_centroid(main_ring)
        if not point_in_ch(cx, cy):
            dropped_foreign.append(name)
            continue
        simplified = []
        for ring in rings:
            small = simplify([[x, y] for x, y in ring], SIMPLIFY_DEGREES)
            if len(small) < 4 or extent(small) < MIN_EXTENT_DEGREES:
                continue
            if small[0] != small[-1]:
                small.append(small[0])
            simplified.append([[round(x, 4), round(y, 4)] for x, y in small])
        if not simplified:
            skipped_unclosed.append(name)
            continue
        out.append({"id": rel_id, "n": name, "r": simplified})
    out.sort(key=lambda r: r["n"])
    return out, skipped_unclosed, dropped_foreign


def main():
    print("Fetching district (admin_level=6) boundaries from OpenStreetMap.")
    raw = run(DISTRICTS_QUERY, "districts")
    if not raw:
        sys.exit("Could not reach OpenStreetMap for districts. Try again shortly.")
    districts, skipped, foreign = parse_districts(raw)
    print(f"  districts: {len(districts)} with usable geometry")
    if skipped:
        print(f"  skipped, could not assemble a closed ring: {len(skipped)}", file=sys.stderr)
    if foreign:
        print(f"  dropped, centroid outside the Swiss outline: {len(foreign)}", file=sys.stderr)

    payload = {
        "source": "OpenStreetMap contributors",
        "note": "Not Google-verified. The house rule makes Google Maps the arbiter.",
        "districts": districts,
    }
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
    size = os.path.getsize(OUT_PATH) // 1024
    print(f"\nWrote {OUT_PATH} ({size} KB)")

    report_lines = [
        "=== OSM DISTRICT FETCH (admin_level=6) ===",
        f"Relations returned by Overpass: {len(raw.get('elements', []))}",
        f"Districts kept (named, with outer geometry, inside the Swiss outline): {len(districts)}",
    ]
    if foreign:
        report_lines.append(f"Dropped, centroid outside the Swiss outline - a neighbouring country's "
                             f"district that leaked in via a shared border way ({len(foreign)}):")
        report_lines += [f"  - {n}" for n in foreign]
    if skipped:
        report_lines.append(f"Skipped, matched the query but the outer ways would not close ({len(skipped)}):")
        report_lines += [f"  - {n}" for n in skipped]
    report_lines.append("=== END ===")
    with open(OUT_REPORT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(report_lines) + "\n")
    print(f"Wrote {OUT_REPORT}")


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
