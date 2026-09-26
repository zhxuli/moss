# tree —— 目录树

```bash
moss :tree                  # 当前目录
moss :tree docs 2           # 只看 docs，深度 2
moss :tree -a               # 显示隐藏文件
moss :tree -venv,dist       # 额外忽略 venv、dist（逗号分隔）
```

## 行为

- 内置忽略：`venv` `.venv` `__pycache__` `.git` `.vscode` `.idea` `node_modules` `.ds_store`
- 往上找最近的 `.gitignore` 并**照它的规则过滤**（只支持基础写法：`/开头`、`目录/`、`*` 通配；`!` 取反不认）
- 单个目录超过 100 项 → 直接标 `... (Skipped large directory: N items)` 不展开
- 目录里若有 `.hide` 文件，或目录名含 `hide`，整棵子树不显示
- 只读，不改任何东西

## 参数

一个 `rest: true` 的参数 `args`：宿主把包名后面的词**全部**原样交给它，由包自己解析
（数字 = 深度；`-a`/`--all` = 显示隐藏；`-xxx,yyy` = 追加忽略名；其它 = 目标子目录）。

带空格的路径要用引号：`moss :tree "my docs"`（宿主不负责拆词，见文档 `CL-10`）。

## 来历

原样搬自 `QuickTools\bin\cli\tree\main.py`（旧宿主 `pa :tree`），
画树与过滤逻辑一字未改，只把参数来源改成读 `MOSS_PKG_PARAMS` / `MOSS_ARGS`。
