# -*- coding: utf-8 -*-
"""背景剧照的「流光溢彩」色光底：真高斯模糊，铺在 fanart_void 黑底之上。

Kodi 皮肤 XML 没有模糊滤镜，只能由 Python 侧算好一张 jpg、把路径写进
Window(home) 属性，皮肤再当普通贴图铺满屏。

**不依赖 TMDbHelper**：只用 Kodi 自带 API（xbmc / xbmcvfs / xbmcgui）和
Kodi 系统 Python 自带的 Pillow。借鉴的只是 fuse3/TMDbHelper 的「缩略图 +
镜像平铺消边界暗角」这个思路，没有任何 import 或 addon.xml 依赖。

PIL 不可用 / 源图打不开时整体静默降级：属性清空，皮肤露出原来的纯黑底，
不影响其它能力，也不写日志噪音。
"""

from __future__ import annotations

import hashlib
import io
import os
import time

from lib import log

PROPERTY_GLOW = "Mistuary.FanartGlow"
PROPERTY_SOURCE = "Mistuary.FanartSource"
HOME_WINDOW_ID = 10000

# 透黑玻璃是相乘关系，超过 0.4 会把 UI 垫灰、把亮度档位差压平。
BRIGHTNESS = 0.25
# 先缩小再模糊：计算量与源图分辨率无关，4K 剧照和 720p 一样快。
SMALL_SIZE = (320, 180)
BLUR_RADIUS = 27
# md5 命中直接复用；按 mtime 淘汰最旧，避免 addon_data 无限长。
MAX_FILES = 24

POLL_SECONDS = 0.4
IDLE_SECONDS = 2.0
SETTLE_SECONDS = 0.3

# 皮肤里与清晰图绑同一个变量的隐藏 label。三个窗口各用不同 id，
# 因为 View_51_Poster 是 Home 窗口里的 view，id 不能和 Home.xml 撞。
SOURCE_LABEL_IDS = (9099, 9098, 9097)


def _pil():
    """Kodi 22 起系统 Python 自带 Pillow；老版本靠 script.module.pil 提供。"""
    try:
        from PIL import Image, ImageEnhance, ImageFilter

        return Image, ImageEnhance, ImageFilter
    except Exception:  # noqa: BLE001 - 缺失/损坏都走降级
        return None


def build_glow(path, brightness=BRIGHTNESS):
    """本地图片 -> 640x360 色光 JPEG 的字节；PIL 不可用返回 None。

    纯函数：只吃本地路径、只吐字节，不碰 Kodi，方便单测。
    2x2 镜像平铺是为了消掉高斯模糊在图像边界的暗角（fuse3 的 -tiled.jpg
    是同一思路，但它在磁盘上另存一份；这里直接在内存里拼好，只出一个文件）。
    """
    pil = _pil()
    if pil is None:
        return None
    Image, ImageEnhance, ImageFilter = pil
    try:
        with Image.open(path) as src:
            im = src.convert("RGB").resize(SMALL_SIZE, Image.LANCZOS)
        blurred = im.filter(ImageFilter.GaussianBlur(BLUR_RADIUS))
        w, h = blurred.size
        tile = Image.new("RGB", (w * 2, h * 2))
        tile.paste(blurred, (0, 0))
        tile.paste(blurred.transpose(Image.FLIP_LEFT_RIGHT), (w, 0))
        tile.paste(blurred.transpose(Image.FLIP_TOP_BOTTOM), (0, h))
        tile.paste(
            blurred.transpose(Image.FLIP_TOP_BOTTOM).transpose(Image.FLIP_LEFT_RIGHT),
            (w, h),
        )
        tile = ImageEnhance.Brightness(tile).enhance(brightness)
        buf = io.BytesIO()
        tile.save(buf, format="JPEG", quality=82, optimize=True)
        return buf.getvalue()
    except Exception as exc:  # noqa: BLE001 - 单张坏图不能拖垮服务
        log.error("fanart glow build failed: %s" % exc)
        return None


def _glow_dir():
    import xbmcvfs

    path = xbmcvfs.translatePath(
        "special://profile/addon_data/script.mistuary.helper/glow"
    )
    os.makedirs(path, exist_ok=True)
    return path


def prune(directory, max_files=MAX_FILES):
    """按 mtime 淘汰最旧的色光 jpg。纯文件系统操作，可单测。"""
    try:
        files = [
            os.path.join(directory, name)
            for name in os.listdir(directory)
            if name.startswith("glow-") and name.endswith(".jpg")
        ]
    except OSError:
        return 0
    if len(files) <= max_files:
        return 0
    files.sort(key=lambda p: os.path.getmtime(p))
    removed = 0
    for path in files[: len(files) - max_files]:
        try:
            os.remove(path)
            removed += 1
        except OSError:
            pass
    return removed


