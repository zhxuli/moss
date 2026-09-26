# path —— 查看/管理 Windows PATH 环境变量

```bash
moss :path                      # 不带参数 = 打开界面（tkinter）
moss :path add D:\tools\bin     # 注册到【当前用户】的 PATH
moss :path add                  # 省略路径 = 注册本插件自己的目录
moss :path remove D:\old\bin    # 从【当前用户】的 PATH 移除
moss :path help                 # 打用法
```

## 这包干什么

**界面（`kind: app`）**：

- 按名字排序列出当前用户 PATH 的全部条目，本插件自己那条标绿
- 「注册自身目录 / 反注册自身目录」一键切换，旁边显示 `已注册 / 未注册`
- 「添加目录...」（文件夹选择框）、「移除选中项」（可多选）
- 把文件/文件夹**拖进窗口**即可添加它所在的目录（依赖 `windnd`）
- 「一键备份」把当前 PATH 存成一个 txt
- 「恢复备份...」两步走：先列出每个备份与当前 PATH 的差异（`+将新增` / `-将移除`），
  选中后进第二步确认，再整体覆盖；第一步还能删掉某个备份

**命令行**：`add` / `remove` / `help`（别名见 `pkg.json` 的 `params.desc`）。
省略 `[路径]` 时操作的是**插件自己的目录**（就是"把 path 这个包挂到 PATH 上"）。

## 参数

只有一个 `rest: true` 的参数 `args`：宿主把包名后面那一整串**原样**交给包，
由包自己按旧语法解析（宿主不拆词、不做引号转义）。带空格的路径请自己加引号：

| 参数 | 含义 |
|---|---|
| 留空 | 打开 tkinter 界面 |
| `add [路径]` | 注册路径；省略 = 插件自身目录。别名 `register` / `reg` |
| `remove [路径]` | 移除路径；省略 = 插件自身目录。别名 `unregister` / `del` |
| `help` | 打用法。别名 `?` / `-h` / `--help` |
| 其它 | 报「未知命令」并打用法，退出码 1 |

退出码：成功 0，失败 1。命令行结果只有 `print`（`output.mode` 是 `text`）。

## 危险点（★ 看这里）

1. **它真改系统环境变量**：直接读写注册表 `HKCU\Environment` 的 `Path`
   （值类型 `REG_EXPAND_SZ`），写完广播 `WM_SETTINGCHANGE` 让已开着的程序刷新。
2. **只动当前用户（HKCU），不动系统级（HKLM）的 PATH**，所以不需要管理员权限；
   反过来，用管理员身份跑它也还是改你自己的用户 PATH。
3. **「恢复备份」是整体覆盖**：界面上原文写着「此操作不可撤销」，覆盖前**不会**再自动备份一次。
4. **写回时是整串重拼**：条目按 `;` 重新 join，读的时候空段已被丢掉，
   所以 PATH 里的空段/多余分号会被规整掉；`add` 还会顺带去重（大小写不敏感比较）。
   PATH 里的变量（如 `%USERPROFILE%\bin`）按原样写回，不展开。
5. **不要让 AI 自动调用**：`pkg.json` 里 `ai.expose` 是 `false`、`risk` 是 `high` ——
   改 PATH 会立刻影响整台机器的命令解析，且「恢复备份」会整体覆盖。

## 数据放哪

宿主给的 `MOSS_PLUGIN_DATA_DIR`（= `user_data/state/path/`）下的
`.path_editor/path_bak/path_backup_<时间戳>.txt`。老 `PA_PLUGIN_DATA_DIR` 作兜底，
两个都没有才退回插件自身目录（直接 `python main.py` 调试时）。
备份放在 state 目录里，**重装/升级这个包不会冲掉**。

## 来历

原样搬自旧项目 `QuickTools\pa_soft\bin\cli\path\`（旧宿主里的 `pa :path`），
`main.py` 是**机械移植**：界面、备份/恢复、注册表读写、命令行语法**一字未改**。
只改了 3 处宿主管道差异：

1. 数据目录变量：`MOSS_PLUGIN_DATA_DIR` 优先，`PA_PLUGIN_DATA_DIR` 兜底，最后才插件目录
2. 参数来源：`MOSS_PKG_PARAMS` / `MOSS_ARGS` 优先，读不到才退回 `sys.argv[1:]`
   （写法照抄 `system/pkgs/exec/main.py` 的 `_moss_args`，另配一个不碰反斜杠的 `_split_args`）
3. 注释里的 `pa` → `moss`

依赖 `windnd`（拖放）和 `tkinter`，两者都在 moss 自带运行时里
（`system/runtimes/python/3.12`），用户不用装。
