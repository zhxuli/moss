# open —— 打开网址 / 本地路径

```bash
moss :open google.com        # 认得出顶级域名 → 补 http:// → 浏览器打开
moss :open main.py           # 不像网址 → 当本地路径 → 用默认程序打开
moss :open "C:\Users\Admin"  # 带空格的路径要加引号
```

## 判断规则（照抄旧脚本）

- 结尾命中白名单 TLD（`.com .cn .net .org .io .gov .edu .dev .app .xyz .top .vip .co .cc .io .hk .xin`）
  → 当**网址**：没有 `http(s)://` 前缀就补 `http://`
- 否则当**本地路径**：存在就用 `start` 打开，不存在就报错并打用法
- 都不匹配 → 报错、打用法

## 文件构成（为什么有两个文件）

- `main.bat` —— **原样照抄**旧项目 `QuickTools\bin\cli\open\main.bat`，判断逻辑全在这里，一字未改
- `main.py` —— 一层薄包装。原因：新宿主的 runner 模板是 `cmd /c {entry}`，**不带参数**；
  宿主把参数放在 `MOSS_PKG_PARAMS` / `MOSS_ARGS` 环境变量里。不包一层的话 `.bat` 里
  的 `%~1` 永远是空的。包装只做"把参数喂给 .bat"这一件事。

> 备注（不是改动建议）：宿主本身已经有内建的 `openUrl` / `openPath` 两种动作
> （`core/engine.py` 的 `_run_builtin`），但现在 `system/runners.json` 里没有
> 声明 `url` / `path` 两种 runner。将来若要省掉这层包装，可以把 `open` 写成
> **声明式包**（不写代码，只声明"这是个 url/path 入口"）—— 那要先做 runner 声明，
> 属于设计决定，见账本 `P-12`。

## 来历

原样搬自 `QuickTools\bin\cli\open`（旧宿主 `pa :open`）。
`ai.expose = false`：它会在你机器上打开东西，不适合让 AI 自己触发。
