# -*- coding: utf-8 -*-
"""背景色光底：只测不依赖 Kodi 的纯逻辑与图像处理。

Kodi 交互（xbmcvfs.copy / Window 属性）留给真机验证，这里不 mock 一个假的
Kodi 出来骗自己 —— 那类测试过了不代表盒子上有图。
"""

from __future__ import annotations

import io
import os
import tempfile
import time
import unittest

from lib import fanart_glow


def _solid_source(path, color=(255, 255, 255)):
    from PIL import Image

    Image.new("RGB", (640, 360), color).save(path, format="JPEG")


class BuildGlowTests(unittest.TestCase):
    def test_white_source_is_dimmed_to_quarter(self):
        """纯白源图压到 0.25 后均值应在 55~75，不能还是白的。"""
        try:
            from PIL import Image
        except ImportError:  # pragma: no cover - CI 无 Pillow 时跳过图像断言
            self.skipTest("Pillow not available")
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "white.jpg")
            _solid_source(src)
            payload = fanart_glow.build_glow(src)
        self.assertIsNotNone(payload)
        self.assertTrue(payload.startswith(b"\xff\xd8"), "应该是 JPEG")
        from PIL import ImageStat

        im = Image.open(io.BytesIO(payload)).convert("RGB")
        self.assertEqual(im.size, (640, 360))
        avg = ImageStat.Stat(im.convert("L")).mean[0]
        self.assertGreater(avg, 45)
        self.assertLess(avg, 85)

    def test_brightness_zero_is_black(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not available")
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "white.jpg")
            _solid_source(src)
            payload = fanart_glow.build_glow(src, brightness=0.0)
        im = Image.open(io.BytesIO(payload)).convert("L")
        self.assertLess(im.getextrema()[1], 6)

    def test_bad_file_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "bad.jpg")
            with open(bad, "wb") as handle:
                handle.write(b"not an image")
            self.assertIsNone(fanart_glow.build_glow(bad))

    def test_missing_file_returns_none(self):
        self.assertIsNone(fanart_glow.build_glow("/no/such/file.jpg"))


class SettleTests(unittest.TestCase):
    """滚动途中不计算，源图停稳才算一次。"""

    def test_first_seen_only_records_pending(self):
        run, pending = fanart_glow.should_render("a.jpg", None, None, 100.0)
        self.assertFalse(run)
        self.assertEqual(pending, ("a.jpg", 100.0))

    def test_renders_after_settle(self):
        run, pending = fanart_glow.should_render(
            "a.jpg", ("a.jpg", 100.0), None, 100.31
        )
        self.assertTrue(run)
        self.assertIsNone(pending)

    def test_does_not_render_during_scroll(self):
        run, pending = fanart_glow.should_render(
            "a.jpg", ("a.jpg", 100.0), None, 100.1
        )
        self.assertFalse(run)
        self.assertEqual(pending, ("a.jpg", 100.0))

    def test_source_change_restarts_settle(self):
        run, pending = fanart_glow.should_render(
            "b.jpg", ("a.jpg", 100.0), None, 100.9
        )
        self.assertFalse(run)
        self.assertEqual(pending, ("b.jpg", 100.9))

    def test_already_published_is_skipped(self):
        run, pending = fanart_glow.should_render(
            "a.jpg", None, "a.jpg", 200.0
        )
        self.assertFalse(run)
        self.assertIsNone(pending)

    def test_empty_source_clears_pending(self):
        run, pending = fanart_glow.should_render("", ("a.jpg", 100.0), None, 200.0)
        self.assertFalse(run)
        self.assertIsNone(pending)


class PruneTests(unittest.TestCase):
    def test_keeps_newest_files_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(30):
                path = os.path.join(tmp, "glow-%02d.jpg" % i)
                with open(path, "wb") as handle:
                    handle.write(b"x")
                os.utime(path, (1000 + i, 1000 + i))
            # 非 glow 文件不能被误删
            with open(os.path.join(tmp, "source.tmp"), "wb") as handle:
                handle.write(b"keep")
            removed = fanart_glow.prune(tmp, max_files=24)
            self.assertEqual(removed, 6)
            left = sorted(n for n in os.listdir(tmp) if n.startswith("glow-"))
            self.assertEqual(len(left), 24)
            self.assertEqual(left[0], "glow-06.jpg")
            self.assertTrue(os.path.isfile(os.path.join(tmp, "source.tmp")))

    def test_under_limit_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(3):
                with open(os.path.join(tmp, "glow-%d.jpg" % i), "wb") as handle:
                    handle.write(b"x")
            self.assertEqual(fanart_glow.prune(tmp), 0)


class ConstantsTests(unittest.TestCase):
    def test_brightness_matches_skin_preview(self):
        """0.42 会把透黑玻璃垫灰，锁死 0.25。"""
        self.assertAlmostEqual(fanart_glow.BRIGHTNESS, 0.25)

    def test_no_external_helper_dependency(self):
        """防止有人图省事又接回 TMDbHelper。"""
        import pathlib

        root = pathlib.Path(__file__).resolve().parent.parent
        addon = (root / "addon.xml").read_text(encoding="utf-8")
        self.assertNotIn("plugin.video.themoviedb.helper", addon)
        self.assertIn("script.module.pil", addon)
        module = (root / "lib" / "fanart_glow.py").read_text(encoding="utf-8")
        imports = [
            line for line in module.splitlines()
            if line.startswith("import ") or line.startswith("from ")
        ]
        self.assertFalse(any("tmdbhelper" in line.lower() for line in imports))


if __name__ == "__main__":
    unittest.main()
