from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path

INDEX_URL = "https://download.mapterhorn.com/download_urls.json"
# download.mapterhorn.com answers 403 to the default Python-urllib User-Agent.
USER_AGENT = "mapterhorn-extract/0.1"


@dataclass(frozen=True)
class Archive:
    name: str
    url: str
    size: int
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float
    min_zoom: int
    max_zoom: int

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return (self.min_lon, self.min_lat, self.max_lon, self.max_lat)

    @classmethod
    def from_item(cls, item: dict) -> Archive:
        return cls(
            name=item["name"],
            url=item["url"],
            size=item["size"],
            min_lon=item["min_lon"],
            min_lat=item["min_lat"],
            max_lon=item["max_lon"],
            max_lat=item["max_lat"],
            min_zoom=item["min_zoom"],
            max_zoom=item["max_zoom"],
        )


def load_index(source: str | Path = INDEX_URL) -> list[Archive]:
    return [Archive.from_item(item) for item in json.loads(_read(str(source)))["items"]]


def _read(source: str) -> str:
    if source.startswith(("http://", "https://")):
        request = urllib.request.Request(source, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read().decode("utf-8")
    return Path(source).read_text(encoding="utf-8")
