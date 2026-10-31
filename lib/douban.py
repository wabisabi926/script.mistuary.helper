# -*- coding: utf-8 -*-
"""豆瓣评分（M2）：按 IMDb id 取分，写窗口属性给皮肤。

取分思路来自 TMDbHelper 的豆瓣模块（GPL-3.0），做了三处改动：
- 用本仓库的 http 封装（失败返回 Response，不抛异常）；
- 双通道按「legacy → frodo」顺序回退，不再随机，排障时路径确定；
- 缓存 7 天，失败也缓存 30 分钟，避免风控时反复重试。

写 Window(home)：

    Mistuary.Rating.Douban      8.6     0–10，一位小数
    Mistuary.Rating.Votes       123456
    Mistuary.Rating.FetchedAt   1793000000
    Mistuary.Rating.Status      ok | missing | error

皮肤只在 Status == ok 时显示；每次调用都会写全四个属性，
避免上一个条目的分数残留。

这个模块**不 import xbmc**（Kodi 部分走 lib.kodi 的惰性 import / JSON-RPC 函数），
可以脱离 Kodi 单测。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import random
import time
from urllib.parse import quote, urlencode, urlparse

from lib import cache, config, http, kodi, log

DOUBAN_TTL = 7 * 24 * 3600
FAILURE_TTL = 30 * 60

LEGACY_IMDB_URL = "https://api.douban.com/v2/movie/imdb/%s"
LEGACY_API_KEY = "0ab215a8b1977939201640fa14c66bab"

FRODO_BASE = "https://frodo.douban.com/api/v2"
FRODO_SEARCH = "/search/movie"
FRODO_API_KEY = "0dad551ec0f84ed02907ff5c42e8ec70"
FRODO_SECRET = "bf7dddc7c9cfe6f7"

TIMEOUT = 10
USER_AGENTS = (
    "api-client/1 com.douban.frodo/7.22.0.beta9(231) Android/23 product/Mate 40 vendor/HUAWEI model/Mate 40 brand/HUAWEI  rom/android  network/wifi  platform/AndroidPad",
    "api-client/1 com.douban.frodo/7.18.0(230) Android/22 product/MI 9 vendor/Xiaomi model/MI 9 brand/Android  rom/miui6  network/wifi  platform/mobile nd/1",
    "api-client/1 com.douban.frodo/7.1.0(205) Android/29 product/perseus vendor/Xiaomi model/Mi MIX 3  rom/miui6  network/wifi  platform/mobile nd/1",
)
COOKIE = "bid=J9zb1zA5sJc"

PROP_RATING = "Mistuary.Rating.Douban"
PROP_VOTES = "Mistuary.Rating.Votes"
PROP_FETCHED = "Mistuary.Rating.FetchedAt"
PROP_STATUS = "Mistuary.Rating.Status"
PROP_SOURCE = "Mistuary.Rating.Source"

# 皮肤在 onload 里写这两个属性：标题可能带逗号，走 RunScript 参数会被拆坏
PROP_QUERY = "Mistuary.Rating.Query"
PROP_YEAR = "Mistuary.Rating.Year"


def _frodo_sign(url: str, ts: str, method: str = "GET") -> str:
    path = urlparse(url).path
    raw = "&".join([method.upper(), quote(path, safe=""), ts])
    digest = hmac.new(FRODO_SECRET.encode(), raw.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def _valid_imdb(value: str) -> bool:
    value = (value or "").strip()
    return value.startswith("tt") and value[2:].isdigit()


def _rating_pair(payload) -> tuple:
    """从 legacy / frodo 的 rating 结构里取 (average, votes)。"""
    rating = (payload or {}).get("rating") or {}
    average = rating.get("average")
    if average is None:
        average = rating.get("value")
    votes = rating.get("numRaters")
    if votes is None:
        votes = rating.get("count")
    return average, votes


def _legacy(imdb_id: str):
    """通道 A：legacy v2 接口（POST apikey）。"""
    body = urlencode({"apikey": LEGACY_API_KEY}).encode("utf-8")
    resp = http.request(
        LEGACY_IMDB_URL % imdb_id,
        headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
            "User-Agent": random.choice(USER_AGENTS),
            "Cookie": COOKIE,
        },
        timeout=TIMEOUT,
        data=body,
        method="POST",
    )
    if not resp.ok:
        return None
    payload = resp.json()
    return _rating_pair(payload)


def _frodo_search(query: str, count: int = 1):
    """frodo 搜索接口（带签名）。返回 items 列表，失败返回空列表。"""
    path = FRODO_BASE + FRODO_SEARCH
    ts = time.strftime("%Y%m%d")
    params = {
        "q": query,
        "count": str(count),
        "apiKey": FRODO_API_KEY,
        "_ts": ts,
        "_sig": _frodo_sign(path, ts),
        "os_rom": "android",
    }
    resp = http.request(
        path + "?" + urlencode(params),
        headers={"User-Agent": random.choice(USER_AGENTS)},
        timeout=TIMEOUT,
    )
    if not resp.ok:
        return []
    payload = resp.json() or {}
    return payload.get("items") or []


def _frodo(imdb_id: str):
    """通道 B：按 IMDb id 搜（frodo）。"""
    items = _frodo_search(imdb_id, 1)
    if not items:
        return None
    return _rating_pair(items[0].get("target") or items[0])


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


def _frodo_by_title(title: str, year: str = ""):
    """没有 IMDb 时的兜底：按标题搜，必要时用年份收紧。

    只接受标题完全一致（忽略大小写/空白）的条目；给了年份就要求年份一致，
    避免同名不同年的条目拿错分。
    """
    items = _frodo_search(title, 5)
    for entry in items:
        subject = entry.get("target") or entry
        if _norm(subject.get("title") or "") != _norm(title):
            continue
        subject_year = str(subject.get("year") or "").strip()
        if year and subject_year and subject_year != str(year).strip():
            continue
        pair = _rating_pair(subject)
        if pair[0] is not None:
            return pair
    return None


def fetch(imdb_id: str) -> tuple:
    """返回 (average_float, votes_int) 或 (None, None)。"""
    for channel in (_legacy, _frodo):
        try:
            average, votes = channel(imdb_id)
        except Exception as exc:  # noqa: BLE001 - 网络/解析都可能炸，统一降级
            log.debug("douban channel %s failed: %s" % (channel.__name__, exc))
            continue
        if average is None:
            continue
        try:
            return float(average), int(votes or 0)
        except (TypeError, ValueError):
            continue
    return None, None


def _write(status: str, rating: str = "", votes: str = "", fetched: str = "",
           source: str = "") -> None:
    kodi.set_home_property(PROP_STATUS, status)
    kodi.set_home_property(PROP_RATING, rating)
    kodi.set_home_property(PROP_VOTES, votes)
    kodi.set_home_property(PROP_FETCHED, fetched)
    kodi.set_home_property(PROP_SOURCE, source)


def _emby_lookup(imdb_id: str):
    """问 StrmAssistant 要这条的豆瓣分。

    - 返回 dict：Emby 认识这条（`rating` 可能为 None = 有条目但没豆瓣分）
    - 返回 None：Emby 不可用/不认识这条 → 调用方回退直连豆瓣
    """
    settings = config.read_settings()
    server = config.ratings_server()
    if server is None:
        return None

    from lib import emby

    try:
        data = emby.douban_ratings_by_imdb(server, [imdb_id])
    except Exception as exc:  # noqa: BLE001 - 网络/解析异常一律回退
        log.debug("emby douban lookup failed: %s" % exc)
        return None

    if data is None:
        return None
    return data.get(imdb_id.lower())


def resolve_imdb(req) -> str:
    """按 imdb → dbid 的顺序找 IMDb id。

    皮肤优先直接传 `imdb`（Emby 动态条目没有 DBID）；老调用方只传 `dbid` 时
    再走 Kodi JSON-RPC 的 uniqueid。
    """
    if _valid_imdb(getattr(req, "imdb", "")):
        return req.imdb.strip()

    dbid = str(getattr(req, "dbid", "") or "").strip()
    if dbid.isdigit() and int(dbid) > 0:
        value = kodi.video_uniqueid(int(dbid), "imdb")
        if _valid_imdb(value):
            return value
    return ""


def run_action(req) -> None:
    """入口：action=rating。永远不抛异常，只写属性。"""
    settings = config.read_settings()
    if not settings.get("douban_enabled", True):
        _write("missing")
        log.debug("douban disabled in settings")
        return

    imdb_id = resolve_imdb(req)
    title = (getattr(req, "title", "") or "").strip() or kodi.get_home_property(PROP_QUERY)
    year = (getattr(req, "year", "") or "").strip() or kodi.get_home_property(PROP_YEAR)

    if not imdb_id and not title:
        _write("missing")
        log.debug("douban: no imdb id and no title (dbid=%s)" % getattr(req, "dbid", ""))
        return

    # 优先问 Emby（StrmAssistant）：数值与应用内主评分同源，且不额外触发豆瓣请求。
    # 返回 None 表示 Emby 不认识这条/不可用 → 继续走下面的直连兜底。
    if imdb_id and settings.get("douban_prefer_emby", True):
        hit = _emby_lookup(imdb_id)
        if hit is not None:
            rating = hit.get("rating")
            if rating is None:
                _write("missing")
                log.debug("douban: emby knows %s but has no rating" % imdb_id)
                return
            try:
                text = "%.1f" % float(rating)
            except (TypeError, ValueError):
                text = str(rating)
            _write("ok", text, str(int(hit.get("votes") or 0)), str(int(time.time())), "emby")
            log.debug("douban via emby: %s -> %s" % (imdb_id, text))
            return

    key = cache.make_key("douban", imdb_id) if imdb_id else cache.make_key("douban_title", title, year)
    cached = cache.get(key, DOUBAN_TTL)
    if cached is not None:
        if cached.get("status") == "ok":
            _write("ok", cached.get("rating", ""), str(cached.get("votes", "")),
                   str(cached.get("ts", int(time.time()))), cached.get("source", "douban"))
        else:
            _write("missing")
        log.debug("douban cache hit: %s" % imdb_id)
        return

    fail_key = cache.make_key("douban_fail", key)
    if cache.get(fail_key, FAILURE_TTL) is not None:
        _write("error")
        log.debug("douban failure cache hit: %s" % imdb_id)
        return

    if imdb_id:
        average, votes = fetch(imdb_id)
        # 豆瓣 legacy/frodo 对剧集（TV）按 IMDb 经常查不到，退回标题+年份匹配
        if average is None and title:
            log.debug("douban: imdb %s missed, retry by title %r" % (imdb_id, title))
            average, votes = _frodo_by_title(title, year) or (None, None)
    else:
        average, votes = _frodo_by_title(title, year) or (None, None)
    now = int(time.time())
    if average is None:
        # 失败也缓存：风控时别每个详情页都重试
        cache.put(fail_key, {"status": "error"})
        _write("error")
        log.error("douban fetch failed: %s" % (imdb_id or ("title=" + title)))
        return

    rating = "%.1f" % average
    cache.put(key, {"status": "ok", "rating": rating, "votes": votes, "ts": now, "source": "douban"})
    _write("ok", rating, str(votes), str(now), "douban")
    log.debug("douban ok: %s -> %s (%d votes)" % (imdb_id or ("title=" + title), rating, votes))
