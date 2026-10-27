# pip · 给 AI 看的说明


## 干什么
Pip 相关操作工具

## 怎么调
```
moss :pip
```

## 形态
- `kind = app`（GUI 程序），runner = `exe`，入口 `main.exe`
- 它是**交互式界面**，不是给 AI 自动调用的工具 → `ai.expose = false`

## 副作用
- 声明能力：`{"run": ["exe"], "net": ["pypi.org"], "elevated": false}`
- 写文件：写到 `MOSS_PLUGIN_DATA_DIR` 下（不写自己包目录 —— 重装包会冲掉）

## 还没验的
- 迁移后**没有跑过**（用户会逐个测）。本文件里的"副作用/失败模式"是照老代码推断的，
  测完请按实际行为订正。
