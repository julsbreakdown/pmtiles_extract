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
    base_job,
    extract_base,
    extract_zone,
    load_index,
    parse_extent,
    plan_zone,
    zones_from_geojson,
)

EXTENT_HELP = "min_lon,min_lat,max_lon,max_lat; write --extent=-1,... when it starts with a minus"


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--output-dir", type=Path, default=Path("."))
    common.add_argument("--pmtiles-bin", help="pmtiles binary (default: pmtiles on PATH)")
    common.add_argument("--threads", type=int, default=16, help="pmtiles --download-threads")
    common.add_argument("--index", default=INDEX_URL, help="Mapterhorn download_urls.json URL or path")
    common.add_argument("--dry-run", action="store_true", help="list what would be extracted")

    parser = argparse.ArgumentParser(prog="mapterhorn-extract", description="Extract Mapterhorn terrain as PMTiles.")
    commands = parser.add_subparsers(dest="command", required=True)

    base = commands.add_parser("base", parents=[common], help="z0-12 file, France by default")
    base_area = base.add_mutually_exclusive_group()
    base_area.add_argument("--geojson", type=Path, help="EPSG:4326 polygon to cut instead of France")
    base_area.add_argument("--extent", help=EXTENT_HELP)

    zones = commands.add_parser("zones", parents=[common], help="one z13+ file per zone")
    zones_area = zones.add_mutually_exclusive_group(required=True)
    zones_area.add_argument("--geojson", type=Path, help="EPSG:4326 polygon zones, optional properties: name, maxzoom")
    zones_area.add_argument("--extent", help=EXTENT_HELP + "; a single zone named extent")
    zones.add_argument("--minzoom", type=int, default=13, help="first zoom of every zone file (default 13); below 13 comes from planet")
    zones.add_argument("--maxzoom", type=int, required=True, help="zoom for zones without maxzoom, >= --minzoom")
    zones.add_argument("--same-zoom", action="store_true", help="use --maxzoom for every zone")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    with tempfile.TemporaryDirectory() as work:
        try:
            if args.command == "base":
                return _base(args)
            return _zones(args, Path(work))
        except (ValueError, OSError) as error:
            parser.error(str(error))
        except (PmtilesNotFound, ExtractError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 1


def _base(args) -> int:
    area = {"region": args.geojson, "bbox": parse_extent(args.extent) if args.extent else None}
    archives = load_index(args.index)
    if args.dry_run:
        job = base_job(archives=archives, **area)
        print(f"base {job.label} z{job.minzoom}-{job.maxzoom}: {job.name}")
        return 0
    print(extract_base(args.output_dir, archives=archives, binary=args.pmtiles_bin, threads=args.threads, **area))
    return 0


def _zones(args, work_dir: Path) -> int:
    zones_path = args.geojson or _extent_zone(parse_extent(args.extent), work_dir / "extent.geojson")
    zones = zones_from_geojson(zones_path, args.maxzoom, work_dir, same_zoom=args.same_zoom, minzoom=args.minzoom)
    archives = load_index(args.index)
    covered = _covered_zones(zones, archives)
    if not covered:
        return 1
    for zone, jobs in covered:
        minzoom = min(job.minzoom for job in jobs)
        maxzoom = max(job.maxzoom for job in jobs)
        plan = f"zone {zone.name} z{minzoom}-{maxzoom}: {', '.join(job.name for job in jobs)}"
        if args.dry_run:
            print(plan)
        else:
            print(plan, file=sys.stderr)
            print(extract_zone(zone, args.output_dir, archives=archives, binary=args.pmtiles_bin, threads=args.threads))
    return 0 if len(covered) == len(zones) else 1


def _extent_zone(bbox, path: Path) -> Path:
    min_lon, min_lat, max_lon, max_lat = bbox
    ring = [[min_lon, min_lat], [max_lon, min_lat], [max_lon, max_lat], [min_lon, max_lat], [min_lon, min_lat]]
    feature = {"type": "Feature", "properties": {"name": "extent"}, "geometry": {"type": "Polygon", "coordinates": [ring]}}
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [feature]}), encoding="utf-8")
    return path


def _covered_zones(zones, archives):
    covered = []
    for zone in zones:
        jobs = plan_zone(zone, archives)
        if jobs:
            covered.append((zone, jobs))
        else:
            print(f"zone {zone.name}: no Mapterhorn archive above zoom 12", file=sys.stderr)
    return covered


if __name__ == "__main__":
    sys.exit(main())
