# mark —— 目录书签

```bash
moss :mark              # 把当前目录记成书签（回车用目录名当标题）
moss :mark list         # 列出全部（ls / all 同义）
moss :mark 项目         # 按标题/路径找：精确匹配直接切，模糊多个就菜单选
moss :mark --gui        # 图形界面编辑（tkinter：改标题/路径、删除）
```

## 数据

`user_data/state/mark/directories.json`，形如
`[{"title": "项目", "path": "D:\\work\\proj"}, ...]`。

## 「切过去」的真实行为

它在**子进程里** `chdir` 然后起一个新的 shell —— 所以**不会**改变你当前 PowerShell 的目录。
想切当前窗口的目录，用宿主自带的 `moss cd`（注入到父 shell 里，不留回显）。
这是旧项目的行为，原样保留，没有改。

## 参数

一个 `rest: true` 的参数 `args`，但**只取第一个词**（照旧行为，后面的忽略）：
关键字 / `list` / `ls` / `all` / `--gui` / `-g` / `gui`。

## 来历

原样搬自 `QuickTools\bin\cli\mark\main.py`（旧宿主 `pa :mark`），只改了参数来源。
依赖 `questionary`（菜单）与 tkinter（`--gui`），都在自带运行时里。
