# Mapterhorn high-zoom PMTiles extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A stdlib-only Python library and CLI (`mapterhorn-extract`) plus a QGIS Processing algorithm (`mapterhorn:extract`) that extract Mapterhorn z13+ terrain PMTiles over an area, one output file per Mapterhorn z6 archive.

**Architecture:** The library reads Mapterhorn's public index (`download_urls.json`), selects the z6 archives intersecting the area, and wraps `pmtiles extract` once per archive. Its API is split into `plan()` (pure, returns serializable `Job`s) and `extract_one()` (one subprocess call, atomic write, skip if done) so a later Airflow DAG can map one task per archive. The QGIS plugin ships the library through a symlink and only converts a polygon layer to a temporary EPSG:4326 GeoJSON.

**Tech Stack:** Python >= 3.10 (stdlib only), go-pmtiles CLI (external), pytest via uv, PyQGIS Processing (QGIS 3.34 LTR to 4.x).

**Spec:** `DEMANDE.md`

## Global Constraints

- Library: Python >= 3.10, standard library only, never imports `qgis`.
- Only z13+ archives (`min_zoom >= 13`); `planet.pmtiles` (z0 to z12) is never extracted.
- Output: one `.pmtiles` per source z6 archive, no merge.
- `pmtiles` binary is not bundled: explicit path (`--pmtiles-bin` / `PMTILES_BIN` parameter), else `pmtiles` on PATH.
- Area input: CLI `--geojson` (passed to `pmtiles extract --region`) or `--extent min_lon,min_lat,max_lon,max_lat` (passed to `--bbox`); QGIS: polygon layer from the layer tree.
- QGIS: `qgisMinimumVersion=3.34`, `qgisMaximumVersion=4.99`; any Qt import goes through `qgis.PyQt`.
- Out of scope: Airflow DAG, S3 upload, hillshade conversion, loading results as QGIS layers.
- Never use the em dash character in code, strings, comments, names or commit messages.
- Comments only for hidden constraints, one line each.
- Commit messages carry no attribution or co-author trailer.

## Review Focus

1. Re-running with a different area into the same output directory must produce new files, not silently return an older extract (Task 3 `test_different_region_gives_different_output_name`, Task 4 skip test).
2. A failed or cancelled `pmtiles extract` must leave nothing that a re-run would treat as done (Task 4 `test_failed_extract_leaves_no_file`, `test_cancel_stops_extract_and_cleans_up`).
3. A `maxzoom` above an archive's own max zoom is clamped per archive; below 13 is rejected with a clear message (Task 3, Task 5 `test_invalid_maxzoom_is_usage_error`).
4. An area with no z13+ coverage (open sea) gives a clear message and a failing exit code, not an empty success (Task 3 `test_area_without_coverage_gives_no_job`, Task 5 `test_no_coverage_exits_1`, Task 6 step 7).
5. A GeoJSON in a projected CRS (for example a Lambert-93 export) is rejected with an EPSG:4326 message instead of yielding zero archives (Task 2 `test_projected_coordinates_are_rejected`); the QGIS path reprojects (Task 6 uses an EPSG:2154 layer).

---

## File map

```
plugin_pmtiles/
├── pyproject.toml
├── .gitignore
├── mapterhorn_extract/
│   ├── __init__.py          # public API re-exports
│   ├── index.py             # Archive, load_index, INDEX_URL
│   ├── area.py              # BBox, parse_extent, bbox_from_geojson, check_bbox
│   ├── pmtiles_bin.py       # PmtilesNotFound, find_pmtiles, extract_command
│   ├── extract.py           # Job, plan, extract_one, ExtractError, ExtractCancelled
│   └── __main__.py          # CLI main()
├── mapterhorn_pmtiles/      # QGIS plugin
│   ├── mapterhorn_extract -> ../mapterhorn_extract
│   ├── metadata.txt
│   ├── __init__.py
│   ├── plugin.py
│   ├── provider.py
│   ├── compat.py
│   └── algorithm.py
└── tests/
    ├── conftest.py
    ├── fixtures/index.json
    ├── test_index.py
    ├── test_area.py
    ├── test_plan.py
    ├── test_extract.py
    └── test_cli.py
```

Test areas used throughout (EPSG:4326, `min_lon, min_lat, max_lon, max_lat`):

| Name | BBox | Archives in fixture |
|---|---|---|
| LYON | `(4.80, 45.70, 4.90, 45.80)` | `6-32-22` (max z17) |
| PARIS | `(2.25, 48.80, 2.45, 48.95)` | `6-32-21`, `6-32-22` (crosses lat 48.9225) |
| CHAMONIX | `(6.80, 45.85, 6.95, 45.95)` | `6-33-22` (max z18) |
| OCEAN | `(-30.0, 40.0, -29.0, 41.0)` | none |
| EDGE | `(-1.0, 46.0, 0.0, 46.5)` | `6-31-22` only (touches `6-32-22` at lon 0) |

---

### Task 1: Project scaffold and index loader

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `mapterhorn_extract/__init__.py`, `mapterhorn_extract/index.py`
- Create: `tests/conftest.py`, `tests/fixtures/index.json`, `tests/test_index.py`

**Interfaces:**
- Produces: `INDEX_URL: str`; `Archive` (frozen dataclass: `name, url, size, min_lon, min_lat, max_lon, max_lat, min_zoom, max_zoom`, property `bbox -> tuple[float, float, float, float]`, classmethod `from_item(dict)`); `load_index(source: str | Path = INDEX_URL) -> list[Archive]` (URL or local path).
- Produces fixtures: `index_path`, `archives`, `fake_pmtiles`, `region_file`.

- [ ] **Step 1: Init repo and project files**

```bash
cd /home/jwaddle/Projets/qgis/plugin_pmtiles
git init
mkdir -p mapterhorn_extract tests/fixtures
```

`pyproject.toml`:

```toml
[project]
name = "mapterhorn-extract"
version = "0.1.0"
description = "Extract high-zoom Mapterhorn terrain PMTiles over an area"
requires-python = ">=3.10"
dependencies = []

[project.scripts]
mapterhorn-extract = "mapterhorn_extract.__main__:main"

[dependency-groups]
dev = ["pytest>=8"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["mapterhorn_extract"]
```

