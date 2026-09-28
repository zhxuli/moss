# moss

> **苔藓**：贴着表面悄悄生长、慢慢铺开 —— Windows 上一个「常驻在身边、会自己长新功能」的效率中枢。
> 现状：**单机版**，v1 只支持 `go` / `python` / `html` 三种插件（先跑通，再逐个回填）。

moss 是**一个启动器 + 插件宿主**。整套东西就是 `moss.exe` + 一个 `system/` 文件夹，没有安装程序、不写注册表。

```powershell
moss                     # 用法 + 列出所有包（直接敲它就行）
moss m                   # 在当前目录（及向上几层）找 main.py / main.go / main.html 并运行
moss b/m                 # 先进 b 开头的子目录，再找 m 开头的
moss :md5 abc            # 跑名为 md5 的包（":" 前缀 = 包命名空间）
moss :img webp 60% *.png # 包自己解释参数（rest 型参数）
moss ~name               # 后台脱离运行，不占住当前控制台
moss --history           # 最近的启动记录，方向键选、回车再跑一次
moss -h                  # 完整用法
moss --selfcheck         # 自检：安装根 / runner 表 / 包 / 自带运行时 / 配置
```

> 不带前缀的**裸名默认当路径**处理（`moss m` = 找文件）。如果你主要用途是「跑装好的包」，
> 打开 `user_data\config.toml` 把 `plugin_mode` 留空、`path_mode` 填 `":"` —— 于是 `moss img` 直接跑包。
> 那个文件是**带注释的 TOML**，每一项干什么、怎么改，打开就知道。

## 目录里都是什么

| 路径 | 是什么 | 进 git 吗 |
|---|---|---|
| `moss.exe` | 打包产物（由 `core/` 编译而成，**构建出来的**） | ❌ 不进 |
| `core/` | 内核：解析算法 / 执行引擎 / 内核协议 | ✅ |
| `system/` | 出厂件：内置包、自带运行时、插件契约、runner 表 | ✅ |
| `system/runtimes/` | 自带 Python 运行时（181 MB / 7863 个文件） | ❌ 不进，用脚本拉 |
| `system/pkgs/<id>/` | 内置包，每个包一个 `AGENT.md` | ✅ |
| `user_data/` | **你的数据**：用户包、状态、历史、`config.toml` | ❌ 不进 |
| `tools/` | 构建与维护脚本 | ✅ |
| `设计与决策.md` | 唯一设计文档（宿主级决策台账） | ✅ |
| `venv/` | 构建用的 Python 环境（nuitka） | ❌ 不进 |

## 日常同步（就这 4 条）

```powershell
cd D:\python\two\moss
git status                                  # 看改了什么
git add -A
git commit -m "这次改了什么"                 # 中文说明，一行写清
git push
```

## 快照：怎么看清单、怎么回到某一个

**每一个 commit 就是一个快照。**（人类可读的对应清单是 `设计与决策.md` 的「附录 A · 变更记录」，第 N 版 ↔ commit 大致一一对应。）

```powershell
git log --oneline              # 一行一个快照，最新的在最上面
git log --oneline -20          # 只看最近 20 个
git log --oneline -- core/     # 只看碰过 core/ 的快照
git show 8970190               # 某个快照具体改了什么（哈希写前 7 位就够）
```

网页上也能看：`https://github.com/zhxuli/moss/commits/main`

### 回到某个快照

| 你想要的效果 | 敲什么 | 说明 |
|---|---|---|
| 未提交的改动不要了，回到最后一个快照 | `git restore .` | 最常用。只丢**没提交**的改动 |
| 从旧快照里**只取回一两个文件** | `git checkout 8970190 -- core/cli.py` | ★ 最安全。之后照常 `git commit` 即可 |
| 整体退回某个旧快照，**连历史一起退** | `git reset --hard 8970190` | 之后那些提交在本机就没了（想连 GitHub 一起退再加 `git push --force-with-lease`） |
| 整体退回，但**保留历史**（推荐，能再退回来） | `git revert 8970190` | 生成一个「反向提交」，不重写历史，直接 `git push` |
| 想先看看旧快照长什么样 | `git checkout 8970190` | 进入游离状态看代码；回主线的命令是 `git switch -` |

> ⚠️ **恢复快照不会带回这三样**（它们不在 git 里）：`moss.exe`（构建产物）、`system/runtimes/`（181 MB）、`user_data/`（你的包/状态/历史/配置）。
> 好消息也是同一件事：`git reset --hard` **碰不到 `user_data/`** —— 你的数据不会被 git 操作删掉。

## 换台机器 / 重装系统后怎么恢复

```powershell
git clone https://github.com/zhxuli/moss.git D:\python\two\moss
cd D:\python\two\moss
py -3.12 -m venv venv                                  # 必须 3.12（nuitka 不支持 3.13+MinGW）
.\venv\Scripts\python.exe -m pip install nuitka
.\venv\Scripts\python.exe tools\拉取运行时.py          # 拉 181 MB 自带运行时（默认从旧项目 runtime 复制）
.\venv\Scripts\python.exe tools\build.py               # 出 moss.exe（约 1~2 分钟，6.3 MB）
.\moss.exe --selfcheck                                 # 自检
```

`user_data\` 不在 git 里 —— 它单独备份/复制过去就行。

## 想了解设计 / 想加一个包

| 想知道 | 看哪 |
|---|---|
| 宿主怎么设计、哪些定了哪些没定 | `设计与决策.md`（平时只看**第一部分 · 决策台账**） |
| 某个包怎么用、有什么坑、从哪来 | `system/pkgs/<id>/AGENT.md` |
| 包格式与宿主契约（怎么写一个包） | `system/spec/插件契约.md`，或直接 `moss --spec` |
| 生成一个能跑的包骨架 | `moss --new <id>`（生成到 `user_data\pkgs\<id>\`） |

改 `core/` 或 `moss.py` 要重新打包（`tools\build.py`，打包前先关掉正在跑的 `moss.exe`）；
改包、改 `system/pkgs/` 里的东西**不用重新打包**，直接生效。
