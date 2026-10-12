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
    area.add_argument("--extent", help="min_lon,min_lat,max_lon,max_lat (passed to pmtiles --bbox); write --extent=-1,... when it starts with a minus")
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
