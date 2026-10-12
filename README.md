# Mapterhorn PMTiles

Extracts [Mapterhorn](https://mapterhorn.com) terrain tiles over a set of zones, as PMTiles:

- **one base file**, zooms 0 to 12, cut from `planet.pmtiles` over all zones;
- **one file per zone**, zoom 13 up to the zone's max zoom, merged from every Mapterhorn z6 archive the zone touches.

Two front ends share the same code:

- `mapterhorn_extract`: a Python library and command line, standard library only, no QGIS needed (scripts, Airflow);
- `mapterhorn_pmtiles`: a QGIS Processing plugin, algorithm `mapterhorn:extract`.

Both wrap the [go-pmtiles](https://github.com/protomaps/go-pmtiles) CLI. Background and design decisions: [DEMANDE.md](DEMANDE.md).

## Requirements

- go-pmtiles **1.31 or later** (`merge` is required). Not bundled: give its path, or put `pmtiles` on the PATH.
- Python 3.10 or later for the library.
- QGIS 3.34 LTR to 4.x for the plugin (validated on 4.2).

## Output

Given zones `Lyon centre` (max zoom 14) and `Voiron` (max zoom 13):

```
planet_z0-12_3504d789.pmtiles          base, all zones
Lyon_centre_z13-14_cd6398dc.pmtiles    one file per zone
Voiron_z13-13_326dc7cc.pmtiles
```

- **Zoom:** a zone's max zoom is capped by what Mapterhorn has where it lies (z17 over most of France, z18 in parts of the Alps). The file name shows the zoom actually reached.
- **Key:** the 8-character key is a hash of the geometry. Editing a zone produces a new file; renaming it or changing its zoom does not touch the base file.
- **Re-runs:** a file that already exists is skipped, so an interrupted run resumes where it stopped. Extractions write to a `.part` file first, so a failed run never leaves a file that looks complete.
- **Zoom below 13:** rejected, the base file already covers 0 to 12.

The tiles are Terrarium-encoded WebP elevation (a MapLibre `raster-dem` source), not a rendered hillshade.

## QGIS plugin

### Install

Development, from the repository:

```bash
ln -s "$PWD/mapterhorn_pmtiles" ~/.local/share/QGIS/QGIS4/profiles/<profile>/python/plugins/mapterhorn_pmtiles
```

Then enable **Mapterhorn PMTiles** in the plugin manager.

Distribution, as a zip (`zip` follows the `mapterhorn_extract` symlink and packs the library inside):

```bash
zip -r mapterhorn_pmtiles.zip mapterhorn_pmtiles -x '*__pycache__*'
```

### Use

**Processing Toolbox > Mapterhorn > Extract Mapterhorn PMTiles per zone.** One polygon of the input layer is one zone; selected features only is supported.

| Parameter | Meaning |
|---|---|
| Zones (polygon layer) | Any CRS, reprojected to EPSG:4326 |
| Zone name field | Optional. Empty values become `zone_<n>` |
| Zone max zoom field | Optional, numeric. Empty values use the default max zoom |
| Default max zoom | 13 to 22, default 15 |
| Same max zoom for all zones | Ignores the zoom field and applies the default to every zone |
| pmtiles binary | Optional. Empty: `pmtiles` on the PATH. QGIS may not see your shell PATH, so set it explicitly if in doubt |
| Download threads | Passed to `pmtiles extract --download-threads` |
| Output folder | Where the files are written |

The run fails if no zone has Mapterhorn coverage above zoom 12. A zone without coverage among covered ones is reported and skipped.

## Command line

```bash
uv run mapterhorn-extract --geojson zones.geojson --maxzoom 15 --output-dir out/ --pmtiles-bin ./pmtiles
```

- `--geojson`: EPSG:4326 polygons, one zone per feature, optional properties `name` and `maxzoom`.
- `--extent min_lon,min_lat,max_lon,max_lat`: a single zone named `extent`. Write `--extent=-1.5,...` when the value starts with a minus sign.
- `--maxzoom`: zoom for zones without a `maxzoom` property.
- `--same-zoom`: use `--maxzoom` for every zone.
- `--dry-run`: list what would be extracted, nothing is downloaded.

```console
$ uv run mapterhorn-extract --extent 4.80,45.70,4.90,45.80 --maxzoom 20 --dry-run
base planet.pmtiles z0-12
zone extent z13-17: 6-32-22.pmtiles
```

Prints the produced paths, base first. Exit code 1 when a zone has no coverage or pmtiles fails, 2 on invalid input.

## Library

```python
from mapterhorn_extract import extract_base, extract_zone, load_index, zones_from_geojson

archives = load_index()
all_zones, zones = zones_from_geojson("zones.geojson", default_maxzoom=15, work_dir="work")
extract_base(all_zones, "out", archives=archives, binary="./pmtiles")
for zone in zones:
    extract_zone(zone, "out", archives=archives, binary="./pmtiles")
```

Lower-level pieces, for one task per archive in an orchestrator such as Airflow:

- `plan_zone(zone, archives) -> list[Job]`: one job per Mapterhorn archive the zone touches; `Job.to_dict()` / `Job.from_dict()` serialize it;
- `extract_one(job, output_dir) -> Path`: one `pmtiles extract`;
- `merge(paths, output) -> Path`: one `pmtiles merge` of a zone's extracts;
- `plan_base(bbox, region, archives) -> Job | None`: the z0 to 12 job.

All long-running calls accept `should_stop`, a callable polled every half second to cancel the running `pmtiles` process.

## Development

```bash
uv run pytest
```

Tests use a fake `pmtiles` and a local excerpt of the Mapterhorn index, so they run offline. One test downloads real tiles across two archives and merges them; enable it with a real binary:

```bash
MAPTERHORN_LIVE_PMTILES=$PWD/pmtiles uv run pytest -k live
```

The plugin has no automated tests; it is checked in a running QGIS.
