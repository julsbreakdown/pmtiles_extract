import json
import os
from pathlib import Path

import pytest

from mapterhorn_extract.zones import Zone, extract_base, extract_zone, zones_from_geojson

LYON_RING = [[4.8, 45.7], [4.9, 45.7], [4.9, 45.8], [4.8, 45.7]]
CROSS_RING = [[5.60, 45.70], [5.65, 45.70], [5.65, 45.72], [5.60, 45.70]]
OCEAN_RING = [[-30, 40], [-29, 40], [-29, 41], [-30, 40]]


def _feature(ring, **properties):
    return {"type": "Feature", "properties": properties, "geometry": {"type": "Polygon", "coordinates": [ring]}}


def _zones_file(tmp_path, *features):
    path = tmp_path / "zones.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": list(features)}))
    return path


def _zone(tmp_path, ring, name="zone", maxzoom=14):
    region = tmp_path / f"{name}.geojson"
    region.write_text(json.dumps({"type": "FeatureCollection", "features": [_feature(ring)]}))
    return Zone(name=name, maxzoom=maxzoom, region=region)


def test_zones_take_name_and_zoom_from_properties(tmp_path):
    path = _zones_file(tmp_path, _feature(LYON_RING, name="Lyon centre", maxzoom=16), _feature(CROSS_RING))
    all_zones, zones = zones_from_geojson(path, 14, tmp_path / "work")
    assert [(z.name, z.maxzoom) for z in zones] == [("Lyon_centre", 16), ("zone_2", 14)]
    assert len(json.loads(all_zones.read_text())["features"]) == 2
    assert len(json.loads(zones[0].region.read_text())["features"]) == 1


def test_same_zoom_overrides_zone_zoom(tmp_path):
    path = _zones_file(tmp_path, _feature(LYON_RING, maxzoom=16), _feature(CROSS_RING, maxzoom=None))
    _, zones = zones_from_geojson(path, 15, tmp_path / "work", same_zoom=True)
    assert [z.maxzoom for z in zones] == [15, 15]


def test_zone_zoom_below_13_is_rejected(tmp_path):
    path = _zones_file(tmp_path, _feature(LYON_RING, name="low", maxzoom=12))
    with pytest.raises(ValueError, match="low.*below 13"):
        zones_from_geojson(path, 14, tmp_path / "work")


def test_duplicate_zone_names_are_rejected(tmp_path):
    path = _zones_file(tmp_path, _feature(LYON_RING, name="a"), _feature(CROSS_RING, name="a"))
    with pytest.raises(ValueError, match="duplicate"):
        zones_from_geojson(path, 14, tmp_path / "work")


def test_non_polygon_features_are_ignored(tmp_path):
    point = {"type": "Feature", "properties": {"name": "pt"}, "geometry": {"type": "Point", "coordinates": [4.8, 45.7]}}
    path = _zones_file(tmp_path, point, _feature(LYON_RING, name="lyon"))
    _, zones = zones_from_geojson(path, 14, tmp_path / "work")
    assert [z.name for z in zones] == ["lyon"]


def test_file_without_polygon_is_rejected(tmp_path):
    path = _zones_file(tmp_path)
    with pytest.raises(ValueError, match="Polygon"):
        zones_from_geojson(path, 14, tmp_path / "work")


def test_extract_base_covers_z0_to_12(archives, fake_pmtiles, tmp_path):
    zone = _zone(tmp_path, LYON_RING)
    out = extract_base(zone.region, tmp_path / "out", archives=archives, binary=str(fake_pmtiles))
    assert out.name.startswith("planet_z0-12_")
    args = json.loads(out.read_text())
    assert {"--minzoom=0", "--maxzoom=12"} <= set(args)


def test_extract_zone_across_archives_merges_and_cleans_parts(archives, fake_pmtiles, tmp_path):
    zone = _zone(tmp_path, CROSS_RING, name="cross", maxzoom=18)
    out = extract_zone(zone, tmp_path / "out", archives=archives, binary=str(fake_pmtiles))
    assert out.name.startswith("cross_z13-18_")
    args = json.loads(out.read_text())
    assert args[0] == "merge" and len(args) == 4
    assert os.listdir(tmp_path / "out") == [out.name]


def test_extract_zone_skips_existing_output(archives, fake_pmtiles, tmp_path, monkeypatch):
    zone = _zone(tmp_path, LYON_RING, name="lyon")
    first = extract_zone(zone, tmp_path / "out", archives=archives, binary=str(fake_pmtiles))
    monkeypatch.setenv("FAKE_PMTILES_MODE", "fail")
    assert extract_zone(zone, tmp_path / "out", archives=archives, binary=str(fake_pmtiles)) == first


def test_extract_zone_without_coverage_is_none(archives, fake_pmtiles, tmp_path):
    zone = _zone(tmp_path, OCEAN_RING, name="sea")
    assert extract_zone(zone, tmp_path / "out", archives=archives, binary=str(fake_pmtiles)) is None


@pytest.mark.skipif(not os.environ.get("MAPTERHORN_LIVE_PMTILES"), reason="set MAPTERHORN_LIVE_PMTILES to a pmtiles binary")
def test_live_zone_across_archives(tmp_path):
    binary = os.environ["MAPTERHORN_LIVE_PMTILES"]
    ring = [[5.620, 45.700], [5.630, 45.700], [5.630, 45.705], [5.620, 45.700]]
    zone = _zone(tmp_path, ring, name="live", maxzoom=13)
    out = extract_zone(zone, tmp_path / "out", binary=binary, threads=4)
    assert out is not None and out.stat().st_size > 0
    assert sorted(p.name for p in Path(tmp_path / "out").iterdir()) == [out.name]
