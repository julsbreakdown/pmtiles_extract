from __future__ import annotations

import hashlib
import logging
import os
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from .area import BBox, part_bboxes
from .index import Archive, load_index
from .pmtiles_bin import extract_command, find_pmtiles, merge_command

HIGH_ZOOM_MIN = 13

logger = logging.getLogger(__name__)


class ExtractError(RuntimeError):
    pass


class ExtractCancelled(RuntimeError):
    pass


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
    parts = part_bboxes(region_path) if region_path is not None else [bbox]
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
        if archive.min_zoom >= HIGH_ZOOM_MIN and any(_intersects(archive.bbox, part) for part in parts)
    ]
    return sorted(jobs, key=lambda job: job.name)


def plan_base(bbox: BBox, region: str | Path | None = None, archives: list[Archive] | None = None) -> Job | None:
    if archives is None:
        archives = load_index()
    planet = next((a for a in archives if a.min_zoom == 0), None)
    if planet is None:
        return None
    region_path = str(Path(region).resolve()) if region is not None else None
    return Job(
        name=planet.name,
        url=planet.url,
        minzoom=0,
        maxzoom=planet.max_zoom,
        bbox=tuple(bbox),
        region=region_path,
        area_key=_area_key(bbox, region_path),
    )


def _intersects(a: BBox, b: BBox) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _area_key(bbox: BBox, region: str | None) -> str:
    digest = hashlib.sha1(repr(tuple(round(c, 6) for c in bbox)).encode())
    if region is not None:
        digest.update(Path(region).read_bytes())
    return digest.hexdigest()[:8]


def extract_one(
    job: Job,
    output_dir: str | Path,
    binary: str | None = None,
    threads: int = 16,
    should_stop: Callable[[], bool] | None = None,
) -> Path:
    output_dir = Path(output_dir)
    output = output_dir / job.output_name
    if output.exists():
        logger.info("%s already extracted, skipping", output.name)
        return output
    binary = find_pmtiles(binary)
    logger.info("extracting %s z%d-%d", job.name, job.minzoom, job.maxzoom)
    _write_atomically(output, lambda part: extract_command(binary, job, part, threads), should_stop)
    return output


def merge(
    inputs: list[Path],
    output: Path,
    binary: str | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> Path:
    output = Path(output)
    if output.exists():
        logger.info("%s already merged, skipping", output.name)
        return output
    if len(inputs) == 1:
        output.parent.mkdir(parents=True, exist_ok=True)
        os.replace(inputs[0], output)
        return output
    binary = find_pmtiles(binary)
    logger.info("merging %d extracts into %s", len(inputs), output.name)
    _write_atomically(output, lambda part: merge_command(binary, inputs, part), should_stop)
    return output


def _write_atomically(
    output: Path,
    command_for: Callable[[Path], list[str]],
    should_stop: Callable[[], bool] | None,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    part = output.with_name(output.stem + ".part.pmtiles")
    part.unlink(missing_ok=True)
    try:
        _run(command_for(part), should_stop)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    os.replace(part, output)


def _run(command: list[str], should_stop: Callable[[], bool] | None) -> None:
    with subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True) as process:
        while True:
            try:
                _, stderr = process.communicate(timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                if should_stop is not None and should_stop():
                    process.terminate()
                    process.wait()
                    raise ExtractCancelled(f"pmtiles {command[1]} cancelled") from None
    if process.returncode != 0:
        raise ExtractError(f"pmtiles {command[1]} failed ({process.returncode}): {stderr.strip()}")
