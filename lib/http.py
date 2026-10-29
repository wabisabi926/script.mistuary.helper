# -*- coding: utf-8 -*-
"""HTTP 封装：只用标准库 urllib，不打包第三方依赖。

设计要点：
- **不抛异常到 UI**。任何失败返回 `Response(ok=False, status=0, error=...)`，
  调用方按状态决定降级，不会出现 Kodi 弹框。
- 超时 6 秒（比文档写的 5 秒略宽，给局域网 NAS 一点余量）。
- 固定 UA，避免部分反代把空 UA 拦掉。
- `Response.text/json` 都是惰性解析，避免为了一次状态判断把大响应全解析。

这个模块**不 import xbmc**，可以直接单测。
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_TIMEOUT = 6
USER_AGENT = "MistuaryHelper/0.1 (+https://github.com/wabisabi926/skin.mistuary)"


class Response(object):
    """一次 HTTP 调用的结果。status=0 表示连请求都没发出去。"""

    __slots__ = ("ok", "status", "body", "error")

    def __init__(self, ok=False, status=0, body=b"", error=""):
        self.ok = ok
        self.status = status
        self.body = body
        self.error = error

    @property
    def text(self) -> str:
        if isinstance(self.body, bytes):
            return self.body.decode("utf-8", "replace")
        return self.body or ""

    def json(self):
        try:
            return json.loads(self.text)
        except ValueError:
            return None

    def __repr__(self):
        return "Response(ok=%s, status=%s, error=%r)" % (self.ok, self.status, self.error)


def build_url(base: str, path: str, params: dict | None = None) -> str:
    """拼 URL。params 里值为 None 的键会被丢掉。"""
    url = "%s/%s" % (base.rstrip("/"), path.lstrip("/"))
    if not params:
        return url
    clean = {k: v for k, v in params.items() if v is not None}
    if not clean:
        return url
    return "%s?%s" % (url, urllib.parse.urlencode(clean, doseq=True))


def request(url: str, headers: dict | None = None, timeout: int = DEFAULT_TIMEOUT,
            data: bytes | None = None, method: str | None = None) -> Response:
    """发一次请求。永远返回 Response，不抛异常。"""
    merged = {"User-Agent": USER_AGENT}
    if headers:
        merged.update(headers)

    req = urllib.request.Request(url, data=data, headers=merged, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return Response(ok=200 <= resp.status < 300, status=resp.status, body=body)
    except urllib.error.HTTPError as exc:
        # 4xx/5xx：把状态码带回去，调用方要区分 401 和 500
        try:
            body = exc.read()
        except Exception:  # noqa: BLE001
            body = b""
        return Response(ok=False, status=exc.code, body=body, error="http %d" % exc.code)
    except urllib.error.URLError as exc:
        return Response(ok=False, status=0, error="unreachable: %s" % (exc.reason,))
    except socket.timeout:
        return Response(ok=False, status=0, error="timeout")
    except Exception as exc:  # noqa: BLE001 - 兜底，绝不让异常冒到 UI
        return Response(ok=False, status=0, error="%s: %s" % (type(exc).__name__, exc))


def get_json(url: str, headers: dict | None = None, timeout: int = DEFAULT_TIMEOUT):
    """GET 并解析 JSON。失败返回 (None, Response)，成功返回 (dict, Response)。"""
    resp = request(url, headers=headers, timeout=timeout)
    if not resp.ok:
        return None, resp
    payload = resp.json()
    if payload is None:
        return None, Response(ok=False, status=resp.status, error="invalid json")
    return payload, resp
