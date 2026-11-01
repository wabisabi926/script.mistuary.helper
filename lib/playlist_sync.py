# -*- coding: utf-8 -*-
"""播放列表补全：播放开始时把同季 / 同文件夹的后续条目加入队列。

只加不播，当前播放不受影响；两个开关都关时完全不动。
纯逻辑（选哪些条目）与 Kodi JSON-RPC 分开，方便单测。
"""

from __future__ import annotations

import json

from lib import log

AUDIO_EXT = {
    ".mp3", ".flac", ".m4a", ".m4b", ".aac", ".ogg", ".oga", ".opus",
    ".wav", ".wma", ".ape", ".alac", ".aif", ".aiff", ".dsf", ".dff",
    ".mka", ".wv", ".tak",
}

# 同目录里不该进播放列表的东西：字幕、刮削、图片、播放列表文件本身。
NON_MEDIA_EXT = {
    ".srt", ".ass", ".ssa", ".sub", ".idx", ".nfo", ".txt", ".xml",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tbn",
    ".cue", ".m3u", ".m3u8", ".log", ".sfv", ".md5",
}


def _norm(path) -> str:
    return (path or "").strip().replace("\\", "/").rstrip("/")


def _ext(path) -> str:
    name = _norm(path).rsplit("/", 1)[-1].split("?", 1)[0].split("#", 1)[0]
    dot = name.rfind(".")
    return name[dot:].casefold() if dot >= 0 else ""


def same_file(a, b) -> bool:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return False
    return a == b or a.casefold() == b.casefold()


def looks_like_video(path) -> bool:
    path = _norm(path)
    if not path:
        return False
    ext = _ext(path)
    if not ext:
        return True  # 插件路径通常没有扩展名
    return ext not in NON_MEDIA_EXT and ext not in AUDIO_EXT


def looks_like_audio(path) -> bool:
    path = _norm(path)
    if not path:
        return False
    ext = _ext(path)
    if not ext:
        return True  # 插件路径通常没有扩展名
    return ext in AUDIO_EXT


def following_episodes(episodes, current_episode):
    """按集号返回当前集之后的剧集（升序）。集号未知时返回空，避免猜。"""
    try:
        current = int(current_episode or 0)
    except (TypeError, ValueError):
        current = 0
    if current <= 0:
        return []
    picked = []
    for ep in episodes or []:
        try:
            number = int(ep.get("episode") or 0)
        except (TypeError, ValueError):
            continue
        if number > current:
            picked.append(ep)
    return sorted(picked, key=lambda e: (int(e.get("episode") or 0), int(e.get("episodeid") or 0)))


def following_files(files, current_file, media_type="video"):
    """按目录顺序返回当前文件之后的同类媒体文件。当前文件不在列表里时返回空。"""
    check = looks_like_audio if media_type == "audio" else looks_like_video
    clean = [f for f in (files or []) if check(f)]
    for idx, path in enumerate(clean):
        if same_file(path, current_file):
            return clean[idx + 1:]
    return []


def should_extend(season_enabled, folder_enabled, playlist_length) -> bool:
    """只补「单文件起播」：已有队列说明用户自己排过，不插手。"""
    try:
        length = int(playlist_length)
    except (TypeError, ValueError):
        return False
    return bool(season_enabled or folder_enabled) and length == 1


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def is_episode(item) -> bool:
    item = item or {}
    if item.get("type") == "episode":
        return True
    season = _as_int(item.get("season"))
    episode = _as_int(item.get("episode"))
    return season is not None and season >= 0 and episode is not None and episode > 0


def item_media_kind(item, player_type="video"):
    """按条目本身判断音频/视频；插件路径没有扩展名时才看播放器类型。"""
    item = item or {}
    item_type = (item.get("type") or "").casefold()
    if item_type in ("song", "audio"):
        return "audio"
    if item_type in ("episode", "movie", "musicvideo", "video"):
        return "video"
    ext = _ext(item.get("file"))
    if ext:
        return "audio" if ext in AUDIO_EXT else "video"
    return "audio" if player_type == "audio" else "video"


def choose_mode(media_kind, item, season_enabled, folder_enabled):
    """剧集优先走同季；拿不到季信息或不是剧集时回退同文件夹。"""
    if media_kind == "video" and season_enabled and is_episode(item):
        return "season"
    if folder_enabled:
        return "folder"
    return None


def folder_path_for(item):
    """取可列举的真实目录；plugin / http / pvr 这类路径返回空。"""
    folder = _norm((item or {}).get("folderpath"))
    if folder:
        return folder
    file = _norm((item or {}).get("file"))
    if not file:
        return ""
    if file.startswith(("plugin://", "http://", "https://", "pvr://")):
        return ""
    return file.rsplit("/", 1)[0]


