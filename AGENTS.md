# AGENTS.md —— 在这个仓库里干活的 AI，先读这一页

> 这一页**只指路、不抄内容**：写包的规矩只有一份（契约）、决策只有一份（账本），
> 抄第二遍必然漂移（这里栽过好几次）。
> 沟通习惯：**中文、简短、小步快跑**；一次一件事，改完说清「改了什么 / 怎么验的 / 要你做什么」。

## 30 秒

* 这是什么：Windows 上的**启动器 + 插件宿主**。发行物 = `moss.exe` + `system/`（不写注册表）。
* **磁盘是真相**：`moss.exe` 读的就是磁盘上的 `system/**` —— 改完**重启一次 moss** 就生效。
* **`core/` 是编进 exe 的**（`K-10`）⇒ 改 `core/**` **必须重新打包**；
  改 `system/**`、`tools/**`、文档**都不用**（绝大多数改动都属于后者）。
* 账本：`设计与决策.md`。**一行 = 一次商量**，ID（`V-nnn`）稳定，最新在最上面；
  顶部「当前状态：N 条议题 —— ✅ / ❌ / ⬜」那行必须和实际行数一致
  （`tools/文档完整性审计.py` 里有这道自检；插入新行时**别覆盖旧行**，这事发生过两次）。
* 写包之前先读契约：`moss --spec`（= `system/spec/插件契约.md`）。

## AI 工作台（`V-230`~`V-232`，在建）

让 moss 自己用 AI 写包的那个功能。**它在 `system/ui/ai/`，不是一个包**（要贴详情页、
要拿宿主进程内的状态）；改完**重启 moss** 就生效，不用重打包。

* `ai_loop.py` —— loop 本体，**能直接命令行跑**（先做无界面那一步）：
  `system\runtimes\python\3.12\python.exe system\ui\ai\ai_loop.py "给我写个 xxx 包"`
* `ai_client.py`（OpenAI 兼容，只用 `urllib`）/ `ai_tools.py`（工具 + **验收闸**）/
  `ai_edits.py`（search/replace + 写权限守卫）
* **界面**：详情页那个「AI」选项卡 = `js/ai.js`（Vue 组件）+ `main.py` 里 `ai_info/ai_start/ai_poll/ai_stop`
  四个方法（后台线程 + 轮询）。**加了新选项卡记得把它登记进 `js/panels.js` 那个数组**，
  否则 `setTab` 会把所有页都关掉（`V-233` 踩过）。
* 提示词是**数据**：`system/ui/ai/prompts/*.md` 出厂、`user_data/ai/prompts/*.md` 覆盖
  （规矩见那个目录的 `README.md`）。**契约正文不许抄进提示词**，用 `spec` 工具当场切。
* **快照**（`ai_snap.py`，`V-236`）：动手改一个已有包之前自动存一条，清单里带**真字段**
  `by="ai"` + `by_task`（那次的任务原文）。**AI 只能清自己存的** —— 清快照只走
  `BackupStore.delete_ai()`（逐条看 `by`，不是 `ai` 就跳过），`run_moss` 里的
  `--snap rm/…` 一律被拒。界面上快照列表带「AI」徽章 + 筛选 + 「清掉 AI 的（N）」。
  标题那一栏**就是那次的任务原文**（`title_for()`：压一行、超 40 字带 `…`；空着留空，
  存储用时间兜底）—— 判据永远是 `by`（列表上的「AI」徽章），别把标识写进标题占地方。
* **会话（`V-251`，接着聊）**：`ai_loop` 收尾时交出**整条对话**（`result["messages"]`）→
  宿主写进 `user_data/ai/runs/<id>.json` → 下次 `ai_start(..., continue_id=<那条的 id>)`
  把对话读出来，`loop.run(..., history=…)` 接上去（只接 `system` 以外的轮次；系统提示每次
  用现在的契约重拼）。界面**按"干活的地方"分会话**：进来就认领这个包上次那条并**默认接着聊**，
  想重开点「新开一条」。★ 别把 `messages` 塞进 `ai_poll`/`ai_run` 的返回值（几百 KB）——
  只给 `cont`/`msgs`，真正接着聊时把 **id** 交回宿主。
* **它动完盘 ⇒ 必须通知界面**（`V-249`）：`ai_poll()` 里看到「跑完 + 有 `files`」就调
  `files.js` 的 `diskChanged(rels)`（作废文件管理缓存 / 重问包表 / 重读开着的那几页 /
  重列目录），**按 run 只通知一次**。★ 静默刷新一律走 `fmRefresh(true)`：它**不许抢顶层
  选项卡**，也**不许把用户正开着的那一页关掉**（`fmGoto` 会把 `s.active` 打回 `__browse__`）。
* ★ **`js/*.js` 是经典脚本、共享一个全局 —— 顶层名字不许重名**：后来的文件里一个同名
  `function` 会把前面那个**整个盖掉，而且一句错都不报**（`V-249`：`drop.js` 的
  `extOf(name)` 盖掉了 `core.js` 的 `extOf(entry)` ⇒ 代码高亮全没了、图标配色一起丢）。
  `tools\界面检查.py` 第 11 条会拦；起名字之前先想一下有没有人叫过。
  ★ 改名之后**全局搜一遍调用点**：`tools/界面预览.py` 里也有直接调 `window.extOf(...)` 的
    场景，`V-249` 改名时漏了它 ⇒ `drop-ext` 红了一轮才被发现（`V-250`）。
