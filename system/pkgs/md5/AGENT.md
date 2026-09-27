# md5 —— MD5 计算

算字符串、文件或文件夹的 MD5；结果自动进剪贴板；不填参数用剪贴板内容

## 怎么用

```bash
moss :md5 <参数>
```

## 参数

| 参数 | 必填 | 说明 |
|---|---|---|
| `target` | 可选 | 文件/文件夹路径，或一段文本；带引号强制按字符串算；不填则用剪贴板 |

## 输出

`output.mode = json` —— 结构化结果写进宿主给的 `MOSS_RESULT_FILE`（给人看的照常 `print`）。

## 来历

从旧项目 **`QuickTools\user_data\exec\cmds\md5.json`** 移植（2026-09-27）—— 那边是 旧 exec 命令库里的**一条命令**（不是插件）。
**功能代码照抄**，只改了宿主差异：数据目录 `MOSS_PLUGIN_DATA_DIR`、参数来源
`MOSS_PKG_PARAMS` / `MOSS_ARGS`（读不到才退回 `sys.argv`）、用户可见文案里的 `pa` → `moss`。

> 这一段原来写在 `pkg.json` 的 `origin.from` 里。2026-09-27 定了"**包里不放来源**"
> （`F-10` ❌：来历写这里；"是官方还是第三方装的"归宿主记账，包自证不可信），
> 所以挪到 `AGENT.md`。
