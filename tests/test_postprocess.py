import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from geokg.geocoding import GeocodeRecord, Geocoder, review_geocode_result
from geokg.postprocess import clean_extraction_record, load_aliases


class PostprocessTest(unittest.TestCase):
    def test_aliases_remap_entities_and_relations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            alias_path = Path(tmpdir) / "aliases.csv"
            alias_path.write_text(
                "alias,canonical_name,canonical_type\n"
                "US,United States,NationState\n"
                "U.S.,United States,NationState\n",
                encoding="utf-8",
            )
            aliases = load_aliases(alias_path)
            record = {
                "article_id": "a1",
                "entities": [
                    {"name": "US", "type": "NationState"},
                    {"name": "Iran", "type": "NationState"},
                ],
                "relations": [
                    {
                        "source": "U.S.",
                        "target": "Iran",
                        "type": "THREATENED",
                        "evidence": "The US threatened Iran.",
                    }
                ],
            }

            cleaned = clean_extraction_record(record, aliases)

            self.assertEqual(cleaned["entities"][0]["name"], "United States")
            self.assertEqual(cleaned["relations"][0]["source"], "United States")

    def test_generic_location_gets_review_flag(self) -> None:
        aliases = load_aliases(Path("/tmp/does-not-exist.csv"))
        record = {
            "article_id": "a2",
            "entities": [{"name": "Iranian ports", "type": "StrategicLocation"}],
            "relations": [],
        }

        cleaned = clean_extraction_record(record, aliases)

        flags = cleaned["entities"][0]["review_flags"]
        self.assertEqual(flags[0]["code"], "generic_location_name")

    def test_geocoder_uses_override_and_no_review_for_good_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            overrides_path = Path(tmpdir) / "geocode_overrides.csv"
            overrides_path.write_text(
                "query,latitude,longitude,display_name,source,notes\n"
                "Strait of Hormuz,26.5667,56.2500,Strait of Hormuz,override,\n",
                encoding="utf-8",
            )
            cache_path = Path(tmpdir) / "cache.json"
            geocoder = Geocoder(
                overrides_path=overrides_path,
                cache_path=cache_path,
            )

            result = geocoder.geocode("Strait of Hormuz")

            self.assertEqual(result.source, "override")
            self.assertAlmostEqual(result.latitude, 26.5667)
            self.assertEqual(review_geocode_result("Strait of Hormuz", result), [])

    def test_cache_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            overrides_path = Path(tmpdir) / "geocode_overrides.csv"
            overrides_path.write_text(
                "query,latitude,longitude,display_name,source,notes\n",
                encoding="utf-8",
            )
            cache_path = Path(tmpdir) / "cache.json"
            geocoder = Geocoder(overrides_path=overrides_path, cache_path=cache_path)
            geocoder._cache["islamabad"] = GeocodeRecord(
                query="Islamabad",
                latitude=33.6844,
                longitude=73.0479,
                display_name="Islamabad, Pakistan",
                source="override",
            )
            geocoder.persist_cache()

            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertIn("islamabad", payload)

    def test_review_for_missing_geocode(self) -> None:
        flags = review_geocode_result(
            "Unknown Place",
            GeocodeRecord(
                query="Unknown Place",
                latitude=None,
                longitude=None,
                display_name=None,
                source="missing",
            ),
        )
        self.assertEqual(flags[0]["code"], "missing_coordinates")

    def test_geocoder_returns_missing_record_on_http_429(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            overrides_path = Path(tmpdir) / "geocode_overrides.csv"
            overrides_path.write_text(
                "query,latitude,longitude,display_name,source,notes\n",
                encoding="utf-8",
            )
            cache_path = Path(tmpdir) / "cache.json"
            geocoder = Geocoder(
                overrides_path=overrides_path,
                cache_path=cache_path,
                min_delay_seconds=0,
                max_retries=0,
            )
            error = HTTPError(
                url="https://nominatim.openstreetmap.org/search",
                code=429,
                msg="Too Many Requests",
                hdrs={},
                fp=None,
            )

            with patch("geokg.geocoding.request.urlopen", side_effect=error):
                result = geocoder.geocode("Gaza")

            self.assertEqual(result.source, "missing")
            self.assertIn("rate limit", result.notes)

    def test_geocoder_can_run_offline_with_cache_and_overrides_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            overrides_path = Path(tmpdir) / "geocode_overrides.csv"
            overrides_path.write_text(
                "query,latitude,longitude,display_name,source,notes\n",
                encoding="utf-8",
            )
            cache_path = Path(tmpdir) / "cache.json"
            geocoder = Geocoder(
                overrides_path=overrides_path,
                cache_path=cache_path,
                allow_remote=False,
            )

            with patch("geokg.geocoding.request.urlopen") as mocked_urlopen:
                result = geocoder.geocode("Ain Mreisseh neighbourhood")

            mocked_urlopen.assert_not_called()
            self.assertEqual(result.source, "missing")
            self.assertEqual(result.notes, "Remote geocoding disabled.")


if __name__ == "__main__":
    unittest.main()
