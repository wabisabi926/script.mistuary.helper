# -*- coding: utf-8 -*-
"""参数解析测试。

重点不是"能解析正常 URL"，而是**畸形输入不炸**：
中文、`&`、`?`、空值、重复键、超长 query。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import router  # noqa: E402


class ParseTest(unittest.TestCase):
    def test_chinese_query(self):
        req = router.parse("?mode=search&type=movies&query=让子弹飞")
        self.assertEqual(req.mode, "search")
        self.assertEqual(req.type, "movies")
        self.assertEqual(req.query, "让子弹飞")

    def test_query_with_ampersand_is_not_split(self):
        """`&` 出现在搜索词里时，parse_qs 会把它当分隔符 —— 这是必须避开的坑。"""
        req = router.parse("?mode=search&type=movies&query=Tom & Jerry")
        self.assertEqual(req.query, "Tom & Jerry")
        self.assertEqual(req.mode, "search")

    def test_query_with_question_mark(self):
        req = router.parse("?mode=search&type=movies&query=what?")
        self.assertEqual(req.query, "what?")

    def test_query_keeps_equals_sign(self):
        req = router.parse("?mode=search&query=a=b")
        self.assertEqual(req.query, "a=b")

    def test_empty_query(self):
        req = router.parse("?mode=search&type=movies&query=")
        self.assertEqual(req.query, "")
        self.assertEqual(req.mode, "search")

    def test_no_leading_question_mark(self):
        req = router.parse("mode=search&type=shows&query=test")
        self.assertEqual(req.mode, "search")
        self.assertEqual(req.type, "shows")

    def test_empty_input(self):
        req = router.parse("")
        self.assertEqual(req.mode, "")
        self.assertEqual(req.action, "")
        self.assertEqual(req.query, "")

    def test_none_input(self):
        req = router.parse(None)
        self.assertEqual(req.mode, "")

    def test_action_rating(self):
        req = router.parse("?action=rating&type=movie&dbid=1234")
        self.assertEqual(req.action, "rating")
        self.assertEqual(req.dbid, "1234")

    def test_offset_is_int(self):
        req = router.parse("?mode=search&offset=100&query=x")
        self.assertEqual(req.offset, 100)

    def test_bad_offset_falls_back_to_zero(self):
        req = router.parse("?mode=search&offset=abc&query=x")
        self.assertEqual(req.offset, 0)

    def test_negative_offset_clamped(self):
        req = router.parse("?mode=search&offset=-5&query=x")
        self.assertEqual(req.offset, 0)

    def test_repeated_key_takes_first(self):
        req = router.parse("?mode=search&type=movies&type=shows&query=x")
        self.assertEqual(req.type, "movies")

    def test_long_query(self):
        long_query = "测试" * 500
        req = router.parse("?mode=search&query=%s" % long_query)
        self.assertEqual(req.query, long_query)


class BuildSearchUrlTest(unittest.TestCase):
    def test_roundtrip(self):
        url = router.build_search_url("plugin://script.mistuary.helper/", "movies", "让子弹飞", 0)
        self.assertIn("query=让子弹飞", url)
        # 拼出来的 URL 必须能被自己解析回去
        req = router.parse(url.split("?", 1)[1])
        self.assertEqual(req.query, "让子弹飞")
        self.assertEqual(req.type, "movies")

    def test_offset_appears(self):
        url = router.build_search_url("plugin://x/", "shows", "a", 100)
        self.assertIn("offset=100", url)


if __name__ == "__main__":
    unittest.main()
