# -*- coding: utf-8 -*-
"""本地化。语言文件在 `resources/language/resource.language.<lang>/strings.po`。

`FALLBACK` 是中文兜底：语言文件没加载（比如用户改坏了 po）时，
至少不会显示成空字符串或 `32021` 这种 ID。

字符串带 `{0}` 占位，用 `.format()` 填；占位不匹配时原样返回，不抛异常。
"""

from __future__ import annotations

FALLBACK = {
    32020: "请从皮肤进入，或在「我的插件」里打开本插件的设置。",
    32021: "没有找到 Emby 服务器配置，请先安装并登录 Emby 插件。",
    32022: "请输入搜索词。",
    32023: "Emby 登录已失效，请在 Emby 插件里重新连接。",
    32024: "Emby 服务端不可达，请检查网络或服务器地址。",
    32025: "Emby 返回错误（HTTP {0}）。",
    32026: "没有找到「{0}」。",
    32027: "加载更多…",
    32028: "缓存已清空。",
}


def t(string_id: int, *args, **kwargs) -> str:
    """取本地化字符串。任何异常都退回中文兜底。"""
    text = ""
    try:
        import xbmcaddon

        text = xbmcaddon.Addon().getLocalizedString(string_id)
    except Exception:  # noqa: BLE001 - 单测 / 语言文件缺失
        text = ""
    if not text:
        text = FALLBACK.get(string_id, str(string_id))
    if args or kwargs:
        try:
            return text.format(*args, **kwargs)
        except (IndexError, KeyError, ValueError):
            return text
    return text
