# -*- coding: utf-8 -*-
"""后台服务：定时把 Emby 的豆瓣评分写进 Kodi 库。

只在本地读 Emby（StrmAssistant），不请求豆瓣；启动 60 秒后跑第一次，
之后按设置的间隔循环。任何异常只记日志，不弹框。
"""

from __future__ import annotations

from lib import config, log, rating_sync


START_DELAY_SECONDS = 60


def main() -> None:
    import xbmc

    monitor = xbmc.Monitor()
    log.info("rating sync service: started (delay=%ds)" % START_DELAY_SECONDS)

    # 等 Kodi 库和皮肤加载完再跑，避免启动期抢数据库
    if monitor.waitForAbort(START_DELAY_SECONDS):
        return




    while not monitor.abortRequested():
        settings = config.read_settings()

        log.debug("rating sync service: enabled=%s interval=%sh server=%s" % (
            settings.get("rating_sync_enabled"), settings.get("rating_sync_interval_hours"),
            "override" if settings.get("emby_url_override") else "e4k"))

        if settings.get("rating_sync_enabled", True):
            try:
                stats = rating_sync.sync(notify=True)
                if stats.get("error"):
                    log.debug("rating sync service: %s" % stats["error"])
            except Exception as exc:  # noqa: BLE001 - 后台服务不能因一次失败退出
                log.error("rating sync service failed: %s" % exc)

        hours = int(settings.get("rating_sync_interval_hours", 6) or 6)
        if monitor.waitForAbort(max(1, hours) * 3600):
            break


if __name__ == "__main__":
    main()
