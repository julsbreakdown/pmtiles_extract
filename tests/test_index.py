from mapterhorn_extract.index import INDEX_URL, load_index


def test_load_index_parses_archives(archives):
    by_name = {a.name: a for a in archives}
    assert len(archives) == 6
    alps = by_name["6-33-22.pmtiles"]
    assert alps.url == "https://download.mapterhorn.com/6-33-22.pmtiles"
    assert (alps.min_zoom, alps.max_zoom) == (13, 18)
    assert alps.bbox == (5.625, 45.089035564831015, 11.25, 48.92249926375824)


def test_load_index_keeps_planet(archives):
    planet = next(a for a in archives if a.name == "planet.pmtiles")
    assert (planet.min_zoom, planet.max_zoom) == (0, 12)


def test_index_url():
    assert INDEX_URL == "https://download.mapterhorn.com/download_urls.json"


def test_remote_index_is_fetched_with_explicit_user_agent(monkeypatch):
    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'{"items": []}'

    def fake_urlopen(request, timeout):
        seen["user_agent"] = request.get_header("User-agent")
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert load_index("https://example.test/download_urls.json") == []
    assert seen["user_agent"].startswith("mapterhorn-extract/")
