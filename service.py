# -*- coding: utf-8 -*-
"""播放服务：播放列表补全 + 文件播放记录。

两个功能都从设置读取开关；关闭时对应回调立即返回，行为与没装插件一致。
文件播放记录默认开启，数据存在 ``addon_data/script.mistuary.helper/resume.db``。
"""

import os
import sys
import threading

import xbmc
import xbmcaddon
import xbmcvfs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import file_resume, log, playlist_sync


class HelperPlayer(xbmc.Player):
    def __init__(self, resume):
        super().__init__()
        self._resume = resume

    def onAVStarted(self):
        # 续播弹窗优先：播放列表补全可能耗时数秒（大目录/网络），
        # 不能挡在弹窗前面。用户选完（或取消）再补列表。
        try:
            self._resume.on_av_started()
        except Exception as exc:  # noqa: BLE001
            log.error("file resume start failed: %s" % exc)

        try:
            if self.isPlayingVideo() or self.isPlayingAudio():
                addon = xbmcaddon.Addon()
                season = addon.getSettingBool("playlist_completion_season")
                folder = addon.getSettingBool("playlist_completion_folder")
                next_season = addon.getSettingBool("playlist_completion_next_season")
                if season or folder:
                    playlist_sync.extend_playlist(season, folder, next_season)
        except Exception as exc:  # noqa: BLE001 - 服务不能因异常退出
            log.error("playlist completion failed: %s" % exc)

    def onPlayBackPaused(self):
        try:
            self._resume.on_paused()
        except Exception as exc:  # noqa: BLE001
            log.error("file resume pause failed: %s" % exc)

    def onPlayBackSeek(self, time, seekOffset):
        try:
            self._resume.on_seek()
        except Exception as exc:  # noqa: BLE001
            log.error("file resume seek failed: %s" % exc)

    def onPlayBackStopped(self):
        try:
            self._resume.on_stopped()
        except Exception as exc:  # noqa: BLE001
            log.error("file resume stop failed: %s" % exc)

    def onPlayBackEnded(self):
        try:
            self._resume.on_ended()
        except Exception as exc:  # noqa: BLE001
            log.error("file resume end failed: %s" % exc)


class HelperService(xbmc.Monitor):
    def __init__(self, resume):
        super().__init__()
        self._resume = resume

    def onCleanFinished(self, library=""):
        try:
            self._resume.on_clean_finished(library)
        except Exception as exc:  # noqa: BLE001
            log.error("file resume clean hook failed: %s" % exc)


def _sync_library_icons_once():
    """首次启动（没有 manifest）静默同步一次；之后只在设置页手动触发。"""
    try:
        from lib import config, library_icons

        if library_icons.has_manifest():
            return
        settings = config.read_settings()
        server = config.find_server(settings.get("server_id", ""))
        if server is None:
            return
        library_icons.sync(server)
    except Exception as exc:  # noqa: BLE001 - 后台线程不能影响服务
        log.error("library icons startup sync failed: %s" % exc)


if __name__ == "__main__":
    log.info("service started")
    # 开关状态属性以前只在插件入口 default.py 里发布，纯服务启动时不会写，
    # 重启 Kodi 后设置页所有 radiobutton 都会错显示成「关」。开机补一次。
    try:
        from lib import skin_bridge

        skin_bridge.snapshot()
    except Exception as exc:  # noqa: BLE001 - 可选状态不能挡住服务启动
        log.error("settings snapshot at startup failed: %s" % exc)
    threading.Thread(
        target=_sync_library_icons_once,
        name="mistuary-library-icons",
        daemon=True,
    ).start()
    profile = xbmcvfs.translatePath(
        "special://profile/addon_data/script.mistuary.helper"
    )
    store = file_resume.ResumeStore(os.path.join(profile, "resume.db"))
    resume = file_resume.FileResumeManager(store)
    resume.start()
    player = HelperPlayer(resume)
    monitor = HelperService(resume)

    # 背景色光底：400ms 轮询，源图停稳 300ms 才算一次；非影视窗口时线程按
    # 2s 空转，不做任何 PIL 计算。功能无常开（0.5.0 起无开关）。
    # 起不来也不能影响播放/续播主流程。
    glow_stop = threading.Event()
    try:
        from lib import fanart_glow

        glow = fanart_glow.FanartGlowMonitor()
        threading.Thread(
            target=glow.run,
            args=(glow_stop,),
            name="mistuary-fanart-glow",
            daemon=True,
        ).start()
    except Exception as exc:  # noqa: BLE001 - 服务不能因可选功能退出
        log.error("fanart glow service failed to start: %s" % exc)

    try:
        monitor.waitForAbort()
    finally:
        glow_stop.set()
        del player
        resume.stop()
