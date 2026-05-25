from pathlib import Path
import unittest

from geokg.bbc_html import parse_bbc_html_file


class BBCHtmlParserTest(unittest.TestCase):
    def test_parse_sample_article(self) -> None:
        matches = sorted(Path("corpus").glob("*c3w39lg84w2o*.html"))
        self.assertTrue(matches, "Missing sample BBC article c3w39lg84w2o in corpus/")
        path = matches[0]

        article = parse_bbc_html_file(path)

        self.assertEqual(article.article_id, "c3w39lg84w2o")
        self.assertEqual(article.source, "BBC News")
        self.assertEqual(article.title, "Strait of Hormuz: How many ships are getting through?")
        self.assertTrue(article.published_at.startswith("2026-04-08T16:13:44"))
        self.assertGreater(len(article.paragraphs), 10)
        self.assertIn("US Central Command (Centcom)", article.text)


if __name__ == "__main__":
    unittest.main()
