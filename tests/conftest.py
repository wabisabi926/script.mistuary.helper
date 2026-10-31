# -*- coding: utf-8 -*-
"""测试环境的最小 Kodi 模块桩。

本地/CI 没有 Kodi，`import xbmcvfs` 等会直接 ModuleNotFoundError；
这里注入足够用的假模块，保证测试和实机走同一套业务代码。
需要更细行为的用例可以自行覆盖 sys.modules。
"""

import os
import sys
import tempfile
import types


def _module(name):
    module = types.ModuleType(name)
    sys.modules.setdefault(name, module)
    return sys.modules[name]


# --- xbmc -------------------------------------------------------------------
xbmc = _module("xbmc")
xbmc.LOGINFO = 1
xbmc.LOGWARNING = 2
xbmc.LOGERROR = 3
xbmc.LOGDEBUG = 0


def _noop(*args, **kwargs):
    return None


xbmc.log = _noop
xbmc.getInfoLabel = lambda label: ""
xbmc.executebuiltin = _noop
xbmc.executeJSONRPC = lambda payload: '{"jsonrpc":"2.0","id":1,"result":{}}'
xbmc.sleep = _noop


class _Monitor(object):
    def abortRequested(self):
        return True

    def waitForAbort(self, timeout=None):
        return True


xbmc.Monitor = _Monitor


class _Player(object):
    def isPlaying(self):
        return False

    def getTime(self):
        return 0

    def getTotalTime(self):
        return 0


xbmc.Player = _Player

# --- xbmcgui ----------------------------------------------------------------
xbmcgui = _module("xbmcgui")
xbmcgui.NOTIFICATION_INFO = "info"
xbmcgui.NOTIFICATION_WARNING = "warning"
xbmcgui.NOTIFICATION_ERROR = "error"


class _Window(object):
    def __init__(self, *args, **kwargs):
        self._props = {}

    def setProperty(self, key, value):
        self._props[key] = value

    def getProperty(self, key):
        return self._props.get(key, "")

    def clearProperty(self, key):
        self._props.pop(key, None)


class _ListItem(object):
    def __init__(self, *args, **kwargs):
        pass

    def setProperty(self, key, value):
        pass

    def getProperty(self, key):
        return ""

    def setArt(self, *args, **kwargs):
        pass

    def setMimeType(self, *args, **kwargs):
        pass

    def setContentLookup(self, *args, **kwargs):
        pass

    def addStreamInfo(self, *args, **kwargs):
        pass

    def getVideoInfoTag(self):
        return _InfoTag()

    def getMusicInfoTag(self):
        return _InfoTag()


class _InfoTag(object):
    def __getattr__(self, name):
        return _noop


class _Dialog(object):
    def notification(self, *args, **kwargs):
        pass

    def ok(self, *args, **kwargs):
        pass


xbmcgui.Window = _Window
xbmcgui.ListItem = _ListItem
xbmcgui.Dialog = _Dialog

# --- xbmcaddon --------------------------------------------------------------
xbmcaddon = _module("xbmcaddon")


class _Addon(object):
    # 与 lib/config.py 的 DEFAULTS 保持一致，测试才能走“功能默认开启”的路径
    _BOOLS = {"douban_enabled": True, "douban_prefer_emby": True,
              "rating_sync_enabled": True, "debug_log": False}
    _INTS = {"page_size": 100, "cache_ttl": 300, "rating_sync_interval_hours": 6}
    _STRINGS = {"server_id": "", "emby_url_override": "", "emby_token_override": ""}

    def getAddonInfo(self, key):
        return "Mistuary Helper"

    def getLocalizedString(self, string_id):
        return ""

    def getSettingString(self, key):
        return self._STRINGS.get(key, "")

    def getSettingInt(self, key):
        return self._INTS.get(key, 0)

    def getSettingBool(self, key):
        return self._BOOLS.get(key, False)


xbmcaddon.Addon = lambda *args, **kwargs: _Addon()

# --- xbmcplugin -------------------------------------------------------------
xbmcplugin = _module("xbmcplugin")
xbmcplugin.addDirectoryItem = _noop
xbmcplugin.endOfDirectory = _noop
xbmcplugin.setContent = _noop

# --- xbmcvfs ----------------------------------------------------------------
xbmcvfs = _module("xbmcvfs")
_PROFILE = os.path.join(tempfile.gettempdir(), "mistuary-helper-test-profile")
os.makedirs(_PROFILE, exist_ok=True)


def _translate_path(path):
    if path == "special://profile":
        return _PROFILE
    if path.startswith("special://profile/"):
        return os.path.join(_PROFILE, path[len("special://profile/"):])
    return path


xbmcvfs.translatePath = _translate_path
