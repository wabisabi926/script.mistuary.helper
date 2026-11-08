# -*- coding: utf-8 -*-
"""磁盘缓存：一次调用一个 JSON 文件，用 sha1(key) 当文件名。

为什么不用 sqlite：并发只有 Kodi 主线程 + 偶尔的 RunScript，
文件系统足够；而且用户能直接删目录清缓存。

TTL 由调用方给（搜索 300 秒、豆瓣 7 天）。
**不缓存失败**：失败结果不进缓存，否则一次网络抖动会锁死 5 分钟。

**过期文件由 `put()` 机会式清扫**：`get()` 只判断过期、不删文件，只靠设置页
「清空缓存」全删的话，搜索词是无限的，缓存目录会一直长。

这个模块**不 import xbmc**（目录由调用方传入或惰性解析），可以直接单测。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time

ADDON_ID = "script.mistuary.helper"
DEFAULT_TTL = 300

# 每 N 次成功写入触发一次清扫；摊销后每次写入只多几毫秒
PRUNE_EVERY = 50
# 超过就按最旧淘汰到 80%，给目录一个硬上限
MAX_FILES = 2000
# 清扫只删「一定过期」的文件，所以这个值必须大于业务侧最长的 TTL
# （目前是豆瓣评分的 30 天），否则会把还有效的缓存删掉。
MAX_AGE = 45 * 24 * 3600

_writes = 0


def cache_dir() -> str:
    """缓存目录，不存在就建。没有 Kodi（单测/CI）时退回临时目录。"""
    try:
        import xbmcvfs

        path = xbmcvfs.translatePath("special://profile/addon_data/%s/cache" % ADDON_ID)
    except Exception:  # noqa: BLE001 - 无 Kodi 环境
        path = os.path.join(tempfile.gettempdir(), "mistuary-helper-cache")
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)
    return path


def _key_to_name(key: str) -> str:
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return digest + ".json"


def get(key: str, ttl: int = DEFAULT_TTL, root: str | None = None):
    """命中返回 (data)，未命中/过期/损坏返回 None。"""
    if ttl <= 0:
        return None
    directory = root or cache_dir()
    path = os.path.join(directory, _key_to_name(key))
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None

    try:
        saved_at = float(payload.get("ts", 0))
    except (TypeError, ValueError):
        return None
    if time.time() - saved_at > ttl:
        return None
    return payload.get("data")


def prune(root: str | None = None, now: float | None = None,
          max_files: int = MAX_FILES, max_age: int = MAX_AGE) -> int:
    """删掉过期文件和超量文件，返回删除数。

    过期用文件 mtime 判断，不读 JSON 里的 ts：读两千个文件才能拿到 ts，
    而 stat 一次就够；mtime 一定不早于 ts（写完即落盘），所以按最长 TTL
    淘汰是安全的。
    """
    directory = root or cache_dir()
    now = time.time() if now is None else now
    removed = 0
    alive = []

    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                if not entry.name.endswith(".json"):
                    continue
                try:
                    mtime = entry.stat().st_mtime
                except OSError:
                    continue
                if now - mtime > max_age:
                    try:
                        os.remove(entry.path)
                        removed += 1
                    except OSError:
                        pass
                    continue
                alive.append((mtime, entry.path))
    except OSError:
        return removed

    if len(alive) > max_files:
        alive.sort()
        for _, path in alive[:len(alive) - int(max_files * 0.8)]:
            try:
                os.remove(path)
                removed += 1
            except OSError:
                pass
    return removed


def _should_prune() -> bool:
    """每 PRUNE_EVERY 次成功写入返回一次 True。"""
    global _writes
    _writes += 1
    return _writes % PRUNE_EVERY == 0


def put(key: str, data, root: str | None = None) -> bool:
    """写缓存。先写 .tmp 再 replace，避免 Kodi 被杀时留下半个文件。"""
    directory = root or cache_dir()
    path = os.path.join(directory, _key_to_name(key))
    tmp = path + ".tmp"
    payload = {"key": key, "ts": time.time(), "data": data}
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        # 缓存写失败不该影响功能，静默吞掉并清理残文件
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return False

    if _should_prune():
        prune(directory)
    return True


def clear(root: str | None = None) -> int:
    """清空缓存，返回删除的文件数。给设置页的「清空缓存」按钮用。"""
    directory = root or cache_dir()
    removed = 0
    try:
        for name in os.listdir(directory):
            if not name.endswith(".json"):
                continue
            try:
                os.remove(os.path.join(directory, name))
                removed += 1
            except OSError:
                pass
    except OSError:
        return 0
    return removed


def make_key(*parts) -> str:
    """拼缓存 key。统一在这里做，避免各处 key 规则漂移。"""
    return "|".join(str(p) for p in parts)