def render(source):
    """把皮肤给的源图换成色光 jpg 的本地路径；失败返回 None。

    源图可能是 image:// 这类 Kodi 虚拟协议，PIL 打不开，所以先由
    xbmcvfs.copy() 落到本地临时文件（TMDbHelper 的 _openimage 同样处理）。
    """
    if not source or _pil() is None:
        return None
    tmp = None
    try:
        import xbmcvfs

        directory = _glow_dir()
        digest = hashlib.md5(source.encode("utf-8")).hexdigest()[:12]
        dest = os.path.join(directory, "glow-%s.jpg" % digest)
        # 命中缓存：连 xbmcvfs.copy 都省掉，滚动回看过的条目是零计算。
        if os.path.isfile(dest) and os.path.getsize(dest) > 0:
            return dest

        tmp = os.path.join(directory, "source.tmp")
        if os.path.exists(tmp):
            os.remove(tmp)
        if not xbmcvfs.copy(source, tmp):
            return None
        payload = build_glow(tmp)
        if payload is None:
            return None

        # 先写 .tmp 再原子改名：避免 Kodi 在文件写一半时把它缓存进贴图。
        staged = dest + ".tmp"
        with open(staged, "wb") as handle:
            handle.write(payload)
        os.replace(staged, dest)
        prune(directory)
        return dest
    except Exception as exc:  # noqa: BLE001 - 服务不能因单张图退出
        log.error("fanart glow render failed: %s" % exc)
        return None
    finally:
        if tmp:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass


def should_render(source, pending, published, now, settle=SETTLE_SECONDS):
    """纯判定：源图停稳 settle 秒才值得算一次，滚动途中不触发。

    pending 是 (source, first_seen) 或 None；published 是上次已发布的源图。
    返回 (是否渲染, 新的 pending)。抽成函数是为了能脱离 Kodi 单测节流逻辑。
    """
    if not source:
        return False, None
    if source == published:
        return False, None
    if pending is None or pending[0] != source:
        return False, (source, now)
    if now - pending[1] < settle:
        return False, pending
    return True, None


class FanartGlowMonitor:
    """低开销轮询：只在影视相关窗口活动，开关关掉时按 2s 空转。"""

    def __init__(self):
        self._published = None
        self._pending = None

    def _enabled(self):
        import xbmc

        # 开关读插件设置；皮肤侧只是显示/切换，不重复存一份状态。
        try:
            import xbmcaddon

            return bool(xbmcaddon.Addon().getSettingBool("fanart_glow"))
        except Exception:  # noqa: BLE001
            return False

    def _relevant_window(self):
        import xbmc

        # View_51_Poster 是 Home 窗口里的 view，所以 Home 命中即覆盖季页。
        # Kodi 22 没有 videoinformation / tvshowinformation 这两个窗口名：
        # 写进表达式会每 tick 刷两条 "Window Translator: Can't find window"。
        # 电影 / 剧集 / 单集详情都是 DialogVideoInfo.xml，统一叫 movieinformation。
        return bool(
            xbmc.getCondVisibility(
                "Window.IsVisible(Home) | Window.IsVisible(movieinformation)"
            )
        )

    def _read_source(self):
        """优先读皮肤隐藏 label（与清晰图严格同源），再逐级兜底。"""
        import xbmc

        candidates = ["Control.GetLabel(%d)" % i for i in SOURCE_LABEL_IDS]
        candidates.append("Window(home).Property(%s)" % PROPERTY_SOURCE)
        for expr in candidates:
            value = xbmc.getInfoLabel(expr)
            if value and value not in ("undefined",) and not value.startswith("$"):
                return value
        # 详情页 <onload> 已经把 infobackground 写进 Window(home)。
        if xbmc.getCondVisibility("Window.IsVisible(movieinformation)"):
            value = xbmc.getInfoLabel("Window(home).Property(infobackground)")
            if value:
                return value
        for expr in ("ListItem.Art(fanart)", "Container.ListItem.Art(fanart)"):
            value = xbmc.getInfoLabel(expr)
            if value:
                return value
        return ""

    def _publish(self, path):
        import xbmcgui

        window = xbmcgui.Window(HOME_WINDOW_ID)
        if path:
            window.setProperty(PROPERTY_GLOW, path)
        else:
            window.clearProperty(PROPERTY_GLOW)

    def tick(self, now=None):
        """跑一次判定。返回本次使用的轮询间隔，方便服务循环 sleep。"""
        import xbmc  # noqa: F401 - 保持与 Kodi 环境一致

        now = time.time() if now is None else now
        if not self._enabled() or not self._relevant_window():
            if self._published is not None:
                self._publish("")
                self._published = None
                self._pending = None
            return IDLE_SECONDS

        source = self._read_source()
        if not source:
            if self._published is not None:
                self._publish("")
                self._published = None
                self._pending = None
            return POLL_SECONDS

        run, self._pending = should_render(
            source, self._pending, self._published, now
        )
        if not run:
            return POLL_SECONDS

        path = render(source)
        if path:
            self._publish(path)
            self._published = source
        # 渲染失败不清空上一张：保留住已有色光比突然闪回纯黑好。
        return POLL_SECONDS

    def run(self, stop):
        """服务线程入口；stop 是 threading.Event。"""
        while not stop.is_set():
            try:
                delay = self.tick()
            except Exception as exc:  # noqa: BLE001 - 后台线程不能影响服务
                log.error("fanart glow tick failed: %s" % exc)
                delay = POLL_SECONDS
            stop.wait(delay)
        try:
            self._publish("")
        except Exception:  # noqa: BLE001
            pass