`.gitignore`:

```
.venv/
__pycache__/
.pytest_cache/
*.pmtiles
```

`mapterhorn_extract/__init__.py` (empty for now):

```python
```

- [ ] **Step 2: Write the index fixture**

`tests/fixtures/index.json` (real excerpt of `download_urls.json` v0.0.13, md5 dropped):

```json
{
 "version": "0.0.13",
 "items": [
  {"name": "planet.pmtiles", "url": "https://download.mapterhorn.com/planet.pmtiles", "size": 355579263191,
   "min_lon": -180.0, "min_lat": -85.0511287798066, "max_lon": 180.0, "max_lat": 85.0511287798066, "min_zoom": 0, "max_zoom": 12},
  {"name": "6-0-21.pmtiles", "url": "https://download.mapterhorn.com/6-0-21.pmtiles", "size": 31749705,
   "min_lon": -180.0, "min_lat": 48.92249926375824, "max_lon": -174.375, "max_lat": 52.48278022207821, "min_zoom": 13, "max_zoom": 13},
  {"name": "6-31-22.pmtiles", "url": "https://download.mapterhorn.com/6-31-22.pmtiles", "size": 138710218423,
   "min_lon": -5.625, "min_lat": 45.089035564831015, "max_lon": 0.0, "max_lat": 48.92249926375824, "min_zoom": 13, "max_zoom": 17},
  {"name": "6-32-21.pmtiles", "url": "https://download.mapterhorn.com/6-32-21.pmtiles", "size": 150871259017,
   "min_lon": 0.0, "min_lat": 48.92249926375824, "max_lon": 5.625, "max_lat": 52.48278022207821, "min_zoom": 13, "max_zoom": 17},
  {"name": "6-32-22.pmtiles", "url": "https://download.mapterhorn.com/6-32-22.pmtiles", "size": 338072264827,
   "min_lon": 0.0, "min_lat": 45.089035564831015, "max_lon": 5.625, "max_lat": 48.92249926375824, "min_zoom": 13, "max_zoom": 17},
  {"name": "6-33-22.pmtiles", "url": "https://download.mapterhorn.com/6-33-22.pmtiles", "size": 614918478203,
   "min_lon": 5.625, "min_lat": 45.089035564831015, "max_lon": 11.25, "max_lat": 48.92249926375824, "min_zoom": 13, "max_zoom": 18}
 ]
}
```

- [ ] **Step 3: Write conftest and the failing test**

`tests/conftest.py`:

```python
import json
import sys
from pathlib import Path

import pytest

from mapterhorn_extract.index import load_index

FIXTURES = Path(__file__).parent / "fixtures"

FAKE_PMTILES = """\
import json, os, sys, time
args = sys.argv[1:]
mode = os.environ.get("FAKE_PMTILES_MODE", "ok")
if mode == "slow":
    time.sleep(30)
with open(args[2], "w") as out:
    json.dump(args, out)
if mode == "fail":
    print("boom", file=sys.stderr)
    sys.exit(1)
"""


@pytest.fixture
def index_path():
    return FIXTURES / "index.json"


@pytest.fixture
def archives(index_path):
    return load_index(index_path)


@pytest.fixture
def fake_pmtiles(tmp_path):
    path = tmp_path / "bin" / "pmtiles"
    path.parent.mkdir()
    path.write_text(f"#!{sys.executable}\n{FAKE_PMTILES}")
    path.chmod(0o755)
    return path


@pytest.fixture
def region_file(tmp_path):
    def write(ring, name="area.geojson"):
        path = tmp_path / name
        geometry = {"type": "Polygon", "coordinates": [ring]}
        feature = {"type": "Feature", "properties": {}, "geometry": geometry}
        path.write_text(json.dumps({"type": "FeatureCollection", "features": [feature]}))
        return path

    return write
```

`tests/test_index.py`:

```python
from mapterhorn_extract.index import INDEX_URL


def test_load_index_parses_archives(archives):
    by_name = {a.name: a for a in archives}
    assert len(archives) == 6
    alps = by_name["6-33-22.pmtiles"]
    assert alps.url == "https://download.mapterhorn.com/6-33-22.pmtiles"
    assert (alps.min_zoom, alps.max_zoom) == (13, 18)
    assert alps.bbox == (5.625, 45.089035564831015, 11.25, 48.92249926375824)


def test_load_index_keeps_planet(archives):
    planet = next(a for a in archives if a.name == "planet.pmtiles")
    assert (planet.min_zoom, planet.max_zoom) == (0, 12)


def test_index_url():
    assert INDEX_URL == "https://download.mapterhorn.com/download_urls.json"
```

- [ ] **Step 4: Run to verify it fails**

Run: `uv run pytest tests/test_index.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'mapterhorn_extract.index'`.

- [ ] **Step 5: Implement `mapterhorn_extract/index.py`**

```python
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path

INDEX_URL = "https://download.mapterhorn.com/download_urls.json"


@dataclass(frozen=True)
class Archive:
    name: str
    url: str
    size: int
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float
    min_zoom: int
    max_zoom: int

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return (self.min_lon, self.min_lat, self.max_lon, self.max_lat)

    @classmethod
    def from_item(cls, item: dict) -> Archive:
        return cls(
            name=item["name"],
            url=item["url"],
            size=item["size"],
            min_lon=item["min_lon"],
            min_lat=item["min_lat"],
            max_lon=item["max_lon"],
            max_lat=item["max_lat"],
            min_zoom=item["min_zoom"],
            max_zoom=item["max_zoom"],
        )


def load_index(source: str | Path = INDEX_URL) -> list[Archive]:
    return [Archive.from_item(item) for item in json.loads(_read(str(source)))["items"]]


def _read(source: str) -> str:
    if source.startswith(("http://", "https://")):
        with urllib.request.urlopen(source, timeout=60) as response:
            return response.read().decode("utf-8")
    return Path(source).read_text(encoding="utf-8")
```

- [ ] **Step 6: Run to verify it passes**

