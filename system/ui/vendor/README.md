# system/ui/vendor —— 这里放的是**第三方前端资源**（离线可用，随发行版一起走）

界面对外不联网：这些库都落在仓库里，`system/ui/` 整个跟着 `moss.exe` 分发。

| 文件 | 是什么 | 版本 | 许可 | 从哪来 |
|---|---|---|---|---|
| `highlight.min.js` | 代码高亮引擎（官方 **common** 构建，34 种语言：python / go / json / markdown / yaml / ini / css / xml / javascript …） | 11.9.0 | BSD-3-Clause | 与 `system/pkgs/exec/ui/vendor/` 里那份**同一份**（exec 早就在用） |
| `powershell.min.js` | 高亮语言包：PowerShell（`.ps1`） | 11.9.0 | BSD-3-Clause | highlight.js 官方语言包 |
| `dos.min.js` | 高亮语言包：DOS 批处理（`.bat` / `.cmd`）—— common 构建里没有，单独补 | 11.9.0 | BSD-3-Clause | highlight.js 官方语言包 |
| `lucide.js` | 图标库：`{名字: '<path .../>'}` 的表 + `ico(name)` 函数，**只收了用到的 74 个** | lucide-static 1.48.0 | ISC | `unpkg.com/lucide-static`，见 `lucide-LICENSE.txt` |

## 为什么这么放

- **不引 CDN**：界面可能在没网的环境下用（而且 `file://` 页面跨源取资源本来也会被挡）。
- **图标内联成路径表**：页面要按**文件后缀**动态换图标（`.py` / `.json` / `.png` … 各一个），
  一个个去读 `.svg` 文件既慢又要处理跨源；内联成一张表最快。
  图标统一 24×24、1.5 描边、`currentColor` —— 和 18 个包自带的 `icon.svg` 同一套风格。
- **高亮语言包按需补**：common 构建已经覆盖我们全部代码文件，只差 `.bat`（dos），
  所以只补了它一个（PowerShell 是照 exec 的做法单独带）。

## 升级怎么办

换版本 = 换这几个文件，**不用重编译 exe**（界面在 exe 外面，`K-10`）：

```
# 语言包（版本号一起改）
https://cdnjs.cloudflare.com/ajax/libs/highlight.js/<版本>/languages/dos.min.js

# 图标（取新版本后重新生成 lucide.js）
https://unpkg.com/lucide-static@<版本>/icons/<名字>.svg
```

`lucide.js` 是脚本生成的（不是手抄）：见提交记录里那份"取图标"的脚本，
它把每个 `<svg>` 里的内容剥出来拼成表；**别手工编辑这个文件**。
