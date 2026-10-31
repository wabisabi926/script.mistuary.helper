# -*- coding: utf-8 -*-
"""Kodi 侧适配：ListItem 构造、提示项、窗口属性桥。

单独一层的原因：`xbmcgui.ListItem` 的字段名在 Kodi 19/20/21 之间改过
（`setInfo` 逐步让位给 `setInfoTag`），集中在这里改一处就够。
"""

from __future__ import annotations

MEDIATYPE = {
    "Movie": "movie",
    "Series": "tvshow",
    "Episode": "episode",
}


def apply_video_info(list_item, item: dict) -> None:
    """把规范化后的条目写进 ListItem。

    用 `setInfo("video", {...})` 而不是新的 `setInfoTag`：
    前者在 19/20/21 都工作，后者只有 20+ 才有。
    """
    info = {
        "title": item.get("name") or "",
        "mediatype": MEDIATYPE.get(item.get("type") or "", "video"),
    }
    if item.get("year"):
        info["year"] = int(item["year"])
    if item.get("overview"):
        info["plot"] = item["overview"]
    if item.get("rating"):
        try:
            info["rating"] = float(item["rating"])
        except (TypeError, ValueError):
            pass
    if item.get("runtime_min"):
        info["duration"] = int(item["runtime_min"]) * 60
    # IMDb / TMDb 的唯一 ID：Kodi 用它做「已看」「演员」等后续查询
    if item.get("imdb"):
        info["imdbnumber"] = item["imdb"]

    list_item.setInfo("video", info)

    # streamdetails 只能走 addStreamInfo —— setInfo 写不进去。
    # 皮肤的技术标识（4K / DV / HEVC / 声道）读的是 ListItem.VideoResolution
    # 这一组值，没有 streamdetails 就整排塌陷成空。
    video = item.get("video") or {}
    if video.get("width") or video.get("height"):
        details = {
            "codec": video.get("codec") or "",
            "width": video.get("width") or 0,
            "height": video.get("height") or 0,
        }
        if video.get("hdrtype"):
            details["hdrtype"] = video["hdrtype"]
        list_item.addStreamInfo("video", details)
    audio = item.get("audio") or {}
    if audio.get("codec") or audio.get("channels"):
        list_item.addStreamInfo("audio", {
            "codec": audio.get("codec") or "",
            "channels": audio.get("channels") or 0,
            "language": audio.get("language") or "",
        })

    # 已看 / 播放进度：Kodi 的 listitem 用 overlay 和 percent 属性
    if item.get("played"):
        list_item.setProperty("Overlay", "OverlayWatched.png")
    position = item.get("position_ticks") or 0
    runtime_ticks = (item.get("runtime_min") or 0) * 60 * 10000000
    if position and runtime_ticks:
        percent = min(100, int(position * 100 / runtime_ticks))
        if percent > 0:
            list_item.setProperty("percentplayed", str(percent))


def add_notice(handle: int, base_url: str, message: str, playable: bool = False) -> None:
    """在结果列表里放一条说明，而不是弹错误框。

    这是「失败静默降级」的具体做法：用户看到的是列表里的一句话，
    不会被对话框打断；皮肤容器也能正常结束，不会一直转圈。
    """
    import xbmcgui
    import xbmcplugin

    list_item = xbmcgui.ListItem(label=message, offscreen=True)
    list_item.setInfo("video", {"title": message, "plot": message, "mediatype": "video"})
    if not playable:
        # 不可播放：isFolder=False 且不设 path 时 Kodi 会当成死条目，
        # 用 IsPlayable=false 明确告诉它不要尝试播放
        list_item.setProperty("IsPlayable", "false")
    xbmcplugin.addDirectoryItem(handle, base_url, list_item, isFolder=False)


def end_directory(handle: int, succeeded: bool = True) -> None:
    """目录调用收尾。

    `RunScript` 的 handle 是 -1，不能调 endOfDirectory；只有通过
    `plugin://...?action=...` 进来的目录调用才需要。不补这一下，Kodi 会报
    `CGUIMediaWindow::GetDirectory(...) failed`。
    """
    if handle < 0:
        return

    import xbmcplugin

    xbmcplugin.endOfDirectory(handle, succeeded=succeeded, cacheToDisc=False)


