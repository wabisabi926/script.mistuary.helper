# -*- coding: utf-8 -*-
"""本地 video source → 媒体库目录项测试。

不碰 Kodi/Emby：sources.xml 用字符串喂，ListItem / xbmcplugin 用 fake。
重点锁两件事：E4K 注入源必须过滤；目录项必须 isFolder=True。
"""

import os
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lib import library_icons, media_libraries  # noqa: E402

SOURCES = """<?xml version="1.0" encoding="UTF-8"?>
<sources>
  <video>
    <source><name>电影</name><path pathversion="1">D:\\Movies\\</path></source>
    <source><name>剧集</name><path pathversion="1">D:\\TV\\</path><thumb>D:\\tv.png</thumb></source>
    <source><name>emby-for-kodi-next-gen-addon-video</name><path pathversion="1">http://127.0.0.1:57342/</path></source>
    <source><name>改名过的 E4K</name><path pathversion="1">/emby_addon_mode/</path></source>
  </video>
  <music>
    <source><name>音乐</name><path pathversion="1">D:\\Music\\</path></source>
  </music>
</sources>
"""


class ParseSourcesTest(unittest.TestCase):
    def test_keeps_only_local_video_sources(self):
        items = media_libraries.parse_sources(SOURCES)
        self.assertEqual([item["name"] for item in items], ["电影", "剧集"])
        self.assertEqual(items[0]["path"], "D:\\Movies\\")
        self.assertEqual(items[1]["thumb"], "D:\\tv.png")

    def test_source_without_name_or_path_is_skipped(self):
        xml = """<sources><video>
          <source><name>无路径</name></source>
          <source><path>/tmp/movies</path></source>
        </video></sources>"""
        self.assertEqual(media_libraries.parse_sources(xml), [])

    def test_broken_xml_returns_empty(self):
        self.assertEqual(media_libraries.parse_sources("<sources><video>"), [])

    def test_local_sources_reads_profile_file(self):
        with tempfile.TemporaryDirectory() as profile:
            with open(os.path.join(profile, "sources.xml"), "w", encoding="utf-8") as handle:
                handle.write(SOURCES)
            items = media_libraries.local_sources(profile)
        self.assertEqual([item["name"] for item in items], ["电影", "剧集"])

    def test_missing_sources_file_is_empty(self):
        with tempfile.TemporaryDirectory() as profile:
            self.assertEqual(media_libraries.local_sources(profile), [])


class FakeListItem(object):
    def __init__(self, label, offscreen=False):
        self.label = label
        self.offscreen = offscreen
        self.art = {}

    def setArt(self, art):
        self.art.update(art)


class FakePlugin(object):
    def __init__(self):
        self.content = ""
        self.items = []

    def setContent(self, handle, content):
        self.content = content

    def addDirectoryItem(self, handle, path, item, isFolder=False):
        self.items.append((path, item, isFolder))


class RenderLibrariesTest(unittest.TestCase):
    def test_renders_folders_with_optional_cover(self):
        plugin = FakePlugin()
        with tempfile.TemporaryDirectory() as icons:
            cover = os.path.join(icons, "电影.png")
            with open(cover, "wb") as handle:
                handle.write(b"PNG")
            fake_modules = {
                "xbmcgui": types.SimpleNamespace(ListItem=FakeListItem),
                "xbmcplugin": plugin,
            }
            with mock.patch.dict(sys.modules, fake_modules), \
                    mock.patch.object(media_libraries, "local_sources",
                                      return_value=[
                                          {"name": "电影", "path": "D:\\Movies\\", "thumb": ""},
                                          {"name": "剧集", "path": "D:\\TV\\", "thumb": "D:\\tv.png"},
                                      ]), \
                    mock.patch.object(library_icons, "icons_dir", return_value=icons):
                ok = media_libraries.render_libraries(12, "plugin://helper/", mock.Mock(type="movies"))

        self.assertTrue(ok)
        self.assertEqual(plugin.content, "videos")
        self.assertEqual(len(plugin.items), 2)
        self.assertTrue(all(is_folder for _, _, is_folder in plugin.items))
        self.assertEqual(plugin.items[0][0], "D:\\Movies\\")
        self.assertEqual(plugin.items[0][1].art["thumb"].replace("\\", "/"), cover.replace("\\", "/"))
        self.assertEqual(plugin.items[1][1].art["thumb"], "D:\\tv.png")


if __name__ == "__main__":
    unittest.main()
