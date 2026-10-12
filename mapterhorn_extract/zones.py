from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .area import POLYGON_TYPES, BBox, bbox_from_geojson
from .extract import HIGH_ZOOM_MIN, Job, _plan, _plan_base, extract_one, merge
from .index import Archive


FRANCE_EXTENT: BBox = (-5.15, 42.33, 8.23, 51.10)


@dataclass(frozen=True)
class Zone:
    name: str
    maxzoom: int
    region: Path


def zones_from_geojson(
    path: str | Path,
    default_maxzoom: int,
    work_dir: str | Path,
    same_zoom: bool = False,
) -> list[Zone]:
    features = [f for f in _features(json.loads(Path(path).read_text(encoding="utf-8"))) if _is_polygon(f)]
    if not features:
        raise ValueError(f"{path}: no Polygon or MultiPolygon feature")
    work_dir = Path(work_dir)
    (work_dir / "zones").mkdir(parents=True, exist_ok=True)

    zones = []
    for number, feature in enumerate(features, start=1):
        properties = feature.get("properties") or {}
        name = _safe_name(properties.get("name")) or f"zone_{number}"
        if any(zone.name == name for zone in zones):
            raise ValueError(f"duplicate zone name: {name}")
        maxzoom = default_maxzoom if same_zoom else _zoom(properties.get("maxzoom"), default_maxzoom, name)
        if maxzoom < HIGH_ZOOM_MIN:
            raise ValueError(f"zone {name}: maxzoom {maxzoom} is below {HIGH_ZOOM_MIN}, the base file covers 0-12")
        region = _write_regions(work_dir / "zones" / f"{name}.geojson", [feature])
        bbox_from_geojson(region)
        zones.append(Zone(name=name, maxzoom=maxzoom, region=region))
    return zones


def base_job(
    region: str | Path | None = None,
    bbox: BBox | None = None,
    archives: list[Archive] | None = None,
) -> Job:
    if region is not None:
        return _plan_base(bbox_from_geojson(region), region=region, archives=archives, label="base")
    if bbox is not None:
        return _plan_base(bbox, archives=archives, label="base")
    return _plan_base(FRANCE_EXTENT, archives=archives, label="france")


def extract_base(
    output_dir: str | Path,
    region: str | Path | None = None,
    bbox: BBox | None = None,
    archives: list[Archive] | None = None,
    binary: str | None = None,
    threads: int = 16,
    should_stop: Callable[[], bool] | None = None,
) -> Path:
    return extract_one(base_job(region=region, bbox=bbox, archives=archives), output_dir, binary=binary, threads=threads, should_stop=should_stop)


def plan_zone(zone: Zone, archives: list[Archive] | None = None) -> list[Job]:
    return _plan(bbox_from_geojson(zone.region), zone.maxzoom, region=zone.region, archives=archives)


def extract_zone(
    zone: Zone,
    output_dir: str | Path,
    archives: list[Archive] | None = None,
    binary: str | None = None,
    threads: int = 16,
    should_stop: Callable[[], bool] | None = None,
) -> Path:
    jobs = plan_zone(zone, archives)
    if not jobs:
        raise ValueError(f"zone {zone.name}: no Mapterhorn archive above zoom 12")
    output_dir = Path(output_dir)
    maxzoom = max(job.maxzoom for job in jobs)
    output = output_dir / f"{zone.name}_z{HIGH_ZOOM_MIN}-{maxzoom}_{jobs[0].area_key}.pmtiles"
    if output.exists():
        return output
    parts_root = output_dir / ".parts"
    parts_dir = parts_root / output.stem
    parts = [
        extract_one(job, parts_dir, binary=binary, threads=threads, should_stop=should_stop) for job in jobs
    ]
    merge(parts, output, binary=binary, should_stop=should_stop)
    shutil.rmtree(parts_dir)
    if not any(parts_root.iterdir()):
        parts_root.rmdir()
    return output


def _features(obj: dict) -> list[dict]:
    kind = obj.get("type")
    if kind == "FeatureCollection":
        return obj["features"]
    if kind == "Feature":
        return [obj]
    return [{"type": "Feature", "properties": {}, "geometry": obj}]


def _is_polygon(feature: dict) -> bool:
    geometry = feature.get("geometry") or {}
    return geometry.get("type") in POLYGON_TYPES


def _safe_name(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"[^\w.-]+", "_", str(value)).strip("._")


def _zoom(value: object, default: int, name: str) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"zone {name}: maxzoom {value!r} is not an integer") from None


def _write_regions(path: Path, features: list[dict]) -> Path:
    geometry_only = [{"type": "Feature", "properties": {}, "geometry": f["geometry"]} for f in features]
    path.write_text(json.dumps({"type": "FeatureCollection", "features": geometry_only}), encoding="utf-8")
    return path
