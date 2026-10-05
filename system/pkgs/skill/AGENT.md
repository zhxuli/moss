# skill —— 技能管理器（给 AI 造的能力做管理界面）

## 它管什么

**技能** = AI 干活时缺一个能力，自己造出来的"手"。比如"给某个界面截屏"这种事
**用户不需要一个插件**（他直接看屏幕就行），但 AI 需要、还可能要频繁调 —— 所以它们
不该出现在插件列表里（你 2026-10-05 的原话：写一堆用户不用、AI 会用的插件，用户会觉得乱）。

## 东西都放在哪

```
system/pkgs/skill/              ← 管理器本身（就是本插件，跟 :exec 并排）
system/pkgs/skill/seed/shot/    ← 出厂样例；第一次跑时**播种**到数据目录（之后可改可删）
user_data/state/skill/shot/     ← **技能本体**：一个目录 = pkg.json + 入口 + icon.svg + AGENT.md
user_data/ai/skills_allow.json  ← **你的授权**（AI 写不到这个文件）
user_data/pkgs/<id>/            ← 点「转为插件」搬过去之后，它就是普通插件
```

技能本体住**本插件的数据目录**（`MOSS_PLUGIN_DATA_DIR`，跟 `exec` 把命令放
`state/exec/cmds/` 一个道理）。**区别只有一处**：exec 把代码内联在 json 里（`"code"` 字段），
技能是**一个目录**——就是插件那种多文件结构。

## 两条规矩（代码拦的，不是提示词劝的）

1. **id 跟插件同一规格**（`shot`，小写字母开头）—— `V-284` 起**不要** `--` 前缀了：
   技能不走包解析那条路（入口是 `moss :skill <动词> <名字>`），两个圈子碰不到一起。
2. **声明 ≠ 授权**：`pkg.json` 里的 `ai.expose` 是包自己"声明我能被 AI 调"（AI 写得动这个
   字段），**授权**在 `user_data/ai/skills_allow.json` 里（AI 写不到），而且**绑指纹**——
   `pkg.json` + 入口 + 图标 改一个字，授权就作废、退回"待批准"。
   （`--` 那套和 `expose` 那套是两件事：前者防**命名污染**，后者防**自己给自己发通行证**。）

## 命令行

```
moss :skill                       打用法 + 列表（**不开窗**；命令行/AI 调都走这条）
moss :skill gui                   打开管理器窗口（图标墙 / 详情模态框 / 转为插件 / 删除）
moss :skill list / show <名字>     列出来 / 看详情（为什么造它 · 时间 · 文件）
moss :skill doc <名字>             **这只技能自己的说明书**（它目录里的 AGENT.md）
moss :skill run <名字> [k=v …]     跑一次（参数用 k=v）
moss :skill allow|revoke <名字>    允许 / 撤销（**必须人来做**）
moss :skill rm <名字>              删掉
moss :skill plan|promote <名字> [新id]  转插件之前先看冲突 / 真转
moss :skill seed                   把出厂样例补回来
```

★ **不开窗的规矩**（`V-284`，你定的"对 AI 友好、又不影响我们在窗口打开"）：
不带参数时，**界面里点「运行」**（宿主会加 `MOSS_INTERACTIVE=1`）→ 开窗口；
**命令行 / AI 通过 run_moss 调** → 只打用法和列表。想显式开窗就 `moss :skill gui`。

## AI 那边怎么接的

* 宿主 AI 工作台 import 的是**同一份规矩**：`system/ai/skill_lib.py`
  （扫描 / 校验 / 指纹 / 授权 / 跑 / 转插件 —— 一处定义，两个消费者）。
* 开工时把**已允许**的技能拼进工具表；技能跑法**走 runner 表**
  （`system/runners.json`，含自带运行时的 `bootstrap.py` 垫片），所以 python / go / shell /
  powershell / exe 都能当技能，跟插件一个待遇。
* **`run_moss(":skill allow …")` 是被拒的**（宿主 `ai_tools._t_run_moss` 里那道闸）——
  允许 / 撤销 / 删除 / 转插件这四下必须由人点；`new` / `list` / `show` / `run` 照旧随便用。

## 界面协议（`ui/app.js` → 后端）

| 方法 | 干什么 |
|---|---|
| `list` | 图标墙要的全部数据（技能 + 来自插件的可调用包 + 目录） |
| `read {id}` | 某个技能里各文件的正文 |
| `plan {id, new_id?}` | 转插件之前的**只算不改**检查（id 冲突） |
| `promote {id, confirm, new_id?}` | 真转（搬目录 + 改 id + 授权跟着走） |
| `allow {id, yes}` / `rm {id, confirm}` | 允许 / 撤销 / 删除 |
| `run_once {id, args}` | 试跑一次（走的是 AI 那条一样的路：stdin JSON → stdout） |
| `reveal {dir}` / `seed` | 打开目录 / 补回出厂样例 |
