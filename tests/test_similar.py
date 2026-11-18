# -*- coding: utf-8 -*-
"""相似影片：E4K DBID 映射、Emby Similar、目录落点。

全部 HTTP / Kodi / 缓存 mock，不依赖网络和 Emby。
"""

import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import emby, http, kodi, router  # noqa: E402


class FakeServer(object):
    server_id = "srv1"
    name = "test"
    base_url = "http://emby:8096"
    token = "SECRET-TOKEN"
    user_id = "USER1"


def _raw(item_id, name, item_type="Movie", year=2020):
    return {
        "Id": item_id,
        "Name": name,
        "Type": item_type,
        "ProductionYear": year,
        "CommunityRating": 8.0,
        "RunTimeTicks": 120 * 6000000,
        "ImageTags": {"Primary": "tag-" + item_id},
        "BackdropImageTags": ["bd-" + item_id],
        "ProviderIds": {"Imdb": "tt-" + item_id, "Tmdb": "1" + item_id},
        "UserData": {"Played": False},
    }


class SimilarApiTest(unittest.TestCase):
    def _call(self, payload, **kwargs):
        resp = http.Response(ok=True, status=200)
        with mock.patch.object(emby.http, "get_json", return_value=(payload, resp)) as get:
            with mock.patch.object(emby.cache, "get", return_value=None), \
                    mock.patch.object(emby.cache, "put"):
                items = emby.similar(FakeServer(), "item-1", **kwargs)
        return items, get

    def test_url_token_and_source_excluded(self):
        payload = {"Items": [
            _raw("item-1", "源片"),
            _raw("item-2", "相似片"),
            _raw("item-3", "相似剧", "Series"),
        ]}
        items, get = self._call(payload, limit=10)
        self.assertEqual([x["id"] for x in items], ["item-2", "item-3"])
        call = get.call_args
        self.assertEqual(call.kwargs["headers"], {"X-Emby-Token": "SECRET-TOKEN"})
        parsed = urlparse(call.args[0])
        self.assertTrue(parsed.path.endswith("/emby/Items/item-1/Similar"))
        params = parse_qs(parsed.query)
        self.assertEqual(params["Limit"], ["10"])
        self.assertEqual(params["UserId"], ["USER1"])

    def test_cache_hit_skips_http(self):
        with mock.patch.object(emby.cache, "get", return_value=[{"id": "cached"}]), \
                mock.patch.object(emby.http, "get_json") as get:
            items = emby.similar(FakeServer(), "item-1")
        self.assertEqual(items, [{"id": "cached"}])
        get.assert_not_called()

    def test_error_carries_status(self):
        resp = http.Response(ok=False, status=401, error="http 401")
        with mock.patch.object(emby.cache, "get", return_value=None), \
                mock.patch.object(emby.http, "get_json", return_value=(None, resp)):
            with self.assertRaises(emby.EmbyError) as ctx:
                emby.similar(FakeServer(), "item-1")
        self.assertEqual(ctx.exception.status, 401)


class ResolveEmbyIdTest(unittest.TestCase):
    def test_prefers_passed_emby_id(self):
        req = router.parse("?mode=similar&type=movie&dbid=5&id=abc")
        self.assertEqual(emby.resolve_emby_id(FakeServer(), req), "abc")

    def test_uses_e4k_mapping(self):
        req = router.parse("?mode=similar&type=movie&dbid=5")
        with mock.patch.object(kodi, "emby_item_id", return_value="90423"):
            self.assertEqual(emby.resolve_emby_id(FakeServer(), req), "90423")

    def test_falls_back_to_title_search(self):
        req = router.parse("?mode=similar&type=movie&dbid=5")
        with mock.patch.object(kodi, "emby_item_id", return_value=""), \
                mock.patch.object(kodi, "video_meta", return_value={"title": "测试片", "year": 2020}), \
                mock.patch.object(emby, "search", return_value=[
                    {"id": "old", "name": "测试片", "year": 1999},
                    {"id": "new", "name": "测试片", "year": 2020},
                ]):
            self.assertEqual(emby.resolve_emby_id(FakeServer(), req), "new")

    def test_empty_title_returns_empty(self):
        req = router.parse("?mode=similar&type=movie&dbid=5")
        with mock.patch.object(kodi, "emby_item_id", return_value=""), \
                mock.patch.object(kodi, "video_meta", return_value={}):
            self.assertEqual(emby.resolve_emby_id(FakeServer(), req), "")


