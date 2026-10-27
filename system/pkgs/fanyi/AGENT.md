# fanyi · 给 AI 看的说明

## 干什么

多免费接口自动切换（Google 主入口 / Google clients5 / 有道 Demo / MyMemory），带本地缓存：把文字粘进来（或从剪贴板读），选目标语言，翻完一键复制回剪贴板。
界面里还能看/清缓存、点历史记录回填。

## 历史记录（2026-10-12 加的）

**历史就是本地缓存** —— 右侧那份历史列表，每一条就是缓存里的一行。
所以「删历史」= 真删缓存，重启不会冒回来；「关掉保留历史」= 新翻译完全不落盘（连缓存也不写），
每次重新联网翻（也不再命中缓存）。这个取舍是用户当面定的（方案 A）。

| 想干什么 | 界面上怎么点 |
|---|---|
| 删某一条 | 鼠标移到那条上 → 右上角出现 `×` → 点它 |
| 全清 | 历史栏标题右边「清空」→ **点两次**（第一次只是上膛变红，3 秒内再点一次才真删） |
| 保留 / 不保留 | 右上角「保留历史」开关（绿=保留，灰=不保留），状态存 `settings.json`，重启还在 |

- 后端方法：`history_remove{src,target}` / `cache_clear` / `keep_history{on}`，
  三个都**回一份和 `cache_info` 一样的现成载荷**（带 `ok / count / keep / history`），
  界面拿到就直接重画，不用自己拼状态。两种跑法（内嵌 `Embedded` / 独立窗口 `Api`）两边同名。
- 「不保留历史」期间的翻译：照旧翻、照旧回填剪贴板，只是不落盘也不进历史（界面会说明一句）。
- 删单条是按 `(原文, 目标语言)` 定位的 —— 跟缓存 key 一致；缓存文件整体重写（数据量小，最稳）。
- 开关状态存 `MOSS_PLUGIN_DATA_DIR/settings.json`（`{"keep_history": true}`）。
- 「清空」故意不用 `confirm()`：内嵌 iframe 里可能被挡，点了没反应（改成"再点一次确认"）。

## 怎么调

```
moss :fanyi              # 不带参数：自己开一个窗口（pywebview）
moss ui → 选它 → 运行     # 内嵌进 moss 的「界面」选项卡里跑
```

两种跑法**共用同一份** `ui/index.html`（Vue 3），靠 `ui/moss-embed.js` 垫片自动分流；
业务全在 `main.py`。

## 形态

- `kind = app`，`runner = python`，入口 `main.py`
- `ui.embed = ui/index.html` → 有它才有「界面」选项卡
- 它是**交互式界面**，不是给 AI 自动调用的工具 → `ai.expose = false`

界面是**热键的可视化台**：**打开即自动开始监听**（顶部状态圆点绿闪=正在监听，点一下可暂停/恢复）；
中间是焦点任务卡片（微型步骤条 + 原文/译文，文本区随容器伸缩、无固定大最小高度），
底部是一条**单行日志 footer**（鼠标移上去展开、可滚动看历史），右边是历史记录（自身可滚动，点一条即复制其译文）。
左侧与右侧之间有一条**可拖动的分隔线**，拖它即可调整两栏宽度比。
页面**全部由后端推来的 `hotkey` 事件驱动**，自己不做翻译。
容器不设最大尺寸，撑满可用的宽高（内嵌时随选项卡、独立窗口时随窗口自适应）。

**全局热键怎么保住的**：宿主自带运行时是**隔离**的，装不了第三方库（契约 §9），
`pynput` 用不了 —— 于是直接用标准库的 `ctypes` 调 Windows API：
`SetWindowsHookEx(WH_KEYBOARD_LL)` 装低级键盘钩子监听双击 Ctrl（Ctrl 是修饰键，
`RegisterHotKey` 认不了），`SendInput` 模拟 Ctrl+A / Ctrl+X / Ctrl+V 复刻"选中→翻译→粘回"。
所以 `capabilities.hotkey` 仍是 `true`，行为跟老版一致。
界面顶部有一张「全局热键」卡片：启动/停止开关 + 运行状态；热键触发的进度会推回页面显示。

> ★ **写这类键盘钩子必踩的两个坑**（都实测过）：
> ① **必须显式声明这些 API 的 64 位参数/返回类型**（`SetWindowsHookExW`、`CallNextHookEx`、
>   `UnhookWindowsHookEx`、`GetMessageW` …）。不声明时 `HHOOK` 会被截成 32 位，
>   `UnhookWindowsHookEx` 拿着半个句柄**卸不掉** → 残留一个死钩子把**整机键盘卡死**。
> ② **慢活儿不能放钩子回调里**（开线程/发网络会让回调超时，系统摘钩甚至卡键盘）。
>   所以是"装钩子+消息循环"一个线程、"真正干活"另一个常驻工作线程，回调只做**判定+入队**；
>   卸载放在 `finally` 并**检查返回值**。护栏见 `tools/fanyi热键探针.py`（断言 `_unhook_ok`）。

## 副作用

- 声明能力：`{"run": ["python"], "net": ["translate.googleapis.com", "clients5.google.com", "aidemo.youdao.com", "api.mymemory.translated.net"], "clipboard": ["read", "write"]}`
- 写文件：只写 `MOSS_PLUGIN_DATA_DIR`（`cache/`）下，不写包目录
- 上网：翻缓存没命中时，优先请求上次成功的通道，然后 Google、Google clients5、有道 Demo、MyMemory 依次兜底；最后成功的通道记在 MOSS_PLUGIN_DATA_DIR/provider.json。

## 后端两种模式（`main.py`）

| | 独立窗口（`moss :fanyi`） | 内嵌（moss 里点「运行」） |
|---|---|---|
| 怎么区分 | 环境里**没有** `MOSS_UI_EMBED` | 宿主机注入 **`MOSS_UI_EMBED=1`** |
| 干什么 | `webview.create_window(url=…, js_api=Api())` | **不开窗口**，在 stdin/stdout 上说 JSON 行 |

内嵌协议：一行一个 JSON 对象（`{"id","method","params"}` → `{"id","ok","result"}`）。

## 界面上会调的方法（`Embedded` 与 `run_window().Api` 两边同名）

`translate` / `read_clipboard` / `copy` / `cache_info` / `cache_clear` / `history` /
`history_remove` / `keep_history` / `targets` / `info` / `hotkey_start` / `hotkey_stop` /
`hotkey_status`

当前这一版页面用到的是 `hotkey_status` / `hotkey_start` / `hotkey_stop` / `cache_info` /
`history_remove` / `cache_clear` / `keep_history`（点历史项时再用 `copy`）；其余方法留着备用。

热键触发的进度/结果由后端**主动推**事件 `{"event":"hotkey","data":{...}}`：
`phase` = `state` / `step`（带 `step` 1~4、`source_text`、`translated`）/ `done`（带 `result`）/ `fail`。
页面用 `moss.on('hotkey', …)` 接，按 `step` 走四步进度条。

## 还没验的

- 真机上**手点**没跑过（用户会测）。缓存/剪贴板/翻译/热键的真机行为以实际为准。
- 已自动验过的（2026-10-12）：后端逻辑（写过缓存→删单条→重启不复活→关开关不落盘→
  开着开关照旧命中缓存→清空后文件被删）与界面交互（真 Edge 里点 `×`、连点两次清空、
  切开关，看它真的调了对应方法、列表/条数/开关跟着变、无 JS 报错）。
