from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
from pathlib import Path

from . import (
    INDEX_URL,
    ExtractError,
    PmtilesNotFound,
    bbox_from_geojson,
    extract_base,
    extract_zone,
    load_index,
    parse_extent,
    plan,
    plan_base,
    zones_from_geojson,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mapterhorn-extract",
        description="Extract a Mapterhorn z0-12 base file and one z13+ file per zone.",
    )
    area = parser.add_mutually_exclusive_group(required=True)
    area.add_argument(
        "--geojson", type=Path, help="EPSG:4326 polygon zones, optional properties: name, maxzoom"
    )
    area.add_argument(
        "--extent",
        help="min_lon,min_lat,max_lon,max_lat as one zone; write --extent=-1,... when it starts with a minus",
    )
    parser.add_argument("--maxzoom", type=int, required=True, help="zoom for zones without maxzoom, >= 13")
    parser.add_argument("--same-zoom", action="store_true", help="use --maxzoom for every zone")
    parser.add_argument("--output-dir", type=Path, default=Path("."))
    parser.add_argument("--pmtiles-bin", help="pmtiles binary (default: pmtiles on PATH)")
    parser.add_argument("--threads", type=int, default=16, help="pmtiles --download-threads")
    parser.add_argument("--index", default=INDEX_URL, help="Mapterhorn download_urls.json URL or path")
    parser.add_argument("--dry-run", action="store_true", help="list what would be extracted")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    with tempfile.TemporaryDirectory() as work:
        work_dir = Path(work)
        try:
            zones_path = args.geojson or _extent_zone(parse_extent(args.extent), work_dir / "extent.geojson")
            all_zones, zones = zones_from_geojson(zones_path, args.maxzoom, work_dir, same_zoom=args.same_zoom)
            archives = load_index(args.index)
        except (ValueError, OSError) as error:
            parser.error(str(error))
        if args.dry_run:
            return _dry_run(all_zones, zones, archives)
        try:
            return _extract(all_zones, zones, archives, args)
        except (PmtilesNotFound, ExtractError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 1


def _extent_zone(bbox, path: Path) -> Path:
    min_lon, min_lat, max_lon, max_lat = bbox
    ring = [[min_lon, min_lat], [max_lon, min_lat], [max_lon, max_lat], [min_lon, max_lat], [min_lon, min_lat]]
    feature = {"type": "Feature", "properties": {"name": "extent"}, "geometry": {"type": "Polygon", "coordinates": [ring]}}
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [feature]}), encoding="utf-8")
    return path


def _dry_run(all_zones, zones, archives) -> int:
    code = 0
    base = plan_base(bbox_from_geojson(all_zones), region=all_zones, archives=archives)
    if base is not None:
        print(f"base {base.name} z{base.minzoom}-{base.maxzoom}")
    for zone in zones:
        jobs = plan(bbox_from_geojson(zone.region), zone.maxzoom, region=zone.region, archives=archives)
        if not jobs:
            print(f"zone {zone.name}: no Mapterhorn archive above zoom 12", file=sys.stderr)
            code = 1
            continue
        maxzoom = max(job.maxzoom for job in jobs)
        print(f"zone {zone.name} z13-{maxzoom}: {', '.join(job.name for job in jobs)}")
    return code


def _extract(all_zones, zones, archives, args) -> int:
    code = 0
    options = {"archives": archives, "binary": args.pmtiles_bin, "threads": args.threads}
    base = extract_base(all_zones, args.output_dir, **options)
    if base is not None:
        print(base)
    for zone in zones:
        output = extract_zone(zone, args.output_dir, **options)
        if output is None:
            print(f"zone {zone.name}: no Mapterhorn archive above zoom 12", file=sys.stderr)
            code = 1
            continue
        print(output)
    return code


if __name__ == "__main__":
    sys.exit(main())
