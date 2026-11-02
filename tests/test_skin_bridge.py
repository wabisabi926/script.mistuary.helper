# -*- coding: utf-8 -*-
"""皮肤助手页 ↔ 插件设置桥的测试：白名单、快照、切换、属性回写。"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import skin_bridge  # noqa: E402


class FakeAddon(object):
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.written = []

    def getSettingBool(self, key):
        return bool(self.values.get(key, False))

    def setSettingBool(self, key, value):
        self.values[key] = bool(value)
        self.written.append((key, bool(value)))


class SkinBridgeTest(unittest.TestCase):

    def setUp(self):
        self.props = {}
        self.addon = FakeAddon()
        p1 = mock.patch.object(skin_bridge, "_addon", return_value=self.addon)
        p2 = mock.patch.object(skin_bridge.kodi, "set_home_property",
                               side_effect=lambda k, v: self.props.__setitem__(k, v))
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)

    def test_snapshot_publishes_all_properties(self):
        self.addon.values = {"douban_enabled": True, "playlist_completion_season": False}
        self.assertTrue(skin_bridge.snapshot())
        self.assertEqual(self.props["Mistuary.Helper.DoubanEnabled"], "true")
        self.assertEqual(self.props["Mistuary.Helper.PlaylistSeason"], "false")
        self.assertEqual(self.props["Mistuary.Helper.PlaylistFolder"], "false")
        self.assertEqual(self.props["Mistuary.Helper.PlaylistNextSeason"], "false")

    def test_toggle_writes_setting_and_property(self):
        self.assertTrue(skin_bridge.toggle("playlist_completion_next_season"))
        self.assertTrue(self.addon.values["playlist_completion_next_season"])
        self.assertEqual(self.props["Mistuary.Helper.PlaylistNextSeason"], "true")
        self.assertTrue(skin_bridge.toggle("playlist_completion_next_season"))
        self.assertEqual(self.props["Mistuary.Helper.PlaylistNextSeason"], "false")

    def test_unknown_key_is_ignored(self):
        self.assertFalse(skin_bridge.toggle("emby_token_override"))
        self.assertEqual(self.addon.written, [])
        self.assertEqual(self.props, {})


if __name__ == "__main__":
    unittest.main()
