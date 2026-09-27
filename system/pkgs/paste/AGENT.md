# paste · 给 AI 看的说明

> 本包**从老项目移植**（`QuickTools/pa_soft/bin/soft/paste`），功能代码照抄，
> 只把"跟宿主打交道"的接口从老 `PA_*` 换成 moss 的 `MOSS_*`（老变量仍是兜底）。
> 数据目录：`MOSS_PLUGIN_DATA_DIR`（= `user_data/state/paste/`）。

## 干什么
常用文本/剪贴板快速粘贴（分组管理，分组间热键可重复，可同时启用多个分组；窗口可拉伸）

## 怎么调
```
moss :paste
```

## 形态
- `kind = app`（GUI 程序），runner = `python`，入口 `main.pyw`
- 它是**交互式界面**，不是给 AI 自动调用的工具 → `ai.expose = false`

## 副作用
- 声明能力：`{"run": ["python"], "clipboard": ["read", "write"], "hotkey": true, "net": []}`
- 写文件：写到 `MOSS_PLUGIN_DATA_DIR` 下（不写自己包目录 —— 重装包会冲掉）

## 还没验的
- 迁移后**没有跑过**（用户会逐个测）。本文件里的"副作用/失败模式"是照老代码推断的，
  测完请按实际行为订正。

## 来历

从旧项目 **`QuickTools\pa_soft\bin\soft\paste`** 移植（2026-09-27）—— 那边是 整包。
**功能代码照抄**，只改了宿主差异：数据目录 `MOSS_PLUGIN_DATA_DIR`、参数来源
`MOSS_PKG_PARAMS` / `MOSS_ARGS`（读不到才退回 `sys.argv`）、用户可见文案里的 `pa` → `moss`。

> 这一段原来写在 `pkg.json` 的 `origin.from` 里。2026-09-27 定了"**包里不放来源**"
> （`F-10` ❌：来历写这里；"是官方还是第三方装的"归宿主记账，包自证不可信），
> 所以挪到 `AGENT.md`。
