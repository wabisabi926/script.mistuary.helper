# Mistuary Helper

Mistuary 皮肤的**可选**配套插件。装了就多几个功能，不装皮肤照常工作。
当前版本 **0.3.3**，101 项单测。

| 功能 | 装了这个插件 | 不装 |
|---|---|---|
| 搜索：中文标题 / 原名 | Emby 服务端，与官方 App 一致 | 皮肤自带本地搜索（够用） |
| 搜索：全拼 | ✅ | ❌ 没有 |
| 搜索：首字母（`HZ` / `S`） | 服务端**前缀严格匹配**（`RZD` 不会命中 `JQRZDY`） | 本地 `startswith` |
| 搜索：中文演员名 / 类型 | ✅ 0.3.3 起（限非 ASCII、≥2 字） | ❌ 没有 |
| 详情页豆瓣胶囊 | ✅ 优先读 StrmAssistant，失败回退豆瓣公开接口 | 不显示 |
| 剧集「代表集」技术标识 | ❌ 不做（M3，收益为零） | 皮肤自己推断，行为不变 |

## 安装

1. 从 Releases 下载 `script.mistuary.helper-<ver>.zip`
2. Kodi → 插件 → 从 zip 安装
3. **重载皮肤**（设置 → 界面 → 皮肤 → 重新加载）

> ⚠️ 第 3 步不能省。Kodi 的 `<include condition>` 和容器 `<content>` 都是**加载时求值**的，
> 装完插件不重载皮肤，新分支不会生效——你会以为插件没起作用。

## 前提

- **搜索**需要已安装并登录 **Emby for Kodi Next Gen**（`plugin.service.emby-next-gen`）；
  插件直接读它的 `addon_data/plugin.service.emby-next-gen/servers_*.json`，
  **不用二次输入地址和令牌**
- **豆瓣评分**不依赖 Emby：有 IMDb id 即可；没有 IMDb 时按标题 + 年份兜底

## 设置

4 个分类，底部有**帮助条** —— 聚焦哪一项就显示那一项的说明，不用查文档。

**Emby 服务器**（一般不用动）

| 项 | 默认 | 说明 |
|---|---|---|
| 测试 Emby 连接 | — | 通知里显示服务器名和版本 |
| 服务器 ID / 地址 / 令牌 | 空 | **不确定就留空**。只有装了多台 Emby、要指定其中一台时才填 |

**搜索**

| 项 | 默认 | 说明 |
|---|---|---|
| 每次查询条数 | 100 | 超过会追加「加载更多」 |
| 搜索缓存（秒） | 300 | 设 0 关闭缓存 |

**豆瓣评分**

| 项 | 默认 | 说明 |
|---|---|---|
| 获取豆瓣评分 | 开 | 关掉即不发豆瓣请求 |
| 优先读 Emby | 开 | 先问 StrmAssistant 要分（与 Emby App 内同源），失败才直连豆瓣 |

**日志与诊断**

| 项 | 默认 | 说明 |
|---|---|---|
| 写调试日志 | 关 | 打开后日志前缀 `MISTUARY.HELPER` |
| 清空缓存 | — | 清掉搜索结果和评分缓存 |

> 服务器 ID / 地址 / 令牌、分页、缓存 TTL 这几项收在**「专家」级别** ——
> 配错会直接连不上 Emby，所以默认不显示。设置页左下角可以切级别，
> 切完**退出设置页再重进**才刷新。

## 隐私

- 只**读** Emby 插件的服务器配置，不修改
- **不写** Kodi 媒体库、不写皮肤设置
- 缓存只存搜索结果和评分，**不含令牌**
- 日志只记 ServerId 和 HTTP 状态码，**不记 token**

## 卸载

从「我的插件」里直接删掉，然后**重载皮肤**（设置 → 界面 → 皮肤 → 重新加载）。

不重载的话，皮肤里已经展开的插件分支不会自动退回本地分支 ——
搜索会指向一个不存在的插件，表现是「点了没反应」，但**不会崩**。

## 常见问题

**装完没生效**
装 / 卸插件后必须**重载皮肤**（设置 → 界面 → 皮肤 → 重新加载）。
Kodi 的 `<include condition>` 和容器 `<content>` 都是**加载时求值**的，
不重载就还是旧分支。

**搜不到中文演员名 / 类型**
0.3.3 起支持，但只对**非 ASCII、≥2 个字**的查询生效 —— 避免把 `5.1` 这类
当成人名去搜。另外确认 Emby 插件本身是启用状态。

**首字母搜出一堆不相干的片子**
0.3.3 改成前缀严格匹配（`RZD` 不再命中 `JQRZDY`）。
如果还是不对，清一下缓存（设置 → 日志与诊断 → 清空缓存）再试。

**详情页没有豆瓣胶囊**
1. 片子要有 IMDb id；没有时按标题 + 年份兜底，命中率低
2. 想要和 Emby App 内一致的分数，需要装神医助手（StrmAssistant）——
   插件会优先读它的 `/Douban/RatingsByImdb`
3. 没装 StrmAssistant 时直连豆瓣公开接口，可能被风控限流，过一会儿再试
4. 皮肤侧也要开着对应的评分来源设置

**想排查到底哪一步失败了**
打开「写调试日志」，然后看 `kodi.log` 里前缀 `MISTUARY.HELPER` 的行。
逐步排查见 [`docs/troubleshooting.md`](docs/troubleshooting.md)。

## 已知限制

- **搜索覆盖不到分集**：Kodi 没有全局的分集节点，插件层拿不到
- **豆瓣分依赖 IMDb id**：纯中文命名的片子命中率明显下降
- **不写 Kodi 媒体库**：0.3.3 移除了「把豆瓣分写进库」的后台服务 ——
  皮肤侧没有消费方，留着只是每次启动跑一遍全库

## 开发

```bash
python -m unittest discover -s tests -p 'test_*.py'
```

HTTP 全部 mock，不依赖网络、不依赖 Emby。本地调试：

```bash
# 把仓库目录联接/复制到 Kodi 的 addons 目录
# 改 *.py 不需要重启（每次调用重新加载）
# 改 addon.xml / resources/ 需要重启
```

文档在 [`docs/`](docs/)：

| 文件 | 内容 |
|---|---|
| [`docs/HANDOVER.md`](docs/HANDOVER.md) | **接手先读**：现状、已知问题、发版与验证入口 |
| [`docs/roadmap.md`](docs/roadmap.md) | 进度表、里程碑验收与回退 |
| [`docs/architecture.md`](docs/architecture.md) | 模块职责、数据流、设计原则 |
| [`docs/contract.md`](docs/contract.md) | 与皮肤的契约（参数、属性、降级表） |
| [`docs/testing.md`](docs/testing.md) | 单测覆盖 + 实机验证清单 |
| [`docs/troubleshooting.md`](docs/troubleshooting.md) | 搜索/豆瓣/日志/缓存的排查步骤 |
| [`docs/release.md`](docs/release.md) | 版本号、CI 打包与发布流程 |

## 许可

GPL-3.0-only。豆瓣取分方案参考
[`plugin.video.themoviedb.helper-douban`](https://github.com/jurialmunkey/plugin.video.themoviedb.helper)（GPL-3.0）。
