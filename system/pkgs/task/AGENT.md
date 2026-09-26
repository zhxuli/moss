# task · 给 AI 看的说明

> 本包**从老项目移植**（`QuickTools/pa_soft/bin/soft/task`），功能代码照抄，
> 只把"跟宿主打交道"的接口从老 `PA_*` 换成 moss 的 `MOSS_*`（老变量仍是兜底）。
> 数据目录：`MOSS_PLUGIN_DATA_DIR`（= `user_data/state/task/`）。

## 干什么
任务/进程查看（webview）：系统状态监控，可结束进程、打开文件位置

## 怎么调
```
moss :task
```

## 形态
- `kind = app`（GUI 程序），runner = `python`，入口 `main.py`
- 它是**交互式界面**，不是给 AI 自动调用的工具 → `ai.expose = false`

## 副作用
- 声明能力：`{"run": ["python"], "process": ["read", "kill"]}`
- 写文件：写到 `MOSS_PLUGIN_DATA_DIR` 下（不写自己包目录 —— 重装包会冲掉）

## 还没验的
- 迁移后**没有跑过**（用户会逐个测）。本文件里的"副作用/失败模式"是照老代码推断的，
  测完请按实际行为订正。