class SimilarTargetTest(unittest.TestCase):
    def test_synced_series_goes_to_kodi_library(self):
        item = {"id": "s1", "type": "Series", "is_folder": False,
                "name": "测试剧", "tmdb": "1", "tvdb": "2"}
        with mock.patch.object(kodi, "library_id_by_provider", return_value=12):
            target = emby._similar_target(FakeServer(), "plugin://helper/", item)
        self.assertEqual(target, "videodb://tvshows/titles/12/")

    def test_unsynced_series_goes_to_browse(self):
        item = {"id": "s1", "type": "Series", "is_folder": True,
                "name": "测试剧", "tmdb": "", "tvdb": ""}
        with mock.patch.object(kodi, "library_id_by_provider", return_value=0):
            target = emby._similar_target(FakeServer(), "plugin://helper/", item)
        self.assertIn("mode=browse&id=s1", target)

    def test_movie_plays_through_emby(self):
        item = {"id": "m1", "type": "Movie", "is_folder": False, "name": "测试片"}
        target = emby._similar_target(FakeServer(), "plugin://helper/", item)
        self.assertTrue(target.startswith("plugin://plugin.service.emby-next-gen/?mode=play"))


class E4kMappingTest(unittest.TestCase):
    def test_reads_movie_and_series_tables(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "emby_srv1.db")
            con = sqlite3.connect(path)
            con.execute("CREATE TABLE Movie (EmbyId INTEGER, KodiId INTEGER)")
            con.execute("CREATE TABLE Series (EmbyId INTEGER, KodiId INTEGER)")
            con.execute("INSERT INTO Movie VALUES (90423, 309)")
            con.execute("INSERT INTO Series VALUES (81490, 37)")
            con.commit()
            con.close()

            self.assertEqual(kodi.emby_item_id(309, "movie", db_path=path), "90423")
            self.assertEqual(kodi.emby_item_id(37, "tvshow", db_path=path), "81490")
            self.assertEqual(kodi.emby_item_id(999, "movie", db_path=path), "")
            self.assertEqual(kodi.emby_item_id(309, "unknown", db_path=path), "")

    def test_prefers_configured_server_db(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ("emby_srv1.db", "emby_other.db"):
                open(os.path.join(folder, name), "wb").close()
            self.assertEqual(
                os.path.basename(kodi.emby_database_path("srv1", folder=folder)),
                "emby_srv1.db")

    def test_falls_back_to_newest_db(self):
        with tempfile.TemporaryDirectory() as folder:
            old = os.path.join(folder, "emby_old.db")
            new = os.path.join(folder, "emby_new.db")
            open(old, "wb").close()
            open(new, "wb").close()
            os.utime(old, (1000, 1000))
            os.utime(new, (2000, 2000))
            self.assertEqual(
                os.path.basename(kodi.emby_database_path("", folder=folder)),
                "emby_new.db")


class SimilarUrlTest(unittest.TestCase):
    def test_builds_skin_facing_url(self):
        url = router.build_similar_url("plugin://helper/", "movie", "309")
        self.assertEqual(url, "plugin://helper/?mode=similar&type=movie&dbid=309")

    def test_appends_optional_emby_id(self):
        url = router.build_similar_url("plugin://helper/", "tvshow", "0", "abc")
        self.assertTrue(url.endswith("&dbid=0&id=abc"))


if __name__ == "__main__":
    unittest.main()
