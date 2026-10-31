# 交接说明（Mistuary Helper 0.3.3）

> 接手先读这份，再看 `contract.md`（皮肤接口）和 `roadmap.md`（还剩什么）。
> 本文只讲现状、已知问题、验证入口和发版，不讲历史演进。

## 1. 一句话现状

`script.mistuary.helper` 是 Mistuary 皮肤的**可选**配套插件，当前 **0.3.3**，
101 项单测全绿，已发布 `v0.2.0` / `v0.2.1` / `v0.2.2` / `v0.3.2`，`v0.3.3` 待发。
搜索和豆瓣评分主路径已接在皮肤 `main`，**M1c 已于 2026-10-30 实机验收通过**（含播放）；
搜索结果的**真海报与真背景图**已于 2026-10-30 修好（`c4ac966`），实机确认正常。

> **0.3.3 相比 0.2.2 的变化**：设置页改 Kodi 21 的 v1 格式（4 分类、逐项 help、
> 覆盖项收进专家）、**移除评分同步**（`service.py` / `lib/rating_sync.py` 已删，
> 写库的 `rating_type=douban` 在皮肤侧没有消费方）、搜索并入中文演员名与类型、
> 首字母改前缀严格匹配、修掉 `<assets>` 放错层级导致图标/背景不显示。

## 2. 当前能力

| 能力 | 状态 | 说明 |
|---|---|---|
| 中文标题 / 原名 / 全拼 / 首字母搜索 | ✅ | Emby `/Items?searchTerm=`，电影 / 剧集两个页签 |
| 搜索结果分页 | ✅ | 满一页追加「加载更多」 |
| 已看 / 播放进度 | ✅ | 写 `Overlay` / `percentplayed` |
| 豆瓣评分 | ✅ | IMDb 优先，dbid 反查，标题 + 年份兜底；7 天缓存 |
| action 模式 | ✅ 0.2.2 | `plugin://...?action=...` 会补 `endOfDirectory`；`RunScript` handle=-1 不调 |
| 演员 / 导演 / 类型 / 别名 / 分词 | ❌ | M1d 暂缓 |
| 代表集技术标识 | ❌ | M3 明确不做，插件侧已移除空壳 |
| 播放地址 | ✅ 实机通过 | `mode=play` 直连 Emby 插件，2026-10-30 验收；直链兜底不需要 |

## 3. 已修复的两个 Kodi 偶发问题

### 3.1 `resume:false` 污染搜索词（0.2.1）

Kodi 21+ 的目录调用会在 `sys.argv` 末尾多传一个 `resume:false`。旧 `router.argv_to_args()`
把它拼进 raw，`parse()` 又把 `query=` 之后整段当搜索词，搜 `yw` 变成
`yw&resume:false`，Emby 返回 0 条。

现在 `argv_to_args()` 过滤所有以 `resume:` 开头的 Kodi 元参数；回归测试
`test_kodi_resume_meta_is_dropped`。

### 3.2 action 模式 `GetDirectory failed`（0.2.2）

`plugin://...?action=rating` 有 handle，但入口直接 `return`，没有 `endOfDirectory`，
Kodi 日志报 `CGUIMediaWindow::GetDirectory(...) failed`。

现在 `lib.kodi.end_directory(handle)`：`handle < 0` 直接返回，目录调用才收尾；
`default.py` 的 rating / clear_cache / 兜底分支都调用。回归测试
`tests/test_default.py` 钉住两种调用形态。

## 4. 已知问题（交接重点）

### 4.1 搜索结果没有封面（已解决，2026-10-30）

**现象**：搜索结果卡片只有默认图标，没有海报，背景也没有剧照。

**根因**：Emby `/Items?searchTerm=` 返回的是 `ImageTags.Primary`，
**没有** `PrimaryImageTag` 字段；`normalize()` 只读后者 → `image_tag` 永远为空。

**已做（`c4ac966`）**：

