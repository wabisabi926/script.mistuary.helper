# -*- coding: utf-8 -*-
"""Emby 客户端：搜索 + 结果映射。

分工：
- `search()` 纯数据，返回 list[dict]，**可以直接单测**（HTTP 用 mock 替掉）
- `render_search()` 把 dict 变成 Kodi 的 ListItem（需要 xbmcgui，惰性 import）

**缓存里不放 token**：图片 URL 带 `api_key`，所以只缓存 `PrimaryImageTag`，
渲染时再拼完整地址。否则缓存文件会泄露令牌。
"""

from __future__ import annotations

from lib import cache, config, http, i18n, log

# movies / shows 两个页签各自查什么类型
TYPE_MAP = {
    "movies": "Movie",
    "shows": "Series",
}

# 只请求渲染需要的字段，减少响应体积
FIELDS = ",".join([
    "ProductionYear",
    "PremiereDate",
    "CommunityRating",
    "CriticRating",
    "Overview",
    "RunTimeTicks",
    "PrimaryImageTag",
    "BackdropImageTags",
    "ProviderIds",
    "UserData",
])

TICKS_PER_MINUTE = 6000000  # Emby 的 RunTimeTicks 是 100ns 单位


class EmbyError(Exception):
    """带状态码的错误，调用方据此决定给用户看什么。"""

    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


def image_url(server, item_id: str, tag: str, width: int = 400) -> str:
    """海报地址。tag 为空返回空串（调用方回退默认图）。"""
    if not tag:
        return ""
    return "%s/Items/%s/Images/Primary?tag=%s&maxWidth=%d&quality=90&api_key=%s" % (
        server.base_url, item_id, tag, width, server.token,
    )


def play_url(server, item_id: str) -> str:
    """播放地址走 Emby 插件自己的 mode=play，避免我们处理直链鉴权。

    ⚠️ 这条路径需要在实机上验证（helper-plugin-plan.md §3.5 第 3 条）：
    如果 `plugin://plugin.service.emby-next-gen/?mode=play&item=…` 打不开，
    退路是 `{base}/Videos/{Id}/stream?static=true&api_key=…`（直链，会带 token）。
    """
    return "plugin://plugin.service.emby-next-gen/?mode=play&item=%s&server=%s" % (
        item_id, server.server_id,
    )


def normalize(raw: dict) -> dict:
    """把 Emby 的 Item 压成渲染需要的字段。不含 token、不含完整图片地址。"""
    user_data = raw.get("UserData") or {}
    runtime_ticks = raw.get("RunTimeTicks") or 0
    try:
        runtime_min = int(runtime_ticks // TICKS_PER_MINUTE)
    except (TypeError, ValueError):
        runtime_min = 0

    provider_ids = raw.get("ProviderIds") or {}
    item_type = (raw.get("Type") or "").strip()

    return {
        "id": raw.get("Id") or "",
        "name": raw.get("Name") or "",
        "type": item_type,
        "is_folder": item_type == "Series",
        "year": raw.get("ProductionYear") or 0,
        "rating": raw.get("CommunityRating") or 0,
        "critic_rating": raw.get("CriticRating") or 0,
        "overview": raw.get("Overview") or "",
        "runtime_min": runtime_min,
        "image_tag": raw.get("PrimaryImageTag") or "",
        "played": bool(user_data.get("Played")),
        "position_ticks": user_data.get("PlaybackPositionTicks") or 0,
        "imdb": provider_ids.get("Imdb") or "",
        "tmdb": provider_ids.get("Tmdb") or "",
    }


def search(server, query: str, media_type: str, limit: int = 100, offset: int = 0,
           ttl: int = 300) -> list[dict]:
    """调 Emby 搜索，返回规范化后的条目列表。

    失败抛 EmbyError（带状态码），由 render_search 翻译成人话。
    """
    item_type = TYPE_MAP.get(media_type)
    if not item_type:
        raise EmbyError("unknown media type: %s" % media_type)

    key = cache.make_key("search", server.server_id, media_type, query, offset, limit)
    cached = cache.get(key, ttl)
    if cached is not None:
        log.debug("search cache hit: %s / %s" % (media_type, query))
        return cached

    url = http.build_url(server.base_url, "emby/Items", {
        "searchTerm": query,
        "Recursive": "true",
        "IncludeItemTypes": item_type,
        "Fields": FIELDS,
        "ImageTypeLimit": 1,
        "EnableImageTypes": "Primary",
        "Limit": limit,
        "StartIndex": offset or None,
        "UserId": server.user_id,
    })

    payload, resp = http.get_json(url, headers={"X-Emby-Token": server.token})
    if payload is None:
        log.error("search failed: status=%s error=%s" % (resp.status, resp.error))
        raise EmbyError(resp.error or "request failed", resp.status)

    raw_items = payload.get("Items") or []
    items = [normalize(item) for item in raw_items if item.get("Id")]
    log.debug("search %s / %r -> %d items" % (media_type, query, len(items)))

    # 空结果也缓存：用户连续打字时不必每次都打服务端
    cache.put(key, items)
    return items


def _human_error(exc: EmbyError) -> str:
    """把错误翻成用户能看懂的一句话（显示在结果列表里）。"""
    if exc.status in (401, 403):
        return i18n.t(32023)
    if exc.status == 0:
        return i18n.t(32024)
    return i18n.t(32025, exc.status)


def render_search(handle: int, base_url: str, req) -> bool:
    """搜索模式的渲染入口。返回 True 表示目录可以正常结束。"""
    import xbmcgui
    import xbmcplugin

    from lib import kodi

    settings = config.read_settings()
    server = config.find_server(settings.get("server_id", ""))
    if server is None:
        kodi.add_notice(handle, base_url, i18n.t(32021))
        return True

    if not req.query:
        kodi.add_notice(handle, base_url, i18n.t(32022))
        return True

    try:
        items = search(server, req.query, req.type or "movies",
                       limit=settings.get("page_size", 100),
                       offset=req.offset,
                       ttl=settings.get("cache_ttl", 300))
    except EmbyError as exc:
        kodi.add_notice(handle, base_url, _human_error(exc))
        return True

    for item in items:
        list_item = xbmcgui.ListItem(label=item["name"], offscreen=True)
        kodi.apply_video_info(list_item, item)
        art = {}
        poster = image_url(server, item["id"], item["image_tag"])
        if poster:
            art["poster"] = poster
            art["thumb"] = poster
        if art:
            list_item.setArt(art)

        target = play_url(server, item["id"]) if not item["is_folder"] else \
            "plugin://plugin.service.emby-next-gen/?mode=browse&id=%s&server=%s" % (
                item["id"], server.server_id)
        xbmcplugin.addDirectoryItem(handle, target, list_item, isFolder=item["is_folder"])

    # 分页：这一页满了就再给一条「加载更多」
    if len(items) >= settings.get("page_size", 100):
        from lib import router

        more = xbmcgui.ListItem(label=i18n.t(32027), offscreen=True)
        xbmcplugin.addDirectoryItem(
            handle,
            router.build_search_url(base_url, req.type or "movies", req.query,
                                    req.offset + len(items)),
            more,
            isFolder=True,
        )

    if not items:
        kodi.add_notice(handle, base_url, i18n.t(32026, req.query), playable=False)
    return True