def set_home_property(key: str, value: str) -> None:
    """写 Window(home) 属性 —— 皮肤读这个（HANDOVER §5.7）。"""
    import xbmcgui

    xbmcgui.Window(10000).setProperty(key, value or "")


def clear_home_property(key: str) -> None:
    import xbmcgui

    xbmcgui.Window(10000).clearProperty(key)


def video_uniqueid(dbid: int, kind: str = "imdb") -> str:
    """从 Kodi 媒体库取一个条目的 uniqueid。查不到返回空串，不抛异常。

    只用于 `dbid > 0` 的老调用方；Emby 动态条目通常没有 DBID，皮肤应直接传 imdb。
    """
    try:
        import json
        import xbmc

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "VideoLibrary.GetItemDetails",
            "params": {"itemid": int(dbid), "properties": ["uniqueid"]},
        }
        raw = xbmc.executeJSONRPC(json.dumps(payload))
        data = json.loads(raw)
        details = ((data.get("result") or {}).get("itemdetails") or {})
        return ((details.get("uniqueid") or {}).get(kind) or "").strip()
    except Exception:  # noqa: BLE001 - Kodi 不可用/条目不存在都按空处理
        return ""


def get_home_property(key: str) -> str:
    """读 Window(home) 属性。没有 Kodi 时返回空串。"""
    try:
        import xbmcgui

        return xbmcgui.Window(10000).getProperty(key) or ""
    except Exception:  # noqa: BLE001
        return ""


VIDEO_LIBRARY = {
    "movies": ("VideoLibrary.GetMovies", "movies", "movieid"),
    "tvshows": ("VideoLibrary.GetTVShows", "tvshows", "tvshowid"),
    "episodes": ("VideoLibrary.GetEpisodes", "episodes", "episodeid"),
}


def video_items(kind: str) -> list:
    """枚举 Kodi 库里某类条目：`[{"id": int, "imdb": str, "title": str}]`。

    分批取（每批 1000），只为拿到「Kodi 内部 id ↔ IMDb」的对应关系。
    失败返回空列表，不抛异常。
    """
    spec = VIDEO_LIBRARY.get(kind)
    if not spec:
        return []

    method, key, id_field = spec
    items = []
    start = 0
    try:
        import json
        import xbmc

        while True:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": method,
                "params": {
                    "properties": ["uniqueid", "title"],
                    "limits": {"start": start, "end": start + 1000},
                },
            }
            raw = xbmc.executeJSONRPC(json.dumps(payload))
            rows = (((json.loads(raw).get("result") or {}).get(key)) or [])
            if not rows:
                break
            for row in rows:
                items.append({
                    "id": row.get(id_field) or 0,
                    "imdb": ((row.get("uniqueid") or {}).get("imdb") or "").strip(),
                    "title": row.get("title") or "",
                })
            if len(rows) < 1000:
                break
            start += 1000
    except Exception:  # noqa: BLE001 - Kodi 不可用/库为空都按空处理
        return items
    return items


def database_path(prefix: str = "MyVideos") -> str:
    """返回版本号最大的 `<prefix><N>.db` 路径；找不到返回空串。"""
    try:
        import os
        import re
        import xbmcvfs

        folder = xbmcvfs.translatePath("special://database/")
        best, best_no = "", -1
        for name in os.listdir(folder):
            match = re.match(r"^%s(\d+)\.db$" % prefix, name, re.IGNORECASE)
            if match and int(match.group(1)) > best_no:
                best_no = int(match.group(1))
                best = os.path.join(folder, name)
        return best
    except Exception:  # noqa: BLE001
        return ""


def refresh_ui() -> None:
    """让界面重读数据库（评分行改动后调用）。

    只发 Container.Refresh 不够：库目录的结果在 CDirectoryCache 里，外部直接改
    sqlite 不会让它失效，皮肤拿到的还是旧的 VideoInfoTag（评分显示不出来）。
    补一次增量扫描来清缓存——它只处理变化的文件，正常情况下几十秒内跑完。
    """
    try:
        import xbmc

        xbmc.executebuiltin("Container.Refresh")
        xbmc.executebuiltin("UpdateLibrary(video)")
    except Exception:  # noqa: BLE001
        pass
