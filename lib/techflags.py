# -*- coding: utf-8 -*-
"""剧集代表集技术标识（P2，尚未实现）。

契约（helper-plugin-plan.md §5.3）：
    输入：dbid（剧集 id）
    输出：给条目写 ListItem.Property(TvShowRepresentative.*)
        VideoResolution / HdrType / HdrDetail / VideoCodec / AudioCodec / AudioChannels

皮肤的 `VideoTechnicalFlagsByPrefix` 已经有 `TvShowRepresentative.*` 分支，
属性一写上去就自动生效，皮肤侧不用改。

⚠️ 这条只对**插件自己生成的列表**有效。Kodi 库里的行（Emby 动态节点）没法在
渲染前拿到 ListItem 引用，需要 Emby 侧的 `/Items?ParentId=…&IncludeItemTypes=Episode&Limit=1`，
属于 P2 的工作。
"""

from __future__ import annotations

from lib import log


def run_action(req) -> None:
    """入口。P2 之前只记日志。"""
    log.debug("techflags action requested (not implemented yet): dbid=%s" % req.dbid)
    # 实现顺序（P2）：
    #   1. 取「当前季首集」：库内走 JSON-RPC，Emby 走 /Items?ParentId=…
    #   2. 解析 VideoResolution / HdrType / HdrDetail / 编码 / 声道
    #   3. 写成 ListItem 属性（不是窗口属性 —— 这个必须绑在条目上）
    return
