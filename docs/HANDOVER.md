# 交接说明（Mistuary Helper 0.5.2 已发布）

> 接手先读这份，再看 `contract.md`（皮肤接口）和 `roadmap.md`（还剩什么）。
> 本文只讲现状、已知问题、验证入口和发版，不讲历史演进。

## 1. 一句话现状

`script.mistuary.helper` 是 Mistuary 皮肤的**必需**配套插件（皮肤 `addon.xml` 硬依赖），
当前发布 **0.5.2**，284 项单测全绿，已发布 `v0.2.0` / `v0.2.1` / `v0.2.2` / `v0.3.2` / `v0.3.4` / `v0.3.5` /
`v0.3.6` / `v0.3.7` / `v0.3.8` / `v0.3.10` / `v0.3.11` / `v0.4.0` / `v0.5.0` / `v0.5.1` / `v0.5.2`（`v0.3.6` 只修发布包漏带 `service.py`；
`v0.4.0` 与 `v0.3.11` 功能相同，仅重新编号；`v0.5.1` 只把色光亮度提到 0.85；
`v0.5.2` 增加豆瓣 ID 桥接查询）。
文件播放记录随 **0.3.7** 发布，见 §2.5；0.3.8 只调插件封面文字；0.3.9 加媒体库封面同步与按目录补全默认开；
0.3.10 搜索剧集改走 Kodi 媒体库；0.3.11 让库里没有的剧集可直接浏览（§2.7）。
搜索和豆瓣评分主路径已接在皮肤 `main`，**M1c 已于 2026-10-30 实机验收通过**（含播放）；
搜索结果的**真海报与真背景图**已于 2026-10-30 修好（`c4ac966`），实机确认正常。

> **0.3.3 相比 0.2.2 的变化**：设置页改 Kodi 21 的 v1 格式（4 分类、逐项 help、
> 覆盖项收进专家）、**移除评分同步**（`service.py` / `lib/rating_sync.py` 已删，
> 写库的 `rating_type=douban` 在皮肤侧没有消费方）、搜索并入中文演员名与类型、
> 首字母改前缀严格匹配、修掉 `<assets>` 放错层级导致图标/背景不显示。

> **0.3.6 的变化**：修复发布包漏带 `service.py` —— 此前从 Release zip 安装的 0.3.4 / 0.3.5
> 都不会启动播放列表补全服务（仓库副本不受影响），CE 日志会报 `service.py` 不存在。
> **0.3.5 的变化**：文件夹补全改自然排序、跳过 sample/预告/花絮、重复文件只加一次；
> 多集共用一个文件不再重复入队；剧集支持跨季继续（默认关，配合按季补全）；
> StrmAssistant 有条目但无豆瓣分时可回退公开接口（新开关，默认开）。
>
> **0.3.4 的变化**：新增事件驱动的 `service.py` 做**播放列表补全**（两个独立开关：
> 媒体库剧集按季补全 / 文件夹播放按目录补全，视频与音乐都支持；初始默认关，0.3.9 起按目录默认开；只加队列、不打断当前播放）。
> 音频按当前播放器自动选队列，m4a / flac 等同目录音乐可补；电影 `season=-1` 与 HTTP 流目录列举报错已修。
> 0.3.3 删除的是评分同步的常驻服务，
> 与这个服务无关；三个开关都关时 `onAVStarted` 立即返回，行为与未安装一致。

## 2. 当前能力

| 能力 | 状态 | 说明 |
|---|---|---|
| 中文标题 / 原名 / 全拼 / 首字母搜索 | ✅ | Emby `/Items?searchTerm=`，电影 / 剧集两个页签 |
| 搜索结果分页 | ✅ | 满一页追加「加载更多」 |
| 已看 / 播放进度 | ✅ | 写 `Overlay` / `percentplayed` |
| 豆瓣评分 | ✅ | IMDb 优先，dbid 反查，标题 + 年份兜底；成功缓存 30 天（无分 3 天复核，失败 30 分钟） |
| action 模式 | ✅ 0.2.2 | `plugin://...?action=...` 会补 `endOfDirectory`；`RunScript` handle=-1 不调 |
| 演员 / 导演 / 类型 | ✅ 0.3.3 | 仅非 ASCII、≥2 字；纯字母按标题处理 |
| 搜索：剧集跳转 | ✅ 0.3.10 | 按标题 + tmdb/tvdb 在 Kodi 库里定位，跳 `videodb://tvshows/titles/<id>/` |
| 搜索：未同步剧集 | ✅ 0.3.11 | 库里没有的剧集进入插件自己的季/集列表；子列表一层、缓存 5 分钟；播放仍走 `mode=play` |
| 别名 / 分词 | ❌ | 未实现 |
| 代表集技术标识 | ❌ | M3 明确不做，插件侧已移除空壳 |
| 播放地址 | ✅ 实机通过 | `mode=play` 直连 Emby 插件，2026-10-30 验收；直链兜底不需要 |
| 播放列表补全 | ✅ 0.3.4 | 三个独立开关：媒体库剧集按季补全 / 文件夹播放按目录补全 / 跨季继续（视频与音乐）；按目录默认开，按季 / 跨季默认关；只加不播 |
| 文件播放记录 | ✅ 0.3.7 | 只记文件管理器 10003：弹窗 + 焦点行圆环；不写 Kodi 原生续播点；账本 `resume.db`，默认开 |
| 媒体库封面 | ✅ 0.3.9 | 从 Emby `/Users/{uid}/Views` 同步 Primary 图到 `library_icons/<库名>.png`，皮肤首页按库名显示；首次启动自动一次，之后手动 |

