# -*- coding: utf-8 -*-
"""磁盘缓存测试：命中、过期、损坏、原子写。

全部在临时目录里跑，不碰用户的 addon_data。
"""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import cache  # noqa: E402


class CacheTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="mistuary-cache-")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_put_then_get(self):
        cache.put("k1", {"a": 1}, root=self.root)
        self.assertEqual(cache.get("k1", 300, root=self.root), {"a": 1})

    def test_miss_returns_none(self):
        self.assertIsNone(cache.get("nope", 300, root=self.root))

    def test_ttl_zero_disables_cache(self):
        cache.put("k1", {"a": 1}, root=self.root)
        self.assertIsNone(cache.get("k1", 0, root=self.root))

    def test_expired_returns_none(self):
        cache.put("k1", {"a": 1}, root=self.root)
        # 把时间戳改到很久以前，模拟过期
        path = os.path.join(self.root, cache._key_to_name("k1"))
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        payload["ts"] = time.time() - 1000
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        self.assertIsNone(cache.get("k1", 300, root=self.root))

    def test_corrupted_file_returns_none(self):
        path = os.path.join(self.root, cache._key_to_name("k1"))
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        self.assertIsNone(cache.get("k1", 300, root=self.root))

    def test_missing_ts_returns_none(self):
        path = os.path.join(self.root, cache._key_to_name("k1"))
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"data": 1}, handle)
        self.assertIsNone(cache.get("k1", 300, root=self.root))

    def test_empty_list_is_cached(self):
        """空结果也要缓存 —— 用户连续打字时不该每次都打服务端。"""
        cache.put("k1", [], root=self.root)
        self.assertEqual(cache.get("k1", 300, root=self.root), [])

    def test_clear_removes_json_only(self):
        cache.put("k1", {"a": 1}, root=self.root)
        cache.put("k2", {"b": 2}, root=self.root)
        keep = os.path.join(self.root, "keep.txt")
        with open(keep, "w", encoding="utf-8") as handle:
            handle.write("x")
        removed = cache.clear(root=self.root)
        self.assertEqual(removed, 2)
        self.assertTrue(os.path.exists(keep))

    def test_key_is_stable_and_hashed(self):
        name_a = cache._key_to_name("server|movies|让子弹飞")
        name_b = cache._key_to_name("server|movies|让子弹飞")
        self.assertEqual(name_a, name_b)
        self.assertTrue(name_a.endswith(".json"))
        # 文件名里不能出现原始 key（中文/竖线会让某些文件系统出问题）
        self.assertNotIn("|", name_a)

    def test_make_key_joins(self):
        self.assertEqual(cache.make_key("a", 1, None), "a|1|None")


if __name__ == "__main__":
    unittest.main()
