import json

import pytest

from mapterhorn_extract.area import bbox_from_geojson, parse_extent


def test_parse_extent():
    assert parse_extent("4.8,45.7,4.9,45.8") == (4.8, 45.7, 4.9, 45.8)


@pytest.mark.parametrize("text", ["4.8,45.7,4.9", "a,b,c,d", "4.9,45.7,4.8,45.8", "4.8,45.7,190,45.8"])
def test_parse_extent_rejects_invalid(text):
    with pytest.raises(ValueError):
        parse_extent(text)


def test_bbox_from_geojson_unions_polygons(tmp_path):
    path = tmp_path / "area.geojson"
    path.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {}, "geometry": {
                "type": "Polygon",
                "coordinates": [[[4.8, 45.7], [4.9, 45.7], [4.9, 45.8], [4.8, 45.7]]]}},
            {"type": "Feature", "properties": {}, "geometry": {
                "type": "MultiPolygon",
                "coordinates": [[[[6.8, 45.85], [6.95, 45.85], [6.95, 45.95], [6.8, 45.85]]]]}},
            {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [0.0, 0.0]}},
        ],
    }))
    assert bbox_from_geojson(path) == (4.8, 45.7, 6.95, 45.95)


def test_bbox_from_bare_geometry(tmp_path):
    path = tmp_path / "area.geojson"
    path.write_text(json.dumps({
        "type": "Polygon", "coordinates": [[[4.8, 45.7], [4.9, 45.7], [4.9, 45.8], [4.8, 45.7]]]}))
    assert bbox_from_geojson(path) == (4.8, 45.7, 4.9, 45.8)


def test_projected_coordinates_are_rejected(tmp_path):
    path = tmp_path / "lambert93.geojson"
    path.write_text(json.dumps({
        "type": "Polygon",
        "coordinates": [[[842000, 6519000], [843000, 6519000], [843000, 6520000], [842000, 6519000]]]}))
    with pytest.raises(ValueError, match="EPSG:4326"):
        bbox_from_geojson(path)


def test_geojson_without_polygon_is_rejected(tmp_path):
    path = tmp_path / "points.geojson"
    path.write_text(json.dumps({"type": "Point", "coordinates": [4.8, 45.7]}))
    with pytest.raises(ValueError, match="Polygon"):
        bbox_from_geojson(path)
