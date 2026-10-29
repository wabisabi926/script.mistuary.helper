# -*- coding: utf-8 -*-
"""豆瓣评分（P1，尚未实现）。

契约（helper-plugin-plan.md §5.2）：
    输入：type=movie|episode, dbid=<Kodi 库 id>
    输出：写 Window(home) 的四个属性
        Mistuary.Rating.Douban     8.6
        Mistuary.Rating.Votes      123456
        Mistuary.Rating.FetchedAt  epoch
        Mistuary.Rating.Status     ok | missing | error

皮肤只读 `Status == ok` 才显示胶囊，其余一律隐藏。

阶段 1 不实现：什么都不写，皮肤读到空属性就自然隐藏。
实现时按 §5.2 的双通道（legacy + frodo 签名）填进来，并保留 TMDbHelper 的
版权声明（GPL-3.0）。
"""

from __future__ import annotations

from lib import log

# 缓存 TTL：豆瓣分变化很慢，7 天足够
DOUBAN_TTL = 7 * 24 * 3600

# 失败结果缓存 30 分钟，避免风控时反复重试
FAILURE_TTL = 30 * 60


def run_action(req) -> None:
    """入口。P1 之前只记一条日志，不写属性。"""
    log.debug("douban action requested (not implemented yet): dbid=%s type=%s"
              % (req.dbid, req.type))
    # 实现顺序（P1）：
    #   1. dbid -> IMDb id（Kodi JSON-RPC VideoLibrary.GetItemDetails 的 uniqueid）
    #   2. 查缓存（key = imdb id，TTL 7 天）
    #   3. 未命中则双通道取分（legacy -> frodo），失败退避 1s/2s/4s
    #   4. 写四个窗口属性
    return
