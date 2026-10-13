import json
import os
from pathlib import Path

import pytest

from mapterhorn_extract.zones import FRANCE_EXTENT, Zone, extract_base, extract_zone, plan_zone, zones_from_geojson

LYON_RING = [[4.8, 45.7], [4.9, 45.7], [4.9, 45.8], [4.8, 45.7]]
CROSS_RING = [[5.60, 45.70], [5.65, 45.70], [5.65, 45.72], [5.60, 45.70]]
OCEAN_RING = [[-30, 40], [-29, 40], [-29, 41], [-30, 40]]


def _feature(ring, **properties):
    return {"type": "Feature", "properties": properties, "geometry": {"type": "Polygon", "coordinates": [ring]}}


def _zones_file(tmp_path, *features):
    path = tmp_path / "zones.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": list(features)}))
    return path


def _zone(tmp_path, ring, name="zone", maxzoom=14, minzoom=13):
    region = tmp_path / f"{name}.geojson"
    region.write_text(json.dumps({"type": "FeatureCollection", "features": [_feature(ring)]}))
    return Zone(name=name, maxzoom=maxzoom, region=region, minzoom=minzoom)


def test_zones_take_name_and_zoom_from_properties(tmp_path):
    path = _zones_file(tmp_path, _feature(LYON_RING, name="Lyon centre", maxzoom=16), _feature(CROSS_RING))
    zones = zones_from_geojson(path, 14, tmp_path / "work")
    assert [(z.name, z.maxzoom) for z in zones] == [("Lyon_centre", 16), ("zone_2", 14)]
    assert len(json.loads(zones[0].region.read_text())["features"]) == 1


def test_same_zoom_overrides_zone_zoom(tmp_path):
    path = _zones_file(tmp_path, _feature(LYON_RING, maxzoom=16), _feature(CROSS_RING, maxzoom=None))
    zones = zones_from_geojson(path, 15, tmp_path / "work", same_zoom=True)
    assert [z.maxzoom for z in zones] == [15, 15]


def test_zone_zoom_below_minzoom_is_rejected(tmp_path):
    path = _zones_file(tmp_path, _feature(LYON_RING, name="low", maxzoom=12))
    with pytest.raises(ValueError, match="low.*below minzoom 13"):
        zones_from_geojson(path, 14, tmp_path / "work")


def test_default_zoom_below_minzoom_is_rejected_even_if_unused(tmp_path):
    path = _zones_file(tmp_path, _feature(LYON_RING, maxzoom=16))
    with pytest.raises(ValueError, match="maxzoom 1 is below minzoom 13"):
        zones_from_geojson(path, 1, tmp_path / "work")


def test_minzoom_applies_to_every_zone(tmp_path):
    path = _zones_file(tmp_path, _feature(LYON_RING, maxzoom=12))
    [zone] = zones_from_geojson(path, 14, tmp_path / "work", minzoom=10)
    assert (zone.minzoom, zone.maxzoom) == (10, 12)


def test_minzoom_below_13_adds_planet_job(archives, tmp_path):
    zone = _zone(tmp_path, LYON_RING, minzoom=10, maxzoom=14)
    assert [(j.name, j.minzoom, j.maxzoom) for j in plan_zone(zone, archives)] == [
        ("planet.pmtiles", 10, 12),
        ("6-32-22.pmtiles", 13, 14),
    ]


def test_maxzoom_up_to_12_uses_planet_only(archives, tmp_path):
    zone = _zone(tmp_path, LYON_RING, minzoom=5, maxzoom=8)
    assert [(j.name, j.minzoom, j.maxzoom) for j in plan_zone(zone, archives)] == [("planet.pmtiles", 5, 8)]


def test_extract_zone_merges_planet_and_high_zooms(archives, fake_pmtiles, tmp_path):
    zone = _zone(tmp_path, LYON_RING, name="lyon", minzoom=10, maxzoom=14)
    out = extract_zone(zone, tmp_path / "out", archives=archives, binary=str(fake_pmtiles))
    assert out.name.startswith("lyon_z10-14_")
    args = json.loads(out.read_text())
    assert args[0] == "merge" and len(args) == 4


def test_duplicate_zone_names_are_rejected(tmp_path):
    path = _zones_file(tmp_path, _feature(LYON_RING, name="a"), _feature(CROSS_RING, name="a"))
    with pytest.raises(ValueError, match="duplicate"):
        zones_from_geojson(path, 14, tmp_path / "work")


def test_non_polygon_features_are_ignored(tmp_path):
    point = {"type": "Feature", "properties": {"name": "pt"}, "geometry": {"type": "Point", "coordinates": [4.8, 45.7]}}
    path = _zones_file(tmp_path, point, _feature(LYON_RING, name="lyon"))
    zones = zones_from_geojson(path, 14, tmp_path / "work")
    assert [z.name for z in zones] == ["lyon"]


def test_file_without_polygon_is_rejected(tmp_path):
    path = _zones_file(tmp_path)
    with pytest.raises(ValueError, match="Polygon"):
        zones_from_geojson(path, 14, tmp_path / "work")


def test_base_defaults_to_france(archives, fake_pmtiles, tmp_path):
    out = extract_base(tmp_path / "out", archives=archives, binary=str(fake_pmtiles))
    assert out.name.startswith("france_z0-12_")
    args = json.loads(out.read_text())
    assert {"--minzoom=0", "--maxzoom=12", "--bbox=-5.15,42.33,8.23,51.1"} <= set(args)
    assert FRANCE_EXTENT == (-5.15, 42.33, 8.23, 51.10)


def test_base_extent_can_be_overridden(archives, fake_pmtiles, tmp_path):
    out = extract_base(tmp_path / "out", bbox=(4.8, 45.7, 4.9, 45.8), archives=archives, binary=str(fake_pmtiles))
    assert out.name.startswith("base_z0-12_")
    assert "--bbox=4.8,45.7,4.9,45.8" in json.loads(out.read_text())


def test_base_region_can_be_a_polygon(archives, fake_pmtiles, tmp_path):
    zone = _zone(tmp_path, LYON_RING)
    out = extract_base(tmp_path / "out", region=zone.region, archives=archives, binary=str(fake_pmtiles))
    assert out.name.startswith("base_z0-12_")
    assert f"--region={zone.region.resolve()}" in json.loads(out.read_text())


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


def test_extract_zone_without_coverage_raises(archives, fake_pmtiles, tmp_path):
    zone = _zone(tmp_path, OCEAN_RING, name="sea")
    with pytest.raises(ValueError, match="sea"):
        extract_zone(zone, tmp_path / "out", archives=archives, binary=str(fake_pmtiles))


@pytest.mark.skipif(not os.environ.get("MAPTERHORN_LIVE_PMTILES"), reason="set MAPTERHORN_LIVE_PMTILES to a pmtiles binary")
def test_live_zone_across_archives(tmp_path):
    binary = os.environ["MAPTERHORN_LIVE_PMTILES"]
    ring = [[5.620, 45.700], [5.630, 45.700], [5.630, 45.705], [5.620, 45.700]]
    zone = _zone(tmp_path, ring, name="live", maxzoom=13)
    out = extract_zone(zone, tmp_path / "out", binary=binary, threads=4)
    assert out.stat().st_size > 0
    assert sorted(p.name for p in Path(tmp_path / "out").iterdir()) == [out.name]
