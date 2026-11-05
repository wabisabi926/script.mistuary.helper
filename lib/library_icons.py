# -*- coding: utf-8 -*-
"""把 Emby 媒体库封面同步成本地文件，供皮肤按库名读取。

E4K 不导出库封面：它只把封面存成 ``image://emby@...`` 地址，Kodi 的 tag
列表项也不带任何 art，皮肤在 XML 层拿不到。所以由本插件直接问 Emby 要
Primary 图，写到 ``addon_data/script.mistuary.helper/library_icons/<库名>.png``，
皮肤按 ``ListItem.Label`` 拼文件名。

**每个库都会落一个文件**：Emby 没设封面时写 1×1 全透明 PNG 占位。
Kodi 没法在 XML 里判断文件是否存在，缺文件就会每次渲染打一条贴图加载
失败日志；占位图让皮肤那层永远能加载，透明像素露出下层的 default.jpg。

同步是幂等的：manifest 记录每个库的 ``id + tag``，没变就不重复下载；
下载失败保留旧文件，下次再试。manifest 里不放 token。
"""

from __future__ import annotations

import base64
import json
import os
import re
import tempfile

from lib import config, http, log

ADDON_ID = "script.mistuary.helper"
MANIFEST_NAME = "manifest.json"
# v2：封面统一存 .png，缺封面写占位。v1 的 .jpg manifest 会被当成不存在，
# 让 service 在下次启动时自动重同步一次，不用用户手动点按钮。
MANIFEST_VERSION = 2
IMAGE_WIDTH = 640
IMAGE_SUFFIX = ".png"
IMAGE_TIMEOUT = 15
VIEWS_TIMEOUT = 10

# 1 × 1 全透明 PNG（IHDR 1x1、8 bit、RGBA）。Emby 没设封面的库用它占位。
PLACEHOLDER_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAACklEQVR4nGMAAQAABQABDQottAAAAABJRU5ErkJggg=="
)

# Windows / Linux 文件名里不能出现的字符，统一换成下划线。
_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def icons_dir() -> str:
    """本地封面目录，不存在就建。没有 Kodi（单测）时退回临时目录。"""
    try:
        import xbmcvfs

        path = xbmcvfs.translatePath(
            "special://profile/addon_data/%s/library_icons" % ADDON_ID
        )
    except Exception:  # noqa: BLE001 - 无 Kodi 环境
        path = os.path.join(tempfile.gettempdir(), "mistuary-helper-library-icons")
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)
    return path


def manifest_path(directory: str | None = None) -> str:
    return os.path.join(directory or icons_dir(), MANIFEST_NAME)


def has_manifest(directory: str | None = None) -> bool:
    """存在且版本匹配才算数：旧版 manifest 要让 service 重跑一次同步。"""
    return bool(_load_manifest(directory or icons_dir()))


def safe_name(name: str) -> str:
    """库名 → 文件名主干。和 ListItem.Label 保持一致，只替换非法字符。"""
    cleaned = _ILLEGAL.sub("_", (name or "").strip())
    return cleaned.rstrip(" .")


def views_url(server) -> str:
    return http.build_url(
        server.base_url,
        "Users/%s/Views" % server.user_id,
        {"api_key": server.token},
    )


def image_url(server, item_id: str, tag: str) -> str:
    # format=png：缺封面的库要写透明占位，整条链路统一用 PNG，
    # 避免"PNG 内容顶 .jpg 名字"这种按扩展名选解码器的写法。
    return http.build_url(
        server.base_url,
        "Items/%s/Images/Primary" % item_id,
        {
            "tag": tag,
            "maxWidth": IMAGE_WIDTH,
            "format": "png",
            "api_key": server.token,
        },
    )


def fetch_views(server):
    """返回 (views, response)。失败时 views 为 None。"""
    payload, resp = http.get_json(views_url(server), timeout=VIEWS_TIMEOUT)
    if payload is None:
        return None, resp
    items = payload.get("Items")
    return (items if isinstance(items, list) else []), resp


def _load_manifest(directory: str) -> dict:
    try:
        with open(manifest_path(directory), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict) or payload.get("version") != MANIFEST_VERSION:
        return {}
    libraries = payload.get("libraries")
    return libraries if isinstance(libraries, dict) else {}


def _write_manifest(directory: str, libraries: dict) -> None:
    path = manifest_path(directory)
    tmp = path + ".tmp"
    payload = {
        "version": MANIFEST_VERSION,
        "libraries": libraries,
    }
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, path)


def _atomic_write(path: str, data: bytes) -> None:
    tmp = path + ".tmp"
    with open(tmp, "wb") as handle:
        handle.write(data)
    os.replace(tmp, path)


