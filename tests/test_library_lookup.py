# -*- coding: utf-8 -*-
"""搜索结果跳转与未同步内容浏览。

三条契约：
1. 已同步的剧集跳 Kodi 媒体库（`videodb://tvshows/titles/<id>/`），不依赖任何
   Emby 插件的浏览接口 —— 各分支对 `mode=browse` 的支持并不一致。
2. 库里没有的剧集改为进 helper 自己的季/集列表，播放仍交给 `mode=play`。
3. 电影直接播放，不受上述改动影响。

`library_id_by_provider` 用桩 xbmc 验证匹配规则；渲染部分只验证「目标路径怎么拼」，
不碰真实 Kodi / Emby。
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


class _Server(object):
    server_id = "srv1"
    base_url = "http://emby:8096"
    token = "T"
    user_id = "U"


class _Req(object):
    def __init__(self, media_type="movies", query="q", item_id=""):
        self.mode = "search"
        self.type = media_type
        self.query = query
        self.offset = 0
        self.item_id = item_id


def _item(name, folder, item_id="x", tmdb="", tvdb=""):
    return {"id": item_id, "name": name, "is_folder": folder,
            "tmdb": tmdb, "tvdb": tvdb, "image_tag": "", "backdrop_tag": ""}


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
            emby.render_search(1, "plugin://script.mistuary.helper/", _Req("shows"))

        return plugin, notice

    def test_synced_series_jumps_to_library(self):
        plugin, notice = self._render([_item("已同步剧", True, "e1", tmdb="1")],
                                      {"已同步剧": 42})
        self.assertEqual(plugin.items[0][0], "videodb://tvshows/titles/42/")
        self.assertTrue(plugin.items[0][2])
        notice.assert_not_called()

    def test_unsynced_series_opens_helper_browse(self):
        plugin, notice = self._render([_item("未同步剧", True, "e1", tmdb="2")], {})
        self.assertEqual(plugin.items[0][0],
                         "plugin://script.mistuary.helper/?mode=browse&id=e1")
        self.assertTrue(plugin.items[0][2])
        notice.assert_not_called()

    def test_movie_still_plays(self):
        plugin, notice = self._render([_item("电影", False, "m1")], {})
        self.assertEqual(plugin.items[0][0], emby.play_url(_Server(), "m1"))
        self.assertFalse(plugin.items[0][2])
        notice.assert_not_called()


class ChildrenTest(unittest.TestCase):
    PAYLOAD = {"Items": [
        {"Id": "s1", "Name": "第 1 季", "Type": "Season", "ProviderIds": {}},
        {"Id": "s2", "Name": "第 2 季", "Type": "Season", "ProviderIds": {}},
    ]}

    def test_normalizes_and_marks_season_as_folder(self):
        with mock.patch.object(emby.cache, "get", lambda *a, **k: None), \
                mock.patch.object(emby.cache, "put", lambda *a, **k: None), \
                mock.patch.object(emby.http, "get_json",
                                  lambda *a, **k: (self.PAYLOAD, _Resp())):
            items = emby.children(_Server(), "series1")
        self.assertEqual([i["id"] for i in items], ["s1", "s2"])
        self.assertTrue(items[0]["is_folder"])

    def test_requests_direct_children(self):
        seen = {}

        def fake_get(url, **kwargs):
            seen["url"] = url
            return self.PAYLOAD, _Resp()

        with mock.patch.object(emby.cache, "get", lambda *a, **k: None), \
                mock.patch.object(emby.cache, "put", lambda *a, **k: None), \
                mock.patch.object(emby.http, "get_json", fake_get):
            emby.children(_Server(), "series1")

        self.assertIn("ParentId=series1", seen["url"])
        self.assertIn("Recursive=false", seen["url"])

    def test_empty_id_returns_empty(self):
        self.assertEqual(emby.children(_Server(), ""), [])

    def test_http_failure_raises(self):
        with mock.patch.object(emby.cache, "get", lambda *a, **k: None), \
                mock.patch.object(emby.http, "get_json",
                                  lambda *a, **k: (None, _Resp(ok=False, status=500))):
            with self.assertRaises(emby.EmbyError):
                emby.children(_Server(), "series1")


class RenderBrowseTest(unittest.TestCase):
    def _render(self, items):
        plugin = FakeXbmcplugin()
        with mock.patch.dict(sys.modules,
                             {"xbmcgui": FakeXbmcgui, "xbmcplugin": plugin}), \
                mock.patch.object(kodi, "apply_video_info", lambda *a, **k: None), \
                mock.patch.object(kodi, "add_notice") as notice, \
                mock.patch.object(emby.config, "read_settings", lambda: {}), \
                mock.patch.object(emby.config, "find_server", lambda sid: _Server()), \
                mock.patch.object(emby, "children", lambda *a, **k: items):
            emby.render_browse(1, "plugin://script.mistuary.helper/", _Req(item_id="s1"))
        return plugin, notice

    def test_season_links_to_next_browse(self):
        plugin, _ = self._render([_item("第 1 季", True, "s1")])
        self.assertEqual(plugin.items[0][0],
                         "plugin://script.mistuary.helper/?mode=browse&id=s1")
        self.assertTrue(plugin.items[0][2])

    def test_episode_plays(self):
        plugin, _ = self._render([_item("第 1 集", False, "e1")])
        self.assertEqual(plugin.items[0][0], emby.play_url(_Server(), "e1"))
        self.assertFalse(plugin.items[0][2])

    def test_empty_result_shows_notice(self):
        plugin, notice = self._render([])
        self.assertEqual(plugin.items, [])
        notice.assert_called_once()


class _Resp(object):
    def __init__(self, ok=True, status=200, error=""):
        self.ok = ok
        self.status = status
        self.error = error


if __name__ == "__main__":
    unittest.main()
