"""Fetch the boundaries of the three closed state forests from ONF.

data/closures.pdf says *which* forests are closed, but it is a scanned Scan25
raster with no text layer, so no geometry can come out of it. The boundaries
here come instead from the ONF's own open dataset, "Forets publiques de France
metropolitaine", published as an ArcGIS feature service on their open-data
portal (geo-onf.opendata.arcgis.com). Unlike the Copernicus fire service this
one is queryable, so we can ask for just the three forests we need.

This is the ownership boundary of each state forest, which is exactly what the
ONF closure order applies to -- the whole forest, not a sub-area of it.

Note this is *not* what OpenStreetMap has: OSM carries only Trois-Pignons
(relation 16615234) as a forest boundary, which is why this dataset is used.

Usage:  python scripts/build_closures.py
Writes: data/closures.geojson
"""

import json
import math
import urllib.parse
import urllib.request
from pathlib import Path

SERVICE = (
    "https://services1.arcgis.com/Y4HgaQpzkE7kenlE/arcgis/rest/services/"
    "For%C3%AAts_publiques_de_France_m%C3%A9tropolitaine/FeatureServer/12"
)

# Selected by name rather than by objectid: objectids are not promised to be
# stable across republications of the dataset, and "Commanderie" and
# "Fontainebleau" both also match forests in other departements, so the
# departement and the state-forest flag are part of the filter.
WHERE = (
    "cinse_dep = '77' AND cdom_frt = 'OUI' AND ("
    "llib_frt LIKE '%Fontainebleau%' OR "
    "llib_frt LIKE '%Trois Pignons%' OR "
    "llib_frt LIKE '%Commanderie%')"
)

EXPECTED = 3

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "closures.geojson"

# The ONF order of 17 July 2026, as printed on data/closures.pdf.
CLOSED_SINCE = "2026-07-17"

# Six decimals is ~10 cm; the boundary is nowhere near that accurate, and the
# extra digits cost 30 kB of a file served to phones.
PRECISION = 5

# Douglas-Peucker tolerance, in metres. The layer answers "is this forest
# closed", at massif zoom levels -- it is not a cadastral boundary -- so
# trading a few metres of outline for a much smaller file is the right call.
# Kept small enough that the simplified edge stays visually identical.
TOLERANCE_M = 15.0

# Smallest detached part to keep, in hectares. Each of the three forests is one
# dominant block plus a long tail of slivers, and the tail is where the file
# size goes: this drops 277 of 292 parts for 0.56% of the closed area, leaving
# four to six parts per forest. 4 ha is 200 x 200 m, still only a few pixels at
# the zoom this map is read at.
#
# The cost is not spread evenly, and it is worth knowing before raising this
# further: Fontainebleau loses 0.19% and Trois-Pignons 0.57%, but la
# Commanderie is genuinely fragmented and loses 3.06% (163 parts, 80 ha).
#
# Note the popup area stays the *whole* forest, measured before this cull --
# the popup describes the forest, not the polygon drawn for it.
MIN_PART_HA = 4.0

# Area of interest, used to check axis order (see is_lat_lon).
LON_RANGE = (2.35, 2.95)
LAT_RANGE = (48.15, 48.55)

# Degrees to metres at ~48.4degN, for the simplifier and the axis check.
M_PER_DEG_LAT = 111_200.0
M_PER_DEG_LON = 74_300.0


def first_pair(coords):
    """First [x, y] pair of an arbitrarily nested coordinate array."""
    while coords and isinstance(coords[0], list):
        coords = coords[0]
    return coords


def in_range(value, bounds):
    return bounds[0] <= value <= bounds[1]


def is_lat_lon(geometry) -> bool:
    """True if the geometry is [lat, lon] instead of GeoJSON's [lon, lat].

    ArcGIS returns longitude first, so this should never fire -- but every
    source we add gets the same check, because a swapped axis renders as a
    plausible-looking polygon in the wrong hemisphere rather than as an error.
    """
    x, y = first_pair(geometry["coordinates"])[:2]
    return in_range(x, LAT_RANGE) and in_range(y, LON_RANGE)


