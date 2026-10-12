import json
import sys
from pathlib import Path

import pytest

from mapterhorn_extract.index import load_index

FIXTURES = Path(__file__).parent / "fixtures"

FAKE_PMTILES = """\
import json, os, sys, time
args = sys.argv[1:]
mode = os.environ.get("FAKE_PMTILES_MODE", "ok")
if mode == "slow":
    time.sleep(30)
with open(args[-1] if args[0] == "merge" else args[2], "w") as out:
    json.dump(args, out)
if mode == "fail":
    print("boom", file=sys.stderr)
    sys.exit(1)
"""


@pytest.fixture
def index_path():
    return FIXTURES / "index.json"


@pytest.fixture
def archives(index_path):
    return load_index(index_path)


@pytest.fixture
def fake_pmtiles(tmp_path):
    path = tmp_path / "bin" / "pmtiles"
    path.parent.mkdir()
    path.write_text(f"#!{sys.executable}\n{FAKE_PMTILES}")
    path.chmod(0o755)
    return path


@pytest.fixture
def region_file(tmp_path):
    def write(ring, name="area.geojson"):
        path = tmp_path / name
        geometry = {"type": "Polygon", "coordinates": [ring]}
        feature = {"type": "Feature", "properties": {}, "geometry": geometry}
        path.write_text(json.dumps({"type": "FeatureCollection", "features": [feature]}))
        return path

    return write
