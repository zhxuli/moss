# system/ui/vendor —— 这里放的是**第三方前端资源**（离线可用，随发行版一起走）

界面对外不联网：这些库都落在仓库里，`system/ui/` 整个跟着 `moss.exe` 分发。

| 文件 | 是什么 | 版本 | 许可 | 从哪来 |
|---|---|---|---|---|
| `highlight.min.js` | 代码高亮引擎（官方 **common** 构建，34 种语言：python / go / json / markdown / yaml / ini / css / xml / javascript …） | 11.9.0 | BSD-3-Clause | 与 `system/pkgs/exec/ui/vendor/` 里那份**同一份**（exec 早就在用） |
| `powershell.min.js` | 高亮语言包：PowerShell（`.ps1`） | 11.9.0 | BSD-3-Clause | highlight.js 官方语言包 |
| `dos.min.js` | 高亮语言包：DOS 批处理（`.bat` / `.cmd`）—— common 构建里没有，单独补 | 11.9.0 | BSD-3-Clause | highlight.js 官方语言包 |
| `lucide.js` | 图标库：`{名字: '<path .../>'}` 的表 + `ico(name)` 函数，**只收了用到的 82 个** | lucide-static 1.48.0 | ISC | `unpkg.com/lucide-static`，见 `lucide-LICENSE.txt` |
| `vue.global.prod.js` | Vue **3 全局构建**（自带模板编译器，所以 `js/settings.js` 里的 `template:` 字符串能直接用） | 3.x | MIT | 与 `system/pkgs/bmi/ui/vendor/` 里那份**同一份**（`V-67` 界面组件化时拿过来的） |

## 为什么这么放

- **不引 CDN**：界面可能在没网的环境下用（而且 `file://` 页面跨源取资源本来也会被挡）。
- **图标内联成路径表**：页面要按**文件后缀**动态换图标（`.py` / `.json` / `.png` … 各一个），
  一个个去读 `.svg` 文件既慢又要处理跨源；内联成一张表最快。
  图标统一 24×24、1.5 描边、`currentColor` —— 和 18 个包自带的 `icon.svg` 同一套风格。
- **框架只在需要组件的地方引入**：`V-67` 起界面用 Vue 3 写组件（第一个是设置面板），
  但**不是**每个页面都改写成组件 —— 没动的那几块还是原来的经典脚本，改一块验一块。
- **高亮语言包按需补**：common 构建已经覆盖我们全部代码文件，只差 `.bat`（dos），
  所以只补了它一个（PowerShell 是照 exec 的做法单独带）。

## 升级怎么办

换版本 = 换这几个文件，**不用重编译 exe**（界面在 exe 外面，`K-10`）：

```
# 语言包（版本号一起改）
https://cdnjs.cloudflare.com/ajax/libs/highlight.js/<版本>/languages/dos.min.js

# 图标（取新版本后重新生成）
https://unpkg.com/lucide-static@<版本>/icons/<名字>.svg
```

`lucide.js` 由 **`tools/取图标.py`** 生成，**别手工编辑这个文件**：

```
venv\Scripts\python.exe tools\取图标.py                 # 只报告，不写
venv\Scripts\python.exe tools\取图标.py history clock   # 把缺的补进去
venv\Scripts\python.exe tools\取图标.py --verify        # 拿线上重新核对现有条目
```

它把每个 `<svg>` 里的内容剥出来拼成表（单引号单行、1.5 描边由 `ico()` 统一给）。
**只增不改** —— 已经有的一条都不重写，免得整个文件产生无意义 diff。
改版本号时把脚本里的 `VERSION` 一起改掉，再跑 `--verify` 核对。

★ 2026-09-28 之前，这个脚本**不在仓库里**（只在提交记录里），README 却写着"别手工编辑" ——
于是想补一个图标就只能手抄，等于破了自己定的规矩。现在补回来了（补 `history` 时顺手做的）。
