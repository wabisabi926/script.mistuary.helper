# 开发路线图与进度

> 本文是**进度与顺序的权威**。改动计划先改这里，再动代码。
> 契约见 [`contract.md`](contract.md)，模块职责见 [`architecture.md`](architecture.md)。

## 硬约束：皮肤在插件未完工前必须能正常用

这不是"尽量"，是**每个里程碑的验收门槛**。三道保险：

1. **皮肤侧只加分支，不替换**：新条件写进已有 `<variable>`，原来那行无条件 `<value>` 永远留在最后当兜底。
2. **`addon.xml` 不写 `<import addon="script.mistuary.helper"/>`**：写了就是硬依赖，没装插件的用户整个皮肤加载失败。只用 `System.AddonIsEnabled` 软探测。
3. **任何失败按"未装"处理**：插件返回空 / 超时 / 版本太低 → 皮肤落到原分支，不弹错误框。

每个里程碑结束后必须过这张表：

| 验证项 | 标准 |
|---|---|
| 卸载插件后 | 相关功能与改动前**完全一致** |
| 禁用插件（不是卸载） | 同上 |
| 插件版本低于要求 | 同上 |
| `audit_skin.py --strict`（皮肤仓库） | EXIT=0 |
| 单测（本仓库） | 全绿 |

## 进度表

| 里程碑 | 内容 | 插件侧 | 皮肤侧 | 状态 |
|---|---|---|---|---|
| **M0** | 骨架：可安装、空跑、CI 能出 zip | ✅ | 无改动 | **完成**（`352e12e`） |
| **M1a** | 搜索桥代码（调 Emby、映射、分页、缓存） | ✅ | 无改动 | **完成**（同上） |
| **M1b** | 搜索分支接入 + 回退 | 无 | 3 处 `<variable>` 加分支 | 待做 |
| **M1c** | 实机验证 + 定播放地址 | 可能改 `play_url()` | 可能 1 处 | 待做 |
| **M2** | 豆瓣评分 | `douban.py` | 评分行加 1 个胶囊 | 待做 |
| **M3** | 代表集技术标识 | `techflags.py` | **0 改动**（分支已有） | 待做 |
| **M4** | 行级增强（首页豆瓣角标、节点名整理） | 多 | 多 | 可选，另立方案 |

**M1b 是唯一会改变皮肤行为的里程碑**，所以单独一步，做完立刻验证。

---

## M0 骨架

**交付**：`addon.xml`、`default.py`（只做分发）、`lib/` 十个模块、`resources/settings.xml` + 中英语言、4 个测试文件、CI、README / changelog / LICENSE。

**验收**：
- 装进 Kodi，「我的插件」能看到 **Mistuary Helper**，点开提示"请从皮肤进入"
- 设置页 5 项可改，改完下次调用生效（不用重启）
- `python -m unittest discover -s tests` 全绿
- CI 的 test job 通过

**回退**：卸载即可，皮肤完全不受影响（此时皮肤还没接任何分支）。

## M1a 搜索桥（插件侧）

**交付**：`lib/emby.py` 的 `search()` / `normalize()` / `render_search()`。

**关键决策**：
- 直接读 Emby 插件的 `servers_*.json`，用户不用二次输入地址和令牌
- 地址优先级 `ServerUrl → ManualAddress → LocalAddress → RemoteAddress`（实测四个，文档原来只写了三个）
- `ServerRemoved=true` 的配置跳过（换过服务器后旧配置不删只置标记）
- 缓存只存 `PrimaryImageTag`，**不存完整图片 URL**（URL 带 `api_key`，落盘就是泄露令牌）

**验收**：58 项单测全绿（HTTP 全 mock）。

**回退**：不接皮肤分支就没有任何行为变化。

## M1b 搜索分支接入（皮肤侧，唯一有行为变化的一步）

**改什么**：

| 文件 | 改动 |
|---|---|
| `xml/Includes.xml` | 加 `<expression name="helper_ready">System.AddonIsEnabled(script.mistuary.helper)</expression>` |
| `xml/Variables.xml` | `NaraSearchMoviesPathVar` / `NaraSearchTVShowsPathVar` 各加一条 `<value condition="...">` |
| `xml/SkinSettings.xml` | 加「使用 Emby 服务端搜索」开关（默认开，未装插件时整行隐藏） |

**验收**（全部通过才算完成）：
- 装插件 + 开关开：搜索走服务端，演员名/全拼能搜到
- 装插件 + 开关关：和现在完全一样
- 卸载插件：和现在完全一样
- `audit_skin.py --strict` EXIT=0

**回退**：删掉新加的 `<value>` 和 `<expression>`，立刻回到原状。

**前置**：需要用户确认搜索页签结构（电影 / 剧集两个？要不要加单集）。

## M1c 实机验证与播放地址

**要验的**：
1. `plugin://plugin.service.emby-next-gen/?mode=play&item=…&server=…` 能不能播
2. 中文、全拼、别名、演员名各搜一次，结果与 Emby 官方 App 一致
3. 已看标记、播放进度是否显示
4. 分页「加载更多」是否正常

**播放地址的退路**：`{base}/Videos/{Id}/stream?static=true&api_key=…`（直链，会带 token，只在 `mode=play` 不通时启用）。

## M2 豆瓣评分

**交付**：`lib/douban.py` 双通道取分（legacy + frodo 签名）、7 天缓存、失败退避。

**皮肤侧**：详情页 `onload` 调 `RunScript(…,action=rating)`，评分行加一颗胶囊，`Status != ok` 时隐藏。

**前置**：需要用户定胶囊位置（评分行第几个）。

**风险**：豆瓣接口变更/风控。处置：双通道互备 + 失败缓存 30 分钟 + `Status=error` 让皮肤隐藏。

## M3 代表集技术标识

**交付**：`lib/techflags.py`——取「当前季首集」，写 `ListItem.Property(TvShowRepresentative.*)`。

**皮肤侧 0 改动**：`VideoTechnicalFlagsByPrefix` 的 `TvShowRepresentative.*` 分支早就留好了，属性一写就生效。

**限制**：只对插件自己生成的列表有效；Kodi 库里的行拿不到 ListItem 引用，保持现状。

## M4 行级增强（可选）

首页 widget 行带豆瓣角标、节点名整理。**要换数据源**，影响面大，按需另立方案，不排期。

---

## 开发方式

- **一次只动一个里程碑**，不混改
- 固定流程：给方案 → 用户确认 → 改代码 → 单测 → 同步实机 → **用户验** → 提交
- 提交纪律：只 `git add` 自己改的文件，`git diff --cached --name-only` 核对

## 需要用户配合

| 时点 | 要做什么 | 耗时 |
|---|---|---|
| M1b 前 | 确认搜索页签结构 | 5 分钟 |
| M1c | 实机点一条搜索结果看能不能播 | 10 分钟 |
| M2 前 | 定豆瓣胶囊位置 | 5 分钟 |
| M2 | 看豆瓣分数对不对 | 5 分钟 |
| 每个里程碑 | 重启 Kodi 验一次 | 5 分钟 |
| 发版 | 确认版本号、是否推 GitHub | 2 分钟 |

## 已知待验证

| 项 | 影响 | 何时解决 |
|---|---|---|
| `mode=play` 播放地址 | 搜索出来的条目点了能不能播 | M1c |
| Kodi 19/20 兼容 | 现在只按 21/22 设计（`xbmc.python 3.0.1`） | 有人报再说 |
| 多服务器切换 | 代码已按 `server_id` 选，没实机验过双服务器 | 有第二台时 |
