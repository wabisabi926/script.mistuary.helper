# 与皮肤的契约

> 本文是**插件与皮肤之间的接口约定**。改任何一方的调用方式前先改这里。
> 皮肤仓库里的 `docs/helper-plugin-plan.md` 是本文的摘要，**以本文为准**。

## 一、可选安装

插件是**可选**的。`addon.xml` 不写 `<import addon="script.mistuary.helper"/>`——
写了就变成硬依赖，没装插件的用户整个皮肤加载失败。

皮肤只做软探测：

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

### 2.1.1 当前实际能力（2026-10-30 实测）

| 能力 | 状态 | 说明 |
|---|---|---|
| 中文标题 | ✅ | `/Items?searchTerm=` |
| 原名 | ✅ | `12th Fail` → 12年级的失败；大小写不敏感 |
| 全拼 | ✅ | `rangzidanfei` → 让子弹飞 |
| 首字母 | ✅ 子串 | `RZD` 会命中 `JQRZDY`（机器人总动员）；不是前缀 |
| 剧集 | ✅ | `20之后` 命中；标点密集的标题可能因 Emby 分词失败 |
| 演员 / 导演 | ❌ | `/Items?searchTerm=` 不索引；方案见 roadmap M1d（暂缓） |
| 类型 | ❌ | 需 `Genres=` 过滤；方案见 roadmap M1d（暂缓） |
| 别名 / 分词 | ❌ | 未实现 |

皮肤侧已经接好（`a6b9f59`），但**插件必须在 Kodi 里启用**，否则软探测为假、
开关隐藏、搜索回退本地。装/卸/启用后都要重载皮肤。

### 2.2 动作（无界面）

```
RunScript(script.mistuary.helper,action=rating,type=movie,dbid=<Kodi 库 id>)
RunPlugin(plugin://script.mistuary.helper/?action=sync_ratings)
```

`action=rating`（0.2.0+）写窗口属性；
`action=sync_ratings`（0.3.0+）立即把 Emby 的豆瓣分同步进 Kodi 库（与后台服务同一入口）。

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


### 3.3 写 Kodi 库（豆瓣评分，0.3.0+）

后台服务（启动 60 秒后、按设置的间隔）与 `action=sync_ratings` 会把豆瓣分写成
Kodi 库里的独立评分记录：

| 项 | 值 |
|---|---|
| 表 | `MyVideos<ver>.db` → `rating` |
| `rating_type` | `douban` |
| `rating` | 0–10，一位小数 |
| `media_type` | `movie` / `tvshow` / `episode` |

规则：

- 只读 Emby 的 `/Douban/RatingsByImdb`，**不请求豆瓣**；
- 主评分（`default` / `imdb`）**不改动**；
- 值变化才写、豆瓣分消失则删除该行；单事务提交，失败只记日志；
- 皮肤用 `ListItem.Rating(douban)` 判断「这条主评分是否来自豆瓣」。

## 四、降级表

**装了就多，不装就少。每一项都有明确的"没有插件"状态，且那个状态是当前已有行为。**

| 功能 | 装了插件 | 没装 / 禁用 / 版本低 |
|---|---|---|
| 搜索：中文标题 / 原名 | Emby 服务端，与官方 App 一致 | 本地 XSP（`contains`） |
| 搜索：首字母（`HZ` / `S`） | 服务端 | 本地 XSP（`startswith`） |
| 搜索：全拼 / 原名 | ✅ | ❌ 没有（本地没有拼音库） |
| 搜索：演员 / 导演 / 类型 | ❌ 未实现（M1d 暂缓） | ❌ 没有（1.2.0 起本地已移除） |
| 搜索：别名 / 分词 | ❌ 未实现 | ❌ 没有（本地没有分词器） |
| 详情页豆瓣胶囊 | ✅ 显示 | 整行不显示，其余评分胶囊照常 |
| 剧集代表集技术标识 | 插件写属性 | 皮肤自己的 `ListItemAbsolute(0)` 推断，**行为不变** |
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
| 代表集标识 | 不适用（M3 暂缓，不承诺版本） |

皮肤目前**不做版本比较**（Kodi 没有可靠的版本比较表达式），只做
`System.AddonIsEnabled` 软探测；旧版插件对新增功能什么都不写，皮肤自然隐藏，
等价于没装。最低版本只写在 README / Release 说明里。

## 八、一个必须写进用户文档的坑

Kodi 的 `<include condition="...">` 和容器的 `<content>` 都是**加载时求值**的。

所以**装完 / 卸载插件后必须重载皮肤**（设置 → 界面 → 皮肤 → 重新加载），
新分支才生效。不写这句，用户会以为插件没起作用。

卸载后回退则是**立即**的——探测是每次渲染求值，不是缓存。

## 九、插件不做什么

- 不写 Kodi 媒体库
- 不写皮肤设置
- 不改用户文件
- 不常驻后台（没有 `service.py`）
- 不做播放代理 / 转码 / 字幕下载（Emby 插件在做）

## 十、已知问题（2026-10-30）

1. **搜索结果没有封面**：Emby `/Items?searchTerm=` 返回的是 `ImageTags.Primary`，
   插件当前只读 `PrimaryImageTag`，所以 `image_tag` 为空。0.2.2 还没修；
   修复方向是在 `normalize()` 里回退读 `ImageTags.Primary`，并同步改测试夹具。
2. **搜索页背景没有兜底图**：皮肤侧问题。非空查询且条目没有 fanart 时，
   `NaraSearchBackground` 的纯黑层是唯一背景；插件不负责皮肤背景。
3. **搜索结果点击播放**：`mode=play` 路径尚未实机验证，直链兜底未实现。
4. **演员 / 导演 / 类型 / 别名 / 分词**：未实现，M1d 暂缓。
5. **代表集技术标识**：M3 明确不做。
