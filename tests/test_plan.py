import json

import pytest

from mapterhorn_extract.extract import Job, plan, plan_base

LYON = (4.80, 45.70, 4.90, 45.80)
PARIS = (2.25, 48.80, 2.45, 48.95)
CHAMONIX = (6.80, 45.85, 6.95, 45.95)
OCEAN = (-30.0, 40.0, -29.0, 41.0)
EDGE = (-1.0, 46.0, 0.0, 46.5)
LYON_RING = [[4.8, 45.7], [4.9, 45.7], [4.9, 45.8], [4.8, 45.7]]


def test_single_archive(archives):
    [job] = plan(LYON, 15, archives=archives)
    assert job.name == "6-32-22.pmtiles"
    assert job.url == "https://download.mapterhorn.com/6-32-22.pmtiles"
    assert (job.minzoom, job.maxzoom) == (13, 15)
    assert job.bbox == LYON
    assert job.region is None


def test_area_across_archives(archives):
    assert [j.name for j in plan(PARIS, 15, archives=archives)] == ["6-32-21.pmtiles", "6-32-22.pmtiles"]


def test_planet_is_never_planned(archives):
    names = {j.name for bbox in (LYON, PARIS, CHAMONIX, EDGE) for j in plan(bbox, 15, archives=archives)}
    assert "planet.pmtiles" not in names


def test_maxzoom_is_clamped_per_archive(archives):
    assert plan(LYON, 20, archives=archives)[0].maxzoom == 17
    assert plan(CHAMONIX, 20, archives=archives)[0].maxzoom == 18


def test_maxzoom_below_13_is_rejected(archives):
    with pytest.raises(ValueError, match=">= 13"):
        plan(LYON, 12, archives=archives)


def test_area_without_coverage_gives_no_job(archives):
    assert plan(OCEAN, 15, archives=archives) == []


def test_touching_edge_does_not_select_neighbour(archives):
    assert [j.name for j in plan(EDGE, 15, archives=archives)] == ["6-31-22.pmtiles"]


def test_region_is_stored_absolute(archives, region_file, monkeypatch, tmp_path):
    region_file(LYON_RING)
    monkeypatch.chdir(tmp_path)
    [job] = plan(LYON, 15, region="area.geojson", archives=archives)
    assert job.region == str(tmp_path / "area.geojson")


def test_output_name(archives):
    [job] = plan(LYON, 15, archives=archives)
    assert job.output_name == f"6-32-22_z13-15_{job.area_key}.pmtiles"
    assert len(job.area_key) == 8


def test_different_region_gives_different_output_name(archives, region_file):
    first = region_file(LYON_RING, "a.geojson")
    second = region_file([[4.8, 45.7], [4.85, 45.7], [4.85, 45.75], [4.8, 45.7]], "b.geojson")
    [a] = plan(LYON, 15, region=first, archives=archives)
    [b] = plan(LYON, 15, region=second, archives=archives)
    [c] = plan((4.80, 45.70, 4.85, 45.75), 15, archives=archives)
    assert len({a.output_name, b.output_name, c.output_name}) == 3


def test_job_round_trips_through_json(archives):
    [job] = plan(LYON, 15, archives=archives)
    assert Job.from_dict(json.loads(json.dumps(job.to_dict()))) == job


def test_plan_base_targets_planet(archives):
    job = plan_base(LYON, archives=archives)
    assert job.name == "planet.pmtiles"
    assert (job.minzoom, job.maxzoom) == (0, 12)
    assert job.output_name.startswith("planet_z0-12_")


def test_plan_base_without_planet_is_none(archives):
    assert plan_base(LYON, archives=[a for a in archives if a.name != "planet.pmtiles"]) is None


def test_archives_are_selected_per_polygon_part(archives, tmp_path):
    chamonix = [[6.80, 45.85], [6.95, 45.85], [6.95, 45.95], [6.80, 45.85]]
    reims = [[4.00, 49.20], [4.10, 49.20], [4.10, 49.30], [4.00, 49.20]]
    region = tmp_path / "two_parts.geojson"
    region.write_text(json.dumps({"type": "MultiPolygon", "coordinates": [[chamonix], [reims]]}))
    jobs = plan((4.00, 45.85, 6.95, 49.30), 15, region=region, archives=archives)
    assert [j.name for j in jobs] == ["6-32-21.pmtiles", "6-33-22.pmtiles"]


def test_plan_base_label_names_the_output(archives):
    job = plan_base(LYON, archives=archives, label="france")
    assert job.output_name.startswith("france_z0-12_")
    assert Job.from_dict(json.loads(json.dumps(job.to_dict()))) == job
