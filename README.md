# Fontainebleau — fire &amp; spots

An interactive map of the July 2026 Fontainebleau forest fire, laid over the
parkour / bouldering spots in the massif, so you can see which spots the fire
reached before planning a trip.

**→ [dimpolo.github.io/Fontainebleau](https://dimpolo.github.io/Fontainebleau/)**

The page is marked `noindex` so it stays out of search results, but anyone with
the link can open it.

Static site: plain [Leaflet](https://leafletjs.com/), no build step, no API
keys, no accounts. Open `index.html` through any web server and it works.

> **The whole massif is closed to the public.** Access to the state forests of
> Fontainebleau, Trois-Pignons and la Commanderie was banned by prefectural
> order on 17 July 2026. This map is for planning, not for deciding it is safe
> to go. Always check the current ONF and prefecture notices.

## Layers

| Layer | Source | Notes |
| --- | --- | --- |
| Burnt area | Copernicus EMS, activation [EMSR894](https://mapping.emergency.copernicus.eu/activations/EMSR894/) | Current and precise, but **raster only** |
| Burnt outline | [EFFIS](https://forest-fire.emergency.copernicus.eu/) `modis.ba.poly.season` | Real polygons, but coarse and delayed |
| Spots | a shared Google My Maps layer | 17 spots |
| Parking &amp; supplies | same My Maps layer | 16 parkings, 5 shops, 1 campsite |

Base maps come from IGN's open [Géoplateforme](https://data.geopf.fr) (Plan IGN
and orthophotos, no key required), with OpenStreetMap as a fallback.

### Why two fire layers

Neither source is sufficient alone:

- Copernicus EMSR894 is the authoritative mapping of this fire, but it is
  published only as pre-rendered tiles. Its service reports `TilesOnly`, so it
  cannot be queried for geometry, and the organisation hosts no feature
  services. There is no vector to download.
- EFFIS does serve vector polygons, but they are MODIS-derived: coarse
  (~250–500 m) and updated with a lag. At the time of writing they total
  ~1 581 ha against a reported 2 000+ ha.

So the Copernicus raster is the primary visual, and the EFFIS polygons provide
a dated outline plus the geometry needed to flag spots inside the burn. A spot
without a red ring is **not** necessarily unburnt.

## Refreshing the data

```sh
python scripts/build_spots.py   # -> data/spots.geojson
python scripts/build_fire.py    # -> data/fire_effis.geojson
```

`build_spots.py` re-exports the Fontainebleau folder of the shared My Maps as
KML and categorises each point by its icon id. `build_fire.py` pulls burnt-area
polygons from the EFFIS WFS; it corrects their axis order, because EFFIS
returns EPSG:4326 latitude-first while GeoJSON requires longitude-first.

The Copernicus layer needs no refresh: it is loaded live from their tile
service, which they update in place.

## Running locally

```sh
python -m http.server 8000
```

Then open <http://127.0.0.1:8000/>. A server is required — the page fetches the
GeoJSON files, which browsers block over `file://`.

## Deploying to GitHub Pages

Push the repository, then in **Settings → Pages** set the source to
`Deploy from a branch`, branch `main`, folder `/ (root)`. The site is served at
`https://<user>.github.io/<repo>/`.

The page sets `noindex`, so it will not show up in search results, but anyone
with the link can view it, and the repository is public.

## Not yet included

- **Closed-area polygons.** The closures are the three state forests shown in
  `data/closures.pdf` (an ONF map). OpenStreetMap only has one of the three
  (Trois-Pignons) as a forest boundary, so this layer was deferred; IGN's public
  forest dataset is the likely source.
- **Fire progression over time** and damage-severity grading.

## Attribution

- Base maps © [IGN](https://www.ign.fr/) / Géoplateforme
- © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors
- Fire mapping © [Copernicus EMS](https://mapping.emergency.copernicus.eu/activations/EMSR894/) (EMSR894) and [EFFIS](https://forest-fire.emergency.copernicus.eu/)
- Spots from a shared Google My Maps layer, by its original author
