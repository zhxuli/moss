# moss

**别再给每个需求做一个软件了。**

手机吃掉相机、地图、闹钟，靠的不是功能更多，是**一个壳**——一部手机装下九个 App，图标排一屏，点一下就开。
moss 对桌面上的「小软件」做的是同一件事：那个文件夹，**变成插件列表里的一行**。

> Windows 10 / 11 · 免费 · 解压即用 · 自带 Python 3.12 · 宿主内核约 7 MB

> **English TL;DR** — moss is a Windows host that deliberately ships almost no features. Everything
> arrives as a package (a directory + `pkg.json` + an entry file, any language), and an in-app AI agent
> can write new ones — including forging its own "skills" at runtime, each behind a one-time human
> approval. One shell, one UI, one history, one undo. Not 1.0 yet; Windows only.

## 一张图说清这层对应

**手机吃掉的是设备。**

| 九件设备 | → | 一部手机 → 九个 App |
|---|---|---|
| 相机 · 地图 · 闹钟 · MP3 · 日历 · 计算器 · 电话机 · 笔记本 · 手电筒 | → | 一个桌面，图标排一屏，点一下就开 |

**moss 吃掉的是文件夹。**

| 九种「小软件」的死法 | → | 一个 moss → 九行插件 |
|---|---|---|
| 「新建文件夹(3)」· `tool_v2.py` · `脚本2.py` · `final_final.py` · 一条启动命令 · 一套虚拟环境 · 打包出来的 exe · `readme.txt` · 桌面快捷方式 | → | 一个窗口，列表一行，点一下就开 |

两列得的是同一种病：**每样东西都得单独找一个地方放、单独记一种打开方式。**
区别只有一点——右边这一列不是「文件」，是「功能」。文件要你管理（放哪、叫什么、怎么启动），
功能只要你用（**列表里点一下**）。

## 程序写完了，你还要想四件事

用 Claude Code、Codex、DSH 这类工具，代码是能写完的。写完那一刻，麻烦才开始：你手上多了一个文件夹，
和四个没人替你回答的问题。

| 问题 | 一个独立小程序 | 长在 moss 上的插件 |
|---|---|---|
| **Q1 放哪？** D 盘还是 C 盘、桌面还是深三层 | 每次现想一遍 | 插件进 `user_data/pkgs`，你只看见列表里的一行 |
| **Q2 叫什么？** tool？脚本2？新建文件夹(3)？ | 三个月后自己都忘了 | 名字就是那一行，列表里认字就行 |
| **Q3 怎么开？** 记路径、记命令、先进哪个虚拟环境 | 换台机器、清次缓存就全丢 | 双击 moss 就有全部功能，不用碰命令行 |
| **Q4 要不要打包？** pyinstaller、图标、依赖、误报 | 本来只想加个小功能 | 一个目录 + `pkg.json` 丢进去就是插件，任何语言 |

moss 的答案是：**一件都不用想。** 因为它根本不产出「另一个文件夹」——它产出插件，长在宿主身上。

## 为什么这么拆：寄生，不是并列

手机之所以舒服，是因为功能长在机身里，不是散在抽屉里。

- **寄生，不是并列** —— 插件不是「另一个软件」，它挂在宿主上干活：共用一个窗口、一套设置、一份历史。
  界面里甚至有**寄生模式**和**自动运行**，可以让它跟系统贴得更紧。
- **一点即用** —— 左边一列插件，右边是它的详情、参数、命令、文件和 AI；想带参数就敲进输入框回车。
- **一套壳，装得下任何东西** —— 宿主只有约 7 MB，自带 Python 3.12 运行时；插件可以是 python、go、
  shell、powershell，甚至是你现成的 exe，不用管用户装没装环境。

| | 一个个独立的小程序 | 寄生在 moss 上的插件 |
|---|---|---|
| 入口 | 先开文件夹，再找文件，可能要敲命令 | **双击 moss → 列表 → 点一下** |
| 界面 | 每个工具一套，风格各异 | 同一套界面：既能内嵌成标签页，也能自己开窗 |
| 加功能 | 再做一个软件、再记一条启动方式 | 丢一个目录进去，或者直接说一句让它写 |
| 数据 | 散在各处，互不相通 | 共用宿主的历史、设置、快照 |
| 改坏了 | 重装、翻备份、到处找旧版本 | 快照一键退回 |
| AI 在哪 | 在旁边开个浏览器标签页 | 在宿主里：读契约、改插件、跑验证、给自己造工具 |

## 缺什么，说一句就行

出厂插件不够用的时候，不必等作者发版。

### 一、插件 —— 功能只有一个形状

一个目录 + `pkg.json` + 入口文件。放进去就能用，不用重新打包 exe。

要界面就写成网页，在 `pkg.json` 里声明 `"ui": {"embed": "ui/index.html"}`：同一份页面既内嵌进
moss 的标签页，也能 `moss :<id>` 单独开一个窗口。

### 二、技能 —— AI 给自己造的手

AI 干到一半，发现宿主没给它这个能力（截屏、量像素、解析一个怪格式……），可以**当场造一个工具**：
用同一份契约写 `pkg.json` + `run.py`，落到 `user_data/state/skill/<名字>/`。

**声明 ≠ 授权。** 造出来不等于能用：你得在「设置 → 技能」（或 `moss :skill`）点一次「允许」，
它下一次开工才进工具表。`allow / revoke / rm / promote` 这四个动作只能人做——AI 拿 `run_moss`
去调会直接被拒。这是设计出来的闸，不是防君子。

### 三、AI 工作台 —— 会长东西的那双手

界面里的 AI 不是聊天框，是一个能动手的循环：读契约、读插件、改代码、跑命令、看退出码。几条硬规矩：

