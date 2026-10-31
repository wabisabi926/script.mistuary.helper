# -*- coding: utf-8 -*-
"""豆瓣评分同步：把 Emby 侧的豆瓣分写成 Kodi 库里的独立评分行。

为什么写库：E4K 只搬「主评分」一个数字，Kodi 无法判断它来自豆瓣还是 TMDB。
在 `rating` 表里补一条 `rating_type='douban'` 的记录，皮肤就能逐条区分：
有这条 → 豆瓣；没有 → 主评分（TMDB/IMDb）。

约束：
- 只读 Emby（StrmAssistant 的 `/Douban/RatingsByImdb`），**不请求豆瓣**；
- 只在值变化时写库，单事务提交；
- 失败不抛到 UI，返回带 `error` 的统计字典。
"""

from __future__ import annotations

import sqlite3
import time

from lib import config, emby, kodi, log

RATING_TYPE = "douban"
# 兜底列：Kodi 22.0-RC1 读不出自定义评分类型（`Rating(douban)` 恒为空），
# 但 `Rating(metacritic)` 这类已知类型能读。本库没人用 metacritic，借来放同一个分。
FALLBACK_TYPE = "metacritic"
VALUE_EPSILON = 0.011

# Emby（StrmAssistant）不认识的条目回退直连豆瓣：每轮最多补这么多条，
# 每条之间停一下，避免一口气打上千个请求被豆瓣限流。跑不完的下一轮继续补。
DOUBAN_FALLBACK_LIMIT = 120
DOUBAN_FALLBACK_DELAY = 0.4

# Kodi 库类型 → rating 表的 media_type
KINDS = (
    ("movies", "movie"),
    ("tvshows", "tvshow"),
    ("episodes", "episode"),
)


def _wanted_rows(entries: list, ratings: dict) -> dict:
    """(media_type, kodi_id) → 豆瓣分。只保留有分的条目。"""
    wanted = {}
    for media_type, kodi_id, imdb in entries:
        hit = ratings.get(imdb)
        if not hit:
            continue
        value = hit.get("rating")
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        # 0 分/负数一律不写：Kodi 的 SetRating 只认 (0,10]，写进去也会显示成 0.0
        if number <= 0:
            continue
        wanted[(media_type, kodi_id)] = number
    return wanted


def _apply(db_path: str, wanted: dict, rating_type: str = RATING_TYPE) -> tuple:
    """写库：返回 (inserted_or_updated, deleted)。单事务。

    `rating_type` 可指定：默认写 `douban`；Kodi 22.0-RC1 上自定义类型读不出来，
    所以同一份数据再往 `metacritic` 这一列写一份当兜底（皮肤两边都读）。
    """
    conn = sqlite3.connect(db_path, timeout=10)
    try:
        conn.execute("PRAGMA busy_timeout=10000")
        rows = conn.execute(
            "SELECT media_id, media_type, rating FROM rating WHERE rating_type = ?",
            (rating_type,),
        ).fetchall()
        existing = {}
        for media_id, media_type, rating in rows:
            existing[(media_type, int(media_id))] = rating

        changed = []
        for key, value in wanted.items():
            old = existing.get(key)
            if old is None or abs(float(old) - value) > VALUE_EPSILON:
                changed.append((key, value))

        removed = [key for key in existing if key not in wanted]

        with conn:
            for media_type, media_id in removed:
                conn.execute(
                    "DELETE FROM rating WHERE media_id = ? AND media_type = ? AND rating_type = ?",
                    (media_id, media_type, rating_type),
                )
            for (media_type, media_id), value in changed:
                conn.execute(
                    "DELETE FROM rating WHERE media_id = ? AND media_type = ? AND rating_type = ?",
                    (media_id, media_type, rating_type),
                )
                conn.execute(
                    "INSERT INTO rating(media_id, media_type, rating_type, rating, votes) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (media_id, media_type, rating_type, value, 0),
                )

        return len(changed), len(removed)
    finally:
        conn.close()


def sync(notify: bool = True) -> dict:
    """执行一次同步。返回统计字典（含 `error`，空串表示成功）。"""
    stats = {
        "items": 0,
        "with_imdb": 0,
        "emby": 0,
        "douban": 0,
        "written": 0,
        "deleted": 0,
        "error": "",
    }

    settings = config.read_settings()
    if not settings.get("rating_sync_enabled", True):
        stats["error"] = "disabled"
        return stats

    server = config.ratings_server()
    if server is None:
        stats["error"] = "no-server"
        log.debug("rating sync: no usable Emby server")
        return stats

    entries = []
    for kind, media_type in KINDS:
        for row in kodi.video_items(kind):
            stats["items"] += 1
            imdb = (row.get("imdb") or "").strip().lower()
            kodi_id = row.get("id") or 0
            if not imdb or not kodi_id:
                continue
            stats["with_imdb"] += 1
            entries.append((media_type, int(kodi_id), imdb))

    if not entries:
        return stats

    ratings = emby.douban_ratings_by_imdb(server, [entry[2] for entry in entries])
    if ratings is None:
        stats["error"] = "emby"
        log.error("rating sync: emby lookup failed")
        return stats

    stats["emby"] = len(ratings)

    # Emby 不认识的条目回退直连豆瓣（legacy → frodo 双通道，douban.fetch 内部已兜底）。
    # 限量 + 节流：一轮跑不完，下一轮接着补，库是增量填的。
    from lib import douban  # 惰性 import：别让 default.py 的导入链提前拉进豆瓣模块

    missing = [imdb for _, _, imdb in entries if imdb not in ratings]
    filled = 0
    for imdb in missing[:DOUBAN_FALLBACK_LIMIT]:
        try:
            average, votes = douban.fetch(imdb)
        except Exception as exc:  # noqa: BLE001 - 单条失败不能拖垮整轮
            log.debug("rating sync: douban fetch failed for %s: %s" % (imdb, exc))
            continue
        if average is None:
            continue
        ratings[imdb] = {"rating": average, "votes": votes or 0}
        filled += 1
        if DOUBAN_FALLBACK_DELAY:
            time.sleep(DOUBAN_FALLBACK_DELAY)
    stats["douban"] = filled

    wanted = _wanted_rows(entries, ratings)

    db_path = kodi.database_path("MyVideos")
    if not db_path:
        stats["error"] = "no-db"
        log.error("rating sync: MyVideos database not found")
        return stats

    try:
        stats["written"], stats["deleted"] = _apply(db_path, wanted)
        # 同一份数据再写一份到 metacritic 列：22.0-RC1 上 `Rating(douban)` 读不出来，
        # 但已知类型（metacritic）能读。皮肤先读 douban，读不到再读 metacritic。
        _apply(db_path, wanted, FALLBACK_TYPE)
    except sqlite3.Error as exc:
        stats["error"] = "db"
        log.error("rating sync: database error: %s" % exc)
        return stats

    if (stats["written"] or stats["deleted"]) and notify:
        kodi.refresh_ui()

    log.info("rating sync: items=%d imdb=%d emby=%d douban=%d written=%d deleted=%d" % (
        stats["items"], stats["with_imdb"], stats["emby"], stats["douban"],
        stats["written"], stats["deleted"]))
    return stats