Run: `uv run pytest tests/test_index.py -v`
Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock .gitignore DEMANDE.md docs mapterhorn_extract tests
git commit -m "feat: scaffold mapterhorn-extract and load Mapterhorn archive index"
```

---

### Task 2: Area input (extent and GeoJSON)

**Files:**
- Create: `mapterhorn_extract/area.py`
- Test: `tests/test_area.py`

**Interfaces:**
- Produces: `BBox = tuple[float, float, float, float]`; `check_bbox(bbox: BBox) -> BBox` (raises `ValueError` mentioning `EPSG:4326`); `parse_extent(text: str) -> BBox`; `bbox_from_geojson(path: str | Path) -> BBox` (accepts geometry, Feature, FeatureCollection, GeometryCollection; uses only Polygon and MultiPolygon).

- [ ] **Step 1: Write the failing tests**

`tests/test_area.py`:

```python
import json

import pytest

from mapterhorn_extract.area import bbox_from_geojson, parse_extent


def test_parse_extent():
    assert parse_extent("4.8,45.7,4.9,45.8") == (4.8, 45.7, 4.9, 45.8)


@pytest.mark.parametrize("text", ["4.8,45.7,4.9", "a,b,c,d", "4.9,45.7,4.8,45.8", "4.8,45.7,190,45.8"])
def test_parse_extent_rejects_invalid(text):
    with pytest.raises(ValueError):
        parse_extent(text)


def test_bbox_from_geojson_unions_polygons(tmp_path):
    path = tmp_path / "area.geojson"
    path.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {}, "geometry": {
                "type": "Polygon",
                "coordinates": [[[4.8, 45.7], [4.9, 45.7], [4.9, 45.8], [4.8, 45.7]]]}},
            {"type": "Feature", "properties": {}, "geometry": {
                "type": "MultiPolygon",
                "coordinates": [[[[6.8, 45.85], [6.95, 45.85], [6.95, 45.95], [6.8, 45.85]]]]}},
            {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [0.0, 0.0]}},
        ],
    }))
    assert bbox_from_geojson(path) == (4.8, 45.7, 6.95, 45.95)


def test_bbox_from_bare_geometry(tmp_path):
    path = tmp_path / "area.geojson"
    path.write_text(json.dumps({
        "type": "Polygon", "coordinates": [[[4.8, 45.7], [4.9, 45.7], [4.9, 45.8], [4.8, 45.7]]]}))
    assert bbox_from_geojson(path) == (4.8, 45.7, 4.9, 45.8)


def test_projected_coordinates_are_rejected(tmp_path):
    path = tmp_path / "lambert93.geojson"
    path.write_text(json.dumps({
        "type": "Polygon",
        "coordinates": [[[842000, 6519000], [843000, 6519000], [843000, 6520000], [842000, 6519000]]]}))
    with pytest.raises(ValueError, match="EPSG:4326"):
        bbox_from_geojson(path)


def test_geojson_without_polygon_is_rejected(tmp_path):
    path = tmp_path / "points.geojson"
    path.write_text(json.dumps({"type": "Point", "coordinates": [4.8, 45.7]}))
    with pytest.raises(ValueError, match="Polygon"):
        bbox_from_geojson(path)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_area.py -v`
Expected: `ModuleNotFoundError: No module named 'mapterhorn_extract.area'`.

- [ ] **Step 3: Implement `mapterhorn_extract/area.py`**

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_area.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add mapterhorn_extract/area.py tests/test_area.py
git commit -m "feat: parse extent and GeoJSON area into a validated EPSG:4326 bbox"
```

---

### Task 3: `plan()` and `Job`

**Files:**
- Create: `mapterhorn_extract/extract.py`
- Test: `tests/test_plan.py`

**Interfaces:**
- Consumes: `Archive`, `load_index` (Task 1); `BBox` (Task 2).
- Produces: `HIGH_ZOOM_MIN = 13`; `Job` (frozen dataclass: `name: str, url: str, minzoom: int, maxzoom: int, bbox: BBox, region: str | None, area_key: str`; property `output_name -> str` formatted `<archive stem>_z<minzoom>-<maxzoom>_<area_key>.pmtiles`; `to_dict() -> dict`; classmethod `from_dict(dict) -> Job`); `plan(bbox: BBox, maxzoom: int, region: str | Path | None = None, archives: list[Archive] | None = None) -> list[Job]` sorted by `name`, `region` stored as an absolute path string.

- [ ] **Step 1: Write the failing tests**

`tests/test_plan.py`:

```python
import json

import pytest

from mapterhorn_extract.extract import Job, plan

LYON = (4.80, 45.70, 4.90, 45.80)
PARIS = (2.25, 48.80, 2.45, 48.95)
CHAMONIX = (6.80, 45.85, 6.95, 45.95)
OCEAN = (-30.0, 40.0, -29.0, 41.0)
EDGE = (-1.0, 46.0, 0.0, 46.5)
LYON_RING = [[4.8, 45.7], [4.9, 45.7], [4.9, 45.8], [4.8, 45.7]]


def test_single_archive(archives):
    [job] = plan(LYON, 15, archives=archives)
    assert job.name == "6-32-22.pmtiles"
    assert job.url == "https://download.mapterhorn.com/6-32-22.pmtiles"
    assert (job.minzoom, job.maxzoom) == (13, 15)
    assert job.bbox == LYON
    assert job.region is None


def test_area_across_archives(archives):
    assert [j.name for j in plan(PARIS, 15, archives=archives)] == ["6-32-21.pmtiles", "6-32-22.pmtiles"]


def test_planet_is_never_planned(archives):
    names = {j.name for bbox in (LYON, PARIS, CHAMONIX, EDGE) for j in plan(bbox, 15, archives=archives)}
    assert "planet.pmtiles" not in names


def test_maxzoom_is_clamped_per_archive(archives):
    assert plan(LYON, 20, archives=archives)[0].maxzoom == 17
    assert plan(CHAMONIX, 20, archives=archives)[0].maxzoom == 18


def test_maxzoom_below_13_is_rejected(archives):
    with pytest.raises(ValueError, match=">= 13"):
        plan(LYON, 12, archives=archives)


def test_area_without_coverage_gives_no_job(archives):
    assert plan(OCEAN, 15, archives=archives) == []


def test_touching_edge_does_not_select_neighbour(archives):
    assert [j.name for j in plan(EDGE, 15, archives=archives)] == ["6-31-22.pmtiles"]


def test_region_is_stored_absolute(archives, region_file, monkeypatch, tmp_path):
    region_file(LYON_RING)
    monkeypatch.chdir(tmp_path)
    [job] = plan(LYON, 15, region="area.geojson", archives=archives)
    assert job.region == str(tmp_path / "area.geojson")


def test_output_name(archives):
    [job] = plan(LYON, 15, archives=archives)
    assert job.output_name == f"6-32-22_z13-15_{job.area_key}.pmtiles"
    assert len(job.area_key) == 8


def test_different_region_gives_different_output_name(archives, region_file):
    first = region_file(LYON_RING, "a.geojson")
    second = region_file([[4.8, 45.7], [4.85, 45.7], [4.85, 45.75], [4.8, 45.7]], "b.geojson")
    [a] = plan(LYON, 15, region=first, archives=archives)
    [b] = plan(LYON, 15, region=second, archives=archives)
    [c] = plan((4.80, 45.70, 4.85, 45.75), 15, archives=archives)
    assert len({a.output_name, b.output_name, c.output_name}) == 3


def test_job_round_trips_through_json(archives):
    [job] = plan(LYON, 15, archives=archives)
    assert Job.from_dict(json.loads(json.dumps(job.to_dict()))) == job
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_plan.py -v`
Expected: `ModuleNotFoundError: No module named 'mapterhorn_extract.extract'`.

