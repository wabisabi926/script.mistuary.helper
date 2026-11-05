# -*- coding: utf-8 -*-
"""媒体库封面同步测试：HTTP 全部 mock，输出到临时目录。

不碰真实 Kodi / Emby，只验证落盘规则、manifest 跳过逻辑和失败回退。
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import http, library_icons  # noqa: E402


class FakeServer(object):
    server_id = "srv1"
    name = "test"
    base_url = "http://emby:8096"
    token = "SECRET-TOKEN"
    user_id = "USER1"


VIEWS = {
    "Items": [
        {"Id": "3", "Name": "华语电影", "ImageTags": {"Primary": "tag-1"}},
        {"Id": "4", "Name": "a/b:c", "ImageTags": {"Primary": "tag-2"}},
        {"Id": "5", "Name": "No Cover", "ImageTags": {}},
    ]
}

OK_IMAGE = http.Response(ok=True, status=200, body=b"JPEG-DATA")


def _views_response(items):
    return items, http.Response(ok=True, status=200)


class SafeNameTest(unittest.TestCase):
    def test_replaces_illegal_characters(self):
        self.assertEqual(library_icons.safe_name("a/b:c*?"), "a_b_c__")

    def test_strips_spaces_and_trailing_dots(self):
        self.assertEqual(library_icons.safe_name(" 华语电影 "), "华语电影")
        self.assertEqual(library_icons.safe_name("trailing. "), "trailing")

    def test_empty_name(self):
        self.assertEqual(library_icons.safe_name(""), "")


class SyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _sync(self, views=VIEWS, image_response=OK_IMAGE):
        with mock.patch.object(
            library_icons.http, "get_json", return_value=_views_response(views)
        ), mock.patch.object(
            library_icons.http, "request", return_value=image_response
        ) as request:
            result = library_icons.sync(FakeServer(), directory=self.tmp.name)
        return result, request

    def _path(self, name):
        return os.path.join(self.tmp.name, name)

    def _manifest(self):
        path = os.path.join(self.tmp.name, library_icons.MANIFEST_NAME)
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def test_writes_covers_by_name(self):
        result, request = self._sync()
        self.assertEqual(result["saved"], 3)
        self.assertEqual(result["failed"], 0)
        self.assertTrue(os.path.isfile(self._path("华语电影.png")))
        self.assertTrue(os.path.isfile(self._path("a_b_c.png")))
        self.assertEqual(request.call_count, 2)

    def test_library_without_cover_gets_placeholder(self):
        """没封面的库也必须落文件，否则皮肤每次渲染都会报贴图加载失败。"""
        self._sync()
        path = self._path("No Cover.png")
        self.assertTrue(os.path.isfile(path))
        with open(path, "rb") as handle:
            data = handle.read()
        self.assertEqual(data, library_icons.PLACEHOLDER_PNG)
        self.assertEqual(data[:4], b"\x89PNG")
        manifest = self._manifest()["libraries"]["No Cover"]
        self.assertTrue(manifest.get("placeholder"))

    def test_request_uses_png_and_expected_item(self):
        _, request = self._sync()
        urls = [call[0][0] for call in request.call_args_list]
        self.assertTrue(any("Items/3/Images/Primary" in url for url in urls))
        self.assertTrue(all("format=png" in url for url in urls))
        self.assertTrue(all("maxWidth=640" in url for url in urls))

    def test_manifest_has_no_token(self):
        self._sync()
        path = self._path(library_icons.MANIFEST_NAME)
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
        self.assertNotIn("SECRET-TOKEN", text)
        manifest = json.loads(text)
        self.assertEqual(manifest["libraries"]["华语电影"]["id"], "3")
        self.assertEqual(manifest["libraries"]["华语电影"]["tag"], "tag-1")

    def test_second_run_skips_unchanged(self):
        self._sync()
        result, request = self._sync()
        self.assertEqual(result["skipped"], 3)
        self.assertEqual(result["saved"], 0)
        self.assertEqual(request.call_count, 0)

    def test_changed_tag_reloads_only_that_library(self):
        self._sync()
        views = {
            "Items": [
                {"Id": "3", "Name": "华语电影", "ImageTags": {"Primary": "tag-new"}},
                {"Id": "4", "Name": "a/b:c", "ImageTags": {"Primary": "tag-2"}},
            ]
        }
        result, request = self._sync(views=views)
        self.assertEqual(result["saved"], 1)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["removed"], 1)
        self.assertEqual(request.call_count, 1)
        url = request.call_args[0][0]
        self.assertIn("Items/3/Images/Primary", url)
        self.assertIn("tag=tag-new", url)

    def test_failed_download_keeps_old_file_and_tag(self):
        self._sync()
        views = {
            "Items": [
                {"Id": "3", "Name": "华语电影", "ImageTags": {"Primary": "tag-new"}},
                {"Id": "4", "Name": "a/b:c", "ImageTags": {"Primary": "tag-2"}},
            ]
        }
        result, _ = self._sync(
            views=views,
            image_response=http.Response(ok=False, status=500, error="http 500"),
        )
        self.assertEqual(result["failed"], 1)
        self.assertTrue(os.path.isfile(self._path("华语电影.png")))
        self.assertEqual(
            self._manifest()["libraries"]["华语电影"]["tag"], "tag-1"
        )

    def test_removed_library_deletes_file(self):
        self._sync()
        views = {
            "Items": [
                {"Id": "4", "Name": "a/b:c", "ImageTags": {"Primary": "tag-2"}},
            ]
        }
        result, _ = self._sync(views=views)
        self.assertEqual(result["removed"], 2)
        self.assertFalse(os.path.exists(self._path("华语电影.png")))
        self.assertFalse(os.path.exists(self._path("No Cover.png")))
        self.assertTrue(os.path.isfile(self._path("a_b_c.png")))

    def test_legacy_jpeg_files_are_swept(self):
        """旧版本存 .jpg，迁移后要被删掉，否则一直占空间。"""
        legacy = self._path("旧库.jpg")
        with open(legacy, "wb") as handle:
            handle.write(b"JPEG-DATA")
        self._sync()
        self.assertFalse(os.path.exists(legacy))
        self.assertEqual(set(os.listdir(self.tmp.name)), {
            "No Cover.png", "a_b_c.png", "华语电影.png", library_icons.MANIFEST_NAME,
        })

    def test_legacy_manifest_forces_resync(self):
        """v1 的 .jpg manifest 不算数，service 启动时会重跑一次同步。"""
        self.assertTrue(library_icons.has_manifest(self.tmp.name) is False)
        self._sync()
        self.assertTrue(library_icons.has_manifest(self.tmp.name))
        path = self._path(library_icons.MANIFEST_NAME)
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        payload["version"] = 1
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        self.assertFalse(library_icons.has_manifest(self.tmp.name))

    def test_views_failure_returns_error(self):
        with mock.patch.object(
            library_icons.http,
            "get_json",
            return_value=(None, http.Response(ok=False, status=0, error="unreachable")),
        ):
            result = library_icons.sync(FakeServer(), directory=self.tmp.name)
        self.assertEqual(result["error"], "unreachable")
        self.assertEqual(result["saved"], 0)
        self.assertEqual(os.listdir(self.tmp.name), [])


if __name__ == "__main__":
    unittest.main()
