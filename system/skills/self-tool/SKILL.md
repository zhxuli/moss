---
name: self-tool
description: 你缺一只手、想自己造一个的时候读它（技能 = 一个包：写到哪、pkg.json 怎么写、写完要用户点「允许」）
---
# 给自己造一只"手"（技能）

**什么时候该用**：你需要一个**宿主没给你的能力**，而且**这次任务里要反复用**它 ——
比如截屏、截某个窗口、量一张图的像素、解析某个格式、反复查一个本地接口。
（一次性的活别造技能，直接写脚本进你的包就行。）

**造出来的东西谁看得见**：**插件页里看不见**（它不住 `user_data/pkgs/`）。
它在「设置 → 技能」…就是 `moss :skill` 那个管理器界面里，用户能看到、能允许、能删、能转成插件。
所以**别往 `user_data/pkgs/` 里塞** —— 那里是面向用户的插件目录。

## 核心一句话：技能就是一个包

跟插件**一字不差**：`pkg.json` + 入口文件。区别只有三处：

| | 插件 | 技能 |
|---|---|---|
| id | `md5`（小写字母开头） | **同一规格**（`shot`） |
| 住哪 | `user_data/pkgs/<id>/` | `user_data/state/skill/<id>/` |
| 谁批准 | 装了就归用户 | **第一次要用户点一次「允许」** |

**不需要任何前缀**：技能不走包解析那条路（入口是 `moss :skill <动词> <名字>`），
名字跟某个插件一样也互不干扰。

## 写到哪

```
user_data/state/skill/<名字>/pkg.json     ← 清单（照契约写：spec("pkg.json")）
user_data/state/skill/<名字>/run.py       ← 入口（pkg.json 的 entry.file 指过来）
user_data/state/skill/<名字>/icon.svg     ← 图标（列表里那个彩色图标；不写就一个默认的）
user_data/state/skill/<名字>/AGENT.md     ← **这只技能自己的说明书**（`moss :skill doc <名字>` 打它）
（同目录还能放别的文件，入口里能 import 它们）

★ 预制/出厂技能：要随 moss 发行版一起打包、出厂默认就允许，写到 system/pkgs/skill/builtin/<名字>/（同名 user_data 技能会覆盖它）。AI 自己现造的手仍然写 user_data/state/skill/<名字>/。
```

## pkg.json 的最小样子

```jsonc
{
  "spec": 1,
  "id": "shot",                   // 必须跟目录名一样（小写字母开头）
  "kind": "task",                 // **必须 task**（app 会开窗，AI 的手不该开窗）
  "version": "1.0.0",
  "name": { "zh-CN": "截屏" },
  "desc": { "zh-CN": "截屏：整个屏幕或某个窗口，存成 png 并把路径回给我" },
  "runner": "python",             // 走 system/runners.json 那张表（python/go/shell/powershell/exe）
  "entry": { "file": "run.py" },
  "params": [                     // 每个参数的 desc 会出现在你的工具表里 —— 写清楚
    { "name": "target", "type": "string", "required": false, "desc": "窗口标题关键词" }
  ],
  "ai": {
    "expose": true,               // 声明"我能被 AI 调"（技能目录里按规矩写 true）
    "why": "为什么要造它 / 它解决了什么问题",   // ★ 用户在详情页看到的就是这句
    "risk": "low",
    "timeout": 60,                // 单次最多跑多久（默认 60，最多 300）
    "examples": [ { "args": { "target": "记事本" } } ]
  }
}
```
`params` 的 `type` 直接用插件契约那几种（`string` / `int` / `float` / `bool`）——
你在工具表里看到的参数类型就是照它生成的。

## 入口的契约（跟插件一样）

* 启动：按 `runner` 表来（python 走自带运行时 + `system/bootstrap.py` 垫片，
  所以**同目录的兄弟文件能 import**）。
* **参数**：`stdin` 一行 JSON，同时也在环境变量 `MOSS_PKG_PARAMS` / `MOSS_TOOL_ARGS` 里。
* **回话**：`stdout` 的文本**原样**回给你（截尾 60 行 / 4000 字）。
  ⇒ **别打印进度、别打印调试信息**；要调试就写 `stderr`。
* 退出码非 0 会标一句（照样把 stdout 给你）；超过 `ai.timeout` 会被杀。
* `cwd` = 技能目录；`MOSS_PLUGIN_DATA_DIR` = 这只技能自己的数据目录（要存东西就存那儿）。

最短能跑的样子：

```python
import json, sys
args = json.loads(sys.stdin.read() or "{}")
print("收到：%s" % json.dumps(args, ensure_ascii=False))
```

## 硬规矩（踩了会挨打）

1. **写完不算生效 —— 要跟用户说清楚**：工具表是**这次任务开工那一刻定死**的，
   你这一步新造的技能**这一次跑用不了**，要**用户点一次「允许」**、下一次跑才进表。
   所以：要么先把它写好、告诉用户"我造了一只 X，你在技能里点一下允许，我下次就能用"，
   要么先用别的手段把这次任务干完。
2. **`ai.why` 一定要写**：用户点开详情看的就是"当初为什么造它"。
   没写的话详情页会空着，而且列表里会挂着一条提醒。
3. **`icon.svg` 画一个 + `AGENT.md` 写一份**：列表是**图标墙**（像桌面那样）；
   说明书给 `moss :skill doc <名字>` 用（人和 AI 都靠它知道怎么用你这只手）。
   图标里**别写 `<script>`、别写 `on…=`** —— 那种会被当成"没有图标"洗掉（界面要把它画出来）。
4. 你**改了** `pkg.json` / 入口 / 图标，**授权会自动作废**（要用户重新允许）。改完说一声。
5. 别拿它当"绕开写权限"的后门：这只手能碰的文件，跟你在这次任务里能碰的**一样多**
   （你自己的包 + `user_data/state/skill/**`）。要动出厂件 / 宿主，那**必须由人来做**。
6. 依赖：自带运行时里已经有的库可以直接用（`PIL` / `pyautogui` / `requests` / `numpy` …）。
   缺少的库不要直接判定不能用：用 pkglib 技能装到目标包自己的 packages/，入口最前面 import deps；pkglib 还没进工具表就让用户先允许。
   不要往宿主运行时或 venv 里 pip install；第三方库必须跟目标包走。
7. **别用 `run_moss` 调 `:skill allow / rm / promote`** —— 那几个动词是**用户决定**的事，
   宿主会直接拒掉（这是设计好的闸，不是提示）。
8. 相关命令（**都不会开窗口**，随便调）：`":skill"` 用法+列表、`":skill show <名字>"`、
   `":skill doc <名字>"` 看说明、`":skill run <名字> k=v …"` 跑一次。