- [ ] **Step 3: Implement `mapterhorn_extract/extract.py`**

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_plan.py -v`
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add mapterhorn_extract/extract.py tests/test_plan.py
git commit -m "feat: plan one extraction job per intersecting Mapterhorn z6 archive"
```

---

### Task 4: `pmtiles` binary and `extract_one()`

**Files:**
- Create: `mapterhorn_extract/pmtiles_bin.py`
- Modify: `mapterhorn_extract/extract.py` (imports, exceptions, `extract_one`, `_run`)
- Modify: `mapterhorn_extract/__init__.py` (public API)
- Test: `tests/test_extract.py`

**Interfaces:**
- Consumes: `Job`, `plan` (Task 3).
- Produces: `PmtilesNotFound(RuntimeError)`; `find_pmtiles(binary: str | None = None) -> str`; `extract_command(binary: str, job: Job, output: Path, threads: int) -> list[str]`; `ExtractError(RuntimeError)`; `ExtractCancelled(RuntimeError)`; `extract_one(job: Job, output_dir: str | Path, binary: str | None = None, threads: int = 16, should_stop: Callable[[], bool] | None = None) -> Path`.
- Package root re-exports: `INDEX_URL, Archive, load_index, BBox, bbox_from_geojson, parse_extent, Job, plan, extract_one, ExtractError, ExtractCancelled, PmtilesNotFound`.

- [ ] **Step 1: Write the failing tests**

`tests/test_extract.py`:

```python
import json
import time

import pytest

from mapterhorn_extract import ExtractCancelled, ExtractError, PmtilesNotFound, extract_one, plan
from mapterhorn_extract.pmtiles_bin import find_pmtiles

LYON = (4.80, 45.70, 4.90, 45.80)
LYON_RING = [[4.8, 45.7], [4.9, 45.7], [4.9, 45.8], [4.8, 45.7]]


def _job(archives, region=None):
    return plan(LYON, 14, region=region, archives=archives)[0]


def test_extract_one_runs_pmtiles_with_bbox(archives, fake_pmtiles, tmp_path):
    out = extract_one(_job(archives), tmp_path / "out", binary=str(fake_pmtiles), threads=4)
    assert out.parent == tmp_path / "out"
    assert out.name.startswith("6-32-22_z13-14_")
    args = json.loads(out.read_text())
    assert args[:2] == ["extract", "https://download.mapterhorn.com/6-32-22.pmtiles"]
    assert {"--minzoom=13", "--maxzoom=14", "--download-threads=4", "--bbox=4.8,45.7,4.9,45.8"} <= set(args)
    assert not any(a.startswith("--region") for a in args)


def test_extract_one_passes_region_instead_of_bbox(archives, fake_pmtiles, region_file, tmp_path):
    region = region_file(LYON_RING)
    out = extract_one(_job(archives, region=region), tmp_path / "out", binary=str(fake_pmtiles))
    args = json.loads(out.read_text())
    assert f"--region={region.resolve()}" in args
    assert not any(a.startswith("--bbox") for a in args)


def test_extract_one_skips_existing_output(archives, fake_pmtiles, tmp_path, monkeypatch):
    job = _job(archives)
    first = extract_one(job, tmp_path / "out", binary=str(fake_pmtiles))
    monkeypatch.setenv("FAKE_PMTILES_MODE", "fail")
    assert extract_one(job, tmp_path / "out", binary=str(fake_pmtiles)) == first


def test_failed_extract_leaves_no_file(archives, fake_pmtiles, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_PMTILES_MODE", "fail")
    with pytest.raises(ExtractError, match="boom"):
        extract_one(_job(archives), tmp_path / "out", binary=str(fake_pmtiles))
    assert list((tmp_path / "out").iterdir()) == []


def test_cancel_stops_extract_and_cleans_up(archives, fake_pmtiles, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_PMTILES_MODE", "slow")
    start = time.monotonic()
    with pytest.raises(ExtractCancelled):
        extract_one(_job(archives), tmp_path / "out", binary=str(fake_pmtiles), should_stop=lambda: True)
    assert time.monotonic() - start < 10
    assert list((tmp_path / "out").iterdir()) == []


def test_missing_binary_raises(archives, tmp_path):
    with pytest.raises(PmtilesNotFound):
        extract_one(_job(archives), tmp_path, binary=str(tmp_path / "nope"))


def test_binary_found_on_path(fake_pmtiles, monkeypatch):
    monkeypatch.setenv("PATH", str(fake_pmtiles.parent))
    assert find_pmtiles() == str(fake_pmtiles)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_extract.py -v`