def count_vertices(coords) -> int:
    if coords and isinstance(coords[0], (int, float)):
        return 1
    return sum(count_vertices(c) for c in coords)


def perpendicular_m(point, a, b) -> float:
    """Distance from point to segment a-b, in metres."""
    px = (point[0] - a[0]) * M_PER_DEG_LON
    py = (point[1] - a[1]) * M_PER_DEG_LAT
    bx = (b[0] - a[0]) * M_PER_DEG_LON
    by = (b[1] - a[1]) * M_PER_DEG_LAT
    len2 = bx * bx + by * by
    t = max(0.0, min(1.0, (px * bx + py * by) / len2)) if len2 else 0.0
    dx, dy = px - t * bx, py - t * by
    return math.hypot(dx, dy)


def douglas_peucker(points, tolerance):
    if len(points) < 3:
        return list(points)
    first, last = points[0], points[-1]
    index, worst = 0, 0.0
    for i in range(1, len(points) - 1):
        d = perpendicular_m(points[i], first, last)
        if d > worst:
            index, worst = i, d
    if worst <= tolerance:
        return [first, last]
    left = douglas_peucker(points[:index + 1], tolerance)
    right = douglas_peucker(points[index:], tolerance)
    return left[:-1] + right


def simplify_ring(ring, tolerance):
    """Simplify a closed ring, keeping it closed and keeping it a polygon.

    A ring simplified below four points is no longer an area, so it is left
    alone rather than collapsed away -- these are small islands and enclaves
    of the forest, and dropping them silently would misstate the boundary.
    """
    if len(ring) < 5:
        return ring
    # Simplify the open run, then close it again explicitly: the first and
    # last points are identical, and Douglas-Peucker on a degenerate
    # start == end segment measures every vertex against a zero-length line.
    simplified = douglas_peucker(ring[:-1], tolerance)
    if len(simplified) < 4:
        return ring
    return simplified + [simplified[0]]


def simplify_geometry(geometry, tolerance):
    kind = geometry["type"]
    if kind == "Polygon":
        rings = [[simplify_ring(r, tolerance) for r in geometry["coordinates"]]]
    elif kind == "MultiPolygon":
        rings = [[simplify_ring(r, tolerance) for r in poly]
                 for poly in geometry["coordinates"]]
    else:
        raise SystemExit(f"unexpected geometry type: {kind}")
    return dict(geometry, coordinates=rings[0] if kind == "Polygon" else rings)


def ring_area_ha(ring) -> float:
    """Signed planar area of a ring in hectares, via the shoelace formula.

    Good enough at this latitude and scale to sanity-check the download
    against the published size of each forest; it is not a survey figure.
    """
    total = 0.0
    for i in range(len(ring) - 1):
        x1 = ring[i][0] * M_PER_DEG_LON
        y1 = ring[i][1] * M_PER_DEG_LAT
        x2 = ring[i + 1][0] * M_PER_DEG_LON
        y2 = ring[i + 1][1] * M_PER_DEG_LAT
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0 / 10_000.0


def area_ha(geometry) -> float:
    """Area of a polygon or multipolygon, outer rings less their holes."""
    polys = ([geometry["coordinates"]] if geometry["type"] == "Polygon"
             else geometry["coordinates"])
    total = 0.0
    for poly in polys:
        for i, ring in enumerate(poly):
            total += ring_area_ha(ring) * (1 if i == 0 else -1)
    return total


def drop_small_parts(geometry, min_ha):
    """Drop detached parts smaller than min_ha. Returns (geometry, n, ha).

    Only whole parts are dropped, judged on their outer ring; holes inside a
    kept part are left alone, since a hole is a gap in the closure rather than
    a piece of it.
    """
    if geometry["type"] != "MultiPolygon":
        return geometry, 0, 0.0

    kept, dropped_ha, dropped = [], 0.0, 0
    for poly in geometry["coordinates"]:
        part_ha = ring_area_ha(poly[0])
        if part_ha < min_ha:
            dropped += 1
            dropped_ha += part_ha
        else:
            kept.append(poly)

    if not kept:
        raise SystemExit("every part was culled -- MIN_PART_HA is far too high")
    return dict(geometry, coordinates=kept), dropped, dropped_ha


