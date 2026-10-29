# -*- coding: utf-8 -*-
"""参数解析。

Kodi 交给插件的是 `sys.argv[2]`，形如：
    `?mode=search&type=movies&query=让子弹飞`
    `?action=rating&type=movie&dbid=1234`

**`query` 必须是最后一个参数**，用 `split("query=", 1)` 取值：
中文不需要解码（Kodi 传的是原始 UTF-8），但 `&` 和 `?` 如果出现在
搜索词里，用 `parse_qs` 会被当成参数分隔符切碎。
已知限制：`#` 会被 Kodi 当锚点截断，无法绕开（文档里写明）。

这个模块**不 import xbmc**，所以可以脱离 Kodi 单测。
"""

from __future__ import annotations

from urllib.parse import parse_qs


class Request(object):
    """一次调用的意图。字段少而明确，避免用 dict 到处传。"""

    __slots__ = ("mode", "action", "type", "query", "dbid", "offset", "raw")

    def __init__(self, mode="", action="", type="", query="", dbid="", offset=0, raw=""):
        self.mode = mode
        self.action = action
        self.type = type
        self.query = query
        self.dbid = dbid
        self.offset = offset
        self.raw = raw

    def __repr__(self):
        return "Request(mode=%r, action=%r, type=%r, query=%r, dbid=%r, offset=%r)" % (
            self.mode, self.action, self.type, self.query, self.dbid, self.offset,
        )


def _clean(raw: str) -> str:
    if not raw:
        return ""
    raw = raw.lstrip("?")
    return raw


def parse(raw: str) -> Request:
    """把 argv[2] 解析成 Request。任何畸形输入都返回空 Request，不抛异常。"""
    raw = _clean(raw or "")
    if not raw:
        return Request(raw=raw)

    query = ""
    head = raw

    # query 是最后一个参数：从第一次出现 "query=" 处切断，右边整段都算搜索词。
    if "query=" in raw:
        head, query = raw.split("query=", 1)
        head = head.rstrip("&")

    params = parse_qs(head, keep_blank_values=True)

    def one(key: str) -> str:
        values = params.get(key) or []
        return values[0] if values else ""

    offset_raw = one("offset")
    try:
        offset = int(offset_raw) if offset_raw else 0
    except (TypeError, ValueError):
        offset = 0

    return Request(
        mode=one("mode"),
        action=one("action"),
        type=one("type"),
        query=query,
        dbid=one("dbid"),
        offset=max(0, offset),
        raw=raw,
    )


def build_search_url(base_url: str, media_type: str, query: str, offset: int = 0) -> str:
    """拼一个目录 URL，给「加载更多」用。

    query 放最后且不做百分号编码 —— 与 parse() 的假设对称。
    """
    url = "%s?mode=search&type=%s&offset=%d&query=%s" % (base_url, media_type, offset, query)
    return url
