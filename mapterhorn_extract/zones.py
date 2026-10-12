from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .area import POLYGON_TYPES, bbox_from_geojson
from .extract import HIGH_ZOOM_MIN, extract_one, merge, plan, plan_base
from .index import Archive


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
) -> tuple[Path, list[Zone]]:
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
    return _write_regions(work_dir / "all_zones.geojson", features), zones


def extract_base(
    region: str | Path,
    output_dir: str | Path,
    archives: list[Archive] | None = None,
    binary: str | None = None,
    threads: int = 16,
    should_stop: Callable[[], bool] | None = None,
) -> Path | None:
    job = plan_base(bbox_from_geojson(region), region=region, archives=archives)
    if job is None:
        return None
    return extract_one(job, output_dir, binary=binary, threads=threads, should_stop=should_stop)


def extract_zone(
    zone: Zone,
    output_dir: str | Path,
    archives: list[Archive] | None = None,
    binary: str | None = None,
    threads: int = 16,
    should_stop: Callable[[], bool] | None = None,
) -> Path | None:
    jobs = plan(bbox_from_geojson(zone.region), zone.maxzoom, region=zone.region, archives=archives)
    if not jobs:
        return None
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
