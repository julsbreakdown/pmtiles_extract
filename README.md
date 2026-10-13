# Mapterhorn PMTiles

Extracts [Mapterhorn](https://mapterhorn.com) terrain tiles over a set of zones, as PMTiles:

- **one base file**, zooms 0 to 12, cut from `planet.pmtiles` over France (or another extent you choose);
- **one file per zone**, zoom 13 up to the zone's max zoom, merged from every Mapterhorn z6 archive the zone touches.

Two front ends share the same code:

- `mapterhorn_extract`: a Python library and command line, standard library only, no QGIS needed (scripts, Airflow);
- `mapterhorn_pmtiles`: a QGIS Processing plugin, algorithms `mapterhorn:extract_base` and `mapterhorn:extract_zones`.

Both wrap the [go-pmtiles](https://github.com/protomaps/go-pmtiles) CLI. Background and design decisions: [DEMANDE.md](DEMANDE.md).

## Quick start

Two commands, run independently, in any order:

| Command | Covers | Zooms | QGIS algorithm |
|---|---|---|---|
| `mapterhorn-extract base` | all of France, once | 0–12 | `mapterhorn:extract_base` |
| `mapterhorn-extract zones --geojson zones.geojson --maxzoom 15` | specific zones only | 13 to each zone's max zoom | `mapterhorn:extract_zones` |

```bash
uv run mapterhorn-extract base --output-dir out/ --pmtiles-bin ./pmtiles
uv run mapterhorn-extract zones --geojson examples/alpes.geojson --maxzoom 15 --output-dir out/ --pmtiles-bin ./pmtiles
```

The base file rarely changes, so run it once; rerun `zones` whenever zones are added or edited. Add `--dry-run` to either to list what it would download.

## Requirements

- go-pmtiles **1.31 or later** (`merge` is required). Not bundled: give its path, or put `pmtiles` on the PATH.
- Python 3.10 or later for the library.
- QGIS 3.34 LTR to 4.x for the plugin (validated on 4.2).

## Output

Given zones `Lyon centre` (max zoom 14) and `Voiron` (max zoom 13):

```
france_z0-12_<key>.pmtiles             base, France (base_z0-12_<key> with a custom base extent)
Lyon_centre_z13-14_cd6398dc.pmtiles    one file per zone
Voiron_z13-13_326dc7cc.pmtiles
```

The France extent is `-5.15,42.33,8.23,51.10` (lon/lat). The base file over all of France is large; it is downloaded once and reused by later runs.

- **Zoom:** a zone's max zoom is capped by what Mapterhorn has where it lies (z17 over most of France, z18 in parts of the Alps). The file name shows the zoom actually reached.
- **Key:** the 8-character key is a hash of the geometry. Editing a zone produces a new file for that zone only; the base file depends on the base extent alone.
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

Two algorithms under **Processing Toolbox > Mapterhorn**.

**Extract Mapterhorn base PMTiles (zooms 0-12)**

| Parameter | Meaning |
|---|---|
| Extent | Optional. Empty: France. Any CRS, reprojected to EPSG:4326 |

**Extract Mapterhorn PMTiles per zone (zooms 13+).** One polygon of the input layer is one zone; selected features only is supported.

| Parameter | Meaning |
|---|---|
| Zones (polygon layer) | Any CRS, reprojected to EPSG:4326 |
| Zone name field | Optional. Empty values become `zone_<n>` |
| Zone max zoom field | Optional, numeric. Empty values use the default max zoom |
| Default max zoom | 13 to 22, default 15 |
| Same max zoom for all zones | Ignores the zoom field and applies the default to every zone |

The run fails if no zone has Mapterhorn coverage above zoom 12. A zone without coverage among covered ones is reported and skipped.

Both share:

| Parameter | Meaning |
|---|---|
| pmtiles binary | Optional. Empty: `pmtiles` on the PATH. QGIS may not see your shell PATH, so set it explicitly if in doubt |
| Download threads | Passed to `pmtiles extract --download-threads` |
| Output folder | Where the files are written |

## Command line

### All of France: `base`

```bash
uv run mapterhorn-extract base --output-dir out/ --pmtiles-bin ./pmtiles
```

Produces `france_z0-12_<key>.pmtiles`. To cut another area instead of France (file `base_z0-12_<key>.pmtiles`):

- `--extent min_lon,min_lat,max_lon,max_lat`;
- `--geojson`: an EPSG:4326 polygon.

### Specific zones: `zones`

```bash
uv run mapterhorn-extract zones --geojson zones.geojson --maxzoom 15 --output-dir out/ --pmtiles-bin ./pmtiles
```

Produces one `<name>_z13-<zoom>_<key>.pmtiles` per zone, never the base file.

- `--geojson`: EPSG:4326 polygons, one zone per feature, optional properties `name` and `maxzoom`;
- `--extent min_lon,min_lat,max_lon,max_lat`: instead of `--geojson`, a single zone named `extent`;
- `--maxzoom` (required): zoom for zones without a `maxzoom` property;
- `--same-zoom`: use `--maxzoom` for every zone.

### Common options

Both take `--output-dir`, `--pmtiles-bin`, `--threads`, `--index` and `--dry-run` (list what would be extracted, nothing is downloaded). Write `--extent=-1.5,...` when the value starts with a minus sign.

Each prints the paths it produced. Exit code 1 when a zone has no coverage or pmtiles fails, 2 on invalid input.

### Example: the French Alps

[`examples/alpes.geojson`](examples/alpes.geojson) is a rough polygon of the French Alps, named `alpes`, with `maxzoom: 16`. Check what it will download first:

```console
$ uv run mapterhorn-extract base --dry-run
base france z0-12: planet.pmtiles
$ uv run mapterhorn-extract zones --geojson examples/alpes.geojson --maxzoom 15 --dry-run
zone alpes z13-16: 6-32-22.pmtiles, 6-32-23.pmtiles, 6-33-22.pmtiles, 6-33-23.pmtiles
```

The zone keeps its own `maxzoom` (16); `--maxzoom 15` only applies to zones without one. Force 15 everywhere with `--same-zoom`. Then download:

```bash
uv run mapterhorn-extract base --output-dir out/ --pmtiles-bin ./pmtiles
uv run mapterhorn-extract zones --geojson examples/alpes.geojson --maxzoom 15 \
  --output-dir out/ --pmtiles-bin ./pmtiles
```

```
out/france_z0-12_<key>.pmtiles
out/alpes_z13-16_<key>.pmtiles
```

A zone this size at z16 is a large download: try a lower `maxzoom` first. In QGIS, load `examples/alpes.geojson` as a layer and run the zones algorithm with `name` and `maxzoom` as the name and max zoom fields; run the base algorithm with an empty extent for France.

## Library

```python
from mapterhorn_extract import extract_base, extract_zone, load_index, zones_from_geojson

archives = load_index()
zones = zones_from_geojson("examples/alpes.geojson", default_maxzoom=15, work_dir="work")
extract_base("out", archives=archives, binary="./pmtiles")  # France; or bbox=... / region=...
for zone in zones:
    extract_zone(zone, "out", archives=archives, binary="./pmtiles")
```

Lower-level pieces, for one task per archive in an orchestrator such as Airflow:

- `plan_zone(zone, archives) -> list[Job]`: one job per Mapterhorn archive the zone touches; `Job.to_dict()` / `Job.from_dict()` serialize it;
- `extract_one(job, output_dir) -> Path`: one `pmtiles extract`;
- `merge(paths, output) -> Path`: one `pmtiles merge` of a zone's extracts;
- `base_job(region=None, bbox=None, archives=None) -> Job`: the z0 to 12 job, France when neither is given (`FRANCE_EXTENT`).

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