def _rpc(method, params):
    try:
        import xbmc

        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        raw = xbmc.executeJSONRPC(json.dumps(payload))
        data = json.loads(raw) if raw else {}
        if data.get("error"):
            log.error("playlist rpc %s: %s" % (method, data.get("error")))
            return None
        return data.get("result")
    except Exception as exc:  # noqa: BLE001 - 服务里任何异常都不能中断播放
        log.error("playlist rpc %s failed: %s" % (method, exc))
        return None


def player_context():
    """返回 (playerid, playlistid, type)。Kodi 的 playerid 就是当前播放列表 id。"""
    result = _rpc("Player.GetActivePlayers", {}) or []
    for player in result:
        media_type = player.get("type")
        playerid = player.get("playerid")
        if media_type in ("video", "audio") and playerid is not None:
            return int(playerid), int(playerid), media_type
    return None


def current_item(playerid):
    # Player.GetItem 只接受 Item.Fields.Base 里的属性；folderpath / tvshowid / type / id
    # 都不在允许列表里，多写一个整条 RPC 就报 Invalid params。
    result = _rpc("Player.GetItem", {
        "playerid": int(playerid),
        "properties": ["title", "season", "episode", "file"],
    })
    return (result or {}).get("item") or {}


def playlist_length(playlistid) -> int:
    result = _rpc("Playlist.GetItems", {"playlistid": int(playlistid), "properties": ["file"]})
    return len((result or {}).get("items") or [])


def season_episodes(tvshowid, season):
    result = _rpc("VideoLibrary.GetEpisodes", {
        "tvshowid": int(tvshowid),
        "season": int(season),
        "properties": ["episode", "file"],
        "sort": {"method": "episode", "order": "ascending"},
    })
    return (result or {}).get("episodes") or []


def episode_details(episodeid):
    result = _rpc("VideoLibrary.GetEpisodeDetails", {
        "episodeid": int(episodeid),
        "properties": ["tvshowid", "season", "episode", "file", "title"],
    })
    return (result or {}).get("episodedetails") or {}


def folder_files(folderpath):
    result = _rpc("Files.GetDirectory", {
        "directory": folderpath,
        "media": "files",
        "properties": ["file"],
    })
    items = (result or {}).get("files") or []
    return [i.get("file") for i in items if i.get("filetype") == "file" and i.get("file")]


def season_targets(item):
    """返回同季后续剧集；不是剧集或缺季/集号时返回 None（交给同文件夹）。"""
    item = item or {}
    if not is_episode(item):
        return None
    tvshowid = item.get("tvshowid")
    season = _as_int(item.get("season"))
    episode = _as_int(item.get("episode"))
    if not tvshowid or season is None or season < 0 or not episode:
        details = episode_details(item.get("id") or 0) if item.get("id") else {}
        tvshowid = tvshowid or details.get("tvshowid")
        if season is None or season < 0:
            season = _as_int(details.get("season"))
        if not episode:
            episode = _as_int(details.get("episode"))
    if not tvshowid or season is None or season < 0 or not episode:
        return None
    return following_episodes(season_episodes(tvshowid, season), episode)


def _add_episodes(playlistid, episodes) -> int:
    added = 0
    for ep in episodes:
        episodeid = ep.get("episodeid")
        if not episodeid:
            continue
        if _rpc("Playlist.Add", {"playlistid": int(playlistid), "item": {"episodeid": int(episodeid)}}):
            added += 1
    return added


def extend_playlist(season_enabled=False, folder_enabled=False) -> int:
    """返回实际加入队列的条数；任何异常/不满足条件都返回 0。"""
    context = player_context()
    if not context:
        return 0
    playerid, playlistid, media_type = context

    if not should_extend(season_enabled, folder_enabled, playlist_length(playlistid)):
        return 0

    item = current_item(playerid)
    if not item:
        return 0

    media_kind = item_media_kind(item, media_type)
    mode = choose_mode(media_kind, item, season_enabled, folder_enabled)
    if mode == "season":
        picked = season_targets(item)
        if picked is not None:
            added = _add_episodes(playlistid, picked)
            log.debug("season completion: +%d" % added)
            return added
        if not folder_enabled:
            return 0

    if not folder_enabled:
        return 0

    folder = folder_path_for(item)
    if not folder:
        return 0
    picked = following_files(folder_files(folder), item.get("file"), media_kind)
    added = 0
    for path in picked:
        if _rpc("Playlist.Add", {"playlistid": int(playlistid), "item": {"file": path}}):
            added += 1
    log.debug("%s folder completion: +%d" % (media_kind, added))
    return added
