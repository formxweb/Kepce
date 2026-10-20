import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.downloader import (MSG_GENERIC, MSG_GONE, MSG_LOGIN, MSG_NO_VIDEO, MSG_PRIVATE,
                            friendly_error)
from app.links import parse_links


class ParseLinksTest(unittest.TestCase):
    def codes(self, text):
        links, _ = parse_links(text)
        return [(l.kind, l.code) for l in links]

    def test_common_forms(self):
        text = """
        https://www.instagram.com/reel/C1aBcD2eFgH/?igsh=MWQ1ZGUxMzBkMA==
        https://instagram.com/p/C9xYz_12345/
        instagram.com/reels/DAbc-12345
        https://m.instagram.com/tv/B7tvCODE99/
        https://www.instagram.com/burak.dev/reel/DUser12345/
        """
        self.assertEqual(self.codes(text), [
            ("reel", "C1aBcD2eFgH"),
            ("p", "C9xYz_12345"),
            ("reel", "DAbc-12345"),
            ("tv", "B7tvCODE99"),
            ("reel", "DUser12345"),
        ])

    def test_messy_text_and_punctuation(self):
        text = ("şuna bak https://www.instagram.com/reel/AAAAA11111/. bir de bu,"
                "(https://www.instagram.com/p/BBBBB22222/) ve <instagram.com/reel/CCCCC33333>!")
        self.assertEqual([c for _, c in self.codes(text)], ["AAAAA11111", "BBBBB22222", "CCCCC33333"])

    def test_duplicates_counted_once_in_order(self):
        text = ("https://www.instagram.com/reel/AAAAA11111/ "
                "https://www.instagram.com/reels/AAAAA11111/?x=1 "
                "https://www.instagram.com/p/BBBBB22222/")
        self.assertEqual([c for _, c in self.codes(text)], ["AAAAA11111", "BBBBB22222"])

    def test_canonical_url(self):
        links, _ = parse_links("instagram.com/reels/AAAAA11111?igsh=abc")
        self.assertEqual(links[0].url, "https://www.instagram.com/reel/AAAAA11111/")

    def test_rejects_non_video_links(self):
        text = """
        https://www.instagram.com/stories/someone/3312345678901234567/
        https://www.instagram.com/someone/
        https://www.youtube.com/watch?v=abc
        https://evil.com/instagram.com/reel/AAAAA11111/
        merhaba nasılsın
        """
        links, rejected = parse_links(text)
        self.assertEqual(links, [])
        self.assertEqual(len(rejected), 4)

    def test_empty(self):
        self.assertEqual(parse_links(""), ([], []))


class FriendlyErrorTest(unittest.TestCase):
    def test_mapping(self):
        cases = {
            "ERROR: [Instagram] X: This content is private": MSG_PRIVATE,
            "ERROR: [Instagram] X: There is no video in this post": MSG_NO_VIDEO,
            "ERROR: [Instagram] X: Requested content is not available, rate-limit reached or login required": MSG_LOGIN,
            "ERROR: HTTP Error 404: Not Found": MSG_GONE,
            "ERROR: something odd": MSG_GENERIC,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(friendly_error(text, 300), expected)

    def test_size_limit(self):
        self.assertIn("300 MB", friendly_error("File is larger than max-filesize (1 > 2 bytes)", 300))


if __name__ == "__main__":
    unittest.main()
