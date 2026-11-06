# 与皮肤的契约

> 本文是**插件与皮肤之间的接口约定**。改任何一方的调用方式前先改这里。
> 皮肤仓库里的 `docs/helper-plugin-plan.md` 是本文的摘要，**以本文为准**。

## 一、硬依赖

2026-11-05 起皮肤 `addon.xml` 声明 `<import addon="script.mistuary.helper" version="0.3.9"/>`，
未安装或禁用时皮肤**不加载**（当前最新插件 0.3.11；0.3.10/0.3.11 是搜索增强，不提高硬性下限）。

运行时仍保留软探测，用于插件在会话中被禁用后隐藏相关入口：

```xml
<expression name="helper_ready">System.AddonIsEnabled(script.mistuary.helper)</expression>
```

注意是 **`AddonIsEnabled`** 不是 `AddonIsInstalled`：用户装了但禁用了，等同没装。

## 二、调用方式

### 2.1 搜索（返回目录）

```
plugin://script.mistuary.helper/?mode=search&type=movies&query=<搜索词>
plugin://script.mistuary.helper/?mode=search&type=shows&query=<搜索词>
```

| 参数 | 值 | 说明 |
|---|---|---|
| `mode` | `search` | 必填 |
| `type` | `movies` / `shows` | 必填，对应 Emby 的 `Movie` / `Series` |
| `offset` | 整数 | 可选，分页用 |
| `query` | 任意文本 | **必须是最后一个参数** |

**`query` 放最后是硬约束**：插件用 `raw.split("query=", 1)` 取值，
这样中文、`&`、`?`、`=` 都不会被截断。已知限制：`#` 会被 Kodi 当锚点截掉，无法绕开。

Kodi 21+ 的目录调用还会在 argv 末尾额外传一个 `resume:false`；0.2.1 起插件会丢弃
所有以 `resume:` 开头的 Kodi 元参数。调用方仍必须把 `query` 放最后，**不要在它后面
再追加业务参数**——追加的内容会被当成搜索词（2026-10-30 实测）。

### 2.1.1 当前实际能力（2026-11-06 更新）

| 能力 | 状态 | 说明 |
|---|---|---|
| 中文标题 | ✅ | `/Items?searchTerm=` |
| 原名 | ✅ | `12th Fail` → 12年级的失败；大小写不敏感 |
| 全拼 | ✅ | `rangzidanfei` → 让子弹飞 |
| 首字母 | ✅ 前缀（0.3.3+） | 2–4 位纯 ASCII 要求 `SortName` 前缀；5 位以上按全拼放行 |
| 剧集 | ✅ | `20之后` 命中；标点密集的标题可能因 Emby 分词失败 |
| 剧集跳转 | ✅ 0.3.10 | 按标题 + tmdb/tvdb 在 Kodi 库里定位，跳 `videodb://tvshows/titles/<id>/` |
| 未同步剧集 | ✅ 0.3.11 | 库里没有的剧集进入插件自己的季/集列表；子列表一层、缓存 5 分钟；播放走 `mode=play` |
| 演员 / 导演 | ✅ 非 ASCII | 中文名（≥2 字）经 `Persons → PersonIds → Items` 并入结果 |
| 类型 | ✅ 非 ASCII | 中文类型词经 `Genres → GenreIds → Items` 并入结果 |
| 别名 / 分词 | ❌ | 未实现 |

皮肤侧已经接好（`a6b9f59`），但**插件必须在 Kodi 里启用**，否则软探测为假、
开关隐藏、搜索回退本地。装/卸/启用后都要重载皮肤。

### 2.2 动作（无界面）

```
RunScript(script.mistuary.helper,action=rating,type=movie,dbid=<Kodi 库 id>)
```

`action=rating`（0.2.0+）写窗口属性。

0.2.2 起，通过 `plugin://...?action=...` 调用时入口会补 `endOfDirectory`，不会再报
`CGUIMediaWindow::GetDirectory(...) failed`；`RunScript` 没有 handle，不会触发收尾。

**参数拼接**：`RunScript(addon,action=rating,type=movie,dbid=…,imdb=…)` 里的逗号会被 Kodi
拆成多个 argv；入口用 `router.argv_to_args()` 判断布局并拼回：

- `plugin://` 目录调用：`argv[1]` 是 handle，参数从 `argv[2]` 开始；
- `RunScript` 调脚本 addon：没有 handle，参数从 `argv[1]` 开始。

因此参数值里不能再出现逗号（标题走 `Mistuary.Rating.Query` 窗口属性）。
插件 `addon.xml` 同时声明 `xbmc.python.script`，否则 Kodi 会警告
「RunScript called for a non-script addon」。

