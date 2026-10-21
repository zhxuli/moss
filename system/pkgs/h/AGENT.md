# h —— 历史快捷运行（给 AI 看）

`moss --history` 的短名字版本：**敲得出名字，就直接切到那个目录再跑一次**。

## 用法

```
moss :h                     等于 moss --history（终端里是方向键列表 + 回车重跑）
moss :h zeen                找最近一条 cwd 末段 / 目标文件名是 zeen 的记录，切过目录再跑
moss :h z/m                 逐级写法：目录段以 z 开头、目标以 m 开头（/ 和 \ 都认）
moss :h wwwroot/zeen/main   段数随便加，越多越准
moss :h D:/python/wwwroot/ZeEn   整条路径也认
moss :h zeen --port 8080    多出来的参数透传给被重跑的程序（追加在历史记录的参数后面）
```

名字规则（`_alignment`）：把查询拆成段，跟每条记录的「cwd 各段 + 目标文件名」逐段
**前缀匹配**（不分大小写）。排序：目标还在 > 尾对齐 > 精确段数 > 深度 > 时间新。
命中多条时取最靠前那条，并把另外几条摆出来提醒。

## 机制（改之前先看这几条）

- **不自己拼解释器**：切目录 + 回头调一次 moss 宿主（`cwd=<记录 cwd>` + `moss <目标文件名>`），
  和用户手动 `cd` 过去再敲同一条路。runner 表 / venv / 自带运行时 bootstrap 只有宿主一份。
- 宿主怎么找：`MOSS_HOST_CMD`（**JSON 数组**，不是命令行字符串）→ `MOSS_HOME/moss.exe`
  → `MOSS_HOME/moss.py`（用 `sys.executable` 跑）→ PATH。
- 起子进程前**清掉全部 `MOSS_*`**（契约 §8 第 16 条），否则 `MOSS_PKG_ID=h` 漏给被重跑的
  程序，宿主会以为 h 一直在跑，点「停止」还可能误杀。
- 数据源是 `MOSS_USER_DATA_DIR/history/*.jsonl`（宿主 `core/history.py` 的追加账）。
  插件 import 不到 core，所以去重 / 墓碑 / "只记路径调用"这几条规则在这里**照抄了一份**：
  改宿主 `history.py` 的规则时，这里要跟着改。
- 只认**路径调用**（`moss zeen`）；`moss :包名` 不进历史，所以 `:h` 也找不到它们。

## 已知限制

- `rest` 参数通道会把引号吃掉：`moss :h zeen --name "My App"` 到这里只剩 `My App` 两段。
  带空格的参数请用程序自己的写法（`--name=My App` 也一样会被切开，得不偿失时直接手敲）。
- 重跑走的是"在那个目录里敲 `moss <文件名>`"，所以如果那个目录里还有**同前缀**的其他入口
  并且消歧需要人挑，宿主会照常弹选择（这是宿主的行为，不是这里的）。
- 「不切目录」那种记录（`moss /x`，宿主里叫 `change_dir=False`）的 cwd 是**调用者**当时的
  目录、目标在别处。照记忆里的 cwd 去跑会找错文件，所以 `_run_cwd()` 会退到**目标所在目录**
  并明说一句 —— 行为跟当初不完全一样，但不会悄悄跑错。
- 记录里的 target / cwd 不在了会明确报错（两种分开说），不会抛 Python 栈。
