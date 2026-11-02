# 架构与模块职责

> 本文讲「代码怎么组织、为什么这样分」。进度见 [`roadmap.md`](roadmap.md)，
> 与皮肤的调用契约见 [`contract.md`](contract.md)。

## 一句话

`default.py` 只做分发，`lib/` 里的每个模块只干一件事，**不 import xbmc 的模块可以脱离 Kodi 单测**。

## 目录

```
script.mistuary.helper/
├── addon.xml                  元数据；provides=video（搜索结果要作为视频目录）
├── default.py                 入口：解析 argv → 分发 → endOfDirectory
├── lib/
│   ├── router.py              参数解析（query 必须是最后一个参数）
│   ├── config.py              读设置 + 发现 Emby 服务器
│   ├── http.py                urllib 封装，失败返回 Response 不抛异常
│   ├── cache.py               磁盘缓存（json + mtime，原子写）
│   ├── log.py                 日志（惰性 import xbmc，绝不打印 token）
│   ├── i18n.py                本地化（带中文兜底）
│   ├── emby.py                Emby 客户端 + 结果映射 + 渲染
│   ├── kodi.py                ListItem 构造、窗口属性桥
│   ├── douban.py              M2：豆瓣取分
├── resources/
│   ├── settings.xml
│   └── language/{en_gb,zh_cn}/strings.po
└── tests/                     7 个文件，146 项
```

## 数据流

```
Kodi 调用
   │  sys.argv[2] = "?mode=search&type=movies&query=让子弹飞"
   ▼
default.py ── router.parse() ──> Request(mode, type, query, offset…)
   │
   ├─ mode=search ──> emby.render_search()
   │                     ├─ config.find_server()   读 servers_*.json
   │                     ├─ cache.get()            命中就直接渲染
   │                     ├─ http.get_json()        GET /emby/Items
   │                     ├─ normalize()            Emby Item → 纯 dict
   │                     ├─ cache.put()            只存 PrimaryImageTag
   │                     └─ kodi.apply_video_info() + addDirectoryItem
   │
   ├─ action=rating ──> douban.run_action()       （M2）
   └─ action=clear_cache ─> cache.clear()
```

## 三条设计原则

### 1. 失败即降级，永不弹框

任何异常都变成**结果列表里的一句话**（`kodi.add_notice`），或者干脆什么都不写。
用户不会被对话框打断，皮肤容器也能正常结束，不会一直转圈。

`default.py` 最外层有 try/except，兜住所有未捕获异常，并在目录模式下补
`endOfDirectory(succeeded=False)`——否则界面卡在加载状态。

### 2. 缓存里不放 token

图片地址形如 `{base}/Items/{id}/Images/Primary?tag=…&api_key={token}`，**带令牌**。
所以：

- `normalize()` 返回 `image_tag`，**不返回完整 URL**
- 缓存只落盘 `image_tag`
- `image_url()` 在渲染时用当前 server 现拼

否则 `addon_data/script.mistuary.helper/cache/*.json` 会明文存着令牌。

### 3. 无状态

搜索 / 评分路径没有内存单例，每次调用重新读配置、重新查缓存。
代价是每次多几十毫秒读文件，换来的是：少一类崩溃面、用户改设置立刻生效。

0.3.4 起新增事件驱动的 `service.py`，只做**播放列表补全**：不轮询、不缓存，
两个开关默认关；都关时 `onAVStarted` 立即返回，等同于没有这个服务。

## 为什么某些模块不 import xbmc

`router` / `http` / `cache` 完全不碰 Kodi；`config` / `log` / `i18n` 把 import 放在函数内部。

好处是 `tests/` 能在**没有 Kodi 的机器**上跑（CI 就是这样）。代价是每个用到 xbmc 的地方
多一层 try/except——但这本来就是需要的，插件不该因为读不到设置就崩。

## 关键实现决策

| 决策 | 为什么 |
|---|---|
| `query` 用 `raw.split("query=", 1)` 而不是 `parse_qs` | `parse_qs` 会把搜索词里的 `&` 当参数分隔符，`Tom & Jerry` 被切成两半 |
| `setInfo("video", {...})` 而不是 `setInfoTag` | 前者 19/20/21 都工作，后者只有 20+ |
| `provides=video` | 没有它，`plugin://` 路径仍能打开，但 content type 未知，皮肤 `Container.Content(movies)` 判断会失效 |
| 缓存 key 用 `sha1` 文件名 | key 里有中文和 `|`，直接当文件名在某些文件系统上出问题 |
| 空结果也缓存 | 用户连续打字时不必每次都打服务端；TTL 只有 5 分钟 |
| 失败**不**缓存 | 一次网络抖动会锁死 5 分钟 |
| 缓存写失败静默 | 缓存是优化不是功能，写不进去也要能正常返回结果 |
| 过滤 Kodi 的 `resume:*` argv | Kodi 21+ 目录调用会额外传 `resume:false`；不丢弃会污染搜索词（0.2.1） |
| action 模式目录收尾 | `plugin://...?action=...` 有 handle，必须 `endOfDirectory`；`RunScript` 的 handle=-1 不调（0.2.2） |

## Emby 服务器发现

读 `addon_data/plugin.service.emby-next-gen/servers_*.json`，实测字段（Next Gen 4.10.x）：

```
ServerId / ServerName / ServerVersion
ServerUrl        末尾带斜杠
ManualAddress    用户手填的地址
LocalAddress
RemoteAddress
AccessToken      32 位
UserId           32 位
ServerRemoved    bool，换过服务器后旧配置只置这个标记、不删除
```

地址优先级 `ServerUrl → ManualAddress → LocalAddress → RemoteAddress`。
**`ManualAddress` 不能漏**：用户手填覆盖时地址只写在这里，漏了会用错服务器。

## 已知实现缺口

- **搜索封面**：`normalize()` 只读 `raw["PrimaryImageTag"]`，而 Emby 实际返回
  `raw["ImageTags"]["Primary"]`，所以搜索结果 `image_tag` 为空、列表没有海报。
  这是 0.2.2 之后仍待修的问题，测试夹具也用了旧字段，未覆盖真实响应。
- **播放地址**：`play_url()` 走 Emby 插件 `mode=play`，2026-10-30 实机验证可直接播放；直链兜底不启用。

## 日志

前缀 `MISTUARY.HELPER`，只在设置里打开 `debug_log` 后写 `kodi.log`。
`error()` 不受开关控制（出错总要能查），但同样**只记 ServerId 和状态码**。
`log.redact()` 用于万一要打令牌时裁成 `abcd…****`。