Expected: `ImportError: cannot import name 'ExtractCancelled' from 'mapterhorn_extract'`.

- [ ] **Step 3: Implement `mapterhorn_extract/pmtiles_bin.py`**

```python
from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .extract import Job


class PmtilesNotFound(RuntimeError):
    pass


def find_pmtiles(binary: str | None = None) -> str:
    wanted = binary or "pmtiles"
    found = shutil.which(wanted)
    if found is None:
        raise PmtilesNotFound(
            f"pmtiles binary not found: {wanted}. Install go-pmtiles or give the path to the binary."
        )
    return found


def extract_command(binary: str, job: Job, output: Path, threads: int) -> list[str]:
    command = [
        binary,
        "extract",
        job.url,
        str(output),
        f"--minzoom={job.minzoom}",
        f"--maxzoom={job.maxzoom}",
        f"--download-threads={threads}",
    ]
    if job.region is not None:
        command.append(f"--region={job.region}")
    else:
        command.append("--bbox=" + ",".join(str(c) for c in job.bbox))
    return command
```

- [ ] **Step 4: Add `extract_one` to `mapterhorn_extract/extract.py`**

Replace the import block at the top with:

```python
from __future__ import annotations

import hashlib
import logging
import os
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from .area import BBox
from .index import Archive, load_index
from .pmtiles_bin import extract_command, find_pmtiles

HIGH_ZOOM_MIN = 13

logger = logging.getLogger(__name__)


class ExtractError(RuntimeError):
    pass


class ExtractCancelled(RuntimeError):
    pass
```

Append at the end of the file:

```python
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
    output_dir.mkdir(parents=True, exist_ok=True)
    part = output.with_name(output.stem + ".part.pmtiles")
    part.unlink(missing_ok=True)
    command = extract_command(find_pmtiles(binary), job, part, threads)
    logger.info("extracting %s z%d-%d", job.name, job.minzoom, job.maxzoom)
    try:
        _run(command, should_stop)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    os.replace(part, output)
    return output


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
                    raise ExtractCancelled(f"extract cancelled: {command[2]}") from None
    if process.returncode != 0:
        raise ExtractError(f"pmtiles extract failed ({process.returncode}): {stderr.strip()}")
```

- [ ] **Step 5: Fill `mapterhorn_extract/__init__.py`**

```python
from .area import BBox, bbox_from_geojson, parse_extent
from .extract import ExtractCancelled, ExtractError, Job, extract_one, plan
from .index import INDEX_URL, Archive, load_index
from .pmtiles_bin import PmtilesNotFound

__all__ = [
    "INDEX_URL",
    "Archive",
    "BBox",
    "ExtractCancelled",
    "ExtractError",
    "Job",
    "PmtilesNotFound",
    "bbox_from_geojson",
    "extract_one",
    "load_index",
    "parse_extent",
    "plan",
]
```

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest -v`
Expected: all tests pass (index, area, plan, extract).

- [ ] **Step 7: Commit**

```bash
git add mapterhorn_extract tests/test_extract.py
git commit -m "feat: run pmtiles extract per job with atomic output and cancellation"
```

---

### Task 5: Command line

**Files:**
- Create: `mapterhorn_extract/__main__.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `INDEX_URL, load_index, bbox_from_geojson, parse_extent, plan, extract_one, ExtractError, PmtilesNotFound` (Tasks 1 to 4).
- Produces: `main(argv: list[str] | None = None) -> int`; exit 0 on success, 1 on no coverage or extract failure, 2 on usage error. Stdout: one output path per line (or, with `--dry-run`, `<archive> z<min>-<max> -> <output_name>`).

- [ ] **Step 1: Write the failing tests**

`tests/test_cli.py`:

```python
from pathlib import Path

import pytest

from mapterhorn_extract.__main__ import main

LYON_RING = [[4.8, 45.7], [4.9, 45.7], [4.9, 45.8], [4.8, 45.7]]


def test_dry_run_lists_jobs(index_path, capsys):
    code = main(["--extent", "2.25,48.80,2.45,48.95", "--maxzoom", "15", "--index", str(index_path), "--dry-run"])
    lines = capsys.readouterr().out.splitlines()
    assert code == 0
    assert [line.split()[0] for line in lines] == ["6-32-21.pmtiles", "6-32-22.pmtiles"]
    assert "z13-15" in lines[0]


def test_no_coverage_exits_1(index_path, capsys):
    assert main(["--extent", "-30,40,-29,41", "--maxzoom", "15", "--index", str(index_path)]) == 1
    assert "No Mapterhorn archive" in capsys.readouterr().err


def test_geojson_and_extent_are_exclusive(tmp_path):
    with pytest.raises(SystemExit) as exc:
        main(["--geojson", str(tmp_path / "a.geojson"), "--extent", "1,2,3,4", "--maxzoom", "15"])
    assert exc.value.code == 2


def test_invalid_maxzoom_is_usage_error(index_path):
    with pytest.raises(SystemExit) as exc:
        main(["--extent", "4.8,45.7,4.9,45.8", "--maxzoom", "12", "--index", str(index_path)])
    assert exc.value.code == 2


def test_missing_geojson_is_usage_error(index_path, tmp_path):
    with pytest.raises(SystemExit) as exc:
        main(["--geojson", str(tmp_path / "missing.geojson"), "--maxzoom", "14", "--index", str(index_path)])
    assert exc.value.code == 2


def test_extracts_with_geojson(index_path, fake_pmtiles, region_file, tmp_path, capsys):
    region = region_file(LYON_RING)
    code = main([
        "--geojson", str(region), "--maxzoom", "14", "--index", str(index_path),
        "--output-dir", str(tmp_path / "out"), "--pmtiles-bin", str(fake_pmtiles),
    ])
    printed = capsys.readouterr().out.strip().splitlines()
    assert code == 0
    assert len(printed) == 1
    assert Path(printed[0]).exists()


def test_extract_failure_exits_1(index_path, fake_pmtiles, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_PMTILES_MODE", "fail")
    code = main([
        "--extent", "4.8,45.7,4.9,45.8", "--maxzoom", "14", "--index", str(index_path),
        "--output-dir", str(tmp_path / "out"), "--pmtiles-bin", str(fake_pmtiles),
    ])
    assert code == 1
    assert "boom" in capsys.readouterr().err
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_cli.py -v`
Expected: `ModuleNotFoundError: No module named 'mapterhorn_extract.__main__'`.

