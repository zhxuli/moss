# system/runtimes —— 自带运行时（解释器）

## 命名规则

```
system/runtimes/
├─ python/          ← 目录名 = runner 里 "runtime" 字段的值
│  ├─ runtime.json      声明：是什么、什么版本、提供哪个 runner
│  ├─ python.exe
│  ├─ python312.zip     标准库
│  └─ Lib/site-packages 第三方库
├─ node/            ← 以后加 Node 就是这里
└─ lua/             ← 再加 Lua 就是这里
```

**为什么叫 `runtimes`（复数）而不是旧项目那个 `runtime`：**
旧项目的 `bin/runtime/` 里其实**只有 Python**，但从文件夹名字看不出来。
以后可能还要带别的解释器（Node / Lua / …），所以：

- 顶层用**复数** `runtimes` —— 表示"这里是各种运行时"
- 每个运行时**一个子目录，目录名就是它是什么** —— `python/`、`node/`

## 谁在用它们

`system/runners.json` 里每个 runner 声明自己用哪个运行时：

```jsonc
"python": {
  "runtime": "python",                    // ← 对应 runtimes/python/
  "interpreters": {
    "package": ["{runtime}\\python.exe", "PATH:python"],   // 包调用：先用自带的
    "path":    ["{cwd}\\venv\\...", "{runtime}\\python.exe", "PATH:python"]  // 路径调用：先尊重项目的 venv
  }
}
```

`{runtime}` 这个 token 会展开成 `system/runtimes/<名字>/`。
查找顺序：**用户层 `user_data/runtimes/<名字>/` 优先，然后出厂层 `system/runtimes/<名字>/`**
—— 所以以后做"组件下载"时，装到用户层就能覆盖出厂的那份。

## 这里的二进制**不进 git**

`python/` 有 **181.8 MB / 7863 个文件**。这种体量的二进制进 git 历史会让仓库不可用。

所以：

- 仓库里只留**说明 + `runtime.json` 模板 + 拉取脚本**
- 运行时本体靠 `tools\拉取运行时.py` 现场复制
- `.gitignore` 里排除了 `system/runtimes/*/`

**这不影响发行** —— 发行包里 `system/` 是整体打包出去的，运行时会跟着走。
只是"克隆仓库"和"拿到发行版"是两件事。
