"""Fetch burnt-area polygons around Fontainebleau from EFFIS.

EFFIS (European Forest Fire Information System) serves burnt-area perimeters
over WFS with no key. This is the only *vector* source we found for this fire:
Copernicus EMS publishes activation EMSR894 as pre-rendered tiles only (the
service reports "TilesOnly", so it cannot be queried for geometry).

Caveats worth remembering when reading the map:
  - the polygons are MODIS-derived, so their outline is coarse (~250-500 m);
  - they lag the event by days, so the burnt area is *under*-stated.
The map therefore shows the Copernicus raster as the primary fire layer and
these polygons only as a dated, indicative outline.

Note: layer effis.nrt.ba.poly would be preferable (near real time) but the
server currently returns an SQL error for it, so we use the seasonal layer.

Usage:  python scripts/build_fire.py
Writes: data/fire_effis.geojson
"""

import json
import urllib.parse
import urllib.request
from pathlib import Path

WFS = "https://maps.wild-fire.eu/effis"
LAYER = "modis.ba.poly.season"
BBOX = "2.35,48.15,2.95,48.55"  # the massif and its surroundings, lon/lat

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "fire_effis.geojson"

KEEP = ["id", "FIREDATE", "LASTUPDATE", "COMMUNE", "PROVINCE", "AREA_HA"]

# Area of interest, used both to request features and to check axis order.
LON_RANGE = (2.35, 2.95)
LAT_RANGE = (48.15, 48.55)


def first_pair(coords):
    """First [x, y] pair of an arbitrarily nested coordinate array."""
    while coords and isinstance(coords[0], list):
        coords = coords[0]
    return coords


def swap_pairs(coords):
    """Recursively swap every [x, y] pair in a coordinate array."""
    if coords and isinstance(coords[0], list):
        return [swap_pairs(c) for c in coords]
    return [coords[1], coords[0]] + list(coords[2:])


def in_range(value, bounds):
    return bounds[0] <= value <= bounds[1]


def is_lat_lon(geometry) -> bool:
    """True if the geometry is [lat, lon] instead of GeoJSON's [lon, lat].

    EFFIS serves EPSG:4326 in official axis order (latitude first), which is
    the opposite of what GeoJSON requires. Both of our coordinate values are
    plausible numbers on their own, so we decide using the area of interest.
    """
    x, y = first_pair(geometry["coordinates"])[:2]
    return in_range(x, LAT_RANGE) and in_range(y, LON_RANGE)


def fetch() -> dict:
    query = urllib.parse.urlencode({
        "service": "WFS",
        "version": "1.0.0",
        "request": "GetFeature",
        "typeName": LAYER,
        "bbox": BBOX,
        "outputFormat": "geojson",
    })
    with urllib.request.urlopen(f"{WFS}?{query}", timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    raw = fetch()
    features = []

    swapped = 0

    for feat in raw.get("features", []):
        props = feat.get("properties", {})
        slim = {k: props[k] for k in KEEP if k in props}
        try:
            slim["AREA_HA"] = round(float(slim.get("AREA_HA", 0)))
        except (TypeError, ValueError):
            pass

        geometry = feat["geometry"]
        if is_lat_lon(geometry):
            geometry = dict(geometry, coordinates=swap_pairs(geometry["coordinates"]))
            swapped += 1

        x, y = first_pair(geometry["coordinates"])[:2]
        if not (in_range(x, LON_RANGE) and in_range(y, LAT_RANGE)):
            raise SystemExit(f"feature {slim.get('id')} lies outside the area of interest: {x}, {y}")

        features.append({
            "type": "Feature",
            "geometry": geometry,
            "properties": slim,
        })

    features.sort(key=lambda f: f["properties"].get("AREA_HA", 0), reverse=True)
    last = max((f["properties"].get("LASTUPDATE", "") for f in features), default="")

    fc = {
        "type": "FeatureCollection",
        "name": "Burnt areas (EFFIS)",
        "attribution": "EFFIS / Copernicus EMS",
        "source_layer": LAYER,
        "last_update": last,
        "features": features,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(fc, ensure_ascii=False, indent=1), encoding="utf-8")

    total = sum(f["properties"].get("AREA_HA", 0) for f in features)
    print(f"wrote {OUT.relative_to(ROOT)}: {len(features)} polygons, {total} ha total")
    print(f"axis order corrected on {swapped}/{len(features)} features")
    print(f"EFFIS last update: {last}")


if __name__ == "__main__":
    main()
