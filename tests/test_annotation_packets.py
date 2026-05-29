import tempfile
import unittest
from pathlib import Path

from geokg.annotation_packets import (
    build_annotation_packets,
    finalize_gold,
    gold_row_schema,
    write_packets,
)


class AnnotationPacketsTest(unittest.TestCase):
    def test_builds_packet_with_article_text_and_candidate(self) -> None:
        candidate = {
            "article_id": "a1",
            "title": "Candidate Title",
            "annotation_status": "needs_human_review",
            "entities": [],
            "relations": [],
            "events": [],
        }
        article = {
            "article_id": "a1",
            "title": "Article Title",
            "source": "BBC News",
            "published_at": "2026-04-10",
            "url": "https://example.invalid/a1",
            "text": "Country A blocked the strait.",
        }

        packets = build_annotation_packets(candidate_rows=[candidate], article_rows=[article])

        self.assertEqual(len(packets), 1)
        self.assertEqual(packets[0]["article"]["text"], "Country A blocked the strait.")
        self.assertEqual(packets[0]["draft_candidate"]["article_id"], "a1")
        self.assertIn("output_schema_hint", packets[0])

    def test_write_packets_creates_json_and_markdown(self) -> None:
        packet = {
            "article_id": "a1",
            "title": "Article Title",
            "source_url": "https://example.invalid/a1",
            "article": {"text": "Article text"},
            "draft_candidate": {"article_id": "a1"},
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            write_packets([packet], output_dir)

            self.assertTrue((output_dir / "a1.packet.json").exists())
            self.assertTrue((output_dir / "a1.packet.md").exists())

    def test_finalize_gold_uses_only_human_gold_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            review_dir = Path(tmpdir) / "review"
            review_dir.mkdir()
            (review_dir / "a1.json").write_text(
                '{"article_id":"a1","annotation_status":"model_reviewed"}\n',
                encoding="utf-8",
            )
            (review_dir / "a2.json").write_text(
                '{"article_id":"a2","annotation_status":"gold"}\n',
                encoding="utf-8",
            )
            output = Path(tmpdir) / "gold.jsonl"

            rows = finalize_gold(
                review_dir=review_dir,
                output=output,
                promote_model_reviewed=False,
            )

            self.assertEqual([row["article_id"] for row in rows], ["a2"])
            self.assertEqual(output.read_text(encoding="utf-8").count("\n"), 1)

    def test_finalize_gold_can_promote_model_reviewed_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            review_dir = Path(tmpdir) / "review"
            review_dir.mkdir()
            (review_dir / "a1.json").write_text(
                '{"article_id":"a1","annotation_status":"model_reviewed","annotation_notes":[]}\n',
                encoding="utf-8",
            )
            output = Path(tmpdir) / "gold.jsonl"

            rows = finalize_gold(
                review_dir=review_dir,
                output=output,
                promote_model_reviewed=True,
            )

            self.assertEqual(rows[0]["annotation_status"], "gold")

    def test_gold_schema_requires_final_fields(self) -> None:
        schema = gold_row_schema()

        self.assertIn("article_id", schema["required"])
        self.assertIn("events", schema["properties"])


if __name__ == "__main__":
    unittest.main()