- `normalize()` 先读 `PrimaryImageTag`，再回退 `ImageTags.Primary`
- 新增 `backdrop_tag`（`BackdropImageTags[0]`，只存 tag 不存 URL）
- 新增 `backdrop_url()`，`render_search()` 补 `art["fanart"]`
- 请求参数 `EnableImageTypes` 改为 `Primary,Backdrop`
- 测试夹具改成 Emby 真实形状，90 项单测全绿

**历史记录（已不适用）**：

```python
"image_tag": raw.get("PrimaryImageTag")
             or ((raw.get("ImageTags") or {}).get("Primary") or ""),
```

同时把 `tests/test_emby.py` 的夹具改成真实响应形状（`ImageTags.Primary`），
补一条“只有 ImageTags 也能取到海报”的用例。改完需要发 0.2.3。

### 4.2 搜索页背景没有兜底图

这是**皮肤侧**问题，不是插件能补的。皮肤 `xml/Includes_Search.xml` 的
`NaraSearchBackground` 先画纯黑 `colors/black.png`，再画 `16590` fanart；`16590` 的
`visible` 要求 `!String.IsEmpty(...Art(fanart))`。非空查询且条目没有 fanart 时，
两层都不显示，只剩纯黑。

**修复方向**：在 `NaraSearchBackground` 加一张 fanart 为空时可见的兜底图
（例如 `special://skin/extras/backgrounds/primary.jpg`），或在 `16590` 的可见性外
补一层 fallback。皮肤仓库 `docs/HANDOVER.md` 也有同样记录。

### 4.3 播放地址（已解决，2026-10-30）

`lib/emby.py: play_url()` 走
`plugin://plugin.service.emby-next-gen/?mode=play&item=…&server=…`，
实机点搜索结果可直接播放，**`play_url()` 不需要改**，
`{base}/Videos/{Id}/stream?static=true&api_key=…` 这条直链兜底也不用做
（它会带 token，本来就不想启用）。

### 4.4 其他

- M1d 演员 / 导演 / 类型 / 别名 / 分词未实现，暂缓。
- M3 代表集技术标识明确不做。
- 多服务器切换未实机验过；Kodi 19/20 未验。
- 皮肤目前不做版本比较，旧版插件不写新属性，等价于没装。

## 5. 验证入口

```bash
cd D:/下载/AI/script.mistuary.helper
python -m unittest discover -s tests -p 'test_*.py'   # 82 项
python -m compileall -q default.py lib
```

实机：

1. Kodi 里启用插件；装/卸/启用后**重载皮肤**。
2. 搜索：`rzd` 应 3 条；`让子弹飞` / `rangzidanfei` / `12th Fail` 各 1 条。
3. 详情页：有 IMDb 的电影应显示豆瓣胶囊；断网时隐藏，不弹框。
4. 日志：`MISTUARY.HELPER`；错误不应包含 token。
5. 缓存：`%APPDATA%/Kodi/userdata/addon_data/script.mistuary.helper/cache`。

## 6. 发版

见 `release.md`。版本号只改 `addon.xml`，`changelog.txt` 顶部段落会作为 Release 正文；
push 到 `main` 且版本号变化时 CI 自动打包。不要手工打 zip。

## 7. 文件地图

| 文件 | 作用 |
|---|---|
| `default.py` | 入口：解析 argv、分发、目录收尾 |
| `lib/router.py` | 参数解析；`query` 最后、过滤 `resume:` 元参数 |
| `lib/config.py` | 读设置 + 从 Emby 插件配置发现服务器 |
| `lib/emby.py` | Emby 搜索、字段映射、播放地址 |
| `lib/douban.py` | 豆瓣双通道、缓存、窗口属性 |
| `lib/kodi.py` | ListItem、窗口属性、目录收尾 |
| `lib/cache.py` | 磁盘缓存（不含 token） |
| `lib/log.py` / `lib/i18n.py` | 日志 / 本地化 |
| `tests/` | 82 项单测，HTTP 全 mock |

## 8. 安全与隐私

- 只读 Emby 插件的 `servers_*.json`，不修改。
- 不写 Kodi 媒体库、不写皮肤设置。
- 缓存只存评分/搜索结果和 `image_tag`，不存完整图片 URL / token。
- 日志只记 ServerId 和 HTTP 状态码，不记 token。