def key_for(name: str) -> str:
    """Stable slug the map styles each forest by.

    The map colours the three forests differently, and matching on the display
    name there would mean matching accented French in JavaScript. Deriving the
    key once, here, keeps that out of index.html.
    """
    lowered = name.lower()
    for needle, key in (("fontainebleau", "fontainebleau"),
                        ("pignons", "trois-pignons"),
                        ("commanderie", "commanderie")):
        if needle in lowered:
            return key
    raise SystemExit(f"no key for forest name: {name!r}")


def fetch() -> dict:
    query = urllib.parse.urlencode({
        "where": WHERE,
        "outFields": "llib_frt,iidtn_frt",
        "outSR": 4326,
        "geometryPrecision": PRECISION,
        "returnGeometry": "true",
        "f": "geojson",
    })
    with urllib.request.urlopen(f"{SERVICE}/query?{query}", timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    raw = fetch()
    if "error" in raw:
        raise SystemExit(f"ONF service error: {raw['error']}")
    if raw.get("exceededTransferLimit"):
        raise SystemExit("ONF service truncated the response")

    incoming = raw.get("features", [])
    if len(incoming) != EXPECTED:
        names = [f["properties"].get("llib_frt") for f in incoming]
        raise SystemExit(f"expected {EXPECTED} forests, got {len(incoming)}: {names}")

    features = []
    before = after = 0
    culled = culled_ha = 0

    for feat in incoming:
        props = feat.get("properties", {})
        geometry = feat["geometry"]

        if is_lat_lon(geometry):
            raise SystemExit(f"{props.get('llib_frt')}: coordinates are latitude-first")

        x, y = first_pair(geometry["coordinates"])[:2]
        if not (in_range(x, LON_RANGE) and in_range(y, LAT_RANGE)):
            raise SystemExit(
                f"{props.get('llib_frt')} lies outside the area of interest: {x}, {y}")

        before += count_vertices(geometry["coordinates"])

        # Measured before the cull: the popup states the size of the forest,
        # not of the simplified outline drawn for it.
        full_ha = area_ha(geometry)

        geometry, dropped, dropped_ha = drop_small_parts(geometry, MIN_PART_HA)
        culled += dropped
        culled_ha += dropped_ha

        geometry = simplify_geometry(geometry, TOLERANCE_M)
        after += count_vertices(geometry["coordinates"])

        name = props.get("llib_frt", "").replace(" de La ", " de la ")
        features.append({
            "type": "Feature",
            "geometry": geometry,
            "properties": {
                "name": name,
                "key": key_for(name),
                "id": props.get("iidtn_frt"),
                "area_ha": round(full_ha),
                "closed_since": CLOSED_SINCE,
            },
        })

    features.sort(key=lambda f: f["properties"]["area_ha"], reverse=True)

    fc = {
        "type": "FeatureCollection",
        "name": "Closed state forests (ONF)",
        "attribution": "ONF",
        "source": SERVICE,
        "closed_since": CLOSED_SINCE,
        # Kept so it is on the record that the drawn outline omits a little of
        # the closed area, and by how much.
        "omitted_parts": culled,
        "omitted_ha": round(culled_ha, 1),
        "features": features,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(fc, ensure_ascii=False, indent=1), encoding="utf-8")

    size_kb = OUT.stat().st_size / 1024
    print(f"wrote {OUT.relative_to(ROOT)}: {len(features)} forests, {size_kb:.0f} kB")
    for f in features:
        print(f"  {f['properties']['name']}: {f['properties']['area_ha']} ha")
    print(f"simplified {before} -> {after} vertices at {TOLERANCE_M:.0f} m")
    total_ha = sum(f["properties"]["area_ha"] for f in features)
    print(f"dropped {culled} parts under {MIN_PART_HA:g} ha "
          f"({culled_ha:.1f} ha, {100 * culled_ha / total_ha:.2f}% of the closed area)")


if __name__ == "__main__":
    main()
