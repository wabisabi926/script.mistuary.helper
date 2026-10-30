# -*- coding: utf-8 -*-
"""入口分发测试：action 模式在 plugin:// 调用下必须收尾目录。

2026-10-30 实测：Kodi 用 plugin://...?action=rating 调进来时，如果入口直接
return，日志会报 `CGUIMediaDirectory::GetDirectory(...) failed`。RunScript 没有
handle，不能调 endOfDirectory；只有插件目录调用才需要补。
"""

import importlib.util
import os
import sys
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class _FakeAddon(object):
    def getAddonInfo(self, key):
        return "Mistuary Helper"

    def getSettingString(self, key):
        return ""

    def getSettingInt(self, key):
        return 0

    def getSettingBool(self, key):
        return False


class _FakeWindow(object):
    def __init__(self, window_id):
        self.window_id = window_id
        self.props = {}

    def setProperty(self, key, value):
        self.props[key] = value

    def getProperty(self, key):
        return self.props.get(key, "")

    def clearProperty(self, key):
        self.props.pop(key, None)


class _FakeDialog(object):
    def notification(self, *args, **kwargs):
        pass

    def ok(self, *args, **kwargs):
        pass


class _FakeXbmcPlugin(object):
    def __init__(self):
        self.calls = []

    def endOfDirectory(self, handle, succeeded=True, cacheToDisc=True):
        self.calls.append((handle, succeeded, cacheToDisc))


class ActionDispatchTest(unittest.TestCase):
    def _run(self, argv, fake_plugin):
        fake_modules = {
            "xbmcaddon": types.SimpleNamespace(Addon=_FakeAddon),
            "xbmcgui": types.SimpleNamespace(
                Window=_FakeWindow,
                Dialog=_FakeDialog,
                ListItem=object,
                NOTIFICATION_INFO=0,
            ),
            "xbmcplugin": fake_plugin,
        }
        spec = importlib.util.spec_from_file_location(
            "default_under_test", os.path.join(ROOT, "default.py")
        )
        module = importlib.util.module_from_spec(spec)
        # main() 也要在 fake 模块上下文里跑：read_settings 会 import xbmcaddon。
        with mock.patch.dict(sys.modules, fake_modules), \
                mock.patch.object(sys, "argv", argv):
            spec.loader.exec_module(module)
            module.main()

    def test_plugin_directory_action_is_closed(self):
        """plugin://...?action=rating 有 handle，必须 endOfDirectory。"""
        plugin = _FakeXbmcPlugin()
        self._run(
            [
                "plugin://script.mistuary.helper/",
                "12",
                "?action=rating&type=movie&dbid=101&imdb=tt1533117",
            ],
            plugin,
        )
        self.assertEqual(plugin.calls, [(12, True, False)])

    def test_runscript_action_has_no_handle(self):
        """RunScript 的 handle=-1，不能调 endOfDirectory。"""
        plugin = _FakeXbmcPlugin()
        self._run(
            [
                "plugin://script.mistuary.helper/",
                "action=rating",
                "type=movie",
                "dbid=101",
                "imdb=tt1533117",
            ],
            plugin,
        )
        self.assertEqual(plugin.calls, [])


if __name__ == "__main__":
    unittest.main()