def _write_placeholder(path: str) -> bool:
    """写透明占位图；失败只记日志，不影响其它库。"""
    try:
        _atomic_write(path, PLACEHOLDER_PNG)
    except OSError as exc:
        log.error("library icons: placeholder write failed: %s" % exc)
        return False
    return True


def _placeholder_entry(item_id: str, filename: str) -> dict:
    return {"id": item_id, "tag": "", "file": filename, "placeholder": True}


def sync(server, directory: str | None = None) -> dict:
    """同步所有库封面。返回计数，不抛异常。"""
    directory = directory or icons_dir()
    previous = _load_manifest(directory)
    views, resp = fetch_views(server)
    if views is None:
        error = resp.error or ("HTTP %s" % resp.status)
        log.error("library icons: views request failed: %s" % error)
        return {"saved": 0, "skipped": 0, "failed": 0, "removed": 0, "error": error}

    current = {}
    saved = skipped = failed = 0

    for view in views:
        if not isinstance(view, dict):
            continue
        name = safe_name(view.get("Name"))
        item_id = str(view.get("Id") or "")
        tag = (view.get("ImageTags") or {}).get("Primary") or ""
        if not name:
            continue

        filename = name + IMAGE_SUFFIX
        if filename in current:
            log.info("library icons: duplicate filename for %r, last one wins" % name)

        target = os.path.join(directory, filename)
        known = previous.get(name) or {}

        if not item_id or not tag:
            # 没有封面：写透明占位，保证皮肤那层不会 404。
            if known.get("placeholder") and os.path.isfile(target):
                current[name] = known
                skipped += 1
                continue
            if not _write_placeholder(target):
                failed += 1
                continue
            current[name] = _placeholder_entry(item_id, filename)
            saved += 1
            continue

        if (known.get("id") == item_id and known.get("tag") == tag
                and not known.get("placeholder") and os.path.isfile(target)):
            current[name] = known
            skipped += 1
            continue

        response = http.request(image_url(server, item_id, tag), timeout=IMAGE_TIMEOUT)
        if not response.ok or not response.body:
            error = response.error or ("HTTP %s" % response.status)
            log.error("library icons: download %r failed: %s" % (name, error))
            failed += 1
            if known and not known.get("placeholder") and os.path.isfile(target):
                current[name] = known
            elif _write_placeholder(target):
                current[name] = _placeholder_entry(item_id, filename)
            continue

        try:
            _atomic_write(target, response.body)
        except OSError as exc:
            log.error("library icons: write %r failed: %s" % (filename, exc))
            failed += 1
            if known and not known.get("placeholder") and os.path.isfile(target):
                current[name] = known
            continue

        current[name] = {"id": item_id, "tag": tag, "file": filename}
        saved += 1

    removed = 0
    for name, entry in previous.items():
        filename = (entry or {}).get("file")
        if not filename:
            continue
        if (current.get(name) or {}).get("file") == filename:
            continue
        try:
            os.remove(os.path.join(directory, filename))
            removed += 1
        except OSError:
            pass

    # 旧版本存的是 .jpg，迁移后残留会白白占空间。
    try:
        leftovers = [f for f in os.listdir(directory) if f.lower().endswith(".jpg")]
    except OSError:
        leftovers = []
    for filename in leftovers:
        try:
            os.remove(os.path.join(directory, filename))
            removed += 1
        except OSError:
            pass

    try:
        _write_manifest(directory, current)
    except OSError as exc:
        log.error("library icons: manifest write failed: %s" % exc)

    log.info("library icons: saved=%d skipped=%d failed=%d removed=%d"
             % (saved, skipped, failed, removed))
    return {"saved": saved, "skipped": skipped, "failed": failed,
            "removed": removed, "error": ""}


def run_action() -> bool:
    """设置页按钮入口：同步并给出通知。"""
    import xbmcaddon
    import xbmcgui

    from lib import i18n

    name = xbmcaddon.Addon(ADDON_ID).getAddonInfo("name")
    settings = config.read_settings()
    server = config.find_server(settings.get("server_id", ""))
    if server is None:
        xbmcgui.Dialog().notification(
            name, i18n.t(32021), xbmcgui.NOTIFICATION_WARNING, 4000,
        )
        return False

    result = sync(server)
    if result.get("error"):
        message = i18n.t(32153, result["error"])
        icon = xbmcgui.NOTIFICATION_WARNING
    else:
        message = i18n.t(32152, result["saved"], result["skipped"], result["failed"])
        icon = xbmcgui.NOTIFICATION_INFO

    xbmcgui.Dialog().notification(name, message, icon, 4000)
    return not result.get("error")
