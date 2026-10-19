# moss

**一个自己会长功能的软件：你不装功能，你告诉它缺什么，它长出来。**

宿主本身几乎不提供业务功能——解析命令行、找解释器、把包列表交给界面、等界面退出，就这些。
其余全在 exe 外面，以「包」的形式挂着：你可以手写、可以让 AI 写、也可以让 AI 在干活的过程中给自己现造一只手。

起因很朴素：桌面上的小工具散在十几个文件夹里，每个都得记住怎么启动。后来想明白——真正的问题是，
**我不想再为每一个新需求单独做一个软件。**

> **English TL;DR** — moss is a self-extending host for Windows. It ships no business features:
> every capability arrives as a package (a directory + `pkg.json` + an entry file, any language).
> An in-app AI agent can write new packages, and forge its own "skills" at runtime — each new hand
> needs a one-time human approval. Not yet 1.0, Windows only.

## 它跟"工具箱"不一样的地方

| | 普通工具箱 | moss |
|---|---|---|
| 加功能 | 等作者发版 | 丢一个目录进去，或者直接说一句 |
| 界面 | 每个工具一套 | 一份 HTML，既能内嵌成标签页，也能自己开窗 |
| 语言 | 焊死在一种 | python / go / shell / powershell / 现成的 exe |
| AI | 旁边开个聊天框 | 在宿主里：读契约、改包、跑验证、给自己造工具 |

## 自生长是怎么长出来的

### 一、包 —— 功能只有一个形状

一个目录 + `pkg.json` + 入口文件。放进去就能用，不用重新打包 exe。

要界面就写成网页，在 `pkg.json` 里声明 `"ui": {"embed": "ui/index.html"}`：同一份页面既内嵌进
moss 的标签页，也能 `moss :<id>` 单独开一个窗口。

### 二、技能 —— AI 给自己造的手

AI 干到一半，发现宿主没给它这个能力（截屏、量像素、解析一个怪格式……），可以**当场造一个工具**：
用同一份契约写 `pkg.json` + `run.py`，落到 `user_data/state/skill/<名字>/`。

**声明 ≠ 授权。** 造出来不等于能用：你得在「设置 → 技能」（或 `moss :skill`）点一次「允许」，
它下一次开工才进工具表。`allow / revoke / rm / promote` 这四个动作只能人做——AI 拿 `run_moss`
去调，宿主会直接拒掉。这是设计出来的闸，不是防君子。

### 三、AI 工作台 —— 会长东西的那双手

界面里的 AI 不是聊天框，是一个能动手的循环：读契约、读包、改代码、跑命令、看退出码。几条硬规矩：

- **改文件不重写整个文件** —— 只发 search/replace。同样改 3 行，输出几十 token 而不是几千；
  也不会出现"重写时悄悄丢一段"。
- **`done` 是硬闸** —— 最后一次改动之后必须有一次退出码 0 的运行，否则把话打回去继续。
  不是"模型说完成了"。
- **每一步都记 token**（`usage`）—— 把"费不费"从感觉变成数字。
- **写权限是一张清单** —— 一个目录一对「读 / 写」勾；`core/`、`moss.exe`、`moss.py`、`venv/`、
  `.git/`、`backups/` 硬锁，勾了 `*` 也写不了。

## 能干什么

```powershell
moss                  # 用法 + 包列表
moss ui               # 打开界面：包列表 / 内嵌标签 / AI 工作台 / 技能
moss m                # 在当前目录找 main.py / main.go / main.html 并跑
moss :<包> [参数]      # 跑装好的包
moss --new <id>       # 生成一个包的骨架
moss --history        # 最近跑过什么，↑↓ 选一个重跑
moss --selfcheck      # 自检：MOSS_HOME、运行时、路径对不对
moss --spec           # 当场从契约文件里读规范（唯一真相只有一份）
```

出厂包 15 个：`exec` 快捷执行、`fanyi` 快捷翻译、`img` 图片工具、`ip` 查询、`kill` 杀进程、
`mark` 目录书签、`md5` 计算、`paste` 贴边快输、`path` PATH 管理、`pip` 工具、`skill` 技能管理、
`suoluetu` 图标修复、`sync` 文件同步、`tree` 目录树、`dsh` 远程桥（在外面访问这台机器上的 DSH）。

## 为什么非要这么拆（内核最小化）

exe 里只有宿主内核，约 7 MB。界面、包、Python 运行时全在 exe 外面：

- **加功能 = 丢一个目录**，不用重编 exe。
- **改界面不用重新打包** —— 界面用自带运行时跑 `system/ui/`，那不属于任何包，也删不掉。
- **用户的地盘跟出厂件分开** —— `user_data/pkgs` 打包时整体排除；同名时高优先级遮蔽低优先级，
  低层原件保留，可对比、可还原。

## 快速开始

发行版就两样东西，放一起即可：`moss.exe` + `system/`（`user_data/` 首次运行自动创建）。
先跑 `.\moss.exe --selfcheck` 确认环境，再 `moss ui`。

从源码跑：

```powershell
venv\Scripts\python.exe moss.py ui
build.cmd                     # 打 exe；命令在 moss.py 顶部也留了一份，改要两处一起改
```

自带运行时是 Python 3.12（`system/runtimes/python`）：包不依赖用户装没装 Python、装的哪个版本。

## 目录

```
core/          宿主内核（编进 exe）：解析、找解释器、包注册表、路径、自检
system/        跟发行版一起走
  pkgs/          出厂包（只读层）
  ui/            宿主自己的界面（不属于任何包，删不掉）
  spec/          插件契约 —— 格式的唯一真相
  skills/        给 AI 看的技能手册
  ai/            技能库（宿主和 :skill 插件共用）
  runtimes/      自带 Python 3.12
user_data/     用户的地盘：自己装的包、技能、配置、运行数据（打包时整体排除）
tools/         构建和维护脚本
```

## 写第一个包（三分钟）

```powershell
moss --new hello      # 在 user_data/pkgs/hello/ 生成骨架
moss :hello           # 改完 pkg.json 和入口就能跑
```

格式只有一个规范：`system/spec/插件契约.md`（或 `moss --spec`）；操作路径看
[插件开发向导](插件开发向导.md)。要界面就照 `system/pkgs/skill/` 抄（Vue 3 + Python 后端，
一份代码两种跑法）。

## 边界（现在的样子，不是承诺）

- **Windows 单机**：不要求装服务。
- **spec 1，没到 1.0**，契约还会动。
- 契约里「密钥」那一章**宿主还没实现** —— 别指望它替你管凭据。
- 技能第一次要人点「允许」：这是设计，不是待修的 bug。

## 文档

| 想干的事 | 看哪 |
|---|---|
| 写 / 改一个包 | `system/spec/插件契约.md`、`插件开发向导.md` |
| 给 AI 加一只新手 | `system/skills/self-tool/SKILL.md` |
| 改宿主 | `core/`、`system/ui/`，先读 `AGENTS.md` |
