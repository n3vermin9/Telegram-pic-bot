import io
import unittest

from PIL import Image

from bot import (
    extract_tiktok_url,
    make_telegram_sticker,
    target_from_html,
    target_from_urls,
    UserError,
)


class LinkTests(unittest.TestCase):
    def test_resolved_share_link(self):
        target = target_from_urls([
            "https://vt.tiktok.com/ZSexample/",
            (
                "https://www.tiktok.com/@creator/video/7654321098765432109"
                "?share_comment_id=7123456789012345678"
                "&share_item_id=7654321098765432109"
            ),
        ])
        self.assertIsNotNone(target)
        self.assertEqual(target.video_id, "7654321098765432109")
        self.assertEqual(target.comment_id, "7123456789012345678")

    def test_ids_can_come_from_different_redirects(self):
        target = target_from_urls([
            "https://m.tiktok.com/v/7654321098765432109.html",
            "https://www.tiktok.com/?share_comment_id=7123456789012345678",
        ])
        self.assertIsNotNone(target)
        self.assertEqual(target.video_id, "7654321098765432109")
        self.assertEqual(target.comment_id, "7123456789012345678")

    def test_html_fallback(self):
        target = target_from_html(
            r"https:\u002F\u002Fwww.tiktok.com\u002F@u\u002Fvideo"
            r"\u002F7654321098765432109?share_comment_id=7123456789012345678"
        )
        self.assertIsNotNone(target)
        self.assertEqual(target.video_id, "7654321098765432109")
        self.assertEqual(target.comment_id, "7123456789012345678")

    def test_rejects_lookalike_domain(self):
        with self.assertRaises(UserError):
            extract_tiktok_url("https://tiktok.com.example.org/video/123")


class StickerTests(unittest.TestCase):
    def test_converts_to_telegram_webp(self):
        source = Image.new("RGBA", (900, 300), (255, 0, 0, 160))
        raw = io.BytesIO()
        source.save(raw, "PNG")

        result = make_telegram_sticker(raw.getvalue())

        self.assertLessEqual(len(result), 512 * 1024)
        with Image.open(io.BytesIO(result)) as sticker:
            self.assertEqual(sticker.format, "WEBP")
            self.assertEqual(sticker.size, (512, 171))


if __name__ == "__main__":
    unittest.main()