推荐调用（详情页 onload）：

```xml
<onload condition="System.AddonIsEnabled(script.mistuary.helper)">RunScript(script.mistuary.helper,action=rating,type=$INFO[ListItem.DBType],dbid=$INFO[ListItem.DBID],imdb=$INFO[ListItem.IMDBNumber])</onload>
```

`imdb` 是主路径（Emby 动态条目没有 DBID），`dbid` 只用于本地库反查 `uniqueid`。

## 三、插件写什么

### 3.1 窗口属性（豆瓣评分，M2，0.2.0）

写 `Window(home)` = 窗口 id **10000**：

| 属性 | 示例 | 说明 |
|---|---|---|
| `Mistuary.Rating.Douban` | `8.6` | 0–10，一位小数 |
| `Mistuary.Rating.Votes` | `123456` | 票数，可能为空 |
| `Mistuary.Rating.FetchedAt` | `1793000000` | epoch，皮肤可用来判过期 |
| `Mistuary.Rating.Status` | `ok` / `missing` / `error` | **皮肤只在 `ok` 时显示** |
| `Mistuary.Rating.Source` | `emby` / `douban` | 0.3.0+：分数来自 StrmAssistant 还是回退直连 |

**皮肤写给插件（兜底输入）**：

| 属性 | 示例 | 说明 |
|---|---|---|
| `Mistuary.Rating.Query` | `让子弹飞` | 详情页标题；标题可能带逗号，不能走 RunScript 参数 |
| `Mistuary.Rating.Year` | `2010` | 年份，用来排除同名不同年的条目 |

插件只在拿不到 IMDb id 时读这两个属性，按标题搜豆瓣并要求标题完全一致、
年份一致（给了年份时）。

### 3.2 条目属性（代表集标识，M3 暂缓）

写在 ListItem 上：

```
TvShowRepresentative.VideoResolution
TvShowRepresentative.HdrType / HdrDetail
TvShowRepresentative.VideoCodec / AudioCodec / AudioChannels
```

皮肤的 `VideoTechnicalFlagsByPrefix` 已有这组分支，**皮肤侧 0 改动**。

限制：只对插件自己生成的列表有效。Kodi 库里的行拿不到 ListItem 引用。


## 四、降级表

**装了就多，不装就少。每一项都有明确的"没有插件"状态，且那个状态是当前已有行为。**

| 功能 | 装了插件 | 没装 / 禁用 / 版本低 |
|---|---|---|
| 搜索：中文标题 / 原名 | Emby 服务端，与官方 App 一致 | 本地 XSP（`contains`） |
| 搜索：首字母（`HZ` / `S`） | 服务端；2–4 位 ASCII 前缀严格 | 本地 XSP（`startswith`） |
| 搜索：全拼 / 原名 | ✅ | ❌ 没有（本地没有拼音库） |
| 搜索：演员 / 导演 / 类型 | ✅ 仅非 ASCII（0.3.3+，并入结果） | ❌ 没有（1.2.0 起本地已移除） |
| 搜索：剧集跳转 | ✅ 0.3.10：Kodi 库内定位 | ❌ 库外剧集不生成可点条目 |
| 搜索：未同步剧集浏览 | ✅ 0.3.11：进插件自己的季/集列表 | ❌ 不显示（只保留库内结果） |
| 搜索：别名 / 分词 | ❌ 未实现 | ❌ 没有（本地没有分词器） |
| 详情页豆瓣胶囊 | ✅ 显示 | 整行不显示，其余评分胶囊照常 |
| 剧集代表集技术标识 | 不适用（皮肤自行处理） | 皮肤自己的 `ListItemAbsolute(0)` 推断，**行为不变** |
| 启动 / 播放 / 设置 | 不受影响 | 不受影响 |

## 五、四条硬约束

1. **皮肤侧只加分支，不替换**：新条件写进已有 `<variable>`，原来那行无条件 `<value>` 永远留在最后。
2. **任何分支都必须有"未装"兜底，且兜底是当前已有行为**，不是空白。
3. **插件返回空 / 报错 / 超时**时，皮肤按"没装"处理（属性为空就隐藏，容器空就回退），**不弹错误框**。
4. **设置开关 `helper_search_off` 反向命名（默认开），未装插件时整行隐藏**——免得用户看到一个拨不动的开关。

## 六、皮肤侧写法

