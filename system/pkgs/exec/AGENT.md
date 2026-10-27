# exec · 给 AI 看的说明

> 本包**从老项目移植**（`QuickTools/pa_soft/bin/soft/exec`），功能代码照抄，
> 只把"跟宿主打交道"的接口从老 `PA_*` 换成 moss 的 `MOSS_*`（老变量仍是兜底）。
> 数据目录：`MOSS_PLUGIN_DATA_DIR`（= `user_data/state/exec/`）。

## 干什么
多语言命令脚本管理器（Apple 风格 WebView 界面，可内嵌进 moss / 也能自己开窗）

## 怎么调
```
moss :exec
```
| 参数 | 类型 | 说明 |
|---|---|---|
| `args` | string | 不填 = 打开管理器；list = 列出命令；<别名> [参数] = 直接执行 |

## 形态
- `kind = app`（GUI 程序），runner = `python`，入口 `main.py`
- 它是**交互式界面**，不是给 AI 自动调用的工具 → `ai.expose = false`

### 一份界面两种跑法（`V-48` / `V-222`）
| 怎么起 | 走哪条路 | 代码在哪 |
|---|---|---|
| 在 moss 的「界面」选项卡里**内嵌** | 宿主给 `MOSS_UI_EMBED=1`，把它起成**后端进程**：不开窗口，在 stdin/stdout 上说 JSON 行 | `embed.py`（协议）+ `ui/moss-embed.js`（页面侧垫片） |
| 独立窗口 | pywebview 开一扇窗 | `gui_web.py` |
| 本机没 pywebview / WebView2 | tkinter 基础界面 | `gui_tk.py` |

**★ 两条路共用同一份 `gui_web.Api`** —— 所以 `Api` 的每个方法都只收**一个 dict**
（`params`），字段按名字取。垫片两种环境都只传一个参数（内嵌是把
`{"id", "method", "params"}` 送进后端进程的 stdin），**别改回位置参数**，一内嵌就散架。
页面那侧的桥只有 `ui/src/api.js` 一处。

**内嵌协议**（一行一个 JSON）：
```
宿主 → 我们： {"id": 1, "method": "cmd_list", "params": {}}
我们 → 宿主： {"id": 1, "ok": true, "result": {…}}
```
★ 规矩：**stdout 只许出 JSON 行**。日志走 `_log()`（stderr）—— 宿主对"不是 `{` 开头"的行
会当输出收进命令行（无害），但**把一条 JSON 拆成两行就真把协议撕了**（别用多行 print）。

**怎么验**（改完先跑这两条）：
```bash
.\system\runtimes\python\3.12\python.exe tools\exec内嵌探针.py   # 内嵌后端：协议+业务 27 条
python tools\包界面检查.py exec                                  # 这一页还画得出来吗
python tools\界面预览.py exec-ui                                 # 宿主→iframe→后端 整条链
```

## 副作用
- 声明能力：`{"run": ["python"], "net": []}`
- 写文件：写到 `MOSS_PLUGIN_DATA_DIR` 下（不写自己包目录 —— 重装包会冲掉）

## 还没验的
- ~~迁移后没有跑过~~ —— 2026-10-03 起：命令行、独立窗口、**内嵌**三条路都验过了
  （内嵌那两条见上面「怎么验」）；tkinter 兜底那条只在"缺 pywebview"时才会走到，没单独验。

## 来历

从旧项目 **`QuickTools\pa_soft\bin\soft\exec`** 移植（2026-09-27）—— 那边是 整包（旧宿主里是有 WebView 界面的插件）。
**功能代码照抄**，只改了宿主差异：数据目录 `MOSS_PLUGIN_DATA_DIR`、参数来源
`MOSS_PKG_PARAMS` / `MOSS_ARGS`（读不到才退回 `sys.argv`）、用户可见文案里的 `pa` → `moss`。

> 这一段原来写在 `pkg.json` 的 `origin.from` 里。2026-09-27 定了"**包里不放来源**"
> （`F-10` ❌：来历写这里；"是官方还是第三方装的"归宿主记账，包自证不可信），
> 所以挪到 `AGENT.md`。
