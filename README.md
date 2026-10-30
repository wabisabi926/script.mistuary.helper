# Mistuary Helper

Mistuary 皮肤的**可选**配套插件。装了就多几个功能，不装皮肤照常工作。

| 功能 | 装了这个插件 | 不装 |
|---|---|---|
| 搜索：中文标题 / 原名 | Emby 服务端，与官方 App 一致 | 皮肤自带本地搜索（够用） |
| 搜索：首字母（`HZ` / `S`） | 服务端（子串匹配） | 本地（`startswith`） |
| 搜索：**演员 / 导演 / 类型** | ❌ 暂缓（M1d） | ❌ 没有 |
| 搜索：全拼 / 原名 | ✅ | ❌ 没有 |
| 搜索：别名 / 分词 | ❌ 未实现 | ❌ 没有 |
| 详情页豆瓣胶囊 | ✅（0.2.0，无 IMDb 时按标题 + 年份兜底） | 不显示 |
| 剧集「代表集」技术标识 | ❌ 暂缓（M3，收益为零） | 皮肤自己推断，行为不变 |

## 安装

1. 从 Releases 下载 `script.mistuary.helper-<ver>.zip`
2. Kodi → 插件 → 从 zip 安装
3. **重载皮肤**（设置 → 界面 → 皮肤 → 重新加载）

> ⚠️ 第 3 步不能省。Kodi 的 `<include condition>` 和容器 `<content>` 都是**加载时求值**的，
> 装完插件不重载皮肤，新分支不会生效——你会以为插件没起作用。

## 前提

- 已安装并登录 **Emby for Kodi Next Gen**（`plugin.service.emby-next-gen`）
- 插件直接读它的 `addon_data/plugin.service.emby-next-gen/servers_*.json`，
  **不用二次输入地址和令牌**

## 设置

| 项 | 默认 | 说明 |
|---|---|---|
| Emby 服务器 ID | 空 | 留空用第一个服务器 |
| 每次查询条数 | 100 | 超过会追加「加载更多」 |
| 搜索缓存（秒） | 300 | 设 0 关闭缓存 |
| 获取豆瓣评分 | 开 | 关掉即不发豆瓣请求 |
| 写调试日志 | 关 | 打开后日志前缀 `MISTUARY.HELPER` |

## 隐私

- 只**读** Emby 插件的服务器配置，不修改
- **不写** Kodi 媒体库、不写皮肤设置
- 缓存只存搜索结果和评分，**不含令牌**
- 日志只记 ServerId 和 HTTP 状态码，**不记 token**

## 卸载

从「我的插件」里直接删掉即可，皮肤下一帧就回到「少功能」状态，
不需要重载皮肤（探测是每次渲染求值，不是缓存）。

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
| [`docs/roadmap.md`](docs/roadmap.md) | 进度表、里程碑验收与回退 |
| [`docs/architecture.md`](docs/architecture.md) | 模块职责、数据流、设计原则 |
| [`docs/contract.md`](docs/contract.md) | 与皮肤的契约（参数、属性、降级表） |
| [`docs/testing.md`](docs/testing.md) | 单测覆盖 + 实机验证清单 |

## 许可

GPL-3.0-only。豆瓣取分方案参考
[`plugin.video.themoviedb.helper-douban`](https://github.com/jurialmunkey/plugin.video.themoviedb.helper)（GPL-3.0）。
