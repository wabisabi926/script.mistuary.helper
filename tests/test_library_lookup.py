# -*- coding: utf-8 -*-
"""搜索结果跳转测试。

两条契约：
1. 剧集一律跳 Kodi 媒体库（`videodb://tvshows/titles/<id>/`），不依赖任何
   Emby 插件的浏览接口 —— 各分支对 `mode=browse` 的支持并不一致。
2. 库里没有的剧集不生成可点条目，改为在列表末尾说明数量。

`library_id_by_provider` 用桩 xbmc 验证匹配规则；`render_search` 只验证
「目标路径怎么拼」，不碰真实 Kodi / Emby。
"""

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import emby, kodi  # noqa: E402


def _jsonrpc_result(rows, key):
    return json.dumps({"jsonrpc": "2.0", "id": 1, "result": {key: rows}})


class FakeXbmc(object):
    """记录最后一次请求，返回预置结果。"""

    def __init__(self, payload):
        self.payload = payload
        self.last_request = None

    def executeJSONRPC(self, raw):
        self.last_request = json.loads(raw)
        return self.payload


class LibraryLookupTest(unittest.TestCase):
    def _lookup(self, rows, **kwargs):
        fake = FakeXbmc(_jsonrpc_result(rows, "tvshows"))
        with mock.patch.dict(sys.modules, {"xbmc": fake}):
            dbid = kodi.library_id_by_provider("tvshows", "测试剧", **kwargs)
        return dbid, fake

    def test_match_by_tmdb(self):
        dbid, _ = self._lookup(
            [{"tvshowid": 12, "title": "测试剧", "uniqueid": {"tmdb": "1234"}}],
            tmdb="1234")
        self.assertEqual(dbid, 12)

    def test_match_by_tvdb(self):
        dbid, _ = self._lookup(
            [{"tvshowid": 7, "title": "测试剧", "uniqueid": {"tvdb": "999"}}],
            tvdb="999")
        self.assertEqual(dbid, 7)

    def test_same_title_different_id_is_rejected(self):
        dbid, _ = self._lookup(
            [{"tvshowid": 12, "title": "测试剧", "uniqueid": {"tmdb": "1111"}}],
            tmdb="2222")
        self.assertEqual(dbid, 0)

    def test_picks_matching_row_among_same_titles(self):
        dbid, _ = self._lookup(
            [{"tvshowid": 1, "title": "测试剧", "uniqueid": {"tmdb": "1111"}},
             {"tvshowid": 2, "title": "测试剧", "uniqueid": {"tmdb": "2222"}}],
            tmdb="2222")
        self.assertEqual(dbid, 2)

    def test_no_provider_id_accepts_unique_hit(self):
        dbid, _ = self._lookup(
            [{"tvshowid": 5, "title": "测试剧", "uniqueid": {}}])
        self.assertEqual(dbid, 5)

    def test_no_provider_id_rejects_ambiguous(self):
        dbid, _ = self._lookup(
            [{"tvshowid": 5, "title": "测试剧", "uniqueid": {}},
             {"tvshowid": 6, "title": "测试剧", "uniqueid": {}}])
        self.assertEqual(dbid, 0)

    def test_empty_title_skips_request(self):
        fake = FakeXbmc(_jsonrpc_result([], "tvshows"))
        with mock.patch.dict(sys.modules, {"xbmc": fake}):
            self.assertEqual(kodi.library_id_by_provider("tvshows", ""), 0)
        self.assertIsNone(fake.last_request)

    def test_filter_uses_title_is(self):
        _, fake = self._lookup([], tmdb="1")
        self.assertEqual(fake.last_request["params"]["filter"],
                         {"field": "title", "operator": "is", "value": "测试剧"})


class FakeListItem(object):
    def __init__(self, label="", offscreen=False):
        self.label = label

    def setArt(self, art):
        pass


class FakeXbmcgui(object):
    ListItem = FakeListItem


class FakeXbmcplugin(object):
    def __init__(self):
        self.items = []

    def addDirectoryItem(self, handle, url, list_item, isFolder=False):
        self.items.append((url, list_item.label, isFolder))
        return True


class RenderSearchTest(unittest.TestCase):
    def _render(self, items, dbid_map):
        plugin = FakeXbmcplugin()

        def fake_lookup(kind, title, tmdb="", tvdb=""):
            return dbid_map.get(title, 0)

        with mock.patch.dict(sys.modules,
                             {"xbmcgui": FakeXbmcgui, "xbmcplugin": plugin}), \
                mock.patch.object(kodi, "apply_video_info", lambda *a, **k: None), \
                mock.patch.object(kodi, "library_id_by_provider", fake_lookup), \
                mock.patch.object(kodi, "add_notice") as notice, \
                mock.patch.object(emby.config, "read_settings", lambda: {}), \
                mock.patch.object(emby.config, "find_server", lambda sid: _Server()), \
                mock.patch.object(emby, "search_page", lambda *a, **k: (items, len(items))):
            emby.render_search(1, "plugin://script.mistuary.helper/?", _Req("shows"))

        return plugin, notice

    def test_series_jumps_to_library(self):
        items = [{"id": "e1", "name": "已同步剧", "is_folder": True,
                  "tmdb": "1", "tvdb": "", "image_tag": "", "backdrop_tag": ""}]
        plugin, notice = self._render(items, {"已同步剧": 42})
        self.assertEqual(plugin.items[0][0], "videodb://tvshows/titles/42/")
        self.assertTrue(plugin.items[0][2])
        notice.assert_not_called()

    def test_unsynced_series_is_hidden_and_counted(self):
        items = [{"id": "e1", "name": "未同步剧", "is_folder": True,
                  "tmdb": "2", "tvdb": "", "image_tag": "", "backdrop_tag": ""}]
        plugin, notice = self._render(items, {})
        self.assertEqual(plugin.items, [])
        notice.assert_called_once()
        self.assertEqual(notice.call_args[0][2], emby.i18n.t(32154, 1))

    def test_movie_still_plays(self):
        items = [{"id": "m1", "name": "电影", "is_folder": False,
                  "tmdb": "3", "tvdb": "", "image_tag": "", "backdrop_tag": ""}]
        plugin, notice = self._render(items, {})
        self.assertEqual(plugin.items[0][0], emby.play_url(_Server(), "m1"))
        self.assertFalse(plugin.items[0][2])
        notice.assert_not_called()


class _Server(object):
    server_id = "srv1"
    base_url = "http://emby:8096"
    token = "T"
    user_id = "U"


class _Req(object):
    def __init__(self, media_type):
        self.mode = "search"
        self.type = media_type
        self.query = "q"
        self.offset = 0


if __name__ == "__main__":
    unittest.main()
