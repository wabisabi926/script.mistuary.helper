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
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import cache  # noqa: E402


class CacheTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="mistuary-cache-")
        # 写入计数是模块级的，跨用例会累积并触发清扫，这里隔离掉
        self._writes = cache._writes
        cache._writes = 0

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)
        cache._writes = self._writes

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


class PruneTest(unittest.TestCase):
    """过期文件不能只靠设置页「清空缓存」——搜索词是无限的。"""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="mistuary-prune-")
        self._writes = cache._writes
        cache._writes = 0

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)
        cache._writes = self._writes

    def _path(self, key):
        return os.path.join(self.root, cache._key_to_name(key))

    def _age(self, key, seconds):
        past = time.time() - seconds
        os.utime(self._path(key), (past, past))

    def test_removes_expired_and_keeps_fresh(self):
        cache.put("old", {"a": 1}, root=self.root)
        self._age("old", cache.MAX_AGE + 60)
        cache.put("new", {"b": 2}, root=self.root)

        self.assertEqual(cache.prune(root=self.root), 1)
        self.assertFalse(os.path.exists(self._path("old")))
        self.assertTrue(os.path.exists(self._path("new")))

    def test_ignores_non_json_files(self):
        keep = os.path.join(self.root, "keep.txt")
        with open(keep, "w", encoding="utf-8") as handle:
            handle.write("x")
        past = time.time() - (cache.MAX_AGE + 60)
        os.utime(keep, (past, past))

        self.assertEqual(cache.prune(root=self.root), 0)
        self.assertTrue(os.path.exists(keep))

    def test_enforces_max_files_by_age(self):
        for i in range(20):
            cache.put("k%d" % i, {"i": i}, root=self.root)
            self._age("k%d" % i, 20 - i)

        # 20 个超过上限 10 → 淘汰到 80%，即删 12 留 8
        self.assertEqual(cache.prune(root=self.root, max_files=10), 12)
        alive = [n for n in os.listdir(self.root) if n.endswith(".json")]
        self.assertEqual(len(alive), 8)
        # 留下的是最新的 8 个
        self.assertTrue(os.path.exists(self._path("k19")))
        self.assertFalse(os.path.exists(self._path("k0")))

    def test_missing_root_returns_zero(self):
        self.assertEqual(cache.prune(root=os.path.join(self.root, "nope")), 0)

    def test_should_prune_every_interval(self):
        with mock.patch.object(cache, "_writes", 0):
            hits = [cache._should_prune() for _ in range(cache.PRUNE_EVERY * 2)]
        self.assertEqual(sum(hits), 2)

    def test_put_triggers_prune_on_interval(self):
        with mock.patch.object(cache, "_writes", cache.PRUNE_EVERY - 1), \
             mock.patch.object(cache, "prune") as prune:
            cache.put("k1", {"a": 1}, root=self.root)
        prune.assert_called_once()

    def test_put_does_not_prune_before_interval(self):
        with mock.patch.object(cache, "_writes", 0), \
             mock.patch.object(cache, "prune") as prune:
            cache.put("k1", {"a": 1}, root=self.root)
        prune.assert_not_called()


if __name__ == "__main__":
    unittest.main()
