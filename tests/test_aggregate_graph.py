import unittest

from geokg.aggregate_graph import build_graph_payload


class AggregateGraphTest(unittest.TestCase):
    def test_aggregates_repeated_relations_and_timeline(self) -> None:
        records = [
            {
                "article_id": "a1",
                "published_at": "2026-04-10T10:00:00+00:00",
                "title": "Article One",
                "source": "BBC News",
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


if __name__ == "__main__":
    unittest.main()
