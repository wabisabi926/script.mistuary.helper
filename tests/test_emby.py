# -*- coding: utf-8 -*-
"""Emby 客户端测试：结果映射、缓存命中、错误映射。

HTTP 全部 mock，不依赖网络、不依赖 Emby。
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import emby, http  # noqa: E402


class FakeServer(object):
    server_id = "srv1"
    name = "test"
    base_url = "http://emby:8096"
    token = "SECRET-TOKEN"
    user_id = "USER1"


RAW_ITEM = {
    "Id": "item-1",
    "Name": "让子弹飞",
    "Type": "Movie",
    "ProductionYear": 2010,
    "CommunityRating": 8.9,
    "CriticRating": 90,
    "Overview": "民国年间，马邦德买官上任。",
    "RunTimeTicks": 132 * 6000000,
    # Emby 的 /Items?searchTerm= 实际返回 ImageTags.Primary，不是 PrimaryImageTag
    "ImageTags": {"Primary": "tag-abc"},
    "BackdropImageTags": ["bd-1"],
    "ProviderIds": {"Imdb": "tt1340507", "Tmdb": "44719"},
    "UserData": {"Played": False, "PlaybackPositionTicks": 0},
}


class NormalizeTest(unittest.TestCase):
    def test_basic_fields(self):
        item = emby.normalize(RAW_ITEM)
        self.assertEqual(item["id"], "item-1")
        self.assertEqual(item["name"], "让子弹飞")
        self.assertEqual(item["year"], 2010)
        self.assertEqual(item["runtime_min"], 132)
        self.assertEqual(item["imdb"], "tt1340507")
        self.assertFalse(item["is_folder"])

    def test_series_is_folder(self):
        item = emby.normalize(dict(RAW_ITEM, Type="Series"))
        self.assertTrue(item["is_folder"])

    def test_missing_fields_do_not_crash(self):
        item = emby.normalize({"Id": "x"})
        self.assertEqual(item["name"], "")
        self.assertEqual(item["year"], 0)
        self.assertEqual(item["runtime_min"], 0)
        self.assertEqual(item["image_tag"], "")
        self.assertEqual(item["backdrop_tag"], "")
        self.assertEqual(item["imdb"], "")

    def test_none_userdata(self):
        item = emby.normalize(dict(RAW_ITEM, UserData=None))
        self.assertFalse(item["played"])

    def test_normalized_dict_has_no_token(self):
        """缓存会把这个 dict 落盘，绝不能带令牌。"""
        item = emby.normalize(RAW_ITEM)
        self.assertNotIn("SECRET-TOKEN", repr(item))
        self.assertNotIn("api_key", repr(item))


class ImageTagTest(unittest.TestCase):
    def test_reads_image_tags_primary(self):
        item = emby.normalize(dict(RAW_ITEM))
        self.assertEqual(item["image_tag"], "tag-abc")

    def test_prefers_legacy_primary_image_tag(self):
        raw = dict(RAW_ITEM, PrimaryImageTag="legacy-tag")
        self.assertEqual(emby.normalize(raw)["image_tag"], "legacy-tag")

    def test_image_tags_not_a_dict_does_not_crash(self):
        for bad in (None, "x", 3):
            item = emby.normalize(dict(RAW_ITEM, ImageTags=bad))
            self.assertEqual(item["image_tag"], "")

    def test_backdrop_tag_takes_first(self):
        item = emby.normalize(dict(RAW_ITEM, BackdropImageTags=["bd-1", "bd-2"]))
        self.assertEqual(item["backdrop_tag"], "bd-1")

    def test_backdrop_tag_empty_and_not_a_list(self):
        self.assertEqual(emby.normalize(dict(RAW_ITEM, BackdropImageTags=[]))["backdrop_tag"], "")
        self.assertEqual(emby.normalize(dict(RAW_ITEM, BackdropImageTags=None))["backdrop_tag"], "")

    def test_cached_dict_has_no_url(self):
        """缓存落盘的是 tag，不能是带 api_key 的地址。"""
        item = emby.normalize(dict(RAW_ITEM))
        self.assertNotIn("Images/", repr(item))
        self.assertNotIn("api_key", repr(item))


class ImageUrlTest(unittest.TestCase):
    def test_builds_url(self):
        url = emby.image_url(FakeServer(), "item-1", "tag-abc", width=400)
        self.assertIn("/Items/item-1/Images/Primary", url)
        self.assertIn("tag=tag-abc", url)
        self.assertIn("maxWidth=400", url)

    def test_empty_tag_returns_empty(self):
        self.assertEqual(emby.image_url(FakeServer(), "item-1", ""), "")


class BackdropUrlTest(unittest.TestCase):
    def test_builds_url(self):
        url = emby.backdrop_url(FakeServer(), "item-1", "bd-1")
        self.assertIn("/Items/item-1/Images/Backdrop/0", url)
        self.assertIn("tag=bd-1", url)
        self.assertIn("maxWidth=1920", url)

    def test_empty_tag_returns_empty(self):
        self.assertEqual(emby.backdrop_url(FakeServer(), "item-1", ""), "")


class SearchTest(unittest.TestCase):
    def setUp(self):
        patcher_get = mock.patch.object(emby.cache, "get", return_value=None)
        patcher_put = mock.patch.object(emby.cache, "put", return_value=True)
        self.mock_get = patcher_get.start()
        self.mock_put = patcher_put.start()
        self.addCleanup(patcher_get.stop)
        self.addCleanup(patcher_put.stop)

    def test_search_maps_items(self):
        payload = {"Items": [RAW_ITEM, dict(RAW_ITEM, Id="item-2", Name="让子弹飞2")]}
        with mock.patch.object(emby.http, "get_json",
                               return_value=(payload, http.Response(ok=True, status=200))):
            items = emby.search(FakeServer(), "让子弹飞", "movies")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[1]["name"], "让子弹飞2")

    def test_search_sends_token_header(self):
        captured = {}

        def fake_get_json(url, headers=None, timeout=6):
            captured["url"] = url
            captured["headers"] = headers
            return {"Items": []}, http.Response(ok=True, status=200)

        with mock.patch.object(emby.http, "get_json", side_effect=fake_get_json):
            emby.search(FakeServer(), "x", "movies")

        self.assertEqual(captured["headers"].get("X-Emby-Token"), "SECRET-TOKEN")
        self.assertIn("searchTerm=x", captured["url"])
        self.assertIn("IncludeItemTypes=Movie", captured["url"])

    def test_series_uses_series_type(self):
        captured = {}

        def fake_get_json(url, headers=None, timeout=6):
            captured["url"] = url
            return {"Items": []}, http.Response(ok=True, status=200)

        with mock.patch.object(emby.http, "get_json", side_effect=fake_get_json):
            emby.search(FakeServer(), "x", "shows")
        self.assertIn("IncludeItemTypes=Series", captured["url"])

    def test_cache_hit_skips_http(self):
        self.mock_get.return_value = [{"id": "cached"}]
        with mock.patch.object(emby.http, "get_json") as fake:
            items = emby.search(FakeServer(), "x", "movies")
        fake.assert_not_called()
        self.assertEqual(items, [{"id": "cached"}])

    def test_empty_result_is_cached(self):
        with mock.patch.object(emby.http, "get_json",
                               return_value=({"Items": []}, http.Response(ok=True, status=200))):
            emby.search(FakeServer(), "x", "movies")
        self.mock_put.assert_called_once()
        self.assertEqual(self.mock_put.call_args[0][1], [])

    def test_http_failure_raises_emby_error(self):
        with mock.patch.object(emby.http, "get_json",
                               return_value=(None, http.Response(ok=False, status=401))):
            with self.assertRaises(emby.EmbyError) as ctx:
                emby.search(FakeServer(), "x", "movies")
        self.assertEqual(ctx.exception.status, 401)

    def test_unreachable_raises_with_status_zero(self):
        with mock.patch.object(emby.http, "get_json",
                               return_value=(None, http.Response(ok=False, status=0))):
            with self.assertRaises(emby.EmbyError) as ctx:
                emby.search(FakeServer(), "x", "movies")
        self.assertEqual(ctx.exception.status, 0)

    def test_unknown_media_type_raises(self):
        with self.assertRaises(emby.EmbyError):
            emby.search(FakeServer(), "x", "episodes")

    def test_invalid_json_raises(self):
        with mock.patch.object(emby.http, "get_json",
                               return_value=(None, http.Response(ok=False, status=200,
                                                                 error="invalid json"))):
            with self.assertRaises(emby.EmbyError):
                emby.search(FakeServer(), "x", "movies")


class HumanErrorTest(unittest.TestCase):
    def test_401_message_mentions_reconnect(self):
        text = emby._human_error(emby.EmbyError("x", 401))
        self.assertIn("登录", text)

    def test_zero_status_mentions_unreachable(self):
        text = emby._human_error(emby.EmbyError("x", 0))
        self.assertIn("不可达", text)

    def test_other_status_has_code(self):
        text = emby._human_error(emby.EmbyError("x", 500))
        self.assertIn("500", text)


if __name__ == "__main__":
    unittest.main()
