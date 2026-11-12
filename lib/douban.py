# -*- coding: utf-8 -*-
"""豆瓣评分（M2）：按 IMDb id 取分，写窗口属性给皮肤。

取分思路来自 TMDbHelper 的豆瓣模块（GPL-3.0），做了四处改动：
- 用本仓库的 http 封装（失败返回 Response，不抛异常）；
- 双通道按「legacy → frodo」顺序回退，不再随机，排障时路径确定；
- 结果分三态，缓存时长按数据变化频率分别定：`ok` 30 天（评分月级不变）、
  `missing`（豆瓣没有这条/没评分）3 天（新片随时开分）、`error`（请求失败）
  30 分钟。把「确定没有」和「暂时取不到」分开，冷门片不会每 30 分钟把两条
  通道重打一遍；
- 超时压到 4 秒：详情页在皮肤 onload 里同步调用，而通道是串行的。

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

# 有分：豆瓣评分是几十万人投票的加权平均，月级基本不动，30 天足够
DOUBAN_TTL = 30 * 24 * 3600
# 没分：新片随时会开分，所以「豆瓣确实没有」不能跟着 30 天，3 天后重查一次
MISSING_TTL = 3 * 24 * 3600
# 请求失败：短冷却，环境恢复后能自愈
FAILURE_TTL = 30 * 60

LEGACY_IMDB_URL = "https://api.douban.com/v2/movie/imdb/%s"
LEGACY_API_KEY = "0ab215a8b1977939201640fa14c66bab"

FRODO_BASE = "https://frodo.douban.com/api/v2"
FRODO_SEARCH = "/search/movie"
FRODO_SUBJECT = "/movie/%s"
FRODO_API_KEY = "0dad551ec0f84ed02907ff5c42e8ec70"
FRODO_SECRET = "bf7dddc7c9cfe6f7"

# 详情页在皮肤 onload 里同步调用，两条通道串行；超时太长会直接卡住页面。
# 实测两条通道正常时 0.2~0.4 秒返回，4 秒有十倍余量。
TIMEOUT = 4
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
    """frodo 搜索接口（带签名）。

    返回 items 列表；**请求失败返回 None**，与「搜到了但没有结果」区分开。
    """
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
        return None
    payload = resp.json() or {}
    return payload.get("items") or []


def _frodo(imdb_id: str):
    """通道 B：按 IMDb id 搜（frodo）。

    请求失败返回 None；搜到了但没有这条返回 ``(None, None)``。
    """
    items = _frodo_search(imdb_id, 1)
    if items is None:
        return None
    if not items:
        return None, None
    return _rating_pair(items[0].get("target") or items[0])


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


def _frodo_by_title(title: str, year: str = ""):
    """没有 IMDb 时的兜底：按标题搜，必要时用年份收紧。

    只接受标题完全一致（忽略大小写/空白）的条目；给了年份就要求年份一致，
    避免同名不同年的条目拿错分。

    返回 ``(average, votes)``；请求失败返回 None，正常但没匹配返回 ``(None, None)``。
    """
    items = _frodo_search(title, 5)
    if items is None:
        return None
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
    return None, None


def _frodo_by_subject(subject_id: str):
    """按豆瓣 subject id 直接取分，返回 ``(average, votes)``。

    比标题搜索稳：不用匹配标题，译名不一致、同名不同年都不会拿错。
    请求失败返回 None；条目正常但没有评分返回 ``(None, None)``。
    """
    subject_id = str(subject_id or "").strip()
    if not subject_id.isdigit():
        return None

    path = FRODO_BASE + FRODO_SUBJECT % subject_id
    ts = time.strftime("%Y%m%d")
    params = {
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
        return None
    return _rating_pair(resp.json() or {})


def fetch(imdb_id: str) -> tuple:
    """按 IMDb id 取分，返回 ``(status, average, votes)``。

    status：
    - ``ok``      取到分数
    - ``missing`` 所有通道都正常响应，但豆瓣没有这条或没有评分（可安全长缓存）
    - ``error``   至少一条通道请求失败（网络/风控/超时），应短冷却后重试

    区分这两种「没分」是必要的：冷门片在豆瓣本来就没有评分，如果当成失败，
    每 30 分钟就会把两条通道重打一遍，且永远得不到结果。
    """
    if not imdb_id:
        return "missing", None, None

    responded = False
    failed = False

    for channel in (_legacy, _frodo):
        try:
            pair = channel(imdb_id)
        except Exception as exc:  # noqa: BLE001 - 网络/解析都可能炸，统一降级
            log.debug("douban channel %s failed: %s" % (channel.__name__, exc))
            failed = True
            continue
        if pair is None:
            failed = True
            continue
        responded = True
        average, votes = pair
        if average is None:
            continue
        try:
            return "ok", float(average), int(votes or 0)
        except (TypeError, ValueError):
            continue

    return ("missing" if responded and not failed else "error"), None, None


def _write(status: str, rating: str = "", votes: str = "", fetched: str = "",
           source: str = "") -> None:
    kodi.set_home_property(PROP_STATUS, status)
    kodi.set_home_property(PROP_RATING, rating)
    kodi.set_home_property(PROP_VOTES, votes)
    kodi.set_home_property(PROP_FETCHED, fetched)
    kodi.set_home_property(PROP_SOURCE, source)


def _emby_lookup(imdb_id: str, douban_id: str = ""):
    """问 StrmAssistant 要这条的豆瓣分。

    - 返回 dict：Emby 认识这条（`rating` 可能为 None = 有条目但没豆瓣分）
    - 返回 None：Emby 不可用/不认识这条 → 调用方回退直连豆瓣
    """
    settings = config.read_settings()
    server = config.ratings_server()
    if server is None:
        return None

    from lib import emby

    keys = []
    if imdb_id:
        keys.append(imdb_id)
    if douban_id:
        keys.append("douban:" + douban_id)
    if not keys:
        return None

    try:
        data = emby.douban_ratings_by_keys(server, keys)
    except Exception as exc:  # noqa: BLE001 - 网络/解析异常一律回退
        log.debug("emby douban lookup failed: %s" % exc)
        return None

    if data is None:
        return None

    # 豆瓣 ID 是精确键；没有时再退回 IMDb。
    if douban_id:
        hit = data.get(("douban:" + douban_id).lower())
        if hit is not None:
            return hit
    return data.get((imdb_id or "").lower())


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

    # 皮肤只传标题时，从 Kodi 库把 ID 补回来：豆瓣 subject id 按 ID 直查最稳，
    # 没有 subject 时 IMDb 还能喂给 Emby 的批量评分接口。
    douban_id = ""
    if title:
        kind = kodi.LIBRARY_KIND.get(getattr(req, "type", "") or "", "")
        ids = kodi.library_uniqueids(kind, title, year) if kind else {}
        douban_id = (ids.get("douban") or "").strip()
        if not imdb_id:
            imdb_id = (ids.get("imdb") or "").strip()

    if not imdb_id and not douban_id and not title:
        _write("missing")
        log.debug("douban: no imdb id and no title (dbid=%s)" % getattr(req, "dbid", ""))
        return

    # 优先问 Emby（StrmAssistant）：数值与应用内主评分同源，且不额外触发豆瓣请求。
    # 返回 None 表示 Emby 不认识这条/不可用 → 继续走下面的直连兜底。
    if (imdb_id or douban_id) and settings.get("douban_prefer_emby", True):
        hit = _emby_lookup(imdb_id, douban_id)
        if hit is not None:
            rating = hit.get("rating")
            if rating is None:
                if not settings.get("douban_fallback_public", True):
                    _write("missing")
                    log.debug("douban: emby knows %s but has no rating (fallback off)" % imdb_id)
                    return
                log.debug("douban: emby knows %s but has no rating, fallback to public" % imdb_id)
            else:
                try:
                    text = "%.1f" % float(rating)
                except (TypeError, ValueError):
                    text = str(rating)
                _write("ok", text, str(int(hit.get("votes") or 0)), str(int(time.time())), "emby")
                log.debug("douban via emby: %s -> %s" % (imdb_id, text))
                return

    ref = imdb_id or (("douban:" + douban_id) if douban_id else ("title=" + title))
    key = (cache.make_key("douban_subject", douban_id) if douban_id
           else cache.make_key("douban", imdb_id) if imdb_id
           else cache.make_key("douban_title", title, year))
    cached = cache.get(key, DOUBAN_TTL)
    if cached is not None and cached.get("status") == "missing":
        # 「没评分」按短 TTL 复核一次：新片随时会开分，不能跟着 30 天一起失效
        cached = cache.get(key, MISSING_TTL)
    if cached is not None:
        if cached.get("status") == "ok":
            _write("ok", cached.get("rating", ""), str(cached.get("votes", "")),
                   str(cached.get("ts", int(time.time()))), cached.get("source", "douban"))
        else:
            _write("missing")
        log.debug("douban cache hit: %s" % ref)
        return

    fail_key = cache.make_key("douban_fail", key)
    if cache.get(fail_key, FAILURE_TTL) is not None:
        _write("error")
        log.debug("douban failure cache hit: %s" % ref)
        return

    if douban_id:
        pair = _frodo_by_subject(douban_id)
        if pair is None:
            # subject 接口失败：有 IMDb 就换条路，别把能拿到的分丢掉
            status, average, votes = fetch(imdb_id) if imdb_id else ("error", None, None)
        elif pair[0] is None:
            status, average, votes = "missing", None, None
        else:
            status, average, votes = "ok", pair[0], pair[1] or 0
            log.debug("douban subject hit: %s -> %s" % (douban_id, average))
    else:
        status, average, votes = fetch(imdb_id) if imdb_id else ("missing", None, None)

    # 豆瓣 legacy/frodo 对剧集（TV）按 IMDb 经常查不到，退回标题+年份匹配。
    # 只在 missing 时兜底：error 说明端点已经挂了，再打一次只是多等一个超时。
    # 有 subject id 时也不用兜底：豆瓣条目已经确定，标题搜索只会是同一个库。
    if status == "missing" and title and not douban_id:
        log.debug("douban: imdb %s missed, retry by title %r" % (imdb_id or "-", title))
        pair = _frodo_by_title(title, year)
        if pair is None:
            status = "error"
        elif pair[0] is not None:
            average, votes = pair
            status = "ok"

    now = int(time.time())
    if status == "ok":
        rating = "%.1f" % average
        cache.put(key, {"status": "ok", "rating": rating, "votes": votes, "ts": now, "source": "douban"})
        _write("ok", rating, str(votes), str(now), "douban")
        log.debug("douban ok: %s -> %s (%d votes)" % (ref, rating, votes))
        return

    if status == "missing":
        # 豆瓣确实没有这条或没有评分：长缓存，别每 30 分钟把两条通道重打一遍
        cache.put(key, {"status": "missing", "ts": now})
        _write("missing")
        log.debug("douban missing: %s" % ref)
        return

    # 请求失败（网络/风控/超时）：只做短冷却，环境恢复后能自愈
    cache.put(fail_key, {"status": "error"})
    _write("error")
    log.error("douban fetch failed: %s" % ref)
