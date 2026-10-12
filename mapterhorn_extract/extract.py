from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path

from .area import BBox
from .index import Archive, load_index

HIGH_ZOOM_MIN = 13


@dataclass(frozen=True)
class Job:
    name: str
    url: str
    minzoom: int
    maxzoom: int
    bbox: BBox
    region: str | None
    area_key: str

    @property
    def output_name(self) -> str:
        return f"{Path(self.name).stem}_z{self.minzoom}-{self.maxzoom}_{self.area_key}.pmtiles"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Job:
        return cls(**{**data, "bbox": tuple(data["bbox"])})


def plan(
    bbox: BBox,
    maxzoom: int,
    region: str | Path | None = None,
    archives: list[Archive] | None = None,
) -> list[Job]:
    if maxzoom < HIGH_ZOOM_MIN:
        raise ValueError(f"maxzoom must be >= {HIGH_ZOOM_MIN}, got {maxzoom}")
    if archives is None:
        archives = load_index()
    region_path = str(Path(region).resolve()) if region is not None else None
    area_key = _area_key(bbox, region_path)
    jobs = [
        Job(
            name=archive.name,
            url=archive.url,
            minzoom=HIGH_ZOOM_MIN,
            maxzoom=min(maxzoom, archive.max_zoom),
            bbox=tuple(bbox),
            region=region_path,
            area_key=area_key,
        )
        for archive in archives
        if archive.min_zoom >= HIGH_ZOOM_MIN and _intersects(archive.bbox, bbox)
    ]
    return sorted(jobs, key=lambda job: job.name)


def _intersects(a: BBox, b: BBox) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _area_key(bbox: BBox, region: str | None) -> str:
    digest = hashlib.sha1(repr(tuple(round(c, 6) for c in bbox)).encode())
    if region is not None:
        digest.update(Path(region).read_bytes())
    return digest.hexdigest()[:8]