```xml
<!-- 1. 探测：插件和 Emby 都启用才走服务端 -->
<expression name="helper_search_ready">System.AddonIsEnabled(script.mistuary.helper) + System.AddonIsEnabled(plugin.service.emby-next-gen)</expression>

<!-- 2. 路径二选一：服务端优先，本地兜底（原值永远在最后） -->
<variable name="NaraSearchMoviesPathVar">
    <value condition="$EXP[helper_search_ready] + !Skin.HasSetting(helper_search_off) + !String.IsEmpty(Control.GetLabel(16999).index(1))">plugin://script.mistuary.helper/?mode=search&amp;type=movies&amp;query=$INFO[Control.GetLabel(16999).index(1)]</value>
    <value>library://video/movies/...</value>
</variable>
```

服务端模式下**不要**给容器加 `sortby="sorttitle"`，否则会把服务端的相关度排序覆盖成字母序。

## 七、版本契约

| 皮肤功能 | 最低插件版本 |
|---|---|
| 服务端搜索 | 0.1.0（0.2.1 修复 `resume:false` 污染搜索词） |
| 详情页豆瓣 | 0.2.0 |
| 播放列表补全（同季 / 同目录） | 0.3.4 |
| 搜索剧集跳 Kodi 媒体库 | 0.3.10 |
| 未同步剧集浏览 | 0.3.11 |
| 代表集标识 | 不适用（M3 不做，不承诺版本） |

皮肤目前**不做版本比较**（Kodi 没有可靠的版本比较表达式），只做
`System.AddonIsEnabled` 软探测；旧版插件对新增功能什么都不写，皮肤自然隐藏，
等价于没装。最低版本只写在 README / Release 说明里。

## 八、一个必须写进用户文档的坑

Kodi 的 `<include condition="...">` 和容器的 `<content>` 都是**加载时求值**的。

所以**装完 / 卸载插件后必须重载皮肤**（设置 → 界面 → 皮肤 → 重新加载），
新分支才生效。不写这句，用户会以为插件没起作用。

卸载后回退则是**立即**的——探测是每次渲染求值，不是缓存。

## 八点五、皮肤设置页的设置桥（0.3.5；0.3.7 增加 FileResume）

皮肤设置页不能可靠地直接读写别的 addon，因此由插件把主要开关写成
`Window(home)` 属性；皮肤只读属性、点击时回调：

```
RunScript(script.mistuary.helper,action=settings_snapshot)
RunScript(script.mistuary.helper,action=toggle_setting,key=douban_enabled)
```

| 属性 | 对应设置 |
|---|---|
| `Mistuary.Helper.DoubanEnabled` | `douban_enabled` |
| `Mistuary.Helper.PlaylistSeason` | `playlist_completion_season` |
| `Mistuary.Helper.PlaylistFolder` | `playlist_completion_folder` |
| `Mistuary.Helper.PlaylistNextSeason` | `playlist_completion_next_season` |
| `Mistuary.Helper.FileResume` | `file_resume`（0.3.7） |

属性值为 `"true"` / `"false"`；`toggle_setting` 只接受上表五个 key，未知 key 忽略。
插件未启用时不写属性；714 搜索开关靠 `helper_search_ready` 隐藏，其余行保持可见（可切换后再启用插件）。

### 8.5.1 文件播放记录属性（0.3.7）

插件在 `service.py` 里维护，皮肤只在文件管理器 10003 的聚焦行读取：

| 属性 | 值 |
|---|---|
| `Mistuary.FileResume.HasResume` | `"true"` / `"false"`（当前焦点项是否有记录） |
| `Mistuary.FileResume.Time` | `h:mm:ss` / `m:ss`（保留，列表暂不显示） |
| `Mistuary.FileResume.Percent` | `0`–`100` 的整数（备用；皮肤数字已烘焙进帧） |
| `Mistuary.FileResume.PercentKey` | `000`–`100` 三位字符串，对应 `progress/resume_ring/ring_XXX.png` |

- 皮肤在 10003 聚焦行显示 40px 圆环：绿弧 `#89C19F` = 已播、白轨 `60FFFFFF` = 全长、
  百分比数字烘焙在帧里（白色 14px，无暗底）；共 101 帧（1% 一档），不显示具体时间。
- 账本没有该路径时，圆环回退 Kodi/Emby 的 `Files.GetFileDetails` 续播点；按路径缓存 10 秒，
  不会每 0.2 秒发 RPC。
- 只在 `Window.IsActive(10003)` 时每 0.1 秒更新；焦点切换瞬间 `FolderPath` 为空时先保留上一次属性，
  持续空 0.2 秒才清；换行时先隐藏旧圆环、30ms 后再显示新值；焦点落到文件夹行、查到非空路径但无记录、或离开窗口时立即清空。
