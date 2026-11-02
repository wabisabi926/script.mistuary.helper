# -*- coding: utf-8 -*-
"""播放列表补全服务。

Kodi 只在插件启用时加载它；两个补全开关都关闭（默认）时，
onAVStarted 直接返回，行为与没装插件完全一致。
"""

import os
import sys

import xbmc
import xbmcaddon

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import log, playlist_sync


class PlaylistFiller(xbmc.Player):
    def onAVStarted(self):
        try:
            if not (self.isPlayingVideo() or self.isPlayingAudio()):
                return
            addon = xbmcaddon.Addon()
            season = addon.getSettingBool("playlist_completion_season")
            folder = addon.getSettingBool("playlist_completion_folder")
            next_season = addon.getSettingBool("playlist_completion_next_season")
            if not (season or folder):
                return
            playlist_sync.extend_playlist(season, folder, next_season)
        except Exception as exc:  # noqa: BLE001 - 服务不能因异常退出
            log.error("playlist completion failed: %s" % exc)


class HelperService(xbmc.Monitor):
    pass


if __name__ == "__main__":
    log.info("service started")
    player = PlaylistFiller()
    monitor = HelperService()
    try:
        monitor.waitForAbort()
    finally:
        del player
