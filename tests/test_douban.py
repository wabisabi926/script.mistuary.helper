# -*- coding: utf-8 -*-
"""豆瓣取分测试：偶像识别、双通道回退、缓存、窗口属性。

HTTP / Kodi 全部 mock，不依赖网络和 Kodi。
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import douban, http  # noqa: E402


class Req(object):
    def __init__(self, dbid="", imdb="", tmdb="", title="", year=""):
        self.dbid = dbid
        self.imdb = imdb
        self.tmdb = tmdb
        self.title = title
        self.year = year


class FakeResponse(object):
    def __init__(self, payload, ok=True, status=200):
        self._payload = payload
        self.ok = ok
        self.status = status
        self.error = "" if ok else "http %d" % status

    def json(self):
        return self._payload


LEGACY_OK = FakeResponse({"rating": {"average": 8.6, "numRaters": 123456}})
FRODO_OK = FakeResponse({"items": [{"target": {"rating": {"value": 8.6, "count": 123456}}}]})


class ImdbResolutionTest(unittest.TestCase):

    def test_valid_imdb_format(self):
        self.assertTrue(douban._valid_imdb("tt1340507"))
        self.assertFalse(douban._valid_imdb("1340507"))
        self.assertFalse(douban._valid_imdb("tt"))
        self.assertFalse(douban._valid_imdb(""))

    def test_prefers_explicit_imdb(self):
        self.assertEqual(douban.resolve_imdb(Req(imdb="tt1340507")), "tt1340507")

    def test_dbid_falls_back_to_uniqueid(self):
        with mock.patch.object(douban.kodi, "video_uniqueid", return_value="tt1340507"):
            self.assertEqual(douban.resolve_imdb(Req(dbid="42")), "tt1340507")

    def test_no_identifier_returns_empty(self):
        with mock.patch.object(douban.kodi, "video_uniqueid", return_value=""):
            self.assertEqual(douban.resolve_imdb(Req(dbid="0")), "")
        self.assertEqual(douban.resolve_imdb(Req()), "")

    def test_invalid_explicit_imdb_falls_through(self):
        with mock.patch.object(douban.kodi, "video_uniqueid", return_value="tt1340507"):
            self.assertEqual(douban.resolve_imdb(Req(imdb="oops", dbid="42")), "tt1340507")


class FetchTest(unittest.TestCase):

    def test_legacy_success(self):
        with mock.patch.object(douban.http, "request", return_value=LEGACY_OK) as called:
            self.assertEqual(douban.fetch("tt1340507"), (8.6, 123456))
        self.assertEqual(called.call_count, 1)
        self.assertEqual(called.call_args.kwargs.get("method"), "POST")

    def test_legacy_fails_frodo_succeeds(self):
        responses = [FakeResponse({}, ok=False, status=500), FRODO_OK]
        with mock.patch.object(douban.http, "request", side_effect=responses):
            self.assertEqual(douban.fetch("tt1340507"), (8.6, 123456))

    def test_both_channels_fail(self):
        with mock.patch.object(douban.http, "request", return_value=FakeResponse({}, ok=False)):
            self.assertEqual(douban.fetch("tt1340507"), (None, None))

    def test_frodo_without_items(self):
        responses = [FakeResponse({}, ok=False), FakeResponse({"items": []})]
        with mock.patch.object(douban.http, "request", side_effect=responses):
            self.assertEqual(douban.fetch("tt1340507"), (None, None))


class TitleFallbackTest(unittest.TestCase):

    def _items(self):
        return [
            {"target": {"title": "让子弹飞", "year": "2010", "rating": {"value": 9.0, "count": 10}}},
            {"target": {"title": "让子弹飞一会儿", "year": "2010", "rating": {"value": 6.0, "count": 1}}},
        ]

    def test_exact_title_and_year(self):
        with mock.patch.object(douban, "_frodo_search", return_value=self._items()):
            self.assertEqual(douban._frodo_by_title("让子弹飞", "2010"), (9.0, 10))

    def test_year_mismatch_returns_none(self):
        with mock.patch.object(douban, "_frodo_search", return_value=self._items()):
            self.assertIsNone(douban._frodo_by_title("让子弹飞", "1999"))

    def test_title_must_match_exactly(self):
        with mock.patch.object(douban, "_frodo_search", return_value=self._items()):
            self.assertIsNone(douban._frodo_by_title("让子弹", "2010"))

    def test_case_and_space_insensitive(self):
        items = [{"target": {"title": "The  Matrix", "year": "1999",
                             "rating": {"value": 9.1, "count": 5}}}]
        with mock.patch.object(douban, "_frodo_search", return_value=items):
            self.assertEqual(douban._frodo_by_title("the matrix", "1999"), (9.1, 5))


class RunActionTest(unittest.TestCase):

    def setUp(self):
        self.written = {}
        patcher = mock.patch.object(douban.kodi, "set_home_property",
                                    side_effect=lambda k, v: self.written.__setitem__(k, v))
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("cache.get", "cache.put"):
            patcher = mock.patch.object(douban.cache, name.split(".")[1],
                                        return_value=None if name.endswith("get") else True)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_missing_without_imdb(self):
        with mock.patch.object(douban, "resolve_imdb", return_value=""):
            douban.run_action(Req())
        self.assertEqual(self.written[douban.PROP_STATUS], "missing")
        self.assertEqual(self.written[douban.PROP_RATING], "")

    def test_ok_writes_all_properties(self):
        with mock.patch.object(douban, "resolve_imdb", return_value="tt1340507"), \
             mock.patch.object(douban, "fetch", return_value=(8.6, 123456)):
            douban.run_action(Req(imdb="tt1340507"))
        self.assertEqual(self.written[douban.PROP_STATUS], "ok")
        self.assertEqual(self.written[douban.PROP_RATING], "8.6")
        self.assertEqual(self.written[douban.PROP_VOTES], "123456")
        self.assertTrue(self.written[douban.PROP_FETCHED].isdigit())

    def test_error_sets_status_and_caches_failure(self):
        with mock.patch.object(douban, "resolve_imdb", return_value="tt1340507"), \
             mock.patch.object(douban, "fetch", return_value=(None, None)), \
             mock.patch.object(douban.cache, "put") as put:
            douban.run_action(Req(imdb="tt1340507"))
        self.assertEqual(self.written[douban.PROP_STATUS], "error")
        self.assertTrue(any("douban_fail" in str(c) for c in put.call_args_list))

    def test_disabled_writes_missing(self):
        with mock.patch.object(douban.config, "read_settings", return_value={"douban_enabled": False}):
            douban.run_action(Req(imdb="tt1340507"))
        self.assertEqual(self.written[douban.PROP_STATUS], "missing")

    def test_emby_without_rating_falls_back_to_public(self):
        settings = {"douban_enabled": True, "douban_prefer_emby": True,
                    "douban_fallback_public": True}
        with mock.patch.object(douban, "resolve_imdb", return_value="tt1533117"),              mock.patch.object(douban.config, "read_settings", return_value=settings),              mock.patch.object(douban, "_emby_lookup", return_value={"rating": None}),              mock.patch.object(douban, "fetch", return_value=(8.6, 10)) as fetch:
            douban.run_action(Req(imdb="tt1533117"))
        fetch.assert_called_once()
        self.assertEqual(self.written[douban.PROP_STATUS], "ok")
        self.assertEqual(self.written[douban.PROP_RATING], "8.6")

    def test_emby_without_rating_can_skip_public_fallback(self):
        settings = {"douban_enabled": True, "douban_prefer_emby": True,
                    "douban_fallback_public": False}
        with mock.patch.object(douban, "resolve_imdb", return_value="tt1533117"),              mock.patch.object(douban.config, "read_settings", return_value=settings),              mock.patch.object(douban, "_emby_lookup", return_value={"rating": None}),              mock.patch.object(douban, "fetch") as fetch:
            douban.run_action(Req(imdb="tt1533117"))
        fetch.assert_not_called()
        self.assertEqual(self.written[douban.PROP_STATUS], "missing")

    def test_title_fallback_when_no_imdb(self):
        with mock.patch.object(douban, "resolve_imdb", return_value=""),              mock.patch.object(douban.kodi, "get_home_property",
                               side_effect=lambda k: "让子弹飞" if k == douban.PROP_QUERY else "2010"),              mock.patch.object(douban, "_frodo_by_title", return_value=(9.0, 10)) as by_title:
            douban.run_action(Req())
        by_title.assert_called_once_with("让子弹飞", "2010")
        self.assertEqual(self.written[douban.PROP_STATUS], "ok")
        self.assertEqual(self.written[douban.PROP_RATING], "9.0")

    def test_title_fallback_when_imdb_misses(self):
        with mock.patch.object(douban, "resolve_imdb", return_value="tt5311514"),              mock.patch.object(douban, "fetch", return_value=(None, None)),              mock.patch.object(douban, "_frodo_by_title", return_value=(8.4, 20)) as by_title,              mock.patch.object(douban.cache, "get", return_value=None),              mock.patch.object(douban.cache, "put"):
            douban.run_action(Req(imdb="tt5311514", title="你的名字", year="2016"))
        by_title.assert_called_once_with("你的名字", "2016")
        self.assertEqual(self.written[douban.PROP_STATUS], "ok")
        self.assertEqual(self.written[douban.PROP_RATING], "8.4")

    def test_cached_ok_is_reused(self):
        cached = {"status": "ok", "rating": "8.6", "votes": 123, "ts": 1}
        with mock.patch.object(douban, "resolve_imdb", return_value="tt1340507"), \
             mock.patch.object(douban.cache, "get", return_value=cached), \
             mock.patch.object(douban, "fetch") as fetch:
            douban.run_action(Req(imdb="tt1340507"))
        fetch.assert_not_called()
        self.assertEqual(self.written[douban.PROP_RATING], "8.6")


if __name__ == "__main__":
    unittest.main()