- 只有 `total > 0` 的记录才画圆环；原生续播点只有位置没有总长时按无记录处理，避免显示 0%。
- 文件管理器 10003 的 `ListItem.Path` 是当前目录，聚焦项的完整路径在
  `ListItem.FolderPath`；插件按后者取值。
- 不是 ListItem 属性，而是 `Window(home)` 属性；Kodi 没有窗口内容更新回调，
  也没有 `Window.getListItem()`，不要尝试逐项注入。
- 10003 起播时会打开皮肤自定义窗口 **1115**（560×180，无标题/正文，上下两个按钮）；
  **只记录 10003 文件管理器的播放**，10025 与插件播放不记账、不弹窗。
  弹窗前先暂停播放；选完「继续/从头播放」才恢复；返回键/点空白 = 取消：停止播放并恢复原记录。
  「继续播放」= seek；「从头播放」= 删除记录并 seek 到 0。
- 协议：本地/UNC/smb/nfs/ftp/sftp/dav/webdav/upnp、`.strm`、`.iso` 记录；
  `http(s)://` 默认排除，设置 `file_resume_http` 可打开。URL 里的 `user:pass@` 不入库。
- 120 秒内的自动连播（路径不同）不弹窗；**同一路径重新打开仍弹窗**。
- 记录只存在 `addon_data/script.mistuary.helper/resume.db`（SQLite WAL）；
  **不写 `MyVideos.db` / Kodi 原生续播点**；账本没有时只读回退 `Files.GetFileDetails`。
- 保留：默认 90 天 / 5000 条，可在插件设置调整；启动时 + 每 6 小时清理；
  设置页提供查看条数、立即清理、清空全部（二次确认）。

### 8.5.2 续播弹窗属性（0.3.7）

helper 在打开 `Custom_1115_FileResume.xml` 前写 `Window(home)` 属性：

| 属性 | 值 |
|---|---|
| `Mistuary.ResumeDialog.Continue` | 按钮一：「从 01:07 继续播放」（时间补两位分钟） |
| `Mistuary.ResumeDialog.Start` | 按钮二：「从头播放」 |
| `Mistuary.ResumeDialog.Choice` | 按钮写回：`continue` / `start` / `cancel` |

- 按钮 id 10/11 只负责 `SetProperty(...Choice...,home)`；helper 轮询到 Choice 后
  `Dialog.Close(1115)` 并清理全部属性。返回/点空白没有 Choice，helper 按 `cancel` 处理。
- 窗口不存在（别的地方用这个 helper / 皮肤没做 1115）时，回退原生 `yesno`：
  No = 继续播放（默认焦点），Yes = 从头播放。
- 继续按钮的文案包含记录时间，不带问号。

## 九、插件不做什么

- 不写 Kodi 媒体库，也不写 Kodi 原生续播点；文件播放记录只写自己的 `resume.db`
  （设置 `file_resume` 可关）
- 不写皮肤设置
- 不改用户文件
- 除播放列表补全与文件播放记录的事件驱动 service 外，不常驻后台；
  唯一的轮询是 10003 焦点行圆环（窗口激活时 0.1 秒一次）
- 不做播放代理 / 转码 / 字幕下载（Emby 插件在做）

## 十、已知问题与限制（2026-10-30 更新）

1. ~~**搜索结果没有封面**~~ **已修复（0.2.2 / `c4ac966`）**：`normalize()` 回退读
   `ImageTags.Primary`，并补 `backdrop_tag` 与 `art["fanart"]`。
2. ~~**搜索页背景没有兜底图**~~ **已修复（皮肤 1.5.x）**：`NaraSearchBackground`
   改为渐变打底 + 剧照层，宽度全部用百分比。
3. ~~**搜索结果点击播放**~~ **已实机验证（2026-10-30）**：`mode=play` 可直接播放，
   `play_url()` 不需要改，直链兜底不启用。
4. **演员 / 导演 / 类型**：0.3.3 起支持，但**仅非 ASCII、≥2 字**；别名 / 分词仍未实现。
5. **皮肤输入限制（重要）**：皮肤搜索键盘是自绘的，只能输入字母，没有中文输入法。
   所以演员 / 类型搜索在皮肤 UI 里**实际不可达**，只能靠全拼 / 首字母搜作品。
   要真正用起来，需要给人物加拼音首字母，或在皮肤里加「人物」结果页签。
6. **代表集技术标识**：M3 明确不做。
