# system/pkgs —— 出厂包（只读层）

**这里放的是要随 moss 一起分发给所有用户的包。**

## 放什么

- 真正要出厂自带的功能包（一个目录 + `pkg.json` + 代码文件）

## 不要放什么

| ❌ 不要放 | 应该放 |
|---|---|
| 用户自己写的东西 | `user_data/pkgs/` |
| 临时试手 / 演示用的包 | 也放 `user_data/pkgs/`，不要了就 `moss --remove <id>` |

## 预制技能（AI 的手）

这不是插件，不要直接放 system/pkgs/<id>/。预制技能放 system/pkgs/skill/builtin/<id>/
（一个目录 = pkg.json + 入口 + icon.svg + AGENT.md），随发行版打包、出厂默认就允许；
用户 user_data/state/skill/<id>/ 同名会覆盖它。

## 两层的关系（优先级从低到高）

```
system/pkgs      出厂包，随程序分发            ← 用户在发行版里能看到
user_data/pkgs   用户自己装的、自己写的         ← 打包时整体排除
```

> 2026-09-27（第 36 版）：原来的第三层 `dev/pkgs/`（演示包 / 测试固件）已删 —— 见 `D-16`。
> 自己写包就直接放 `user_data/pkgs/`，不用另开一层。

同名时**高优先级遮蔽低优先级**，低层原件**保留**（可对比、可还原）。

## 带界面的包（默认方案）

**要界面就写成网页**，在 `pkg.json` 里声明 `"ui": {"embed": "ui/index.html"}` —— 同一份界面
既能内嵌进 moss 的「界面」选项卡、也能 `moss :<id>` 自己开窗口。

- **样板**：`skill/`（Vue 3 + Python 后端，一份代码两种跑法）—— 新包照它抄
- **规范**：`system/spec/插件契约.md` §1.0 与 §4.2（或 `moss --spec`）
- **三个坑**：JS 桥的方法要收得下那一个参数；别把 `window` 挂成 `js_api` 的属性；
  想证明"是 Python 在干活"就 `print`（详见 `skill/AGENT.md`）

## 关于编译型语言的包

Go / Rust / C 这类语言的包，**出厂时应该带编译好的 `exe`，而不是源码**：

- 源码需要用户装整套工具链（Go 约 500MB）
- 每次运行都要重新编译 —— 实测 `go run` 约 **19 秒**，编译好的 exe 约 **0.05 秒**

所以：源码留在 `src/`，用 `build.cmd` 产出 exe，`pkg.json` 的 `entry` 指向 exe。

（早先有两个演示包 `hello-go` / `hello-exe` 专门演示这件事，2026-09-27 已删除 ——
它们只会让包列表变乱。要参考的话在 git 里：`git show 89801ad:dev/pkgs/hello-exe/pkg.json`。）
