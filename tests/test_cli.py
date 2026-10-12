import json
from pathlib import Path

import pytest

from mapterhorn_extract.__main__ import main

LYON_RING = [[4.8, 45.7], [4.9, 45.7], [4.9, 45.8], [4.8, 45.7]]
CROSS_RING = [[5.60, 45.70], [5.65, 45.70], [5.65, 45.72], [5.60, 45.70]]


def _zones(tmp_path, *zones):
    features = [
        {"type": "Feature", "properties": props, "geometry": {"type": "Polygon", "coordinates": [ring]}}
        for ring, props in zones
    ]
    path = tmp_path / "zones.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    return path


def test_zones_dry_run_lists_zones_only(index_path, tmp_path, capsys):
    zones = _zones(tmp_path, (LYON_RING, {"name": "lyon", "maxzoom": 16}), (CROSS_RING, {}))
    code = main(["zones", "--geojson", str(zones), "--maxzoom", "14", "--index", str(index_path), "--dry-run"])
    assert code == 0
    assert capsys.readouterr().out.splitlines() == [
        "zone lyon z13-16: 6-32-22.pmtiles",
        "zone zone_2 z13-14: 6-32-22.pmtiles, 6-33-22.pmtiles",
    ]


def test_same_zoom_applies_default_to_every_zone(index_path, tmp_path, capsys):
    zones = _zones(tmp_path, (LYON_RING, {"name": "lyon", "maxzoom": 16}), (CROSS_RING, {"maxzoom": 13}))
    main(["zones", "--geojson", str(zones), "--maxzoom", "15", "--same-zoom", "--index", str(index_path), "--dry-run"])
    lines = capsys.readouterr().out.splitlines()
    assert [line.split(":")[0] for line in lines] == ["zone lyon z13-15", "zone zone_2 z13-15"]


def test_extent_is_one_zone(index_path, capsys):
    main(["zones", "--extent", "2.25,48.80,2.45,48.95", "--maxzoom", "15", "--index", str(index_path), "--dry-run"])
    assert capsys.readouterr().out.splitlines() == ["zone extent z13-15: 6-32-21.pmtiles, 6-32-22.pmtiles"]


def test_zone_without_coverage_exits_1(index_path, capsys):
    assert main(["zones", "--extent=-30,40,-29,41", "--maxzoom", "15", "--index", str(index_path), "--dry-run"]) == 1
    assert "zone extent: no Mapterhorn archive above zoom 12" in capsys.readouterr().err


def test_zones_need_an_area(index_path):
    with pytest.raises(SystemExit) as exc:
        main(["zones", "--maxzoom", "15", "--index", str(index_path)])
    assert exc.value.code == 2


def test_geojson_and_extent_are_exclusive(tmp_path):
    with pytest.raises(SystemExit) as exc:
        main(["zones", "--geojson", str(tmp_path / "a.geojson"), "--extent", "1,2,3,4", "--maxzoom", "15"])
    assert exc.value.code == 2


def test_invalid_maxzoom_is_usage_error(index_path):
    with pytest.raises(SystemExit) as exc:
        main(["zones", "--extent", "4.8,45.7,4.9,45.8", "--maxzoom", "12", "--index", str(index_path)])
    assert exc.value.code == 2


def test_missing_geojson_is_usage_error(index_path, tmp_path):
    with pytest.raises(SystemExit) as exc:
        main(["zones", "--geojson", str(tmp_path / "missing.geojson"), "--maxzoom", "14", "--index", str(index_path)])
    assert exc.value.code == 2


def test_zones_need_maxzoom(index_path):
    with pytest.raises(SystemExit) as exc:
        main(["zones", "--extent", "4.8,45.7,4.9,45.8", "--index", str(index_path)])
    assert exc.value.code == 2


def test_extracts_zones_without_base(index_path, fake_pmtiles, tmp_path, capsys):
    zones = _zones(tmp_path, (LYON_RING, {"name": "lyon"}), (CROSS_RING, {"name": "cross"}))
    code = main([
        "zones", "--geojson", str(zones), "--maxzoom", "14", "--index", str(index_path),
        "--output-dir", str(tmp_path / "out"), "--pmtiles-bin", str(fake_pmtiles),
    ])
    printed = [Path(line) for line in capsys.readouterr().out.strip().splitlines()]
    assert code == 0
    assert [p.name.split("_z")[0] for p in printed] == ["lyon", "cross"]
    assert all(p.exists() for p in printed)
    assert not list((tmp_path / "out").glob("france_*"))


def test_extract_failure_exits_1(index_path, fake_pmtiles, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_PMTILES_MODE", "fail")
    code = main([
        "zones", "--extent", "4.8,45.7,4.9,45.8", "--maxzoom", "14", "--index", str(index_path),
        "--output-dir", str(tmp_path / "out"), "--pmtiles-bin", str(fake_pmtiles),
    ])
    assert code == 1
    assert "boom" in capsys.readouterr().err


def test_no_coverage_extracts_nothing(index_path, fake_pmtiles, tmp_path, capsys):
    code = main([
        "zones", "--extent=-30,40,-29,41", "--maxzoom", "15", "--index", str(index_path),
        "--output-dir", str(tmp_path / "out"), "--pmtiles-bin", str(fake_pmtiles),
    ])
    assert code == 1
    assert "no Mapterhorn archive above zoom 12" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_base_defaults_to_france(index_path, capsys):
    assert main(["base", "--index", str(index_path), "--dry-run"]) == 0
    assert capsys.readouterr().out.splitlines() == ["base france z0-12: planet.pmtiles"]


def test_base_extent_override(index_path, capsys):
    main(["base", "--extent", "4.8,45.7,4.9,45.8", "--index", str(index_path), "--dry-run"])
    assert capsys.readouterr().out.splitlines() == ["base base z0-12: planet.pmtiles"]


def test_base_geojson_override(index_path, region_file, capsys):
    region = region_file([[4.8, 45.7], [4.9, 45.7], [4.9, 45.8], [4.8, 45.7]])
    main(["base", "--geojson", str(region), "--index", str(index_path), "--dry-run"])
    assert capsys.readouterr().out.splitlines() == ["base base z0-12: planet.pmtiles"]


def test_extracts_base(index_path, fake_pmtiles, tmp_path, capsys):
    code = main([
        "base", "--index", str(index_path), "--output-dir", str(tmp_path / "out"), "--pmtiles-bin", str(fake_pmtiles),
    ])
    printed = Path(capsys.readouterr().out.strip())
    assert code == 0
    assert printed.name.startswith("france_z0-12_")
    assert printed.exists()


def test_command_is_required():
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2
