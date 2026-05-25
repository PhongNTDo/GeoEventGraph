import json
import unittest

from geokg.crawl_bbc_topic import (
    TopicPromo,
    build_output_filename,
    is_regular_article_promo,
    parse_topic_page,
)


def build_topic_html(payload: dict) -> str:
    escaped = json.dumps(json.dumps(payload))
    return f"<script>window.__INITIAL_DATA__={escaped};</script>"


class CrawlBBCTopicTest(unittest.TestCase):
    def test_parse_topic_page_extracts_promos_and_pagination(self) -> None:
        payload = {
            "data": {
                "simple-promo-grid?topic=test&pageNumber=2": {
                    "data": {
                        "page": {"index": 2, "total": 42, "totalItems": 1000},
                        "promos": [
                            {
                                "headline": "After Iran talks falter",
                                "contentTitle": "After Iran talks falter",
                                "type": "article",
                                "url": "/news/articles/c5y943x2g8qo",
                                "lastPublished": "2026-04-12T12:48:01.811Z",
                            },
                            {
                                "headline": "Iran talks video clip",
                                "type": "video",
                                "url": "/news/videos/cqj82xn9n8eo",
                                "lastPublished": "2026-04-12T02:33:35.846Z",
                            },
                        ],
                    }
                }
            }
        }

        promos, page_info = parse_topic_page(build_topic_html(payload))

        self.assertEqual(page_info["index"], 2)
        self.assertEqual(page_info["total"], 42)
        self.assertEqual(len(promos), 2)
        self.assertEqual(promos[0].article_id, "c5y943x2g8qo")
        self.assertEqual(promos[0].url, "https://www.bbc.co.uk/news/articles/c5y943x2g8qo")

    def test_regular_article_filter_skips_video_and_live_urls(self) -> None:
        article = TopicPromo(
            headline="Article",
            url="https://www.bbc.co.uk/news/articles/c5y943x2g8qo",
            type="article",
            published_at="2026-04-12T12:48:01.811Z",
            page_number=1,
            article_id="c5y943x2g8qo",
        )
        live = TopicPromo(
            headline="Live",
            url="https://www.bbc.co.uk/news/live/cp9vm5ezxz4t",
            type="article",
            published_at="2026-04-12T12:48:01.811Z",
            page_number=1,
            article_id=None,
        )
        video = TopicPromo(
            headline="Video",
            url="https://www.bbc.co.uk/news/videos/cqj82xn9n8eo",
            type="video",
            published_at="2026-04-12T02:33:35.846Z",
            page_number=1,
            article_id=None,
        )

        self.assertTrue(is_regular_article_promo(article))
        self.assertFalse(is_regular_article_promo(live))
        self.assertFalse(is_regular_article_promo(video))

    def test_output_filename_uses_date_and_article_id(self) -> None:
        promo = TopicPromo(
            headline="Article",
            url="https://www.bbc.co.uk/news/articles/c5y943x2g8qo",
            type="article",
            published_at="2026-04-12T12:48:01.811Z",
            page_number=1,
            article_id="c5y943x2g8qo",
        )

        filename = build_output_filename(promo)

        self.assertEqual(filename, "2026-04-12__c5y943x2g8qo.html")


if __name__ == "__main__":
    unittest.main()
