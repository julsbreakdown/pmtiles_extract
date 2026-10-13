import json
import time

import pytest

from mapterhorn_extract import ExtractCancelled, ExtractError, PmtilesNotFound, extract_one, merge
from mapterhorn_extract.extract import _plan as plan
from mapterhorn_extract.extract import _plan_base
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


def _inputs(tmp_path, count):
    paths = []
    for n in range(count):
        path = tmp_path / f"in{n}.pmtiles"
        path.write_text(f"tiles {n}")
        paths.append(path)
    return paths


def test_merge_runs_pmtiles_merge(fake_pmtiles, tmp_path):
    inputs = _inputs(tmp_path, 2)
    out = merge(inputs, tmp_path / "zone.pmtiles", binary=str(fake_pmtiles))
    args = json.loads(out.read_text())
    assert args[0] == "merge"
    assert args[1:3] == [str(p) for p in inputs]
    assert all(p.exists() for p in inputs)


def test_merge_single_input_is_moved(fake_pmtiles, tmp_path):
    [single] = _inputs(tmp_path, 1)
    out = merge([single], tmp_path / "zone.pmtiles", binary=str(fake_pmtiles))
    assert out.read_text() == "tiles 0"
    assert not single.exists()


def test_merge_skips_existing_output(fake_pmtiles, tmp_path, monkeypatch):
    inputs = _inputs(tmp_path, 2)
    first = merge(inputs, tmp_path / "zone.pmtiles", binary=str(fake_pmtiles))
    monkeypatch.setenv("FAKE_PMTILES_MODE", "fail")
    assert merge(inputs, tmp_path / "zone.pmtiles", binary=str(fake_pmtiles)) == first


def test_failed_merge_leaves_no_file(fake_pmtiles, tmp_path, monkeypatch):
    inputs = _inputs(tmp_path, 2)
    monkeypatch.setenv("FAKE_PMTILES_MODE", "fail")
    with pytest.raises(ExtractError, match="boom"):
        merge(inputs, tmp_path / "out" / "zone.pmtiles", binary=str(fake_pmtiles))
    assert list((tmp_path / "out").iterdir()) == []


def test_extract_log_names_the_archive_kind(archives, fake_pmtiles, tmp_path, caplog):
    caplog.set_level("INFO")
    extract_one(_plan_base(LYON, archives=archives, minzoom=10, maxzoom=12), tmp_path, binary=str(fake_pmtiles))
    extract_one(_job(archives), tmp_path, binary=str(fake_pmtiles))
    assert "extracting planet.pmtiles z10-12 (global archive, zooms 0-12 only)" in caplog.text
    assert "extracting 6-32-22.pmtiles z13-14 (high-resolution archive, zoom-6 tile 32/22)" in caplog.text