- [ ] **Step 3: Implement `mapterhorn_extract/__main__.py`**

```python
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import (
    INDEX_URL,
    ExtractError,
    PmtilesNotFound,
    bbox_from_geojson,
    extract_one,
    load_index,
    parse_extent,
    plan,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mapterhorn-extract",
        description="Extract Mapterhorn z13+ terrain PMTiles over an area, one file per z6 archive.",
    )
    area = parser.add_mutually_exclusive_group(required=True)
    area.add_argument("--geojson", type=Path, help="EPSG:4326 polygon GeoJSON (passed to pmtiles --region)")
    area.add_argument("--extent", help="min_lon,min_lat,max_lon,max_lat (passed to pmtiles --bbox)")
    parser.add_argument("--maxzoom", type=int, required=True, help="highest zoom, >= 13, capped per archive")
    parser.add_argument("--output-dir", type=Path, default=Path("."))
    parser.add_argument("--pmtiles-bin", help="pmtiles binary (default: pmtiles on PATH)")
    parser.add_argument("--threads", type=int, default=16, help="pmtiles --download-threads")
    parser.add_argument("--index", default=INDEX_URL, help="Mapterhorn download_urls.json URL or path")
    parser.add_argument("--dry-run", action="store_true", help="list jobs without extracting")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        if args.geojson is not None:
            bbox, region = bbox_from_geojson(args.geojson), args.geojson
        else:
            bbox, region = parse_extent(args.extent), None
        jobs = plan(bbox, args.maxzoom, region=region, archives=load_index(args.index))
    except (ValueError, OSError) as error:
        parser.error(str(error))

    if not jobs:
        print("No Mapterhorn archive covers this area above zoom 12.", file=sys.stderr)
        return 1
    for job in jobs:
        if args.dry_run:
            print(f"{job.name} z{job.minzoom}-{job.maxzoom} -> {job.output_name}")
            continue
        try:
            print(extract_one(job, args.output_dir, binary=args.pmtiles_bin, threads=args.threads))
        except (PmtilesNotFound, ExtractError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest -v`
Expected: all tests pass.

- [ ] **Step 5: Smoke-test against the live index (network, no download)**

Run: `uv run mapterhorn-extract --extent 4.80,45.70,4.90,45.80 --maxzoom 20 --dry-run`
Expected: one line starting `6-32-22.pmtiles z13-17 -> 6-32-22_z13-17_`.

- [ ] **Step 6: Commit**

```bash
git add mapterhorn_extract/__main__.py tests/test_cli.py
git commit -m "feat: add mapterhorn-extract command line"
```

---

### Task 6: QGIS Processing plugin, validated live through the QGIS MCP

**Files:**
- Create: `mapterhorn_pmtiles/metadata.txt`, `mapterhorn_pmtiles/__init__.py`, `mapterhorn_pmtiles/plugin.py`, `mapterhorn_pmtiles/provider.py`, `mapterhorn_pmtiles/compat.py`, `mapterhorn_pmtiles/algorithm.py`
- Create: symlink `mapterhorn_pmtiles/mapterhorn_extract -> ../mapterhorn_extract`

**Interfaces:**
- Consumes: `plan, extract_one, bbox_from_geojson, ExtractError, ExtractCancelled, PmtilesNotFound` (Tasks 2 to 4), imported as `from .mapterhorn_extract import ...`.
- Produces: provider id `mapterhorn`, algorithm id `mapterhorn:extract`. Parameters: `INPUT` (polygon feature source), `MAXZOOM` (int 13 to 18, default 15), `PMTILES_BIN` (file, optional), `THREADS` (int 1 to 64, default 16), `OUTPUT_DIR` (folder destination). Outputs: `OUTPUT_DIR`, `OUTPUT_FILES` (list of paths).

Validation has no pytest suite: QGIS's Python is not the uv environment. It runs in the live QGIS 4.2.3 session (profile `jwe`) through the `qgis` MCP server. If an MCP call fails with "Could not connect to Qgis", ask the user to click **Start Server** in the QGIS MCP plugin.

- [ ] **Step 1: Plugin skeleton**

```bash
cd /home/jwaddle/Projets/qgis/plugin_pmtiles
mkdir mapterhorn_pmtiles
ln -s ../mapterhorn_extract mapterhorn_pmtiles/mapterhorn_extract
```

`mapterhorn_pmtiles/metadata.txt`:

```ini
[general]
name=Mapterhorn PMTiles
qgisMinimumVersion=3.34
qgisMaximumVersion=4.99
supportsQt6=True
description=Extract high-zoom Mapterhorn terrain PMTiles over an area
about=Wraps the go-pmtiles CLI to extract Mapterhorn z13+ archives over a polygon layer, one PMTiles per Mapterhorn z6 archive. Requires the pmtiles binary.
version=0.1.0
author=Camptocamp
email=julien.waddle@camptocamp.com
tags=pmtiles,terrain,dem,mapterhorn,processing
hasProcessingProvider=yes
experimental=True
```

`mapterhorn_pmtiles/__init__.py`:

```python
def classFactory(iface):
    from .plugin import MapterhornPlugin

    return MapterhornPlugin()
```

`mapterhorn_pmtiles/plugin.py`:

```python
from qgis.core import QgsApplication

from .provider import MapterhornProvider


class MapterhornPlugin:
    def __init__(self):
        self.provider = None

    def initProcessing(self):
        self.provider = MapterhornProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):
        self.initProcessing()

    def unload(self):
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None
```

`mapterhorn_pmtiles/provider.py`:

```python
from qgis.core import QgsProcessingProvider

from .algorithm import ExtractMapterhornAlgorithm


class MapterhornProvider(QgsProcessingProvider):
    def id(self):
        return "mapterhorn"

    def name(self):
        return "Mapterhorn"

    def loadAlgorithms(self):
        self.addAlgorithm(ExtractMapterhornAlgorithm())
```

