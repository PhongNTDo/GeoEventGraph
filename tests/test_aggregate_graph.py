import unittest

from geokg.aggregate_graph import build_events_payload, build_graph_payload


class AggregateGraphTest(unittest.TestCase):
    def test_aggregates_repeated_relations_and_timeline(self) -> None:
        records = [
            {
                "article_id": "a1",
                "published_at": "2026-04-10T10:00:00+00:00",
                "title": "Article One",
                "source": "BBC News",
                "url": "https://example.invalid/a1",
                "entities": [
                    {"name": "United States", "type": "NationState"},
                    {"name": "Iran", "type": "NationState"},
                    {
                        "name": "Strait of Hormuz",
                        "type": "StrategicLocation",
                        "latitude": 26.4,
                        "longitude": 56.2,
                    },
                ],
                "relations": [
                    {
                        "source": "United States",
                        "target": "Iran",
                        "type": "THREATENED",
                        "evidence": "threat one",
                    },
                    {
                        "source": "Iran",
                        "target": "Strait of Hormuz",
                        "type": "BLOCKADED",
                        "evidence": "blockade one",
                    },
                ],
            },
            {
                "article_id": "a2",
                "published_at": "2026-04-12T10:00:00+00:00",
                "title": "Article Two",
                "source": "BBC News",
                "entities": [
                    {"name": "United States", "type": "NationState"},
                    {"name": "Iran", "type": "NationState"},
                ],
                "relations": [
                    {
                        "source": "United States",
                        "target": "Iran",
                        "type": "THREATENED",
                        "evidence": "threat two",
                    }
                ],
            },
        ]

        payload = build_graph_payload(records)

        self.assertEqual(payload["metadata"]["node_count"], 3)
        self.assertEqual(payload["metadata"]["edge_count"], 2)
        self.assertEqual(payload["metadata"]["timeline"]["min_date"], "2026-04-10")
        self.assertEqual(payload["metadata"]["timeline"]["max_date"], "2026-04-12")

        threatened = next(edge for edge in payload["edges"] if edge["type"] == "THREATENED")
        self.assertEqual(threatened["weight"], 2)
        self.assertEqual(threatened["article_count"], 2)
        self.assertEqual(threatened["dates"], ["2026-04-10", "2026-04-12"])

        hormuz = next(node for node in payload["nodes"] if node["name"] == "Strait of Hormuz")
        self.assertEqual(hormuz["latitude"], 26.4)
        self.assertEqual(hormuz["relation_count"], 1)

    def test_builds_event_payload_with_node_references(self) -> None:
        records = [
            {
                "article_id": "a1",
                "published_at": "2026-04-10T10:00:00+00:00",
                "title": "Article One",
                "source": "BBC News",
                "url": "https://example.invalid/a1",
                "entities": [
                    {"name": "Iran", "type": "NationState"},
                    {
                        "name": "Strait of Hormuz",
                        "type": "StrategicLocation",
                        "latitude": 26.4,
                        "longitude": 56.2,
                    },
                ],
                "relations": [
                    {
                        "source": "Iran",
                        "target": "Strait of Hormuz",
                        "type": "BLOCKADED",
                        "evidence": "blockade one",
                    }
                ],
                "events": [
                    {
                        "event_id": "event:a1:001:blockadeevent",
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
                                "evidence": "blockade one",
                            }
                        ],
                        "summary": "Iran blockaded the Strait of Hormuz.",
                        "evidence": "blockade one",
                        "confidence": 0.8,
                    }
                ],
            }
        ]

        graph_payload = build_graph_payload(records)
        event_payload = build_events_payload(records, graph_payload["nodes"])

        self.assertEqual(event_payload["metadata"]["event_count"], 1)
        event = event_payload["events"][0]
        self.assertEqual(event["location_node_id"], "StrategicLocation:strait-of-hormuz")
        self.assertEqual(event["source_url"], "https://example.invalid/a1")
        self.assertEqual(event["location_geocode_source"], None)
        self.assertEqual(event["validation_status"], "schema_validated")
        self.assertEqual(event["participants"][0]["node_id"], "NationState:iran")
        self.assertEqual(event["relations"][0]["target_id"], "StrategicLocation:strait-of-hormuz")


if __name__ == "__main__":
    unittest.main()
