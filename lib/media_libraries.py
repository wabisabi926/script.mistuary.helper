# -*- coding: utf-8 -*-
"""把 Kodi 本地视频源列成「媒体库」目录项。

官方 Kodi 22 没有 `videodb://medialibraries/`：上游 RC2 的
`medialibraries` / `sources=local` / `library.art` 都是魔改内核能力，
不能照搬。纯本地刮削库能稳定拿到的只有 `sources.xml` 里的 video source，
所以这里把每个 source 当成一个「媒体库」卡片返回给皮肤。

不做的事：
- 不解析 E4K 注入的 `emby-for-kodi-next-gen-*` 源（它是 Emby 库，不是本地库）；
- 不把 source 路径改写/library node（官方内核没有对应虚拟节点）；
- 不在数据层 import xbmc，纯函数可直接单测。

点击卡片进入的是对应视频源。若该源已刮削进 Kodi 库，仍能在文件视图里
看到刮削信息；这是官方内核上不依赖魔改的最稳路径。
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET

from lib import config, library_icons, log

EMBY_SOURCE_PREFIX = "emby-for-kodi-next-gen-"
# 兼容源被改名但路径还是 E4K 注入路径的情况；普通本地源不会命中。
EMBY_PATH_MARKERS = ("/emby_addon_mode/", "127.0.0.1:57342")


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

    items = local_sources(profile)
    log.info("media libraries: %d local video source(s), type=%s"
             % (len(items), getattr(req, "type", "")))

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