* **快照边栏的对照色**（`V-250`，你 2026-10-04 定的）：变了（大/小）= **同一个琥珀**，
  `df-deep`/`df-soft` 分深浅（谁大谁更深）；添加/缺少 = **同一个蓝**（`--df-add` 深 / `--df-add-soft` 浅）；
  **没变化 = 灰**（`df-same`，只在快照边栏；左边那张表不变色）。方向另有记号
  `+/−/↑/↓`，两边共用 `core.js` 的 `bkDiffMark(rel)`；图标一律 `fileIconHTML(e)`（和文件管理同一张）。
  断言在 `backup-diff` 场景里是**数字**（把 `getComputedStyle().color` 转成 hsl 比 hue / 明度），别靠看截图。
* 改动它之后跑这两个：`python tools\ai循环探针.py`（loop，假模型）、
  `.\system\runtimes\python\3.12\python.exe tools\ai工作台探针.py`（宿主那半，假模型+假宿主），
  再加 `python tools\界面预览.py ai-pane ai-disk-refresh ai-snap-refresh ai-continue`
  （这一页画不画得出来 / 干完活文件管理刷不刷新 / 开工前那条快照刷不刷出来 /
  重启后能不能接着上次那条聊）。**都不烧 token。**

## 要写包 / 改包

1. **新包**：`moss --new <id>` 生成一个能跑的骨架（`user_data/pkgs/<id>/`）。
2. **要界面**：照 `system/pkgs/bmi/` 抄 —— 网页界面 + `ui/moss-embed.js` 垫片，
   在 `pkg.json` 里声明 `"ui": {"embed": "ui/index.html"}`。
   **别自己 `webview.create_window` 开窗口**（内嵌模式下开窗等于把宿主晾在那儿）。
3. **要接拖放**：契约 **§4.2「★ 要接拖放：照这个清单写，一次就对」** 那张六道关的表 ——
   漏一道的症状就是"拖进来没反应""提示不消失""没有这个方法 X"（`V-204`~`V-228` 全踩过）。
4. 每个包自己的 `AGENT.md` 是**给 AI 看的**用法说明（`pkg.json` 的 `docs.agent` 声明）；
   `README.md` 给人看。语法唯一真相在代码里（`cli.py` 的 `USAGE`），别在文档里另抄一份。

## 改完必须自己验（"看着对"不算）

* **界面静态闸**：`python tools\界面检查.py`
* **真渲染一遍**：`python tools\包界面检查.py [包…]`（模板/计算属性出错在这里拦下）
* **宿主 → iframe → 后端整条链**：`python tools\界面预览.py <包>-ui`
  （全量 `--check`；其中 5 个 `settings-*` 是**已知过期**场景，见账本 `V-203`）
  ★ **全量跑完别只看输出尾巴**（`V-250` 的血）：`drop-ext` 因为一个改名悄悄红了一整轮，
    而我当时只 `Select-Object -Last 25` ⇒ 报了个假的"全绿"。一律
    `python tools\界面预览.py 2>&1 | Select-String 'FAIL'` 逐条看，**除了那 5 个 STALE 不许有别的**。
* **探针样板**（照它写新的）：`tools\exec内嵌探针.py`（内嵌协议）、
  `tools\img内嵌探针.py`（拖放 + 页面参数形状）、`tools\窗口记忆探针.py`、
  `tools\跑完探针.py`、`tools\包状态探针.py`
* ★ **先证明探针抓得住**（这台机器的硬规矩）：加了断言之后，**临时把修复注掉**跑一遍，
  确认它真的会红，再还原 —— 假绿比没验还糟（`V-202` / `V-226` 都是这么抓出来的）。
* 跑宿主那类探针用 **`system\runtimes\python\3.12\python.exe`**：系统那个 3.13 **没有 psutil**，
  `_pids_by_cmdline()` 会**静默返回空**（于是什么包都显示"没在跑"——假阴性）。

## 打包（`core/**` 或 `moss.exe` 本身）

* 规矩 `V-158`：**先看 `moss` 在不在跑，在跑就先结束它**，再 `tools\build.py`；
  打完整 `moss.exe --selfcheck`。

## 别做的事

* **不要自己 `git commit` / `git push`**：用户说「推」才推。
* **别碰真实的 `user_data/`**：验证一律把 `MOSS_PLUGIN_DATA_DIR` / `MOSS_USER_DATA_DIR`
  指到临时目录（探针工具已经这么干了，照抄）。
* 别装第三方依赖来解决界面问题：自带运行时是**隔离**的，包只能用标准库 + 随包带的 vendor。

## 撞到环境的坑

* 先查这台机器的避坑库：
  `python "C:\Users\Administrator\.dsh\skills\pitfalls\pit.py" query "<关键词>" --top 6`
* 撞到新的**环境/工具链**坑就 `add`；但**项目自己的设计决定写进契约或账本**，不进避坑库。
