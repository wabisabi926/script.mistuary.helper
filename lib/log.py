# -*- coding: utf-8 -*-
"""日志：默认静默，只在插件设置里打开 debug_log 后写 kodi.log。

**绝不打印 AccessToken / UserId。** 排查问题只需要 ServerId 和 HTTP 状态码。

`xbmc` 是惰性 import 的：单测在没有 Kodi 的机器上跑时，日志直接丢弃，
不会因为 import 失败把整个测试拖垮。
"""

from __future__ import annotations

_PREFIX = "MISTUARY.HELPER"
_addon = None
_enabled_cache = None


def _enabled() -> bool:
    global _addon, _enabled_cache
    if _enabled_cache is not None:
        return _enabled_cache
    try:
        import xbmcaddon

        if _addon is None:
            _addon = xbmcaddon.Addon("script.mistuary.helper")
        _enabled_cache = bool(_addon.getSettingBool("debug_log"))
    except Exception:  # noqa: BLE001 - 设置读不到就静默
        _enabled_cache = False
    return _enabled_cache


def reset_cache() -> None:
    """改设置后清掉缓存（Kodi 里插件设置页关掉再开不会重启进程）。"""
    global _enabled_cache
    _enabled_cache = None


def _write(level: str, msg: str) -> None:
    try:
        import xbmc

        xbmc.log("%s [%s] %s" % (_PREFIX, level, msg), xbmc.LOGINFO)
    except Exception:  # noqa: BLE001 - 没有 xbmc 就丢弃
        pass


def debug(msg: str) -> None:
    if _enabled():
        _write("DEBUG", msg)


def info(msg: str) -> None:
    if _enabled():
        _write("INFO", msg)


def error(msg: str) -> None:
    """错误总是写日志（不受 debug_log 控制），但同样不含敏感值。"""
    _write("ERROR", msg)


def redact(value: str, keep: int = 4) -> str:
    """把 token 之类的值裁成 `abcd…`，只用于日志。"""
    if not value:
        return "<empty>"
    if len(value) <= keep:
        return "*" * len(value)
    return value[:keep] + "…" + "*" * 4
