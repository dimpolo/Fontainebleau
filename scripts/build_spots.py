"""Convert the Fontainebleau layer of the shared Google My Maps into GeoJSON.

Source: a public Google My Maps ("/maps/d/"), exported as KML with no API key.
The map holds several city folders; we only want the "Fontainebleau" one.

Category is taken from the KML styleUrl icon id, which the map's author used
consistently -- it is more reliable than guessing from the placemark name.

Usage:  python scripts/build_spots.py
Writes: data/spots.geojson
"""

import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

MID = "1iLuzjZSOej3g2xdy1baiNKWFBC9-k4Dv"
KML_URL = f"https://www.google.com/maps/d/kml?mid={MID}&forcekml=1"
FOLDER = "Fontainebleau"

KML_NS = "http://www.opengis.net/kml/2.2"
NS = {"k": KML_NS}

# icon id in the styleUrl -> (kind, group). group drives the two map layers.
ICON_KIND = {
    "1680": ("spot", "spots"),
    "1644": ("parking", "other"),
    "1578": ("shop", "other"),
    "1684": ("shop", "other"),
    "1765": ("camping", "other"),
}

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "spots.geojson"


def fetch_kml() -> bytes:
    with urllib.request.urlopen(KML_URL, timeout=60) as resp:
        return resp.read()


def find_folder(root: ET.Element) -> ET.Element:
    for folder in root.iter(f"{{{KML_NS}}}Folder"):
        name = folder.find("k:name", NS)
        if name is not None and (name.text or "").strip() == FOLDER:
            return folder
    raise SystemExit(f"folder {FOLDER!r} not found in KML")


def classify(style_url: str) -> tuple[str, str]:
    m = re.search(r"icon-(\d+)", style_url or "")
    return ICON_KIND.get(m.group(1) if m else "", ("other", "other"))


def main() -> None:
    root = ET.fromstring(fetch_kml())
    features = []

    for pm in find_folder(root).findall("k:Placemark", NS):
        coords = pm.find(".//k:Point/k:coordinates", NS)
        if coords is None or not (coords.text or "").strip():
            continue  # only points are expected in this layer
        lon, lat = (float(v) for v in coords.text.strip().split(",")[:2])

        name_el = pm.find("k:name", NS)
        name = (name_el.text or "").strip() if name_el is not None else "Unnamed"
        style_el = pm.find("k:styleUrl", NS)
        kind, group = classify(style_el.text if style_el is not None else "")

        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
            "properties": {"name": name, "kind": kind, "group": group},
        })

    fc = {
        "type": "FeatureCollection",
        "name": "Fontainebleau spots",
        "attribution": "Spots from a shared Google My Maps layer",
        "features": features,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(fc, ensure_ascii=False, indent=1), encoding="utf-8")

    counts: dict[str, int] = {}
    for f in features:
        counts[f["properties"]["kind"]] = counts.get(f["properties"]["kind"], 0) + 1
    print(f"wrote {OUT.relative_to(ROOT)}: {len(features)} features {counts}")


if __name__ == "__main__":
    main()
