# bmi —— BMI 计算器（**示例包**：带界面的包该怎么写）

**这个包是拿来当样板的，不是拿来用的工具。** 想写一个"带界面"的包？照这个目录抄。

一句话：**一份网页界面（Vue 3），两种跑法** ——

```bash
moss :bmi              # 不带参数：它自己开一个窗口（不依赖 moss 的界面）
moss ui → 选它 → 运行    # 或者：内嵌进 moss 的「界面」选项卡里跑
```

两边的**界面代码是同一份**（`ui/index.html`），靠 `ui/moss-embed.js` 这个垫片自动分流；
**业务（BMI 怎么算、时间是多少）全在 Python 那边**，前端只负责显示。

## 目录里都是什么

| 文件 | 干什么 |
|---|---|
| `pkg.json` | 声明。关键是 `"ui": {"embed": "ui/index.html"}` —— **有它才有「界面」选项卡** |
| `main.py` | 后端 + 两种模式的入口（见下） |
| `ui/index.html` | 界面骨架（引 Vue、引垫片、引 app.js） |
| `ui/app.js` | Vue 3 应用：`moss.call(...)` 拿数据、`moss.on('time')` 接后端推的事件 |
| `ui/moss-embed.js` | **垫片**：内嵌时走 postMessage，独立窗口时走 pywebview 的 js_api |
| `ui/style.css` | 样式（就是个普通网页，想怎么长怎么长） |
| `ui/vendor/vue.global.prod.js` | Vue 3 **本地**放着（离线也要能跑，别引 CDN） |

## 后端那两种模式（`main.py`）

| | 独立窗口（`moss :bmi`） | 内嵌（moss 里点「运行」） |
|---|---|---|
| 怎么区分 | 环境里**没有** `MOSS_UI_EMBED` | 宿主机注入 **`MOSS_UI_EMBED=1`** |
| 干什么 | `webview.create_window(url=…, js_api=Api())` | **不开窗口**，在 stdin/stdout 上说 JSON 行 |

内嵌模式的协议（**一行一个 JSON 对象**，`{` 开头的才算消息；宿主横幅是 `[` 开头，不当消息）：

```jsonc
{"id": "r1", "method": "bmi", "params": {"height": 175, "weight": 70}}
{"id": "r1", "ok": true,  "result": {"bmi": 22.86, "level": "正常"}}
{"event": "time", "data": {"text": "20:08:53"}}          // 主动推，没有 id
```

## 三个坑（写完一定要自查；都实测踩过）

1. **JS 桥的方法要收得下那一个参数**：界面里 `moss.call('now', {})` → Python 那边是
   `now({})`；写 `def now(self):` 就 `TypeError: takes 1 positional argument but 2 were given`。
   一律 `def now(self, params=None):`。
2. **别把 `window` 挂成 `js_api` 实例的属性**：pywebview 生成桥时要遍历这个对象的属性，
   挂上去**整个桥会失效**（方法列表变空、页面全调不通），控制台还会刷一屏
   `Empty.Empty.Empty…: maximum recursion depth exceeded`。要拿窗口就用**闭包**（本包里
   `ticker()` 就是这么干的）。
3. **想证明"是 Python 在干活"就 `print`**：内嵌时这些行进 moss 的「命令行」那一页，
   独立窗口时进控制台。本包每个方法都打了一行（`[bmi] Python 算完：175 cm / 70 kg → BMI 22.86（正常）`），
   每秒推时间那次**每 10 秒**才说一声（别刷屏）。

## 想改这个包

- **加一个按钮/字段**：改 `ui/app.js`（Vue）+ 需要的话在 `main.py` 的 `Embedded` 与
  `run_window().Api` **两边各加一个同名方法**（两个模式的业务应当共用同一个函数，
  像 `calc_bmi` / `now_payload` 那样）。
- **换个框架**（React / 原生 JS 都行）：只要还引 `moss-embed.js`、还走 `moss.call` /
  `moss.on`，宿主那边一个字都不用改。
- **界面文件改了**：不用重打包，界面顶栏那颗「重新加载这一页」按钮一点就见效
  （本地服务带 `no-store`）。

## 来历

2026-09-29（第 104 版）为"插件界面能不能内嵌"这件事（`V-47`）现写的试点包，
按你的要求做：前端后端通信、BMI 与时间都在 Python、Vue 3、命令行与 moss 界面两种跑法、
切走选项卡不关。规范在 `system/spec/插件契约.md` §4.2，`moss --spec` 随时打印。
