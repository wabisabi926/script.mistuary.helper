# 排障

## 装完没反应 / 开关不出现

1. 确认插件在 Kodi 里是**启用**状态：设置 → 插件 → 我的插件 → 程序插件 → Mistuary Helper。
2. 搜索还要求 `plugin.service.emby-next-gen` 也启用；只装 helper 没装 Emby 时不切服务端。
3. 装 / 卸 / 启用后**重载皮肤**。`<include condition>` 和容器 `<content>` 是加载时求值，
   不重载皮肤不会切换。
4. 检查皮肤设置 → 媒体里是否有「使用 Emby 服务端搜索」；没有就是软探测为假。

## 搜索没有结果

1. 先搜一个确定存在的词（如 `让子弹飞`、`rzd`）。
2. 看结果提示里的搜索词。如果显示 `yw&resume:false`，说明插件低于 0.2.1；
   0.2.1 起会过滤 Kodi 追加的 `resume:false`。
3. 打开插件设置里的「写调试日志」，在 `kodi.log` 查 `MISTUARY.HELPER`：
   - `search failed: status=401/403` → Emby 令牌或用户失效；
   - `status=0` → 网络 / 地址不通；
   - `-> 0 items` → Emby 确实没有匹配。
4. 确认 Emby 里该条目已入库、且类型是 `Movie` / `Series`。
5. 演员 / 导演 / 类型 / 别名目前**搜不到**，不是故障，见 `roadmap.md` M1d。

## 搜索结果没有封面

已知问题，0.2.2 仍未修。Emby 搜索返回 `ImageTags.Primary`，插件只读
`PrimaryImageTag`，所以列表没有海报。根因与修复方向见 `HANDOVER.md` §4.1。
不是 Emby 缺图，也不是皮肤遮罩问题。

## 搜索页背景是纯黑

皮肤侧问题：非空查询且条目没有 fanart 时，`NaraSearchBackground` 没有兜底图。
见皮肤仓库 `docs/HANDOVER.md` 的已知问题；插件不负责皮肤背景。

## 豆瓣胶囊不显示

按顺序排查：

1. 插件设置 →「获取豆瓣评分」是否打开。
2. 详情页条目是否是电影 / 剧集（单集、季不显示）。
3. 是否有 IMDb id；没有时插件会按标题 + 年份查豆瓣，标题要完全一致。
4. 看窗口属性 `Mistuary.Rating.Status`：
   - `ok` → 有分；
   - `missing` → 没找到条目；
   - `error` → 网络 / 风控，30 分钟内不重试。
5. 打开调试日志看 `douban fetch failed` / `douban ok`。

## 日志里 `GetDirectory failed`

如果路径是 `plugin://...?action=rating`，升级到 **0.2.2**。
0.2.2 起 action 目录调用会补 `endOfDirectory`。`RunScript` 形态没有 handle，
本来就不该调。

## 缓存与日志位置

```text
%APPDATA%\Kodi\userdata\addon_data\script.mistuary.helper\cache\
%APPDATA%\Kodi\kodi.log
```

缓存可在插件设置里点「清除缓存」。缓存文件不含 token；如果看到完整
`api_key` / `AccessToken` / 32 位 UserId，按泄露处理。

## 播放失败

`play_url()` 走 Emby 插件的 `mode=play`，目前未实机验证。
先确认 Emby 插件自己能播；仍失败时再考虑直链兜底（会带 token，只在必要时启用）。
