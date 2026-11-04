# -*- coding: utf-8 -*-
"""文件播放记录：本地账本 + Kodi 原生续播点。

两层存储：

* ``resume.db`` 是本插件自己的 SQLite（WAL），记录所有非库内视频/STRM；
* Kodi 的 ``MyVideos*.db`` 只通过 JSON-RPC ``Files.SetFileDetails`` 写，
  作为视频窗口（10025）原生续播的镜像。

**不直接打开 MyVideos.db**，也不依赖它的表结构。单测只覆盖纯逻辑和账本，
Kodi 相关代码全部惰性 import。
"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
import time
import xml.etree.ElementTree as ElementTree

from lib import i18n, log

SETTING_ENABLED = "file_resume"

SAMPLE_SECONDS = 30
MIRROR_SECONDS = 300
DEFAULT_START_GRACE = 180
DEFAULT_END_PERCENT = 8
TTL_DAYS = 90
MAX_RECORDS = 5000
# 10003-only：不写 Kodi MyVideos 原生续播点，resume.db 是唯一来源。
# 只有将来要把 10025 的原生进度条也交给 helper 管时才改成 True。
NATIVE_MIRROR = False

RESUME_MIN_SECONDS = 10
POLL_SECONDS = 0.1
FOCUS_NATIVE_TTL = 10
MAINTENANCE_SECONDS = 6 * 3600
SETTINGS_CACHE_SECONDS = 3.0

PLUGIN_WINDOW = 10003
HOME_WINDOW = 10000

INELIGIBLE_PREFIXES = (
    "plugin://", "pvr://",
    "sources://", "special://", "videodb://", "library://",
)
HTTP_PREFIXES = ("http://", "https://")
_USERINFO_RE = re.compile(r"(?i)^([a-z][a-z0-9+.-]*://)[^/@]+@")

PROP_HAS_RESUME = "Mistuary.FileResume.HasResume"
PROP_TIME = "Mistuary.FileResume.Time"
PROP_PERCENT = "Mistuary.FileResume.Percent"
PROP_KEY = "Mistuary.FileResume.PercentKey"

LIBRARY_TYPES = {"movie", "episode", "musicvideo", "song", "album", "artist"}

_SQLITE_TIMEOUT = 5.0


# ---------------------------------------------------------------------------
# 纯逻辑（可单测）
# ---------------------------------------------------------------------------

def _strip_userinfo(text: str) -> str:
    return _USERINFO_RE.sub(r"\1", text, count=1)


def normalize_key(path) -> str:
    """账本主键：统一斜杠、去尾斜杠、去 URL 里的 user:pass@；保留大小写。"""
    if not path:
        return ""
    key = _strip_userinfo(str(path).strip().replace("\\", "/"))
    while key.endswith("/"):
        key = key[:-1]
    return key


def fold_key(key) -> str:
    """大小写折叠索引：Windows/SMB 上同一文件可能返回不同大小写。"""
    return (key or "").casefold()


def format_time(seconds) -> str:
    try:
        total = max(0, int(seconds))
    except (TypeError, ValueError):
        return ""
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return "%d:%02d:%02d" % (hours, minutes, secs)
    return "%d:%02d" % (minutes, secs)


def format_dialog_time(seconds) -> str:
    """弹窗按钮用：不足 1 小时补成两位分钟（01:07），超过 1 小时保持 1:23:45。"""
    text = format_time(seconds)
    if not text:
        return ""
    if text.count(":") == 1:
        minutes, secs = text.split(":")
        return "%02d:%s" % (int(minutes), secs)
    return text


def percent_key(percent) -> str:
    """把 0–100 的百分比映射成三位文件名：7 -> '007'。"""
    try:
        value = max(0, min(100, int(percent)))
    except (TypeError, ValueError):
        value = 0
    return "%03d" % value


def is_eligible_path(path, allow_http=False) -> bool:
    key = normalize_key(path)
    if not key:
        return False
    lowered = key.casefold()
    if lowered.startswith(INELIGIBLE_PREFIXES):
        return False
    if not allow_http and lowered.startswith(HTTP_PREFIXES):
        return False
    return True


def source_for_path(path) -> str:
    return "strm" if normalize_key(path).casefold().endswith(".strm") else "file"


def is_finished(position, total, end_percent=DEFAULT_END_PERCENT) -> bool:
    try:
        position, total = float(position), float(total)
    except (TypeError, ValueError):
        return False
    if total <= 0 or position <= 0:
        return False
    return position * 100.0 / total >= (100.0 - float(end_percent))


def should_save(position, total, start_grace=DEFAULT_START_GRACE,
                end_percent=DEFAULT_END_PERCENT) -> bool:
    """起播 180 秒内不写，剩余 ≤8% 视为看完。"""
    try:
        position, total = float(position), float(total)
    except (TypeError, ValueError):
        return False
    if total <= 0:
        return False
    if position < float(start_grace):
        return False
    return not is_finished(position, total, end_percent)


def is_library_item(item) -> bool:
    """库内条目交给 Kodi/Emby，本插件不重复处理。"""
    if not isinstance(item, dict):
        return False
    return (item.get("type") or "").casefold() in LIBRARY_TYPES


# ---------------------------------------------------------------------------
# 账本
# ---------------------------------------------------------------------------

class ResumeStore:
    """一个进程一个连接；所有操作走锁，写事务都很短。"""

    def __init__(self, db_path):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._conn = None

    def open(self):
        with self._lock:
            if self._conn is not None:
                return
            folder = os.path.dirname(self.db_path)
            if folder:
                os.makedirs(folder, exist_ok=True)
            conn = sqlite3.connect(
                self.db_path, timeout=_SQLITE_TIMEOUT, check_same_thread=False
            )
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=3000")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS file_resume ("
                "  path_key TEXT PRIMARY KEY,"
                "  key_fold TEXT NOT NULL,"
                "  path TEXT NOT NULL,"
                "  pos REAL NOT NULL,"
                "  total REAL NOT NULL,"
                "  updated_at INTEGER NOT NULL,"
                "  source TEXT NOT NULL"
                ")"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_file_resume_updated "
                "ON file_resume(updated_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_file_resume_fold "
                "ON file_resume(key_fold)"
            )
            conn.commit()
            self._conn = conn

    def close(self):
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def _require(self):
        if self._conn is None:
            self.open()
        return self._conn

    @staticmethod
    def _row(row):
        if not row:
            return None
        return {
            "key": row[0],
            "path": row[1],
            "pos": row[2],
            "total": row[3],
            "updated_at": row[4],
            "source": row[5],
        }

    def get(self, path):
        key = normalize_key(path)
        if not key:
            return None
        with self._lock:
            conn = self._require()
            row = conn.execute(
                "SELECT path_key, path, pos, total, updated_at, source "
                "FROM file_resume WHERE path_key=?",
                (key,),
            ).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT path_key, path, pos, total, updated_at, source "
                    "FROM file_resume WHERE key_fold=? ORDER BY updated_at DESC LIMIT 1",
                    (fold_key(key),),
                ).fetchone()
        return self._row(row)

    def upsert(self, path, position, total, source=None, now=None) -> bool:
        key = normalize_key(path)
        try:
            position, total = float(position), float(total)
        except (TypeError, ValueError):
            return False
        if not key or total <= 0:
            return False
        ts = int(now if now is not None else time.time())
        with self._lock:
            conn = self._require()
            conn.execute(
                "INSERT OR REPLACE INTO file_resume"
                "(path_key, key_fold, path, pos, total, updated_at, source) "
                "VALUES (?,?,?,?,?,?,?)",
                (key, fold_key(key), key, position, total, ts,
                 source or source_for_path(path)),
            )
            conn.commit()
        return True

    def delete(self, path) -> None:
        key = normalize_key(path)
        if not key:
            return
        with self._lock:
            conn = self._require()
            cur = conn.execute(
                "DELETE FROM file_resume WHERE path_key=?", (key,)
            )
            if not cur.rowcount:
                conn.execute(
                    "DELETE FROM file_resume WHERE key_fold=?",
                    (fold_key(key),),
                )
            conn.commit()

    def recent(self, since=None, limit=MAX_RECORDS):
        with self._lock:
            conn = self._require()
            if since is None:
                rows = conn.execute(
                    "SELECT path_key, path, pos, total, updated_at, source "
                    "FROM file_resume ORDER BY updated_at DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT path_key, path, pos, total, updated_at, source "
                    "FROM file_resume WHERE updated_at>=? "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (int(since), int(limit)),
                ).fetchall()
        return [self._row(row) for row in rows]

    def cleanup(self, now=None, ttl_days=TTL_DAYS, max_records=MAX_RECORDS) -> int:
        """删过期记录，并把总量压到 max_records 以内。返回删除条数。"""
        removed = 0
        with self._lock:
            conn = self._require()
            if ttl_days and ttl_days > 0:
                cutoff = int((now if now is not None else time.time()) - ttl_days * 86400)
                cur = conn.execute("DELETE FROM file_resume WHERE updated_at<?", (cutoff,))
                removed = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
            if max_records and max_records > 0:
                cur = conn.execute(
                    "DELETE FROM file_resume WHERE path_key NOT IN ("
                    "SELECT path_key FROM file_resume ORDER BY updated_at DESC LIMIT ?)",
                    (int(max_records),),
                )
                if cur.rowcount and cur.rowcount > 0:
                    removed += cur.rowcount
            conn.commit()
        return removed

    def clear_all(self) -> int:
        with self._lock:
            conn = self._require()
            cur = conn.execute("DELETE FROM file_resume")
            removed = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
            conn.commit()
        return removed

    def data_version(self) -> int:
        """SQLite 的跨连接版本号：别的进程写库后这里会变。"""
        with self._lock:
            row = self._require().execute("PRAGMA data_version").fetchone()
        return int(row[0]) if row else 0

    def count(self) -> int:
        with self._lock:
            conn = self._require()
            row = conn.execute("SELECT COUNT(*) FROM file_resume").fetchone()
        return int(row[0]) if row else 0


def maintenance_action(action):
    """设置页按钮：查看条数 / 立即清理 / 清空全部。"""
    import xbmcaddon
    import xbmcgui
    import xbmcvfs

    profile = xbmcvfs.translatePath(
        "special://profile/addon_data/script.mistuary.helper"
    )
    store = ResumeStore(os.path.join(profile, "resume.db"))
    name = xbmcaddon.Addon("script.mistuary.helper").getAddonInfo("name")
    try:
        store.open()
        if action == "file_resume_status":
            xbmcgui.Dialog().notification(
                name, i18n.t(32101, store.count()),
                xbmcgui.NOTIFICATION_INFO, 3000
            )
        elif action == "file_resume_clear":
            if xbmcgui.Dialog().yesno(i18n.t(32070), i18n.t(32096)):
                store.clear_all()
                xbmcgui.Dialog().notification(
                    name, i18n.t(32097), xbmcgui.NOTIFICATION_INFO, 3000
                )
        else:
            removed = store.cleanup(
                ttl_days=retention_days(), max_records=max_records()
            )
            xbmcgui.Dialog().notification(
                name, i18n.t(32100, removed), xbmcgui.NOTIFICATION_INFO, 3000
            )
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Kodi 适配
# ---------------------------------------------------------------------------

def _jsonrpc(method, params):
    try:
        import json
        import xbmc

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or {},
        }
        return json.loads(xbmc.executeJSONRPC(json.dumps(payload)))
    except Exception:  # noqa: BLE001 - Kodi 不可用按空结果处理
        return {}


def _setting_bool(name, default=False) -> bool:
    try:
        import xbmcaddon

        return bool(xbmcaddon.Addon("script.mistuary.helper").getSettingBool(name))
    except Exception:  # noqa: BLE001
        return default


def _setting_string(name, default="") -> str:
    try:
        import xbmcaddon

        value = xbmcaddon.Addon("script.mistuary.helper").getSettingString(name)
        return value or default
    except Exception:  # noqa: BLE001
        return default


def retention_days() -> int:
    """保留天数：0 = 永不按时间清理。"""
    try:
        value = int(_setting_string("file_resume_ttl_days", str(TTL_DAYS)))
    except (TypeError, ValueError):
        value = TTL_DAYS
    return max(0, value)


def max_records() -> int:
    try:
        value = int(_setting_string("file_resume_max_records", str(MAX_RECORDS)))
    except (TypeError, ValueError):
        value = MAX_RECORDS
    return value if value > 0 else MAX_RECORDS


def _myvideos_resume_enabled() -> bool:
    data = _jsonrpc("Settings.GetSettingValue", {"setting": "myvideos.resume"})
    value = (data.get("result") or {}).get("value")
    if value is None:
        return True
    return bool(value)


def _video_limits(default_start=DEFAULT_START_GRACE,
                  default_end=DEFAULT_END_PERCENT):
    start, end = default_start, default_end
    try:
        import xbmcvfs

        path = xbmcvfs.translatePath("special://profile/advancedsettings.xml")
        root = ElementTree.parse(path).getroot()
        node = root.find("./video/ignoresecondsatstart")
        if node is not None and node.text:
            start = int(node.text)
        node = root.find("./video/ignorepercentatend")
        if node is not None and node.text:
            end = int(node.text)
    except Exception:  # noqa: BLE001 - 文件不存在/格式错误都用默认值
        pass
    return start, end


def _player_item():
    active = _jsonrpc("Player.GetActivePlayers", {})
    for row in (active.get("result") or []):
        if row.get("type") != "video":
            continue
        data = _jsonrpc("Player.GetItem", {
            "playerid": row.get("playerid", 1),
            "properties": ["file", "title"],
        })
        return (data.get("result") or {}).get("item") or {}
    return {}


def _from_filemanager() -> bool:
    try:
        import xbmc

        return bool(xbmc.getCondVisibility("Window.Previous(filemanager)"))
    except Exception:  # noqa: BLE001
        return False


def _best_playback_path(item, allow_http=False):
    """优先拿 .strm 本体路径，避免记到解析后的 http 地址上。"""
    candidates = []
    file_path = (item.get("file") or "").strip()
    if file_path:
        candidates.append(file_path)
    try:
        import xbmc

        list_path = (xbmc.getInfoLabel("ListItem.Path") or "").strip()
        if list_path:
            candidates.append(list_path)
        playing = (xbmc.Player().getPlayingFile() or "").strip()
        if playing:
            candidates.append(playing)
    except Exception:  # noqa: BLE001
        pass

    for candidate in candidates:
        if (candidate.casefold().endswith(".strm")
                and is_eligible_path(candidate, allow_http=allow_http)):
            return candidate
    for candidate in candidates:
        if is_eligible_path(candidate, allow_http=allow_http):
            return candidate
    return ""


def _native_resume(path):
    data = _jsonrpc("Files.GetFileDetails", {
        "file": path,
        "media": "video",
        "properties": ["resume"],
    })
    details = (data.get("result") or {}).get("filedetails") or {}
    resume = details.get("resume") or {}
    try:
        position = float(resume.get("position") or 0)
        total = float(resume.get("total") or 0)
    except (TypeError, ValueError):
        return None
    if position <= 0:
        return None
    return {"path": path, "pos": position, "total": total, "updated_at": 0}


def _has_total(row):
    try:
        return float(row.get("total") or 0) > 0
    except (TypeError, ValueError, AttributeError):
        return False


class FileResumeManager:
    """服务侧门面：播放回调、采样、10003 弹窗与焦点角标。"""

    def __init__(self, store: ResumeStore):
        self.store = store
        self._lock = threading.RLock()
        self._current = None
        self._sample_stop = None
        self._stop = threading.Event()
        self._poll_thread = None
        self._maint_thread = None
        self._cache = {}
        self._cache_fold = {}
        self._cache_version = 0
        self._last_version_check = 0.0
        self._focus_native = {}
        self._last_props = None
        self._enabled_cache = (0.0, True)
        self._native_cache = (0.0, True)
        self._start_grace, self._end_percent = _video_limits()

    # -- 设置 --------------------------------------------------------------

    def _enabled(self) -> bool:
        now = time.time()
        ts, value = self._enabled_cache
        if now - ts >= SETTINGS_CACHE_SECONDS:
            value = _setting_bool(SETTING_ENABLED, True)
            self._enabled_cache = (now, value)
        return value

    def _native_enabled(self) -> bool:
        now = time.time()
        ts, value = self._native_cache
        if now - ts >= SETTINGS_CACHE_SECONDS:
            value = _myvideos_resume_enabled()
            self._native_cache = (now, value)
        return value

    # -- 生命周期 ----------------------------------------------------------

    def start(self):
        try:
            self.store.open()
            ttl = retention_days()
            maxr = max_records()
            removed = self.store.cleanup(ttl_days=ttl, max_records=maxr)
            self._reload_cache(ttl, maxr)
            self._cache_version = self.store.data_version()
            log.info("file resume: %d records, %d expired" %
                     (len(self._cache), removed))
        except Exception as exc:  # noqa: BLE001 - 服务不能因账本失败退出
            log.error("file resume store failed: %s" % exc)

        self._poll_thread = threading.Thread(
            target=self._poll_loop, name="file-resume-focus", daemon=True
        )
        self._poll_thread.start()
        self._maint_thread = threading.Thread(
            target=self._maintenance_loop, name="file-resume-maint", daemon=True
        )
        self._maint_thread.start()
        self._publish(None)

    def _reload_cache(self, ttl, maxr):
        since = time.time() - ttl * 86400 if ttl > 0 else None
        rows = self.store.recent(since=since, limit=maxr)
        with self._lock:
            self._cache = {row["key"]: row for row in rows}
            self._cache_fold = {fold_key(row["key"]): row for row in rows}
            self._focus_native.clear()

    def _maintenance_loop(self):
        while not self._stop.wait(MAINTENANCE_SECONDS):
            try:
                ttl = retention_days()
                maxr = max_records()
                removed = self.store.cleanup(ttl_days=ttl, max_records=maxr)
                self._reload_cache(ttl, maxr)
                self._cache_version = self.store.data_version()
                if removed:
                    log.info("file resume maintenance: removed %d" % removed)
            except Exception as exc:  # noqa: BLE001
                log.error("file resume maintenance failed: %s" % exc)

    def stop(self):
        self._stop.set()
        self._persist(mirror=True)
        self._clear_badge()
        try:
            self.store.close()
        except Exception:  # noqa: BLE001
            pass

    # -- 播放回调 ----------------------------------------------------------

    def on_av_started(self):
        try:
            import xbmc

            player = xbmc.Player()
            if not player.isPlayingVideo():
                return
            item = _player_item()
            if is_library_item(item):
                return
            # 只记录皮肤 10003 文件管理器里的播放；10025/插件播放不记。
            if not _from_filemanager():
                return
            if not self._enabled():
                return

            path = _best_playback_path(
                item, allow_http=_setting_bool("file_resume_http", False)
            )
            if not path:
                return
            total = float(player.getTotalTime() or 0)
            if total <= 0:
                return

            previous = self._take_current()
            now = time.time()
            is_transition = False
            if previous:
                self._save_and_mirror(previous)
                is_transition = self._is_auto_transition(previous, path, now)

            with self._lock:
                self._current = {
                    "path": path,
                    "key": normalize_key(path),
                    "source": source_for_path(path),
                    "pos": 0.0,
                    "total": total,
                    "last_saved": 0.0,
                    "last_mirror": time.time(),
                    "last_update": now,
                }
            self._start_sampler()

            if not is_transition:
                self._maybe_prompt(path, total)
        except Exception as exc:  # noqa: BLE001 - 播放不能因续播失败中断
            log.error("file resume start failed: %s" % exc)

    def on_paused(self):
        self._persist(mirror=True)

    def on_seek(self):
        self._persist(mirror=True)

    def on_stopped(self):
        current = self._take_current()
        if current:
            self._persist_snapshot(current, mirror=True)

    def on_ended(self):
        current = self._take_current()
        if not current:
            return
        try:
            self.store.delete(current["path"])
        except Exception as exc:  # noqa: BLE001
            log.error("file resume clear failed: %s" % exc)
        with self._lock:
            self._forget(current["key"])
        self._mirror(current, clear=True)

    def on_clean_finished(self, library=""):
        if str(library).casefold() not in ("", "video"):
            return
        if not self._enabled() or not self._native_enabled():
            return
        thread = threading.Thread(
            target=self._restore_native, name="file-resume-restore", daemon=True
        )
        thread.start()

    # -- 采样 --------------------------------------------------------------

    def _start_sampler(self):
        self._stop_sampler()
        stop = threading.Event()
        self._sample_stop = stop
        thread = threading.Thread(
            target=self._sample_loop, args=(stop,),
            name="file-resume-sample", daemon=True,
        )
        thread.start()

    def _stop_sampler(self):
        stop = self._sample_stop
        self._sample_stop = None
        if stop is not None:
            stop.set()

    def _sample_loop(self, stop):
        import xbmc

        player = xbmc.Player()
        while not stop.is_set() and not self._stop.is_set():
            if stop.wait(1.0):
                break
            try:
                if not player.isPlaying():
                    break
                position = float(player.getTime() or 0)
                total = float(player.getTotalTime() or 0)
            except Exception:  # noqa: BLE001 - 播放器切换/停止
                break

            with self._lock:
                current = self._current
                if current is None:
                    break
                current["pos"] = position
                if total > 0:
                    current["total"] = total
                current["last_update"] = time.time()
                snapshot = dict(current)

            if not should_save(snapshot["pos"], snapshot["total"],
                               self._start_grace, self._end_percent):
                continue

            now = time.time()
            if now - snapshot["last_saved"] >= SAMPLE_SECONDS:
                self._save_ledger(snapshot)
                with self._lock:
                    if self._current is current:
                        self._current["last_saved"] = now
            if now - snapshot["last_mirror"] >= MIRROR_SECONDS:
                self._mirror(snapshot)
                with self._lock:
                    if self._current is current:
                        self._current["last_mirror"] = now

    # -- 写入 --------------------------------------------------------------

    def _take_current(self):
        with self._lock:
            current = self._current
            self._current = None
        self._stop_sampler()
        return current

    def _persist(self, mirror=False):
        with self._lock:
            current = dict(self._current) if self._current else None
        self._persist_snapshot(current, mirror=mirror)

    def _persist_snapshot(self, current, mirror=False):
        if not current:
            return
        if not self._enabled():
            return

        if is_finished(current["pos"], current["total"], self._end_percent):
            try:
                self.store.delete(current["path"])
            except Exception as exc:  # noqa: BLE001
                log.error("file resume clear failed: %s" % exc)
            with self._lock:
                self._forget(current["key"])
            if mirror:
                self._mirror(current, clear=True)
            return

        if not should_save(current["pos"], current["total"],
                           self._start_grace, self._end_percent):
            return
        self._save_ledger(current)
        if mirror:
            self._mirror(current)

    def _save_ledger(self, current):
        try:
            self.store.upsert(
                current["path"], current["pos"], current["total"],
                source=current["source"],
            )
            row = {
                "key": current["key"],
                "path": current["path"],
                "pos": current["pos"],
                "total": current["total"],
                "updated_at": int(time.time()),
                "source": current["source"],
            }
            with self._lock:
                self._cache[current["key"]] = row
                self._cache_fold[fold_key(current["key"])] = row
                self._focus_native.pop(current["key"], None)
        except Exception as exc:  # noqa: BLE001 - 账本写失败不打断播放
            log.error("file resume save failed: %s" % exc)

    def _save_and_mirror(self, current):
        if not self._enabled():
            return
        if not should_save(current["pos"], current["total"],
                           self._start_grace, self._end_percent):
            return
        self._save_ledger(current)
        self._mirror(current)

    def _mirror(self, current, clear=False):
        if not NATIVE_MIRROR:
            return
        if not self._native_enabled():
            return
        position = 0 if clear else int(max(0.0, current["pos"]))
        data = _jsonrpc("Files.SetFileDetails", {
            "file": current["path"],
            "media": "video",
            "resume": {
                "position": position,
                "total": int(max(0.0, current["total"])),
            },
        })
        if data.get("error"):
            log.debug("file resume mirror failed: %s" % data["error"])

    def _forget(self, key):
        fold = fold_key(key)
        with self._lock:
            for cached_key in list(self._cache):
                if fold_key(cached_key) == fold:
                    self._cache.pop(cached_key, None)
            self._cache_fold.pop(fold, None)
            self._focus_native.pop(key, None)

    def _clear_resume(self, path, total=0):
        try:
            self.store.delete(path)
        except Exception as exc:  # noqa: BLE001
            log.error("file resume clear failed: %s" % exc)
        self._forget(normalize_key(path))
        self._mirror({"path": path, "total": total}, clear=True)

    # -- 10003 弹窗 --------------------------------------------------------

    @staticmethod
    def _is_auto_transition(previous, path, now):
        """同一文件重开必须弹窗；120 秒内的不同文件才算连播切换。"""
        if not previous:
            return False
        last_update = float(previous.get("last_update") or 0)
        if now - last_update > 120:
            return False
        return previous.get("key") != normalize_key(path)

    def _maybe_prompt(self, path, total):
        if not _from_filemanager():
            return
        record = self.store.get(path)
        if record is None:
            record = _native_resume(path)
        if record is None:
            return
        position = float(record.get("pos") or 0)
        record_total = float(record.get("total") or 0) or total
        if position < RESUME_MIN_SECONDS:
            return
        if is_finished(position, record_total, self._end_percent):
            return

        import xbmc

        started = time.time()
        player = xbmc.Player()
        if not player.isPlaying():
            return
        # 先冻住画面再问：等价于“先弹窗、再播放”，避免背后先走半秒。
        if not xbmc.getCondVisibility("Player.Paused"):
            xbmc.executebuiltin("PlayerControl(Pause)")
            xbmc.sleep(120)
        log.info("resume pause done after %.2fs" % (time.time() - started))
        choice = self._show_resume_dialog(position, started)
        log.info("file resume prompt: pos=%.1f total=%.0f choice=%s"
                 % (position, record_total, choice))
        if choice == "continue":
            player.seekTime(position)
        elif choice == "cancel":
            # 取消 = 不播：停掉播放并恢复原记录，别让 Kodi 把续播点写成 0
            xbmc.executebuiltin("PlayerControl(Stop)")
            xbmc.sleep(150)
            self._mirror({"path": path, "pos": position, "total": record_total})
            return
        elif choice == "start":
            # 从头开始 = 删记录 + 明确回到 0；暂停时播放器可能已停在旧位置
            self._clear_resume(path, record_total)
            player.seekTime(0)
        if xbmc.getCondVisibility("Player.Paused"):
            xbmc.executebuiltin("PlayerControl(Play)")

    def _show_resume_dialog(self, position, started=None):
        """打开皮肤 1115 紧凑弹窗；返回 continue / start / cancel。"""
        import xbmc
        import xbmcgui

        home = xbmcgui.Window(HOME_WINDOW)
        props = {
            "Continue": i18n.t(32082, format_dialog_time(position)),
            "Start": i18n.t(32075),
            "Choice": "",
        }
        try:
            for name, value in props.items():
                home.setProperty("Mistuary.ResumeDialog." + name, value)
            xbmc.executebuiltin("ActivateWindow(1115)")
            start = time.time()
            if started:
                log.info("resume dialog requested after %.2fs" % (start - started))
            deadline = start + 60
            seen = False
            choice = ""
            while time.time() < deadline:
                active = bool(xbmc.getCondVisibility("Window.IsActive(1115)"))
                if active:
                    if not seen:
                        log.info("resume dialog active after %.2fs (activate %.2fs)"
                                 % (time.time() - (started or start), time.time() - start))
                    seen = True
                choice = home.getProperty("Mistuary.ResumeDialog.Choice") or ""
                if choice:
                    break
                if not seen and time.time() - start > 2.0:
                    break
                if seen and not active:
                    break
                xbmc.sleep(100)
            try:
                xbmc.executebuiltin("Dialog.Close(1115)")
            except Exception:  # noqa: BLE001
                pass
            if choice:
                return choice
            if not seen:
                # 别的地方用这个 helper / 皮肤没有 1115：退回原生 yes/no。
                # yesno 默认聚焦 No；让 No = 继续播放，行为与紧凑弹窗一致。
                result = xbmcgui.Dialog().yesno(
                    i18n.t(32072),
                    i18n.t(32073, format_dialog_time(position)),
                    nolabel=i18n.t(32074),
                    yeslabel=i18n.t(32075),
                )
                return "start" if result else "continue"
            return "cancel"
        except Exception as exc:  # noqa: BLE001
            log.error("file resume dialog failed: %s" % exc)
            return "continue"
        finally:
            for name in props:
                home.clearProperty("Mistuary.ResumeDialog." + name)

    # -- 清理媒体库后恢复 --------------------------------------------------

    def _restore_native(self):
        if not NATIVE_MIRROR:
            return
        try:
            time.sleep(3.0)
            rows = self.store.recent(
                since=time.time() - TTL_DAYS * 86400, limit=500
            )
            restored = 0
            for row in rows:
                if not is_eligible_path(row["path"]):
                    continue
                if not should_save(row["pos"], row["total"],
                                   self._start_grace, self._end_percent):
                    continue
                native = _native_resume(row["path"])
                if native and abs(native["pos"] - row["pos"]) <= 5:
                    continue
                self._mirror(row)
                restored += 1
            log.info("file resume restore: %d records" % restored)
        except Exception as exc:  # noqa: BLE001
            log.error("file resume restore failed: %s" % exc)

    # -- 10003 焦点角标 ----------------------------------------------------

    def _poll_loop(self):
        import xbmc

        active = False
        empty_since = None
        last_path = None
        while not self._stop.is_set():
            try:
                # 别的进程（设置里的清理/清空）改过库时，5 秒内刷新缓存。
                now = time.time()
                if now - self._last_version_check >= 5.0:
                    self._last_version_check = now
                    version = self.store.data_version()
                    if version != self._cache_version:
                        self._reload_cache(retention_days(), max_records())
                        self._cache_version = version
                if self._enabled() and xbmc.getCondVisibility(
                        "Window.IsActive(%d)" % PLUGIN_WINDOW):
                    # 文件管理器 10003 的 ListItem.Path 是当前目录，
                    # 完整文件路径在 ListItem.FolderPath（实机确认）。
                    path = (xbmc.getInfoLabel("ListItem.FolderPath")
                            or xbmc.getInfoLabel("ListItem.Path") or "")
                    probe = self._focus_probe(
                        path, xbmc.getCondVisibility("ListItem.IsFolder"))
                    if probe is None:
                        # 焦点切换瞬间路径为空：先保留，持续 0.2 秒才清。
                        now = time.time()
                        if empty_since is None:
                            empty_since = now
                        elif now - empty_since >= 0.2:
                            self._publish(None)
                    else:
                        empty_since = None
                        if probe == "clear":
                            self._publish(None)
                            last_path = None
                        else:
                            if (probe != last_path and self._last_props
                                    and self._last_props[0] == "true"):
                                # 换行时先隐藏旧圆环，停 30ms 再显示新值：
                                # 缩短上一行进度残留，也逼图片控件重新取贴图。
                                self._publish(None)
                                time.sleep(0.03)
                            last_path = probe
                            self._publish(self._lookup(probe))
                    active = True
                elif active:
                    self._clear_badge()
                    active = False
                    empty_since = None
                    last_path = None
            except Exception:  # noqa: BLE001 - 轮询不能把服务拖死
                pass
            self._stop.wait(POLL_SECONDS)

    @staticmethod
    def _focus_probe(path, is_folder):
        """None = 瞬态空路径（保留旧值）；"clear" = 文件夹行；其余 = 文件路径。"""
        if is_folder:
            return "clear"
        return path or None

    def _lookup(self, path):
        key = normalize_key(path)
        if not key:
            return None
        with self._lock:
            row = self._cache.get(key) or self._cache_fold.get(fold_key(key))
            if row and _has_total(row):
                return row
            now = time.time()
            hit = self._focus_native.get(key)
            if hit and now - hit[0] < FOCUS_NATIVE_TTL:
                return hit[1] if hit[1] and _has_total(hit[1]) else None
        # 账本里没有时回退 Kodi/Emby 的续播点，圆环和弹窗口径一致。
        row = _native_resume(path)
        if row and not _has_total(row):
            row = None  # 只有位置没有总长时算不出百分比，宁可不显示
        with self._lock:
            self._focus_native[key] = (now, row)
            if len(self._focus_native) > 64:
                oldest = min(self._focus_native, key=lambda k: self._focus_native[k][0])
                self._focus_native.pop(oldest, None)
        return row

    @staticmethod
    def _ring_props(row):
        if not row:
            return None
        try:
            total = float(row.get("total") or 0)
            pos = float(row.get("pos") or 0)
        except (TypeError, ValueError):
            return None
        if total <= 0 or pos <= 0:
            return None
        percent = max(0, min(100, int(pos * 100 / total)))
        return ("true", format_time(pos), str(percent), percent_key(percent))

    def _publish(self, row):
        props = self._ring_props(row) or ("false", "", "", "000")
        with self._lock:
            if self._last_props == props:
                return
            self._last_props = props
        self._set_props(*props)

    def _clear_badge(self):
        self._publish(None)

    @staticmethod
    def _set_props(has_resume, time_text, percent, bucket):
        try:
            import xbmcgui

            window = xbmcgui.Window(HOME_WINDOW)
            window.setProperty(PROP_HAS_RESUME, has_resume)
            window.setProperty(PROP_TIME, time_text)
            window.setProperty(PROP_PERCENT, percent)
            window.setProperty(PROP_KEY, bucket)
        except Exception:  # noqa: BLE001
            pass
