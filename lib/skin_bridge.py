# -*- coding: utf-8 -*-
"""皮肤助手页与插件设置的桥。

皮肤不能可靠地直接读写别的 addon，所以由本插件把几个主要开关写成
Window(home) 属性；皮肤只读属性、点击时回调 toggle_setting。

属性（值都是 "true" / "false"）：

    Mistuary.Helper.DoubanEnabled
    Mistuary.Helper.PlaylistSeason
    Mistuary.Helper.PlaylistFolder
    Mistuary.Helper.PlaylistNextSeason
"""

from __future__ import annotations

from lib import kodi, log

SETTINGS = {
    "douban_enabled": "Mistuary.Helper.DoubanEnabled",
    "playlist_completion_season": "Mistuary.Helper.PlaylistSeason",
    "playlist_completion_folder": "Mistuary.Helper.PlaylistFolder",
    "playlist_completion_next_season": "Mistuary.Helper.PlaylistNextSeason",
}


def _addon():
    import xbmcaddon

    return xbmcaddon.Addon()


def _publish(addon, key):
    prop = SETTINGS[key]
    value = "true" if addon.getSettingBool(key) else "false"
    kodi.set_home_property(prop, value)


def snapshot() -> bool:
    """把主要开关一次性写进窗口属性；失败返回 False，不抛异常。"""
    try:
        addon = _addon()
        for key in SETTINGS:
            _publish(addon, key)
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("settings snapshot failed: %s" % exc)
        return False


def toggle(key: str) -> bool:
    """切换白名单里的开关；未知 key 直接忽略。"""
    if key not in SETTINGS:
        log.error("unknown helper setting: %s" % key)
        return False
    try:
        addon = _addon()
        value = not addon.getSettingBool(key)
        addon.setSettingBool(key, value)
        _publish(addon, key)
        log.debug("helper setting %s -> %s" % (key, value))
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("toggle helper setting failed: %s" % exc)
        return False
