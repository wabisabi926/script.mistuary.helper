# 测试策略

> 目标：**没有 Kodi、没有 Emby、没有网络**也能验证大部分逻辑。
> 剩下那部分（播放地址、搜索结果正确性）只能实机验，列在 §3。

## 1. 单测（`tests/`，72 项）

```bash
python -m unittest discover -s tests -p 'test_*.py'
```

HTTP 全部 mock，不依赖网络和 Emby。CI 每次 push 都跑。

| 文件 | 覆盖什么 | 项数 |
|---|---|---|
| `test_router.py` | 参数解析：中文、`&`、`?`、`=`、空值、重复键、负数 offset、超长 query、URL 往返 | 15 |
| `test_douban.py` | IMDb 识别、dbid 回退、双通道回退、失败缓存、窗口属性、关闭开关 | 14 |
| `test_cache.py` | 命中、TTL 过期、损坏 JSON、缺 `ts`、空列表也缓存、只删 `.json`、key 稳定性 | 9 |
| `test_config.py` | 服务器发现、地址优先级、`ServerRemoved` 跳过、缺 token、坏 JSON、按 id 选、未知 id 回退、repr 不泄露 token | 12 |
| `test_emby.py` | 字段映射、`Series` 是文件夹、缺字段不崩、结果不含 token、图片 URL、搜索参数、缓存命中不打 HTTP、空结果缓存、401 / 超时 / 未知类型 / 坏 JSON 的错误映射 | 22 |

### 几条值得单独说的用例

**`test_query_with_ampersand_is_not_split`** —— `Tom & Jerry` 不能被 `parse_qs` 切成两半。
这是整个参数解析模块存在的理由。

**`test_normalized_dict_has_no_token`** —— 断言 `normalize()` 的返回值 repr 里
既没有 `SECRET-TOKEN` 也没有 `api_key`。因为那个 dict 会落盘到缓存文件。

**`test_repr_does_not_leak_token`** —— `Server.__repr__` 不含 token，因为 repr 可能进日志。

**`test_empty_list_is_cached`** —— 空结果也要缓存，否则用户连续打字每次都打服务端。

**`test_unknown_id_falls_back_to_first`** —— 设置里钉的服务器被删了，退回第一个而不是整个失效。

## 2. 静态检查

```bash
python -m compileall -q default.py lib
```

语法错误在 Kodi 里只表现为"插件打不开"，日志里也不说清是哪一行。CI 提前拦住。

## 2.5 直连插件测试（不需要 Kodi 界面）

Kodi 的 Web 服务 / JSON-RPC 关闭时，可以直接在 Python 里调 `lib` 验证「插件 → Emby」这一段：

```python
import sys; sys.path.insert(0, "D:/下载/AI/script.mistuary.helper")
from lib import config, emby, cache
cache.get = lambda *a, **k: None      # 不落盘
cache.put = lambda *a, **k: None
s = config.load_servers("C:/Users/<你>/AppData/Roaming/Kodi/userdata")[0]
print([i["name"] for i in emby.search(s, "RZD", "movies", limit=5, ttl=0)])
```

2026-10-30 实测结果：

| 查询 | 结果 |
|---|---|
| `RZD` / movies | 让子弹飞、机器人总动员、燃烧女子的肖像（3 条，子串匹配） |
| `让子弹飞` / movies | 1 条 |
| `rangzidanfei` / movies | 1 条 |
| `12th Fail` / movies | 1 条（原名） |
| `Avatar` / movies | 1 条（大小写不敏感） |
| `20之后` / shows | 1 条 |
| `姜文` / `科幻` | 0 条（未实现，见 roadmap M1d） |

豆瓣实网验证（2026-10-30）：

| 条目 | IMDb | 结果 |
|---|---|---|
| 让子弹飞 | tt1533117 | 9.0 / 1,948,866 票 |
| 阿凡达 | tt0499549 | 8.8 / 1,608,113 票 |
| 20之后（剧集） | tt10908354 | 8.2 / 1,259 票 |

这条路径绕过了 Kodi 的参数传递，**不能**验证皮肤侧 `query=` 拼接和排序，
那两项必须在实机做。

## 3. 实机验证清单

只能在 Kodi 里做的部分。**每个里程碑结束都要过一遍。**

### 3.1 安装与探测

- [ ] 重启 Kodi 后「我的插件」里出现 **Mistuary Helper**
- [ ] 点开显示"请从皮肤进入"，不是报错
- [ ] 设置页 5 项可改，改完下次调用生效（不用重启）
- [ ] 卸载后皮肤相关功能回到改动前状态

### 3.2 搜索（M1b / M1c）

前置：插件**已启用** + 重载皮肤 + 皮肤设置 → 媒体里能看到「使用 Emby 服务端搜索」。

- [ ] `RZD`：出现 3 条，第一条是「让子弹飞」（服务端）；关掉开关后只剩 1 条（本地）
- [ ] `rangzidanfei` / `让子弹飞`：1 条
- [ ] 剧集页签：`20之后` 有结果
- [ ] 特殊字符：`Tom & Jerry` 不报错（库里没有该片，0 条也算通过）
- [ ] 已看标记：看过的条目显示 OverlayWatched
- [ ] 禁用或卸载插件并重载皮肤：开关消失，搜索结果回到本地
- [ ] 演员名：当前应为 0 条（M1d 之前不验收这一项）
- [ ] 播放进度：看了一半的条目显示进度
- [ ] 分页：满一页后出现「加载更多」，点了能继续
- [ ] **点一条结果能播**（这条是 M1c 的核心，播放地址没验过）

### 3.3 降级（每次改皮肤侧都要验）

- [ ] 卸载插件 → 搜索与改动前完全一致
- [ ] 禁用插件（不是卸载）→ 同上
- [ ] 插件版本低于要求 → 同上

### 3.4 豆瓣评分（M2）

- [ ] 有 IMDb id 的电影：胶囊显示分数，与豆瓣网页一致
- [ ] 没有 IMDb id：胶囊隐藏，不显示 `0.0`
- [ ] 断网：胶囊隐藏，不弹错误框
- [ ] 7 天缓存：第二次进入明显更快

### 3.5 代表集标识（M3）

- [ ] 首页 / 搜索的剧集卡显示 4K / HDR / 音轨，与详情页一致
- [ ] 没有分集的剧集：不显示，不报错

## 4. 日志检查

每次实机验证后看 `kodi.log`：

```bash
# 不该出现
grep -i "MISTUARY.HELPER \[ERROR\]" kodi.log

# 打开 debug_log 后才有的调试信息
grep -i "MISTUARY.HELPER" kodi.log | tail -30
```

**永远不该出现**：`AccessToken` 的值、32 位的 `UserId`。
看到任何一处就是泄露，要立刻修。

## 5. 发版前

- [ ] `python -m unittest discover -s tests -p 'test_*.py'` 全绿
- [ ] `python -m compileall -q default.py lib` 无输出
- [ ] `addon.xml` 版本号已升
- [ ] `changelog.txt` 顶部有对应版本段落（CI 用它当 Release 正文）
- [ ] 本地模拟打包，文件清单里没有 `tests/`、`__pycache__`、`.git*`
