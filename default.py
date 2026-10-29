# -*- coding: utf-8 -*-
"""Mistuary Helper —— 入口，只做分发，不写业务。

Kodi 每次调用插件都会重新执行这个脚本，所以这里保持极薄：
解析 sys.argv → 交给 lib.router → 由对应模块处理。
调试时一眼能分清是"路由错了"还是"业务错了"。

两种调用形态：
  1. 目录：plugin://script.mistuary.helper/?mode=search&type=movies&query=...
     → 必须调用 endOfDirectory()，否则 Kodi 一直转圈
  2. 动作：RunScript(script.mistuary.helper,action=rating,dbid=...)
     → 不产生界面，只写窗口属性
"""

import sys

import xbmcaddon
import xbmcgui
import xbmcplugin

from lib import i18n, log, router

ADDON = xbmcaddon.Addon()
HANDLE = int(sys.argv[1]) if len(sys.argv) > 1 else -1
BASE_URL = sys.argv[0] if sys.argv else ""


def main():
    args = sys.argv[2] if len(sys.argv) > 2 else ""
    req = router.parse(args)
    log.debug("dispatch mode=%s action=%s type=%s" % (req.mode, req.action, req.type))

    if req.mode == "search":
        # 搜索是唯一会返回目录的模式。
        from lib import emby

        emby.render_search(HANDLE, BASE_URL, req)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=True, cacheToDisc=False)
        return

    if req.action == "rating":
        # P1：豆瓣评分。阶段 1 什么都不写，皮肤读到空属性就隐藏胶囊。
        from lib import douban

        douban.run_action(req)
        return

    if req.action == "techflags":
        # P2：代表集技术标识。
        from lib import techflags

        techflags.run_action(req)
        return

    if req.action == "clear_cache":
        from lib import cache

        removed = cache.clear()
        log.info("cache cleared: %d files" % removed)
        xbmcgui.Dialog().notification(
            ADDON.getAddonInfo("name"), i18n.t(32028), xbmcgui.NOTIFICATION_INFO, 3000
        )
        return

    # 无参数 / 无法识别：给出人话提示，不要静默什么都不做。
    xbmcgui.Dialog().ok(ADDON.getAddonInfo("name"), i18n.t(32020))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - 任何异常都不能把 Kodi 弹框炸出来
        log.error("unhandled: %s" % exc)
        # 目录模式下必须收尾，否则界面卡在加载状态
        if HANDLE >= 0:
            try:
                xbmcplugin.endOfDirectory(HANDLE, succeeded=False, cacheToDisc=False)
            except Exception:  # noqa: BLE001
                pass