## 2.5 文件播放记录（0.3.7 已发）

- 入口：设置 → 文件管理器；首页「文件」源卡片（`target=filemanager`）。两者都是
  Kodi 窗口 10003，原生不处理续播，所以由本插件负责。
- 只处理文件管理器 10003 的播放（`Window.Previous(filemanager)`）；10025 和插件播放不记账、不弹窗。
- 协议：本地盘符/Unix、UNC、smb/nfs/ftp/sftp/dav/webdav/upnp、`.strm`、`.iso` 都记；
  `http(s)://` 默认不记，可在设置里打开（`file_resume_http`）。
- 账本 key/展示路径会剥掉 URL 里的 `user:pass@`；带 token 的直链仍会随保留期过期。
- 存储只有账本一层：
  - `addon_data/script.mistuary.helper/resume.db`（SQLite WAL）：30 秒采样 +
    暂停/拖动/停止/切集；路径归一化主键 + `key_fold` 大小写回退；`.strm` 用本体路径。
  - **不写 Kodi `MyVideos.db` / 原生续播点**（`NATIVE_MIRROR=False`）；也不依赖 `myvideos.resume` 开关。
- 阈值：起播 180 秒内不写，剩余 ≤8% 清除；读 `advancedsettings` 的同名配置。
- 保留：默认 90 天 / 5000 条，可在插件设置里改为 30/90/180/365 天或「永不」，
  上限 1000/3000/5000/10000；启动时 + 每 6 小时清理，别的进程改库后 5 秒内刷新缓存。
- 设置页分两组：「文件播放记录」（开关、保留天数、记录上限、HTTP）和
  「记录维护」（查看条数、立即清理、清空全部，后者二次确认）。
- 账本没有时只读回退 `Files.GetFileDetails`，不写回；不写 Kodi 原生续播点。
- 10003 焦点行圆环：仅在窗口激活时每 0.1 秒读当前焦点项，写
  `Window(home)` 的 `Mistuary.FileResume.HasResume / Percent / PercentKey`；
  皮肤显示 40px 绿弧（已播）/白轨（全长）/百分比数字（烘焙在帧里），共 101 帧；
  账本无记录时只读回退 `Files.GetFileDetails` 续播点（按路径缓存 10 秒），只有 `total>0` 才显示；
  焦点切换瞬间空路径先保留、持续 0.2 秒才清；换行时先隐藏旧圆环 30ms 再显示新值，避免残留。
- 10003 续播弹窗：打开皮肤自定义窗口 1115（560×180，无标题/正文，上下两个按钮）；
  播放开始后**先暂停**再弹窗（不再等 450ms），选完才恢复播放。
  按钮「从 01:07 继续播放」/「从头播放」，默认焦点继续；返回/点空白 = 停止播放并恢复原记录。
  「继续播放」= seek；「从头播放」= 删记录并 seek 到 0。
  面板/透明度由皮肤决定（round20 + 浮窗档）。
  120 秒内路径不同的自动连播不弹窗，同一路径重开仍弹窗。窗口缺失时回退原生 yes/no（No = 继续播放）。
- 开关：`file_resume`（默认开），皮肤设置「播放」页可切；`skin_bridge` 暴露
  `Mistuary.Helper.FileResume`。
- 单测：`tests/test_file_resume.py` 全覆盖；全仓共 284 项。
- **实机验证（2026-11-04）**：`.strm` 播放到 5:00 停止后账本写入 300s；
  再次播放 1.0 秒弹出 1115 紧凑弹窗，默认「继续播放」，回车跳到 5:19；
  10003 焦点行属性 `HasResume / Percent / PercentKey` = true / 7 / 007。

**实机踩到的三个坑（已修）**

1. `Player.GetItem` 的 `properties` 不能写 `type` / `id`，否则整条请求
   `Invalid params`；只请求 `file`（可选 `title`），`type` / `id` 会自动返回。
2. 30 秒采样器最初绕过了 180 秒起播阈值，会把 39 秒的进度写进账本；
   采样循环也必须先过 `should_save()`。
