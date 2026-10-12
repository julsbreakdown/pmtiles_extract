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
    assert main(["--extent=-30,40,-29,41", "--maxzoom", "15", "--index", str(index_path)]) == 1
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
