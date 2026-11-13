# system/runtimes —— 自带运行时（解释器）

## 结构

```
system/runtimes/
├─ default.json        ★ 各家族的【默认版本】（钉住的，不是自动取最高）
├─ python/
│  ├─ 3.12/
│  │  ├─ runtime.json     声明：家族 / 版本 / 提供哪个 runner / 来源 / 可搬迁性
│  │  ├─ python.exe
│  │  ├─ python312.zip    标准库
│  │  └─ Lib/site-packages 第三方库
│  └─ 3.14/               ← 以后加新版本就是这里
├─ node/                  ← 以后加别的语言就是这里
│  └─ 20/
└─ README.md
```

**命名规则**：`<家族>/<版本>/`

- 顶层是**家族**（`python` / `node` / `lua`…）—— 旧的 `bin/runtime` 里其实只有 Python，
  从文件夹名字看不出来，所以这里改成显式的家族名
- 第二层是**版本** —— 同一个家族可以并存多个版本

## 版本怎么选（这是关键规则）

| 优先级 | 规则 |
|---|---|
| 1 | **包钉死的版本**：`pkg.json` 里 `"requires": { "python": "3.12" }` → 只用 3.12；**没装就报错，绝不改用别的版本** |
| 2 | **`default.json` 钉住的默认版本** ← 绝大多数包走这条 |
| 3 | 都没配 → 用最高的（`--selfcheck` 会提醒去钉一个） |

> ### ⚠️ 默认版本是【钉住】的，不是"自动取最高"
>
> 假如以后你装了 3.14，如果默认是"取最高"，那么**所有没声明版本的包
> 会在你毫无察觉的情况下换解释器** —— 某天某个包就莫名其妙坏了，
> 而且你根本想不到是 Python 版本变了。
>
> 所以要换默认版本，**必须显式改 `default.json`**。那是一个有意识的决定。

`"3.12"` 是**精确到 major.minor**（3.12.11 也算 3.12）；写 `"3"` 表示 3.x 里最高的那个。

## 用户层可以覆盖

```
user_data/runtimes/<家族>/<版本>/      ← 同名版本优先于 system 层
user_data/runtimes/default.json        ← 也能覆盖默认版本
```

这是为**以后做"组件下载"留的位置**：装到用户层就能盖掉出厂的那份，不用动 `system/`。

## pip 和命令行入口

运行时里的 `Scripts/` 是复制源环境时留下的 console launchers。`pip.exe` 这类文件内部写死了
复制前的绝对路径，**不能随发行包搬迁**，否则用户机器上会指到旧目录。

所以 `tools\拉取运行时.py` 复制完运行时会自动删除整个 `Scripts/`。需要 pip 时一律用模块调用：

```
.\python.exe -m pip --version
.\python.exe -m pip install 包名
```

已经有现成运行时、只想修复它：

```
python tools\拉取运行时.py --repair
```

不要依赖 `Scripts\pip.exe` / `pip3.exe` / `pip3.12.exe`。

## 这里的二进制【不进 git】

`python/3.12/` 有 **178.2 MB / 8966 个文件**。这种体量的二进制进 git 历史会让仓库不可用。

- 仓库里只留**说明 + `runtime.json` + 拉取脚本**
- 运行时本体靠 `python tools\拉取运行时.py` 现场复制
- `.gitignore` 里排除了 `system/runtimes/*/*/`

**这不影响发行** —— 发行包里 `system/` 是整体打包出去的，运行时跟着走。
只是"克隆仓库"和"拿到发行版"是两件事。

## 体积备忘

| 部分 | 大小 |
|---|---|
| 全部 | 178.2 MB |
| numpy + numpy.libs | 41.0 MB |
| matplotlib | 18.6 MB |
| PIL | 14.1 MB |
| fontTools | 10.2 MB |

以后要瘦身，numpy / matplotlib / fontTools 是大头（约 70MB）。
**先别删** —— 旧项目的插件依赖它们。
