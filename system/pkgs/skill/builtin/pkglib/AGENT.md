# pkglib · 给插件装依赖（给 AI 看的说明）

## 干什么
宿主自带运行时里**装不了第三方库**。这只手把库（连同依赖）用 pip 装进**某个插件自己的
`<插件目录>/packages/`**，并在插件目录生成 `deps.py` 垫片 —— 插件入口里 `import deps`
一下，那个目录就进了 `sys.path`，接着正常 `import fastapi` 之类。

插件因此仍然是自包含的：库跟着包目录走，不污染宿主环境、不动宿主的 venv。

## 怎么调
```
moss :skill run pkglib mode=probe
moss :skill run pkglib mode=install pkg="fastapi uvicorn" into=my-first
moss :skill run pkglib mode=list into=my-first
```
| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `pkg` | string | 否 | 要装的库，空格/逗号分隔：`"fastapi uvicorn"` |
| `into` | string | 否* | 装到哪个插件：绝对路径，或 `user_data/pkgs/<id>` 里的包 id |
| `mode` | string | 否 | `install`（默认）/ `probe` / `list` |
| `index` | string | 否 | pip 源，默认清华镜像；要官方源填 `https://pypi.org/simple` |
| `python` | string | 否 | 指定用哪个解释器装（默认自动挑一个带 pip 的） |

\* `install` / `list` 必须给 `into`；`probe` 不用。

## 装完插件那边怎么改
入口文件最前面加一行（**必须在 import 那些库之前**）：
```python
import deps   # noqa: F401  —— 由 pkglib 生成，负责把 packages/ 加进 sys.path
import fastapi
```

## 副作用
- 联网：**要**（pip 从 index 下载）。没网就装不了。
- 写文件：`<插件目录>/packages/**`（库本体）+ `<插件目录>/deps.py`（垫片）。
- 不碰宿主运行时、不碰宿主的 venv、不动注册表。
- pip 子进程的环境里已经清掉了 `MOSS_*`（免得它被当成"某个包的进程"）。

## 失败模式（退出码）
- `2` 参数不全（没给 `into`，或 `into` 指向的目录不存在；`pkg` 为空）
- `3` 目录建不了 / 找不到带 pip 的解释器
- 其它非 0 = pip 自己的退出码（没网、库名写错、需要编译工具没装）
- `probe` 永远回 0，把环境现状打给你看（有 pip 的解释器清单、pypi 通不通）

## 要注意的
1. **库装在包目录里，升级/重装插件会被冲掉**。要长期留，装到数据目录那一侧
   （`MOSS_PLUGIN_DATA_DIR`），或者让插件第一次启动时自己检查 + 自愈。
2. 宿主运行时的 python 版本可能比 pip 装下来的 wheel 老/新 —— 挑解释器时优先用
   **宿主自己的**（`sys.executable`），这样装出来的 wheel 一定和运行时匹配。
3. `--target` 装出来的包在 Windows 上带 dll 的情况（cryptography 等）靠 `deps.py`
   里的 `os.add_dll_directory` 兜一层。
