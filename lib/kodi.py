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
