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
    "SortName",
    "OriginalTitle",
    # 搜索结果的 hero 要显示 4K / HEVC / TRUEHD 那排技术标识，
    # 皮肤读的是 ListItem.VideoResolution / VideoCodec / AudioCodec，
    # 这些值只能来自 streamdetails —— 不请求 MediaSources 就永远是空的。
    "MediaSources",
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


def backdrop_url(server, item_id: str, tag: str, width: int = 1920) -> str:
    """背景图地址（取第一张 Backdrop）。tag 为空返回空串，调用方回退皮肤兜底。"""
    if not tag:
        return ""
    return "%s/Items/%s/Images/Backdrop/0?tag=%s&maxWidth=%d&quality=90&api_key=%s" % (
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


def _hdr_type(video_range_type: str) -> str:
    """Emby 的 VideoRangeType → Kodi 的 hdrtype 字符串（Kodi 21 的取值）。

    认不出来就返回空串：Kodi 收到未知值会直接不认，不如不给。
    """
    value = (video_range_type or "").strip().upper()
    if not value or value == "SDR":
        return ""
    if value.startswith("DOVI"):
        return "dolbyvision"
    if value in ("HDR10PLUS", "HDR10+"):
        return "hdr10plus"
    if value.startswith("HDR10"):
        return "hdr10"
    if value == "HLG":
        return "hlg"
    return ""


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

    # 流信息：电影/单集有 MediaSources，剧集（Series）本身没有 —— 所以剧集行
    # 在搜索页仍然拿不到技术标识，这不是皮肤的问题。
    media_sources = raw.get("MediaSources")
    if not isinstance(media_sources, list):
        media_sources = []
    streams = []
    if media_sources and isinstance(media_sources[0], dict):
        streams = media_sources[0].get("MediaStreams") or []
    video_stream = next(
        (s for s in streams if (s.get("Type") or "").lower() == "video"), {})
    audio_stream = next(
        (s for s in streams if (s.get("Type") or "").lower() == "audio"), {})

    # Emby 的 /Items?searchTerm= 返回的是 ImageTags.Primary，不是 PrimaryImageTag；
    # 老版本/别的端点才给 PrimaryImageTag。两个都认，先旧后新。
    image_tags = raw.get("ImageTags")
    if not isinstance(image_tags, dict):
        image_tags = {}
    backdrop_tags = raw.get("BackdropImageTags")
    if not isinstance(backdrop_tags, list):
        backdrop_tags = []

    return {
        "id": raw.get("Id") or "",
        "name": raw.get("Name") or "",
        "sort_name": raw.get("SortName") or "",
        "original_title": raw.get("OriginalTitle") or "",
        "type": item_type,
        "is_folder": item_type == "Series",
        "year": raw.get("ProductionYear") or 0,
        "rating": raw.get("CommunityRating") or 0,
        "critic_rating": raw.get("CriticRating") or 0,
        "overview": raw.get("Overview") or "",
        "runtime_min": runtime_min,
        "image_tag": raw.get("PrimaryImageTag") or image_tags.get("Primary") or "",
        # 只存 tag，不存完整地址（地址带 api_key，落盘就是泄露令牌）
        "backdrop_tag": backdrop_tags[0] if backdrop_tags else "",
        "played": bool(user_data.get("Played")),
        "position_ticks": user_data.get("PlaybackPositionTicks") or 0,
        "imdb": provider_ids.get("Imdb") or "",
        "tmdb": provider_ids.get("Tmdb") or "",
        # 只保留渲染需要的几项，MediaStreams 原始结构不往外传
        "video": {
            "codec": (video_stream.get("Codec") or "").lower(),
            "width": int(video_stream.get("Width") or 0),
            "height": int(video_stream.get("Height") or 0),
            "hdrtype": _hdr_type(video_stream.get("VideoRangeType") or ""),
        } if video_stream else {},
        "audio": {
            "codec": (audio_stream.get("Codec") or "").lower(),
            "channels": int(audio_stream.get("Channels") or 0),
            "language": audio_stream.get("Language") or "",
        } if audio_stream else {},
    }


# 首字母严格性：纯 ASCII、2–4 字看成拼音首字母（如 RZD），要求 SortName 前缀命中，
# 避免 RZD 把 JQRZDY（机器人总动员）也捞出来。更长的是全拼，交给服务端匹配，不做过滤。
STRICT_MAX_LEN = 4


def _is_strict_query(query: str) -> bool:
    query = (query or "").strip()
    return 2 <= len(query) <= STRICT_MAX_LEN and query.isascii() and query.isalnum()


def _strict_keep(item: dict, query: str) -> bool:
    q = query.strip().lower()
    name = (item.get("name") or "").lower()
    original = (item.get("original_title") or "").lower()
    sort_name = (item.get("sort_name") or "").lower()
    return q in name or q in original or sort_name.startswith(q)


def search(server, query: str, media_type: str, limit: int = 100, offset: int = 0,
           ttl: int = 300) -> list[dict]:
    """调 Emby 搜索，返回规范化后的条目列表。

    失败抛 EmbyError（带状态码），由 render_search 翻译成人话。
    """
    item_type = TYPE_MAP.get(media_type)
    if not item_type:
        raise EmbyError("unknown media type: %s" % media_type)

    key = cache.make_key("search_v2", server.server_id, media_type, query, offset, limit)
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
        "EnableImageTypes": "Primary,Backdrop",
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
    if _is_strict_query(query):
        items = [item for item in items if _strict_keep(item, query)]
    log.debug("search %s / %r -> %d items" % (media_type, query, len(items)))

    # 空结果也缓存：用户连续打字时不必每次都打服务端
    cache.put(key, items)
    return items


# 非 ASCII 查询（中文名 / 类型词）才做人员与类型并集；纯字母走标题，避免 JW 之类炸出
# 一堆人的全部作品。单字查询也不扩展，噪音和请求量都不划算。
EXTRA_MIN_QUERY = 2
EXTRA_PERSON_LIMIT = 5
EXTRA_GENRE_LIMIT = 5
EXTRA_ITEM_LIMIT = 100


def _is_expandable_query(query: str) -> bool:
    query = (query or "").strip()
    return len(query) >= EXTRA_MIN_QUERY and any(ord(ch) > 127 for ch in query)


def _lookup_ids(server, path: str, query: str, limit: int) -> list:
    """查 Persons / Genres 的 Id 列表；失败返回空（扩展失败不能拖垮标题搜索）。"""
    url = http.build_url(server.base_url, path, {
        "searchTerm": query,
        "Limit": limit,
        "Fields": "Id",
    })
    payload, resp = http.get_json(url, headers={"X-Emby-Token": server.token})
    if payload is None:
        log.debug("extra lookup %s failed: status=%s" % (path, resp.status))
        return []
    return [item.get("Id") for item in payload.get("Items") or [] if item.get("Id")]


def _items_by_ids(server, param: str, ids: list, item_type: str) -> list:
    if not ids:
        return []
    url = http.build_url(server.base_url, "emby/Items", {
        param: ",".join(ids),
        "Recursive": "true",
        "IncludeItemTypes": item_type,
        "Fields": FIELDS,
        "ImageTypeLimit": 1,
        "EnableImageTypes": "Primary,Backdrop",
        "Limit": EXTRA_ITEM_LIMIT,
        "UserId": server.user_id,
    })
    payload, resp = http.get_json(url, headers={"X-Emby-Token": server.token})
    if payload is None:
        log.debug("extra items by %s failed: status=%s" % (param, resp.status))
        return []
    return [normalize(item) for item in payload.get("Items") or [] if item.get("Id")]


def search_page(server, query: str, media_type: str, limit: int = 100, offset: int = 0,
                ttl: int = 300) -> tuple:
    """搜索一页：返回 (条目列表, 标题命中数)。

    - 标题结果照旧分页；非 ASCII 查询在**第一页**额外并入演员作品与类型作品；
    - 第二页起只返回标题结果（offset>0 不再扩展）；
    - 标题命中数是「加载更多」的依据，避免并入的额外条目把 offset 算错。
    """
    title_items = search(server, query, media_type, limit=limit, offset=offset, ttl=ttl)
    if offset > 0 or not _is_expandable_query(query):
        return title_items, len(title_items)

    key = cache.make_key("search_merged", server.server_id, media_type, query, limit)
    cached = cache.get(key, ttl)
    if cached is not None:
        return cached.get("items", []), cached.get("title_count", 0)

    item_type = TYPE_MAP.get(media_type)
    persons = _lookup_ids(server, "emby/Persons", query.strip(), EXTRA_PERSON_LIMIT)
    genres = _lookup_ids(server, "emby/Genres", query.strip(), EXTRA_GENRE_LIMIT)
    extras = _items_by_ids(server, "PersonIds", persons, item_type)
    extras += _items_by_ids(server, "GenreIds", genres, item_type)

    merged, seen = [], set()
    for item in title_items + extras:
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        merged.append(item)

    cache.put(key, {"items": merged, "title_count": len(title_items)})
    log.debug("search merged %s / %r -> %d (+%d extras)" % (
        media_type, query, len(merged), len(merged) - len(title_items)))
    return merged, len(title_items)


RATINGS_BY_IMDB_PATH = "emby/Douban/RatingsByImdb"
RATINGS_BATCH = 80


def test_connection(server) -> tuple:
    """探测服务器是否可达、令牌是否有效。返回 (ok, 说明)。"""
    url = http.build_url(server.base_url, "emby/System/Info")
    payload, resp = http.get_json(url, headers={"X-Emby-Token": server.token})
    if payload is None:
        return False, resp.error or ("HTTP %s" % resp.status)
    name = payload.get("ServerName") or payload.get("Name") or server.name
    version = payload.get("Version") or ""
    return True, ("%s %s" % (name, version)).strip()


def douban_ratings_by_imdb(server, imdbs, ttl: int = 600):
    """按 IMDb 批量取豆瓣分（StrmAssistant 的 `/Douban/RatingsByImdb`）。

    返回 `{imdb_lower: {"rating", "votes", "applied", "item_id", "subject_id"}}`。

    - **请求失败返回 None**：调用方据此回退直连豆瓣；
    - 返回空 dict 表示请求成功但 Emby 一条都不认识（可据此判断要不要回退）；
    - 条目存在但没豆瓣分时，`rating` 为 None（调用方应显示「无豆瓣」而不是回退）。
    """
    wanted = sorted({(i or "").strip().lower() for i in imdbs if (i or "").strip()})
    if not wanted:
        return {}

    result = {}
    for start in range(0, len(wanted), RATINGS_BATCH):
        batch = wanted[start:start + RATINGS_BATCH]
        key = cache.make_key("emby_douban", server.server_id, *batch)
        cached = cache.get(key, ttl)
        if cached is not None:
            result.update(cached)
            continue

        url = http.build_url(server.base_url, RATINGS_BY_IMDB_PATH, {"Ids": ",".join(batch)})
        payload, resp = http.get_json(url, headers={"X-Emby-Token": server.token})
        if payload is None:
            log.error("douban ratings by imdb failed: status=%s error=%s" % (resp.status, resp.error))
            return None

        rows = {}
        for row in payload.get("Ratings") or []:
            imdb = (row.get("Imdb") or "").strip().lower()
            if not imdb:
                continue
            rows[imdb] = {
                "rating": row.get("Rating"),
                "votes": row.get("Votes") or 0,
                "applied": bool(row.get("Applied")),
                "item_id": row.get("ItemId") or "",
                "subject_id": row.get("SubjectId") or "",
            }

        cache.put(key, rows)
        result.update(rows)

    return result


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
        items, title_count = search_page(server, req.query, req.type or "movies",
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
        backdrop = backdrop_url(server, item["id"], item.get("backdrop_tag", ""))
        if backdrop:
            art["fanart"] = backdrop
        if art:
            list_item.setArt(art)

        target = play_url(server, item["id"]) if not item["is_folder"] else \
            "plugin://plugin.service.emby-next-gen/?mode=browse&id=%s&server=%s" % (
                item["id"], server.server_id)
        xbmcplugin.addDirectoryItem(handle, target, list_item, isFolder=item["is_folder"])

    # 分页：标题结果这一页满了就再给一条「加载更多」；并入的额外条目不参与 offset 计算
    if title_count >= settings.get("page_size", 100):
        from lib import router

        more = xbmcgui.ListItem(label=i18n.t(32027), offscreen=True)
        xbmcplugin.addDirectoryItem(
            handle,
            router.build_search_url(base_url, req.type or "movies", req.query,
                                    req.offset + title_count),
            more,
            isFolder=True,
        )

    if not items:
        kodi.add_notice(handle, base_url, i18n.t(32026, req.query), playable=False)
    return True
