from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

BBox = tuple[float, float, float, float]

POLYGON_TYPES = {"Polygon", "MultiPolygon"}


def check_bbox(bbox: BBox) -> BBox:
    min_lon, min_lat, max_lon, max_lat = bbox
    if not (-180 <= min_lon < max_lon <= 180 and -90 <= min_lat < max_lat <= 90):
        raise ValueError(
            f"{bbox} is not a valid EPSG:4326 extent (lon -180 to 180, lat -90 to 90, min < max)"
        )
    return bbox


def parse_extent(text: str) -> BBox:
    parts = text.split(",")
    if len(parts) != 4:
        raise ValueError(f"extent must be min_lon,min_lat,max_lon,max_lat, got {text!r}")
    try:
        min_lon, min_lat, max_lon, max_lat = (float(part) for part in parts)
    except ValueError:
        raise ValueError(f"extent must contain 4 numbers, got {text!r}") from None
    return check_bbox((min_lon, min_lat, max_lon, max_lat))


def bbox_from_geojson(path: str | Path) -> BBox:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    polygons = [g for g in _geometries(data) if g["type"] in POLYGON_TYPES]
    if not polygons:
        raise ValueError(f"{path}: no Polygon or MultiPolygon geometry")
    xs: list[float] = []
    ys: list[float] = []
    for polygon in polygons:
        for x, y, *_ in _positions(polygon["coordinates"]):
            xs.append(x)
            ys.append(y)
    return check_bbox((min(xs), min(ys), max(xs), max(ys)))


def _geometries(obj: dict) -> Iterator[dict]:
    kind = obj.get("type")
    if kind == "FeatureCollection":
        for feature in obj["features"]:
            yield from _geometries(feature)
    elif kind == "Feature":
        if obj.get("geometry"):
            yield from _geometries(obj["geometry"])
    elif kind == "GeometryCollection":
        for geometry in obj["geometries"]:
            yield from _geometries(geometry)
    elif kind is not None:
        yield obj


def _positions(coords: list) -> Iterator[list[float]]:
    if coords and isinstance(coords[0], (int, float)):
        yield coords
    else:
        for item in coords:
            yield from _positions(item)
