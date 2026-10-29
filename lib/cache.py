# -*- coding: utf-8 -*-
"""磁盘缓存：一次调用一个 JSON 文件，用 sha1(key) 当文件名。

为什么不用 sqlite：并发只有 Kodi 主线程 + 偶尔的 RunScript，
文件系统足够；而且用户能直接删目录清缓存。

TTL 由调用方给（搜索 300 秒、豆瓣 7 天）。
**不缓存失败**：失败结果不进缓存，否则一次网络抖动会锁死 5 分钟。

这个模块**不 import xbmc**（目录由调用方传入或惰性解析），可以直接单测。
"""

from __future__ import annotations

import hashlib
import json
import os
import time

ADDON_ID = "script.mistuary.helper"
DEFAULT_TTL = 300


def cache_dir() -> str:
    """缓存目录，不存在就建。抽成函数方便测试替换。"""
    import xbmcvfs

    path = xbmcvfs.translatePath("special://profile/addon_data/%s/cache" % ADDON_ID)
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
        return True
    except OSError:
        # 缓存写失败不该影响功能，静默吞掉并清理残file
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return False


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
