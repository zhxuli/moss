# fanyi · 给 AI 看的说明

> 这一版（v2.0）把原来的 Tk 单窗口改成了**网页界面、两种跑法**（照 `system/pkgs/skill/` 的样板）。
> 功能代码从老项目 `QuickTools/pa_soft/bin/soft/fanyi` 移植，但**依赖全换成标准库**。

## 干什么

Google 翻译，带本地缓存：把文字粘进来（或从剪贴板读），选目标语言，翻完一键复制回剪贴板。
界面里还能看/清缓存、点历史记录回填。

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

## 和 v1（Tk + 三方库）比，改了什么

| | v1 | v2 |
|---|---|---|
| 界面 | Tk 窗口 | 网页（原生 JS，Mac 风格 Pro 界面），内嵌 / 独立窗口两跑法 |
| 翻译 | `googletrans`（三方） | `urllib` 调 Google 免费接口 `translate.googleapis.com` |
| 剪贴板 | `pyperclip`（三方） | `ctypes` 调 Windows 剪贴板 API |
| 触发 | **双击 Ctrl 全局热键**（`pynput`，三方） | **双击 Ctrl 全局热键**（`ctypes` 低级键盘钩子，等价） |
| 缓存 | `MOSS_PLUGIN_DATA_DIR/translation_cache.txt` | `MOSS_PLUGIN_DATA_DIR/cache/translation_cache.jsonl` |

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

**缓存迁移**：首次启动时若新缓存（`cache/translation_cache.jsonl`）不存在，会读旧版
`MOSS_PLUGIN_DATA_DIR/translation_cache.txt`（一行 `a | b`）**一次性导入**（按脚本猜语言，
双向各一条）—— 升级不丢缓存。

## 副作用

- 声明能力：`{"run": ["python"], "net": ["translate.googleapis.com"], "clipboard": ["read", "write"]}`
- 写文件：只写 `MOSS_PLUGIN_DATA_DIR`（`cache/`）下，不写包目录
- 上网：翻缓存没命中时才请求 Google 免费接口

## 后端两种模式（`main.py`）

| | 独立窗口（`moss :fanyi`） | 内嵌（moss 里点「运行」） |
|---|---|---|
| 怎么区分 | 环境里**没有** `MOSS_UI_EMBED` | 宿主机注入 **`MOSS_UI_EMBED=1`** |
| 干什么 | `webview.create_window(url=…, js_api=Api())` | **不开窗口**，在 stdin/stdout 上说 JSON 行 |

内嵌协议：一行一个 JSON 对象（`{"id","method","params"}` → `{"id","ok","result"}`）。

## 界面上会调的方法（`Embedded` 与 `run_window().Api` 两边同名）

`translate` / `read_clipboard` / `copy` / `cache_info` / `cache_clear` / `history` /
`targets` / `info` / `hotkey_start` / `hotkey_stop` / `hotkey_status`

当前这一版页面用到的是 `hotkey_status` / `hotkey_start` / `hotkey_stop` / `cache_info`
（点历史项时再用 `copy`）；其余方法留着备用。

热键触发的进度/结果由后端**主动推**事件 `{"event":"hotkey","data":{...}}`：
`phase` = `state` / `step`（带 `step` 1~4、`source_text`、`translated`）/ `done`（带 `result`）/ `fail`。
页面用 `moss.on('hotkey', …)` 接，按 `step` 走四步进度条。

## 还没验的

- 端到端手点没跑过（用户会测）。缓存/剪贴板/翻译的真机行为以实际为准。

## 来历

从旧项目 **`QuickTools\pa_soft\bin\soft\fanyi`** 移植（2026-09-27）—— 那边是整包，
功能代码照抄，只把宿主接口从老 `PA_*` 换成 moss 的 `MOSS_*`。v2.0（内嵌化）另行重写了界面层。

> 2026-09-27 定了"**包里不放来源**"（`F-10` ❌：来历写这里；"是官方还是第三方装的"归宿主记账），
> 所以这段写在 `AGENT.md` 而不是 `pkg.json`。
