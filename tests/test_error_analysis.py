import tempfile
import unittest
from pathlib import Path

from geokg.error_analysis import build_error_analysis, write_error_analysis


def gold_record() -> dict:
    return {
        "article_id": "a1",
        "title": "Article One",
        "entities": [
            {"name": "Iran", "type": "NationState"},
            {"name": "Strait of Hormuz", "type": "StrategicLocation"},
        ],
        "relations": [
            {"source": "Iran", "target": "Strait of Hormuz", "type": "BLOCKADED"}
        ],
        "events": [
            {
                "event_type": "BlockadeEvent",
                "event_date": "2026-04-10",
                "date_precision": "day",
                "location": "Strait of Hormuz",
                "participants": [
                    {"name": "Iran", "type": "NationState", "role": "initiator"},
                    {
                        "name": "Strait of Hormuz",
                        "type": "StrategicLocation",
                        "role": "affected_location",
                    },
                ],
                "relations": [
                    {
                        "source": "Iran",
                        "target": "Strait of Hormuz",
                        "type": "BLOCKADED",
                    }
                ],
                "summary": "Iran blockaded the Strait of Hormuz.",
                "evidence": "Iran blockaded the Strait of Hormuz.",
                "location_geocode": {
                    "latitude": 26.56,
                    "longitude": 56.25,
                    "geocode_source": "gold",
                    "geocode_display_name": "Strait of Hormuz",
                },
            }
        ],
    }


def pred_record() -> dict:
    return {
        "article_id": "a1",
        "title": "Article One",
        "entities": [
            {"name": "Iran", "type": "NationState"},
            {"name": "Hormuz Strait", "type": "StrategicLocation"},
        ],
        "relations": [{"source": "Iran", "target": "Hormuz Strait", "type": "BLOCKADED"}],
        "events": [
            {
                "event_type": "BlockadeEvent",
                "event_date": "2026-04-10",
                "date_precision": "article_date",
                "location": "Hormuz Strait",
                "participants": [
                    {"name": "Iran", "type": "NationState", "role": "initiator"},
                    {
                        "name": "Strait of Hormuz",
                        "type": "StrategicLocation",
                        "role": "target",
                    },
                ],
                "relations": [
                    {"source": "Iran", "target": "Hormuz Strait", "type": "BLOCKADED"}
                ],
                "summary": "Iran blocked Hormuz.",
                "evidence": "Iran blocked Hormuz.",
            }
        ],
    }


class ErrorAnalysisTest(unittest.TestCase):
    def test_build_error_analysis_finds_structural_errors(self) -> None:
        result = build_error_analysis(
            gold_records=[gold_record()],
            prediction_records=[pred_record()],
            report={},
        )

        self.assertGreaterEqual(len(result["entity_errors"]), 2)
        self.assertGreaterEqual(len(result["relation_errors"]), 2)
        self.assertEqual(len(result["event_errors"]), 1)
        self.assertTrue(
            any(item["error_type"] == "role_mismatch" for item in result["participant_errors"])
        )
        self.assertTrue(
            any(
                item["error_type"] == "predicted_location_missing_coordinates"
                for item in result["geocoding_errors"]
            )
        )

    def test_write_error_analysis_outputs_markdown_and_csvs(self) -> None:
        result = build_error_analysis(
            gold_records=[gold_record()],
            prediction_records=[pred_record()],
            report={},
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "error_analysis.md"
            error_dir = Path(tmpdir) / "errors"

            write_error_analysis(result, output=output, error_dir=error_dir)

            self.assertIn("GeoKG Error Analysis", output.read_text(encoding="utf-8"))
            self.assertTrue((error_dir / "events.csv").exists())
            self.assertTrue((error_dir / "participants.csv").exists())
            self.assertTrue((error_dir / "geocoding.csv").exists())


if __name__ == "__main__":
    unittest.main()