`mapterhorn_pmtiles/compat.py`:

```python
from qgis.core import Qgis, QgsProcessing, QgsProcessingParameterNumber

try:
    POLYGON = Qgis.ProcessingSourceType.VectorPolygon
    INTEGER = Qgis.ProcessingNumberParameterType.Integer
except AttributeError:  # QGIS < 3.36
    POLYGON = QgsProcessing.TypeVectorPolygon
    INTEGER = QgsProcessingParameterNumber.Integer
```

- [ ] **Step 2: The algorithm**

`mapterhorn_pmtiles/algorithm.py`:

```python
import json
from pathlib import Path

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputMultipleLayers,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFile,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterNumber,
    QgsProcessingUtils,
)

from .compat import INTEGER, POLYGON
from .mapterhorn_extract import (
    ExtractCancelled,
    ExtractError,
    PmtilesNotFound,
    bbox_from_geojson,
    extract_one,
    plan,
)


class ExtractMapterhornAlgorithm(QgsProcessingAlgorithm):
    INPUT = "INPUT"
    MAXZOOM = "MAXZOOM"
    PMTILES_BIN = "PMTILES_BIN"
    THREADS = "THREADS"
    OUTPUT_DIR = "OUTPUT_DIR"
    OUTPUT_FILES = "OUTPUT_FILES"

    def name(self):
        return "extract"

    def displayName(self):
        return "Extract Mapterhorn high-zoom PMTiles"

    def shortHelpString(self):
        return (
            "Extracts Mapterhorn terrain tiles from zoom 13 up to the chosen max zoom over the "
            "polygons of the input layer, one PMTiles per Mapterhorn z6 archive. Zooms 0 to 12 "
            "are not extracted. Each archive's own max zoom caps the requested one. Requires the "
            "pmtiles binary (go-pmtiles), from the parameter or the PATH."
        )

    def createInstance(self):
        return ExtractMapterhornAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(self.INPUT, "Area (polygon layer)", [POLYGON]))
        self.addParameter(QgsProcessingParameterNumber(self.MAXZOOM, "Max zoom", INTEGER, 15, False, 13, 18))
        self.addParameter(
            QgsProcessingParameterFile(self.PMTILES_BIN, "pmtiles binary (empty: use PATH)", optional=True)
        )
        self.addParameter(QgsProcessingParameterNumber(self.THREADS, "Download threads", INTEGER, 16, False, 1, 64))
        self.addParameter(QgsProcessingParameterFolderDestination(self.OUTPUT_DIR, "Output folder"))
        self.addOutput(QgsProcessingOutputMultipleLayers(self.OUTPUT_FILES, "Extracted PMTiles"))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        if source is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.INPUT))
        maxzoom = self.parameterAsInt(parameters, self.MAXZOOM, context)
        binary = self.parameterAsFile(parameters, self.PMTILES_BIN, context) or None
        threads = self.parameterAsInt(parameters, self.THREADS, context)
        output_dir = Path(self.parameterAsString(parameters, self.OUTPUT_DIR, context))

        region = Path(QgsProcessingUtils.generateTempFilename("area.geojson"))
        _write_region(source, context, region)
        try:
            jobs = plan(bbox_from_geojson(region), maxzoom, region=region)
        except (ValueError, OSError) as error:
            raise QgsProcessingException(str(error)) from error
        if not jobs:
            raise QgsProcessingException("No Mapterhorn archive covers this area above zoom 12.")

        outputs = []
        for done, job in enumerate(jobs):
            feedback.pushInfo(f"{job.name}: z{job.minzoom}-{job.maxzoom} -> {job.output_name}")
            try:
                path = extract_one(job, output_dir, binary=binary, threads=threads, should_stop=feedback.isCanceled)
            except ExtractCancelled:
                break
            except (PmtilesNotFound, ExtractError) as error:
                raise QgsProcessingException(str(error)) from error
            outputs.append(str(path))
            feedback.setProgress(100 * (done + 1) / len(jobs))
        return {self.OUTPUT_DIR: str(output_dir), self.OUTPUT_FILES: outputs}


def _write_region(source, context, path):
    transform = QgsCoordinateTransform(
        source.sourceCrs(), QgsCoordinateReferenceSystem("EPSG:4326"), context.transformContext()
    )
    features = []
    for feature in source.getFeatures():
        geometry = feature.geometry()
        if geometry.isEmpty():
            continue
        geometry.transform(transform)
        features.append({"type": "Feature", "properties": {}, "geometry": json.loads(geometry.asJson())})
    if not features:
        raise QgsProcessingException("The area layer has no polygon to extract.")
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
```

- [ ] **Step 3: Check the pmtiles binary is available**

