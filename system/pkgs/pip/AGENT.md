# pip · 给 AI 看的说明

## 一句话

管 **moss 自带 Python 运行时**（`system/runtimes/python/<ver>/`）里的第三方库。
不是 venv，不是插件的 `packages/`。

## 它不该被 AI 调

`ai.expose = false`。AI 要给某个包装依赖，走 `pkglib`（装进那个包自己的 `packages/`），
**不要**往宿主运行时里装 —— 那会影响所有 `runner: python` 的包。

## 代码结构

```
pkg.json       runner=python / entry=main.py / ui.embed=ui/index.html
main.py        三条路分流：MOSS_UI_EMBED=1 → embed.py；argv 给命令 → core.Api().cli()；空 → 界面
embed.py       stdio 上的一行一个 JSON（{id,method,params} → {id,ok,result}）
core.py        定位运行时 + 调 pip + 界面后端 + CLI
ui/            界面（index.html + app.js + style.css + moss-embed.js 垫片，无框架）
```

## 设计要点（改之前先看这几条）

1. **CLI 是透传的**：`Api.cli()` 只截住 `env / source / search / web / export / upgrade / gui`
   和 `uninstall pip` 这几种，其余 `argv` **原样**丢给 `python -m pip`（`_passthrough`）。
   pip 的子命令输出直接流到终端，退出码就是 pip 的退出码。
   ⇒ **别在这儿给 pip 已有命令重新实现一遍**，那是白写还容易过时。
   想把某个 pip 命令改行为，先问「是真需要，还是 pip 原样更好」。
2. `runtime()` —— **"管哪一套"的唯一来源**。顺序：`default.json` 的 `python`
   → 用户层 `user_data/runtimes/python/<ver>` → 系统层 `system/runtimes/python/<ver>`。
   钉的版本不存在时退回装了的版本里第一个。带 5 秒缓存。
3. `GUARD = {"pip"}` —— 卸载 `pip` 在 `cli()` 和 `start_job()` 两处都挡。
4. **界面**装 / 卸 / 升走 `start_job()` → 后台线程跑 pip、逐行收集 → 界面用 `job(id)`
   轮询。**不要**在界面回调里同步跑 pip（会卡住那一帧）。
5. `lookup()` —— 按名字查包，走 `pypi.org/pypi/<名>/json`，失败依次退
   `mirrors.aliyun.com` / `tuna`。
6. `source()` / `set_source()` —— 切源靠设 `PIP_INDEX_URL` 环境变量，**不写 pip.ini**。
   `auto` 就是一条都不设。
7. **界面（ui/）的设计约束**：这是 Operate 型界面（设计服务于任务）。改之前先读
   `frontend-design` 技能的 `craft-floor` 和 `operate` 两份。已定的几条：
   - 一个字体家族（系统 sans），mono 只给包名/版本/命令行这类真实数据
   - accent 只给主操作、当前选中；amber 只给「有新版」
   - 行高固定 32px、版本列宽度固定（`--act-w`），操作出现时布局不跳动
   - 已装页操作**指到版本号才出现**（需求明确要求的）；查包页按钮常亮（就几条结果）
   - 加载用骨架屏（`.sk-row`），不用「正在加载」文字
   - 过渡 120–140ms，一次只有一个作者性动效
8. `delete_export()` —— 删导出的 requirements。三道保护：只要 `.txt/.in`、不许删
   包目录和运行时里的文件、空路径直接拒。
9. **性能：别为了拿本地数据去起 pip 子进程。** 这套界面是 Operate 型，
   首屏越快越好。实测（这台机器）：
   ```
   pip list --format=json      532 ms   ← 每次都要启动一个 Python + import pip
   importlib.metadata          120 ms
   扫 site-packages 的 *.dist-info  0.3 ms   ← 现在用的
   pip --version               389 ms   ← 改成 importlib.metadata.version("pip")，0.7ms
   起子进程问 Python 版本       36 ms    ← 改成直接读 sys.version，0ms
   ```
   `installed()` 直接扫目录名（`名字-版本.dist-info` 本身就是索引），
   并用 `site-packages` 的 mtime+条目数当缓存指纹 —— 装了包指纹就变，不会读到旧数据。
   `env()` 一次带回「环境 + 已装列表」，前端启动只发一个请求（实测 116ms 出 88 行）。
   **改这里之前先量一遍**，别把 1ms 的东西换成 500ms 的。
10. 只用标准库。这套代码自己就跑在它管的那个解释器里，不能假定有 requests。

## 为什么没有关键词搜索

试过的三条路都不可用：

| 路子 | 实测结果 |
|---|---|
| `pip search` / XML-RPC `search()` | `Fault -32500: PyPI no longer supports 'pip search'` |
| `pypi.org/search/?q=` 网页 | 200 但是 3036 字节空壳，`package-snippet` 为 0（JS 渲染） |
| 全量包名表（`/simple/` PEP 691 JSON） | 能用，但要下 14MB 存本地 —— 为搜个包不值，已删 |

所以：知道名字就精确查，不知道就开官方网页。**别再改回建本地索引。**

## 校验过的方式

```bash
moss :pip --version              # pip 26.2.1 ... (python 3.12)   ← 证明透传
moss :pip --help                 # pip 官方帮助
moss :pip list --format=json     # pip 原生 JSON 输出
moss :pip list --outdated --format=columns
moss :pip cache dir              # 冷门子命令也通
moss :pip index versions requests
moss :pip show zzz-xxx           # 退出码 1 原样传出来
moss :pip install six            # 实时输出
moss :pip uninstall -y pip       # 被挡，退出码 1
moss :pip search requests        # 精确查，带已装版本
moss :pip source                 # 列源 + pip 自己的配置
moss :pip export                 # 87 行
```

内嵌协议：`MOSS_UI_EMBED=1` 真起进程，`env/installed/lookup/source/web_search/
open_dir/export/outdated/start/job` 全 `ok:true`，`cli` 和乱写的名字回「没有这个方法」。
