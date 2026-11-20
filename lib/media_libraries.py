# -*- coding: utf-8 -*-
"""把 Kodi 本地视频源列成「媒体库」目录项。

官方 Kodi 22 没有 `videodb://medialibraries/`：上游 RC2 的
`medialibraries` / `sources=local` / `library.art` 都是魔改内核能力，
不能照搬。纯本地刮削库能稳定拿到的只有 `sources.xml` 里的 video source，
所以这里把每个 source 当成一个「媒体库」卡片返回给皮肤。

不做的事：
- 不解析 E4K 注入的 `emby-for-kodi-next-gen-*` 源（它是 Emby 库，不是本地库）；
- 不写任何库数据；只读 MyVideos 的 `path` 表拿「源 → 内容类型」；
- 不把 source 路径改写/library node（官方内核没有对应虚拟节点）；
- 不在数据层 import xbmc，纯函数可直接单测。

点击卡片进入的是对应视频源。若该源已刮削进 Kodi 库，仍能在文件视图里
看到刮削信息；这是官方内核上不依赖魔改的最稳路径。

类型来源：Kodi 新增视频源时选的「电影/电视剧」存在 `MyVideos*.db` 的
`path.strContent`（JSON-RPC 没有读取接口）。源没设过类型时归为「未分类」，
只在 `type=movies` 行里兜底出现，避免两页重复。
"""

from __future__ import annotations

import os
import re
import sqlite3
import urllib.parse
from pathlib import Path
import xml.etree.ElementTree as ET

from lib import config, library_icons, log

EMBY_SOURCE_PREFIX = "emby-for-kodi-next-gen-"
# 兼容源被改名但路径还是 E4K 注入路径的情况；普通本地源不会命中。
EMBY_PATH_MARKERS = ("/emby_addon_mode/", "127.0.0.1:57342")
# Kodi 视频源可选的内容类型里，本插件只关心这两种。
VIDEO_CONTENTS = ("movies", "tvshows")
_DB_NAME = re.compile(r"^myvideos(\d+)\.db$", re.IGNORECASE)


def video_db_path(profile: str | None = None) -> str:
    """当前版本的 MyVideos*.db；没有就返回空。"""
    folder = os.path.join(profile or config.profile_dir(), "Database")
    try:
        names = os.listdir(folder)
    except OSError:
        return ""
    best = None
    best_version = -1
    for name in names:
        match = _DB_NAME.match(name)
        if match and int(match.group(1)) > best_version:
            best, best_version = name, int(match.group(1))
    return os.path.join(folder, best) if best else ""


def normalize_source_path(path: str) -> str:
    """比较用：反斜杠转正斜杠、折叠重复斜杠、去尾斜杠、大小写归一。"""
    text = (path or "").strip().replace("\\", "/")
    if "://" in text:
        scheme, rest = text.split("://", 1)
        text = scheme.lower() + "://" + re.sub(r"/+", "/", rest)
    else:
        text = re.sub(r"/+", "/", text)
    return text.rstrip("/").casefold()


def library_content_map(profile: str | None = None) -> list[tuple[str, str]]:
    """只读 MyVideos 的 path 表，返回 [(归一化源路径, movies|tvshows)]。"""
    db_path = video_db_path(profile)
    if not db_path:
        return []
    try:
        uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    except (OSError, ValueError):
        return []
    try:
        con = sqlite3.connect(uri, uri=True, timeout=3.0)
        try:
            rows = con.execute(
                "SELECT strPath, strContent FROM path "
                "WHERE strContent IN ('movies','tvshows')"
            ).fetchall()
        finally:
            con.close()
    except (sqlite3.Error, OSError):
        return []
    return [(normalize_source_path(path), content)
            for path, content in rows if path]


def classify_source(path: str, rows) -> set[str]:
    """一个源包含哪些内容类型。

    优先按「源在某个已分类目录之下」找最长前缀；
    源是父目录时，收集其下所有已分类子目录的类型。
    """
    key = normalize_source_path(path)
    if not key:
        return set()
    ancestors = [(len(prefix), content) for prefix, content in rows
                 if key == prefix or key.startswith(prefix + "/")]
    if ancestors:
        longest = max(size for size, _ in ancestors)
        return {content for size, content in ancestors if size == longest}
    return {content for prefix, content in rows
            if prefix.startswith(key + "/")}


def filter_sources(items, rows, media_type: str):
    """按请求的媒体类型过滤；未设类型的源只留在 movies 行。"""
    if media_type not in VIDEO_CONTENTS:
        return list(items)
    result = []
    for item in items:
        kinds = classify_source(item.get("path", ""), rows)
        if media_type in kinds or (not kinds and media_type == "movies"):
            result.append(item)
    return result


def sources_path(profile: str | None = None) -> str:
    """Kodi 的 userdata/sources.xml。单测可传临时 profile。"""
    return os.path.join(profile or config.profile_dir(), "sources.xml")


def is_emby_source(name: str, path: str) -> bool:
    name = (name or "").strip().lower()
    path = (path or "").strip().lower()
    if name.startswith(EMBY_SOURCE_PREFIX):
        return True
    return any(marker in path for marker in EMBY_PATH_MARKERS)


def parse_sources(xml_text: str) -> list[dict]:
    """从 sources.xml 取 video source，过滤 E4K 注入项。畸形 XML 返回空。"""
    if not xml_text:
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    items = []
    for node in root.findall("./video/source"):
        name = (node.findtext("name") or "").strip()
        path = (node.findtext("path") or "").strip()
        if not name or not path or is_emby_source(name, path):
            continue
        thumb = (node.findtext("thumb") or "").strip()
        items.append({"name": name, "path": path, "thumb": thumb})
    return items


def local_sources(profile: str | None = None) -> list[dict]:
    """读本机 sources.xml；文件不存在/读失败都按没有本地源处理。"""
    try:
        with open(sources_path(profile), "r", encoding="utf-8") as handle:
            return parse_sources(handle.read())
    except (OSError, UnicodeError):
        return []


def cover_path(name: str, directory: str | None = None) -> str:
    """已有 helper 同步封面时把路径交给 ListItem，Skin 也能按库名再兜底。"""
    filename = library_icons.safe_name(name) + library_icons.IMAGE_SUFFIX
    path = os.path.join(directory or library_icons.icons_dir(), filename)
    return path if os.path.isfile(path) else ""


def render_libraries(handle: int, base_url: str, req, profile: str | None = None) -> bool:
    """mode=libraries 的渲染入口；目录由入口统一 endOfDirectory。"""
    import xbmcgui
    import xbmcplugin

    media_type = (getattr(req, "type", "") or "").strip().lower()
    items = local_sources(profile)
    total = len(items)
    if media_type in VIDEO_CONTENTS:
        items = filter_sources(items, library_content_map(profile), media_type)
    log.info("media libraries: %d/%d local video source(s), type=%s"
             % (len(items), total, media_type))

    try:
        xbmcplugin.setContent(handle, "videos")
    except AttributeError:
        pass

    for item in items:
        list_item = xbmcgui.ListItem(label=item["name"], offscreen=True)
        art = {}
        thumb = item.get("thumb") or cover_path(item["name"])
        if thumb:
            art["thumb"] = thumb
            art["poster"] = thumb
        if art:
            list_item.setArt(art)
        xbmcplugin.addDirectoryItem(handle, item["path"], list_item, isFolder=True)
    return True
