# 发布流程

## 1. 版本规则

- 版本号只写在 `addon.xml` 的 `version`。
- `changelog.txt` 顶部第一段必须与版本号一致；CI 用 `awk` 取第一段作为 Release 正文。
- 修 bug 升 patch（0.2.2 → 0.2.3）；新增功能升 minor；不改 `xbmc.python` 接口不升 major。
- 已经 push 的版本不要回改；需要补修就再升 patch。

## 2. 发版前自检

```bash
python -m unittest discover -s tests -p 'test_*.py'   # 当前 229 项
python -m compileall -q default.py lib
```

另外确认：

- `addon.xml` 版本与 `changelog.txt` 顶部一致。
- 没有把 `tests/`、`__pycache__`、`.git*` 打进包（CI 的 Package 步骤会清理）。
- 新增/修改的行为已写进 `contract.md` 或 `HANDOVER.md`。

## 3. 提交与推送

```bash
git add <具体文件>
git diff --cached --name-only      # 核对，不混入别的改动
git commit -m "release: X.Y.Z — 一句话"
git push origin main
```

`ci.yml` 的 `build` job 在 push 到 `main` 时比较 `addon.xml` 版本：

- 版本没变 → 跳过打包；
- 版本变了且 Release 不存在 → 打包 `script.mistuary.helper-X.Y.Z.zip`，
  用 changelog 第一段当正文，创建 `vX.Y.Z` Release。

**不要手工打 zip 上传**，否则会和 CI 产物不一致。

## 4. 发布后核对

```bash
git ls-remote --tags origin | tail -5
```

确认 `vX.Y.Z` 已出现。Release 里应只有一个 zip，且包内没有 `tests/` / `__pycache__`。

本地验证新包：

1. Kodi → 插件 → 从 zip 安装。
2. 我的插件里版本号应为 `X.Y.Z`。
3. 重载皮肤；搜索 / 豆瓣各验一次。
4. 看 `kodi.log` 没有 `MISTUARY.HELPER [ERROR]`。

## 5. 版本与皮肤兼容

| 皮肤功能 | 最低插件版本 |
|---|---|
| 服务端搜索 | 0.1.0（0.2.1 修 `resume:false`） |
| 详情页豆瓣 | 0.2.0 |
| action 目录收尾 | 0.2.2 |
| 播放列表补全（同季 / 同目录） | 0.3.4 |
| 跨季继续 | 0.3.5 |
| 文件播放记录 | 0.3.7 |
| 媒体库封面同步 | 0.3.9 |
| 搜索剧集跳 Kodi 媒体库 | 0.3.10 |
| 未同步剧集浏览 | 0.3.11 / 0.4.0 |
| 代表集标识 | 不适用（M3 暂缓） |

2026-11-05 起皮肤 `addon.xml` 声明硬依赖，未装插件不加载；运行时仍保留 `AddonIsEnabled`
软探测用于隐藏入口，不比较版本。

### 5.1 发布顺序：先插件，后皮肤（2026-11-07 定）

皮肤对插件是硬依赖，所以**必须先发插件、再发皮肤**：

1. 插件升版本 → push → CI 建 `vX.Y.Z` Release
2. 核对 `git ls-remote --tags origin` 已有该 tag，Release 里的 zip 可下载
3. 皮肤再升 import 下限并 push

先发皮肤的后果：用户升级皮肤时若本地插件低于新下限，Kodi 判定依赖不满足 →
**皮肤不加载**（整屏打不开）。皮肤侧用到插件新能力时，必须写软探测，保证旧插件下能降级。

## 6. 已发布

| 版本 | 内容 |
|---|---|
| 0.2.0 | 豆瓣评分 M2 |
| 0.2.1 | 修复 `resume:false` 污染搜索词 |
| 0.2.2 | 修复 action 模式 `GetDirectory failed` |
| 0.3.2 | CI / 无 Kodi 环境单测修复 |
| 0.3.4 | 播放列表补全（含 0.3.3 的设置整理与搜索补齐） |
| 0.3.5 | 播放列表自然排序/去重/跳过花絮；豆瓣无分可回退公开接口 |
| 0.3.6 | 发布包补上 `service.py` |
| 0.3.7 | 文件播放记录（10003 弹窗 + 焦点行圆环） |
| 0.3.8 | 插件封面文字下移、去掉豆瓣 / 搜索那行 |
| 0.3.9 | 媒体库封面同步；按目录补全默认开 |
| 0.3.10 | 搜索剧集改走 Kodi 媒体库 |
| 0.3.11 | 未同步剧集进入插件自己的季/集列表 |
| 0.4.0 | 与 0.3.11 功能相同，仅重新编号发布（0.3.x 尾巴收口） |

`0.4.0` 已发布，Release 由 CI 在 push 时自动创建。