Run: `which pmtiles || ls ~/.local/bin/pmtiles`
If neither exists: stop and ask the user to install go-pmtiles (https://github.com/protomaps/go-pmtiles/releases) or give a path. Do not install it yourself. Note the absolute path as `PMTILES` for the steps below; QGIS may not have `~/.local/bin` on its PATH, so pass it explicitly.

- [ ] **Step 4: Install the plugin into the QGIS profile and load it**

```bash
ln -s /home/jwaddle/Projets/qgis/plugin_pmtiles/mapterhorn_pmtiles \
  ~/.local/share/QGIS/QGIS4/profiles/jwe/python/plugins/mapterhorn_pmtiles
```

MCP `execute_code`:

```python
import qgis.utils
from qgis.core import QgsApplication
qgis.utils.updateAvailablePlugins()
qgis.utils.loadPlugin("mapterhorn_pmtiles")
qgis.utils.startPlugin("mapterhorn_pmtiles")
print(QgsApplication.processingRegistry().algorithmById("mapterhorn:extract") is not None)
```

Expected: `True`. After any later code change, use MCP `reload_plugin("mapterhorn_pmtiles")`.

- [ ] **Step 5: Create a small Lambert-93 test area (exercises reprojection)**

MCP `execute_code`:

```python
from qgis.core import QgsFeature, QgsGeometry, QgsProject, QgsVectorLayer
layer = QgsVectorLayer("Polygon?crs=EPSG:2154", "mapterhorn_test_lyon", "memory")
feature = QgsFeature()
feature.setGeometry(QgsGeometry.fromWkt(
    "POLYGON((842000 6519000, 843000 6519000, 843000 6520000, 842000 6520000, 842000 6519000))"))
layer.dataProvider().addFeatures([feature])
QgsProject.instance().addMapLayer(layer)
print(layer.id())
```

- [ ] **Step 6: Run the algorithm on it**

MCP `execute_processing`, algorithm `mapterhorn:extract`, `timeout: 600`, parameters:

```json
{"INPUT": "<layer id from step 5>", "MAXZOOM": 14, "PMTILES_BIN": "<PMTILES>", "THREADS": 8, "OUTPUT_DIR": "/tmp/mapterhorn_qgis_test"}
```

Expected: `OUTPUT_FILES` holds one path `/tmp/mapterhorn_qgis_test/6-32-22_z13-14_<key>.pmtiles`.
Then run: `<PMTILES> show /tmp/mapterhorn_qgis_test/6-32-22_z13-14_*.pmtiles`
Expected: min zoom 13, max zoom 14, bounds near lon 4.8 to 4.9, lat 45.7 to 45.8.
Run the same `execute_processing` again: it must return the same path within seconds (skip).

- [ ] **Step 7: Check the failure paths in QGIS**

MCP `execute_code` to add an open-sea layer:

```python
from qgis.core import QgsFeature, QgsGeometry, QgsProject, QgsVectorLayer
layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "mapterhorn_test_ocean", "memory")
feature = QgsFeature()
feature.setGeometry(QgsGeometry.fromWkt("POLYGON((-30 40, -29 40, -29 41, -30 41, -30 40))"))
layer.dataProvider().addFeatures([feature])
QgsProject.instance().addMapLayer(layer)
print(layer.id())
```

- `execute_processing` with that layer: expected error `No Mapterhorn archive covers this area above zoom 12.`
- `execute_processing` with the Lyon layer and `"PMTILES_BIN": "/nonexistent/pmtiles"`: expected error starting `pmtiles binary not found`.

Then remove both test layers (MCP `remove_layer`) and `rm -r /tmp/mapterhorn_qgis_test`.

- [ ] **Step 8: Commit**

```bash
git add mapterhorn_pmtiles
git commit -m "feat: add QGIS Processing algorithm mapterhorn:extract"
```

---

## Addendum (2026-10-12): base file + one merged file per zone

Spec change in `DEMANDE.md` ("Comportement cible"): one base file z0-12 from `planet.pmtiles` over all zones, plus one file per zone z13 to the zone's max zoom, merged with `pmtiles merge` (go-pmtiles 1.31.2, disjoint inputs only). Per-zone max zoom from a field/property, a default zoom, and a "same zoom for all" switch.

### Task 7: `plan_base()` and `merge()`

**Files:** Modify `mapterhorn_extract/extract.py`, `mapterhorn_extract/pmtiles_bin.py`, `mapterhorn_extract/__init__.py`, `tests/conftest.py` (fake handles `merge`: output is the last argument). Test: `tests/test_plan.py`, `tests/test_extract.py`.

**Produces:** `plan_base(bbox, region=None, archives=None) -> Job | None` (archive with `min_zoom == 0`, job z0 to its `max_zoom`); `merge_command(binary, inputs, output) -> list[str]`; `merge(inputs: list[Path], output: Path, binary=None, should_stop=None) -> Path` (skip if output exists, single input copied, atomic `.part`, never deletes inputs).

Tests: `test_plan_base_targets_planet`, `test_plan_base_without_planet_is_none`, `test_merge_runs_pmtiles_merge`, `test_merge_single_input_is_copied`, `test_merge_skips_existing_output`, `test_failed_merge_leaves_no_file`.

### Task 8: zones

**Files:** Create `mapterhorn_extract/zones.py`, `tests/test_zones.py`. Modify `mapterhorn_extract/__init__.py`.

**Produces:** `Zone(name: str, maxzoom: int, region: Path)`; `zones_from_geojson(path, default_maxzoom, work_dir, same_zoom=False) -> tuple[Path, list[Zone]]` (all-zones region file + one region file per polygon feature; name from `name` property sanitized for file names, else `zone_<n>`; duplicate names, maxzoom < 13, or no polygon raise `ValueError`); `extract_base(region, output_dir, archives=None, binary=None, threads=16, should_stop=None) -> Path | None`; `extract_zone(zone, output_dir, archives=None, binary=None, threads=16, should_stop=None) -> Path | None` (per-archive extracts in `<output_dir>/.parts/<stem>/`, merged to `<name>_z13-<effective max>_<area_key>.pmtiles`, parts removed).

Tests: names and defaults, per-zone and default zoom, `same_zoom` override, zoom < 13 rejected, duplicate names rejected, non-polygon features ignored, `extract_base` output name, `extract_zone` across two archives merges and cleans parts, `extract_zone` skips existing, no coverage returns None, live merge test skipped unless `MAPTERHORN_LIVE_PMTILES` points to a real binary.

### Task 9: CLI on zones

**Files:** Modify `mapterhorn_extract/__main__.py`, `tests/test_cli.py`.

`--geojson` zones (properties `name`, `maxzoom`) or `--extent` (one zone `extent`), `--maxzoom` default zoom, `--same-zoom`; prints base path then zone paths; `--dry-run` prints `base planet.pmtiles z0-12` and `zone <name> z13-<max>: <archives>`; a zone without coverage is reported on stderr and makes the exit code 1.

### Task 10: QGIS algorithm on zones

**Files:** Modify `mapterhorn_pmtiles/algorithm.py`, `mapterhorn_pmtiles/compat.py`.

New parameters `NAME_FIELD` (optional field), `MAXZOOM_FIELD` (optional numeric field), `SAME_ZOOM` (boolean, default false); `MAXZOOM` becomes the default zoom (13 to 22). Output `OUTPUT_FILES` = base then zones. Live check through the MCP: two zones (Lyon in EPSG:2154 at z14, a zone across lon 5.625 at z13), then `SAME_ZOOM`.