3. 文件管理器 10003 的 `ListItem.Path` 是**当前目录**，聚焦项的完整路径在
   `ListItem.FolderPath`；焦点行圆环轮询用后者。

**Kodi JSON-RPC 文件读写的边界**

- `Files.GetDirectory` / `Files.GetFileDetails` 只对**已配置媒体源**内的路径生效；
  非源路径返回 `Invalid params`（2026-11-04 实测）。
- `Files.SetFileDetails`（写续播点）本版本**不再使用**；原生续播点只读回退。
- 原生回退只对源内文件可靠；非源路径以 `resume.db` 账本为准。

## 2.6 媒体库封面同步（0.3.9）

E4K 不导出库封面：它只把封面存成 `image://emby@...` 地址，Kodi 的 tag 列表项
也不带 art，皮肤在 XML 层拿不到。所以由本插件直接读 Emby 的 `/Users/{uid}/Views`，
把每个库的 Primary 图下载到 `addon_data/script.mistuary.helper/library_icons/<库名>.png`，
没设封面的库写 1×1 透明 PNG 占位（皮肤那层永远能加载，不会每次渲染报错）。
皮肤按 `ListItem.Label` 拼文件名。

- 文件名只替换 `\/:*?"<>|` 和控制字符，其余保持库名原样
- `manifest.json` 记录 `id + tag`，没变就跳过；下载失败保留旧文件，下次再试
- 请求带 `format=png`（整条链路统一 PNG，缺封面才能写透明占位）
- manifest v2：v1（`.jpg`）会被当成不存在，启动时自动重同步一次并清掉旧 jpg
- manifest 不写 token；首次启动（没有有效 manifest）后台静默同步一次
- 手动入口：设置 → Emby 服务器 → 同步媒体库封面；皮肤「界面」页也有按钮

## 2.7 未同步内容浏览（0.3.10 / 0.3.11）

- 0.3.10：搜索里点剧集不再走 Emby 插件的 `mode=browse`（部分分支已移除该接口，会打开空列表）；
  改为按标题 + tmdb/tvdb 在 Kodi 库里定位，跳 `videodb://tvshows/titles/<id>/`。
- 0.3.11：库里没有的剧集不再隐藏，搜索结果进入插件自己的季/集列表；
  子项列表只拉一层（`ParentId` + `Limit 500`），结果缓存 5 分钟；
  播放仍走 Emby 插件的 `mode=play`，由它从服务端取数据。
- 剧集 / 季 / 合集 / 专辑统一按“不可播放”处理，不再被当成视频直接播。
- 搜索页签仍只有电影 / 剧集，不直接返回单集。

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

**已做（`c4ac966`，0.2.2 已发布）**：

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
补一条“只有 ImageTags 也能取到海报”的用例（已随 0.2.2 发布）。

### 4.2 搜索页背景没有兜底图（已解决，皮肤 1.5.x）

这是**皮肤侧**问题，不是插件能补的；皮肤后来改成渐变打底 + 剧照层，已在 1.5.x 修复。皮肤 `xml/Includes_Search.xml` 的
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

- M1d 演员 / 导演 / 类型已完成（仅非 ASCII、≥2 字）；别名 / 分词仍未实现。
- **皮肤键盘只能输入字母**，演员 / 类型在皮肤 UI 里实际不可达，需要中文输入或人物页签。
- M3 代表集技术标识明确不做。
- 多服务器切换未实机验过；Kodi 19/20 未验。
- 皮肤目前不做版本比较，旧版插件不写新属性，等价于没装。

## 5. 验证入口

```bash
cd D:/下载/AI/script.mistuary.helper
python -m unittest discover -s tests -p 'test_*.py'   # 284 项
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
| `lib/emby.py` | Emby 搜索、字段映射、播放地址、未同步内容 browse 列表 |
| `lib/douban.py` | 豆瓣双通道、缓存、窗口属性 |
| `lib/kodi.py` | ListItem、窗口属性、目录收尾、库内条目定位 |
| `lib/cache.py` | 磁盘缓存（不含 token） |
| `lib/library_icons.py` | 媒体库封面同步：Views → 本地 PNG（缺封面写透明占位）+ manifest v2 |
| `lib/log.py` / `lib/i18n.py` | 日志 / 本地化 |
| `tests/` | 284 项单测，HTTP 全 mock |

## 8. 安全与隐私

- 只读 Emby 插件的 `servers_*.json`，不修改。
- 不写 Kodi 媒体库、不写皮肤设置。
- 缓存只存评分/搜索结果和 `image_tag`，不存完整图片 URL / token。
- 库封面 manifest 只存库 id / tag / 文件名，不存 token。
- 日志只记 ServerId 和 HTTP 状态码，不记 token。
