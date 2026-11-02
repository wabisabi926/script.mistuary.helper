# 发布流程

## 1. 版本规则

- 版本号只写在 `addon.xml` 的 `version`。
- `changelog.txt` 顶部第一段必须与版本号一致；CI 用 `awk` 取第一段作为 Release 正文。
- 修 bug 升 patch（0.2.2 → 0.2.3）；新增功能升 minor；不改 `xbmc.python` 接口不升 major。
- 已经 push 的版本不要回改；需要补修就再升 patch。

## 2. 发版前自检

```bash
python -m unittest discover -s tests -p 'test_*.py'   # 当前 146 项
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
| 代表集标识 | 不适用（M3 暂缓） |

皮肤只做 `AddonIsEnabled` 软探测，不比较版本；旧版插件不写新属性，皮肤自然隐藏。

## 6. 已发布

| 版本 | 内容 |
|---|---|
| 0.2.0 | 豆瓣评分 M2 |
| 0.2.1 | 修复 `resume:false` 污染搜索词 |
| 0.2.2 | 修复 action 模式 `GetDirectory failed` |
| 0.3.2 | CI / 无 Kodi 环境单测修复 |
| 0.3.4 | 播放列表补全（含 0.3.3 的设置整理与搜索补齐） |
| 0.3.5 | 播放列表自然排序/去重/跳过花絮；豆瓣无分可回退公开接口 |

`0.3.5` 待发布，Release 由 CI 在 push 时自动创建；后续改动升 patch 再发。