- **改文件不重写整个文件** —— 只发 search/replace。同样改 3 行，输出几十 token 而不是几千；
  也不会出现「重写时悄悄丢一段」。
- **`done` 是硬闸** —— 最后一次改动之后必须有一次退出码 0 的运行，否则把话打回去继续。
  不是「模型说完成了」。
- **每一步都记 token**（`usage`）—— 把「费不费」从感觉变成数字。
- **动手前先存快照** —— 改坏了 `moss --snap revert` 一键退回。
- **写权限是一张清单** —— 一个目录一对「读 / 写」勾；`core/`、`moss.exe`、`moss.py`、`venv/`、
  `.git/`、`backups/` 硬锁，勾了 `*` 也写不了。

## 出厂插件（12 个）

`exec` 快捷执行 · `fanyi` 快捷翻译 · `img` 图片工具 · `kill` 杀进程 · `mark` 目录书签 ·
`paste` 贴边快输 · `path` PATH 管理 · `skill` 技能管理 · `tree` 目录树 · `h` 历史快捷运行 ·
`github` GitHub 可视化助手 · `dsh` 远程桥（在外面访问这台机器上的 DSH）

它们住在 `system/pkgs/`（出厂层，升级整体替换）。你自己的包住在 `user_data/pkgs/`（用户层，
升级一个字都不动，**而且同名时压住出厂层**——低层原件保留，可对比、可还原；`moss --layer` 可搬层）。

## 快速开始

发行版就两样东西，放一起即可：`moss.exe` + `system/`（`user_data/` 首次运行自动创建）。

1. 解压到一个**固定目录**（比如 `D:\soft\moss`）。别放 `Program Files`（写不了 `user_data`），
   也别放桌面 / 下载目录（升级是整包覆盖，这两处容易被清理工具扫掉）。
2. 双击 `moss.exe` —— 没有控制台时直接开界面。想先体检：`moss.exe --selfcheck`。
3. 想用 AI 就在「设置 → AI」填一次接口（base_url / key / model）。出厂插件不填也能用。

```powershell
moss                  # 用法 + 包列表
moss ui               # 打开界面：包列表 / 内嵌标签 / 文件管理 / AI 工作台 / 技能
moss m                # 在当前目录找 main.py / main.go / main.html 并跑
moss :<包> [参数]      # 跑装好的包，例如  moss :img webp 60% 1200 *.png
moss --new <id>       # 生成一个能跑的包骨架
moss --history        # 最近跑过什么，↑↓ 选一个重跑
moss --snap list      # 看版本快照
moss --selfcheck      # 自检：MOSS_HOME、runner 表、运行时、cd 注入
moss --spec           # 当场从契约文件里读规范（唯一真相只有一份）
```

从源码跑：

```powershell
venv\Scripts\python.exe moss.py ui
build.cmd                     # 打 exe；命令在 moss.py 顶部也留了一份，改要两处一起改
```

自带运行时是 Python 3.12（`system/runtimes/python`，不进 git，用 `tools/拉取运行时.py` 恢复）：
插件不依赖用户装没装 Python、装的哪个版本。

## 目录

```
core/          宿主内核（编进 exe）：解析、找解释器、包注册表、路径、自检
system/        跟发行版一起走
  pkgs/          出厂包（只读层，12 个）
  ui/            宿主自己的界面（不属于任何包，删不掉）
  spec/          插件契约 —— 格式的唯一真相
  skills/        给 AI 看的技能手册
  ai/            技能库（宿主和 :skill 插件共用）
  runtimes/      自带 Python 3.12
user_data/     用户的地盘：自己装的包、技能、配置、快照、运行数据（不进 git）
tools/         构建和维护脚本
```

## 写第一个插件（三分钟）

```powershell
moss --new hello      # 在 user_data/pkgs/hello/ 生成骨架
moss :hello           # 改完 pkg.json 和入口就能跑
```

格式只有一个规范：`system/spec/插件契约.md`（或 `moss --spec`）；操作路径看
[插件开发向导](插件开发向导.md)。要界面就照 `system/pkgs/skill/` 抄（Vue 3 + Python 后端，
一份代码两种跑法）。

## 边界（现在的样子，不是承诺）

- **只支持 Windows 10 / 11 单机** —— 不要求装服务，也还没做 macOS / Linux。
- **插件契约还是 spec 1，没到 1.0** —— 格式还会变，以 `moss --spec` 为准。
- **契约里「密钥」那一章宿主还没实现** —— 别指望它替你管凭据。
- **软件免费，AI 要自己填接口** —— 不订阅、无内购；模型费用直接付给你选的服务商
  （DeepSeek / OpenAI / Kimi / 通义 / 智谱 / 硅基流动 / 本地 Ollama 都认识）。
- **技能第一次要人点「允许」** —— 这是设计，不是待修的 bug。
- **没有代码签名** —— Windows 会提示「未知发布者」，点「更多信息 → 仍要运行」。

## 文档

| 想干的事 | 看哪 |
|---|---|
| 装、用、常见问题 | [`使用说明.txt`](使用说明.txt) |
| 写 / 改一个插件 | [`system/spec/插件契约.md`](system/spec/插件契约.md)、[`插件开发向导.md`](插件开发向导.md) |
| 给 AI 加一只新手 | `system/skills/self-tool/SKILL.md` |
| 改宿主 | `core/`、`system/ui/`，先读 [`AGENTS.md`](AGENTS.md) |
| 看它到底长什么样 | [MOSS 宣传片（B 站）](https://www.bilibili.com/video/BV1J8xt62E6R/) |

## 许可证

[MIT](LICENSE)。第三方前端资源（Vue 3、xterm.js、highlight.js、lucide）各自的许可见
`system/ui/vendor/README.md` 与同目录下的 `*-LICENSE.txt`。
