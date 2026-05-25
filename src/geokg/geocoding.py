"""Geocoding utilities with overrides, cache, and review support."""

from __future__ import annotations

import csv
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib import parse, request
from urllib.error import HTTPError, URLError


@dataclass(slots=True)
class GeocodeRecord:
    query: str
    latitude: float | None
    longitude: float | None
    display_name: str | None
    source: str
    osm_type: str | None = None
    osm_category: str | None = None
    osm_addresstype: str | None = None
    raw_importance: float | None = None
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Geocoder:
    def __init__(
        self,
        *,
        overrides_path: Path,
        cache_path: Path,
        user_agent: str = "GeoKG/0.1",
        timeout_seconds: int = 30,
        min_delay_seconds: float = 1.1,
        max_retries: int = 2,
        allow_remote: bool = True,
    ) -> None:
        self._overrides = load_geocode_overrides(overrides_path)
        self._cache_path = cache_path
        self._cache = self._load_cache(cache_path)
        self._user_agent = user_agent
        self._timeout_seconds = timeout_seconds
        self._min_delay_seconds = min_delay_seconds
        self._max_retries = max_retries
        self._allow_remote = allow_remote
        self._last_remote_request_at = 0.0

    def geocode(self, query: str) -> GeocodeRecord:
        normalized_query = _normalize_query(query)
        if normalized_query in self._overrides:
            return self._overrides[normalized_query]
        if normalized_query in self._cache:
            return self._cache[normalized_query]

        if not self._allow_remote:
            return GeocodeRecord(
                query=query,
                latitude=None,
                longitude=None,
                display_name=None,
                source="missing",
                notes="Remote geocoding disabled.",
            )

        record = self._geocode_nominatim(query)
        self._cache[normalized_query] = record
        return record

    def persist_cache(self) -> None:
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {key: value.to_dict() for key, value in self._cache.items()}
        self._cache_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _geocode_nominatim(self, query: str) -> GeocodeRecord:
        params = {"q": query, "format": "jsonv2", "limit": "1"}
        email = os.environ.get("GEOKG_NOMINATIM_EMAIL")
        if email:
            params["email"] = email
        url = "https://nominatim.openstreetmap.org/search?" + parse.urlencode(params)
        req = request.Request(url, headers={"User-Agent": self._user_agent})

        data: list[dict[str, Any]] | None = None
        for attempt in range(self._max_retries + 1):
            self._respect_rate_limit()
            try:
                with request.urlopen(req, timeout=self._timeout_seconds) as response:
                    data = json.loads(response.read().decode("utf-8"))
                break
            except HTTPError as exc:
                if exc.code == 429:
                    if attempt >= self._max_retries:
                        return _failed_geocode(
                            query,
                            "Nominatim rate limit exceeded after retries.",
                        )
                    retry_after = _retry_after_seconds(exc)
                    time.sleep(retry_after or self._backoff_seconds(attempt))
                    continue
                return _failed_geocode(query, f"Nominatim HTTP error {exc.code}: {exc.reason}")
            except (TimeoutError, URLError, json.JSONDecodeError) as exc:
                if attempt >= self._max_retries:
                    return _failed_geocode(query, f"Nominatim request failed: {exc}")
                time.sleep(self._backoff_seconds(attempt))

        if data is None:
            return _failed_geocode(query, "Nominatim request failed.")

        if not data:
            return GeocodeRecord(
                query=query,
                latitude=None,
                longitude=None,
                display_name=None,
                source="missing",
                notes="No Nominatim result.",
            )

        top = data[0]
        return GeocodeRecord(
            query=query,
            latitude=float(top["lat"]),
            longitude=float(top["lon"]),
            display_name=top.get("display_name"),
            source="nominatim",
            osm_type=top.get("type"),
            osm_category=top.get("class"),
            osm_addresstype=top.get("addresstype"),
            raw_importance=_safe_float(top.get("importance")),
        )

    def _respect_rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_remote_request_at
        if elapsed < self._min_delay_seconds:
            time.sleep(self._min_delay_seconds - elapsed)
        self._last_remote_request_at = time.monotonic()

    @staticmethod
    def _backoff_seconds(attempt: int) -> float:
        return min(60.0, 5.0 * (2**attempt))

    @staticmethod
    def _load_cache(path: Path) -> dict[str, GeocodeRecord]:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            key: GeocodeRecord(**value)
            for key, value in data.items()
            if isinstance(value, dict)
        }


def load_geocode_overrides(path: Path) -> dict[str, GeocodeRecord]:
    overrides: dict[str, GeocodeRecord] = {}
    if not path.exists():
        return overrides

    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            query = row.get("query", "")
            if not query:
                continue
            overrides[_normalize_query(query)] = GeocodeRecord(
                query=query,
                latitude=_safe_float(row.get("latitude")),
                longitude=_safe_float(row.get("longitude")),
                display_name=row.get("display_name") or query,
                source=row.get("source") or "override",
                notes=row.get("notes") or None,
            )
    return overrides


def review_geocode_result(name: str, record: GeocodeRecord) -> list[dict[str, str]]:
    flags: list[dict[str, str]] = []
    if record.latitude is None or record.longitude is None:
        flags.append(
            {
                "code": "missing_coordinates",
                "message": f"No coordinates found for '{name}'.",
            }
        )
        return flags

    if record.source == "nominatim" and record.osm_addresstype in {"country", "state", "region"}:
        flags.append(
            {
                "code": "broad_geocode_match",
                "message": (
                    f"'{name}' resolved to a broad administrative area "
                    f"({record.osm_addresstype}); review manually."
                ),
            }
        )
    if record.raw_importance is not None and record.raw_importance < 0.01:
        flags.append(
            {
                "code": "low_importance_match",
                "message": (
                    f"'{name}' resolved with low Nominatim importance "
                    f"({record.raw_importance:.4f}); review manually."
                ),
            }
        )
    return flags


def _normalize_query(value: str) -> str:
    return " ".join(value.split()).casefold()


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _failed_geocode(query: str, notes: str) -> GeocodeRecord:
    return GeocodeRecord(
        query=query,
        latitude=None,
        longitude=None,
        display_name=None,
        source="missing",
        notes=notes,
    )


def _retry_after_seconds(exc: HTTPError) -> float | None:
    value = exc.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None
