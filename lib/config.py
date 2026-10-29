# -*- coding: utf-8 -*-
"""读插件设置 + 定位 Emby 服务器。

服务器配置不在本插件里，而是直接读 Emby for Kodi Next Gen 的
`addon_data/plugin.service.emby-next-gen/servers_<id>.json`：
用户不用二次输入地址和令牌，装了 Emby 插件就能用。

实测字段（Emby Next Gen 4.10.x）：

    ServerId / ServerName / ServerVersion
    ServerUrl        http://192.168.50.250:8096/      ← 末尾带斜杠
    ManualAddress    http://192.168.50.250:8096/
    LocalAddress     http://192.168.50.250:8096       ← 不带斜杠
    RemoteAddress    http://xxx.ddns.net:8096
    AccessToken      32 位
    UserId           32 位
    ServerRemoved    bool

地址优先级：ServerUrl → ManualAddress → LocalAddress → RemoteAddress。
（文档 §5.1 只写了三个，实测 ManualAddress 也要算进去，否则用户手填的地址会被忽略。）
"""

from __future__ import annotations

import glob
import json
import os

EMBY_ADDON_ID = "plugin.service.emby-next-gen"
ADDRESS_KEYS = ("ServerUrl", "ManualAddress", "LocalAddress", "RemoteAddress")

DEFAULTS = {
    "server_id": "",
    "page_size": 100,
    "douban_enabled": True,
    "cache_ttl": 300,
    "debug_log": False,
}


class Server(object):
    """一个可用的 Emby 服务器。base_url 保证不带尾部斜杠。"""

    __slots__ = ("server_id", "name", "base_url", "token", "user_id", "version")

    def __init__(self, server_id, name, base_url, token, user_id, version=""):
        self.server_id = server_id
        self.name = name
        self.base_url = (base_url or "").rstrip("/")
        self.token = token
        self.user_id = user_id
        self.version = version

    @property
    def usable(self) -> bool:
        return bool(self.base_url and self.token and self.user_id)

    def __repr__(self):
        # 故意不含 token：这个 repr 可能被日志打印
        return "Server(id=%s, name=%r, base_url=%r)" % (self.server_id, self.name, self.base_url)


def profile_dir() -> str:
    """Kodi 的 userdata 目录。抽成函数方便测试替换。"""
    import xbmcvfs

    return xbmcvfs.translatePath("special://profile")


def _pick_address(data: dict) -> str:
    for key in ADDRESS_KEYS:
        value = (data.get(key) or "").strip()
        if value:
            return value
    return ""


def load_servers(profile: str | None = None) -> list[Server]:
    """扫描所有 servers_*.json，返回可用服务器（保持文件顺序）。

    任何一步失败都返回空列表 —— 调用方按「未配置」处理，不抛异常。
    """
    root = profile or profile_dir()
    pattern = os.path.join(root, "addon_data", EMBY_ADDON_ID, "servers_*.json")
    servers: list[Server] = []

    for path in sorted(glob.glob(pattern)):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or data.get("ServerRemoved"):
            continue

        server = Server(
            server_id=(data.get("ServerId") or "").strip(),
            name=(data.get("ServerName") or "").strip(),
            base_url=_pick_address(data),
            token=(data.get("AccessToken") or "").strip(),
            user_id=(data.get("UserId") or "").strip(),
            version=(data.get("ServerVersion") or "").strip(),
        )
        if server.usable:
            servers.append(server)

    return servers


def find_server(server_id: str = "", profile: str | None = None) -> Server | None:
    """按设置里的 server_id 选服务器；为空取第一个。"""
    servers = load_servers(profile)
    if not servers:
        return None
    if server_id:
        for server in servers:
            if server.server_id == server_id:
                return server
        # 设置里钉的服务器已经不存在（用户换过服务器）：退回第一个，别让功能整个失效
        return servers[0]
    return servers[0]


def read_settings() -> dict:
    """读插件设置。任何一项读不到就用 DEFAULTS，不抛异常。"""
    values = dict(DEFAULTS)
    try:
        import xbmcaddon

        addon = xbmcaddon.Addon()
        values["server_id"] = addon.getSettingString("server_id") or ""
        try:
            values["page_size"] = max(1, int(addon.getSettingInt("page_size") or DEFAULTS["page_size"]))
        except (TypeError, ValueError):
            pass
        values["douban_enabled"] = bool(addon.getSettingBool("douban_enabled"))
        try:
            values["cache_ttl"] = max(0, int(addon.getSettingInt("cache_ttl") or DEFAULTS["cache_ttl"]))
        except (TypeError, ValueError):
            pass
        values["debug_log"] = bool(addon.getSettingBool("debug_log"))
    except Exception:  # noqa: BLE001 - 单测环境没有 xbmcaddon
        pass
    return values
