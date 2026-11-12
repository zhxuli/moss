# skill —— 技能管理器（给 AI 造的能力做管理界面）

## 它管什么

**技能** = AI 干活时缺一个能力，自己造出来的"手"。比如"给某个界面截屏"这种事
**用户不需要一个插件**（他直接看屏幕就行），但 AI 需要、还可能要频繁调 —— 所以它们
不该出现在插件列表里（你 2026-10-05 的原话：写一堆用户不用、AI 会用的插件，用户会觉得乱）。

## 东西都放在哪

```
system/pkgs/skill/              ← 管理器本身（就是本插件，跟 :exec 并排）
system/pkgs/skill/seed/shot/    ← 出厂样例；**只留作"照它抄"的样板**（不会再自己长进数据目录）
system/pkgs/skill/builtin/<id>/   ← 预制技能：随发行版打包，出厂默认已允许；同名 user 技能覆盖它
user_data/state/skill/shot/     ← **技能本体**：一个目录 = pkg.json + 入口 + icon.svg + AGENT.md
user_data/ai/skills_allow.json  ← **你的授权**（AI 写不到这个文件）
user_data/ai/skill_stats.json   ← **调用统计**：每只被调了几次 + 最近一次调用时间（`V-295` 加）
user_data/pkgs/<id>/            ← 点「转为插件」搬过去之后，它就是普通插件
```

★ **调用次数 / 最近调用时间从哪来**（`V-295`）：`skill_lib.bump_stat(id)` 在**每次 `run()` 真跑之前**
记一笔（次数 +1、`at` 写现在），存进 `user_data/ai/skill_stats.json`。**AI 调的、命令行调的、
界面「运行测试」调的，都从 `run()` 这一条路走**，所以一处埋点全覆盖；详情页那句「最近调用时间」
没记录就显示 `—`。统计文件**故意放在技能目录外面**（跟授权表一层）——省得它混进"这个技能有哪些
文件"里。

★ **想要样例就自己复制一份**（`system/pkgs/skill/seed/shot/` → `user_data/state/skill/<名字>/`）——
「补回出厂样例」那个功能（按钮 / `moss :skill seed` / 自动回填）**已经删干净了**（`V-288`/`V-289`）。

技能本体分两层：用户自己造的住**本插件的数据目录**（MOSS_PLUGIN_DATA_DIR，跟 exec 把命令放
state/exec/cmds 一个道理）；预制技能住 system/pkgs/skill/builtin/<id>/，随发行版走、默认已允许，
同名 user 技能覆盖它。**区别只有一处**：exec 把代码内联在 json 里（"code" 字段），技能是**一
个目录**——就是插件那种多文件结构。

## 两条规矩（代码拦的，不是提示词劝的）

1. **id 跟插件同一规格**（`shot`，小写字母开头）—— `V-284` 起**不要** `--` 前缀了：
   技能不走包解析那条路（入口是 `moss :skill <动词> <名字>`），两个圈子碰不到一起。
2. **声明 ≠ 授权**：`pkg.json` 里的 `ai.expose` 是包自己"声明我能被 AI 调"（AI 写得动这个
   字段），**授权**在 `user_data/ai/skills_allow.json` 里（AI 写不到），而且**绑指纹**——
   `pkg.json` + 入口 + 图标 改一个字，授权就作废、退回"待批准"。
   （声明防的是**自己给自己发通行证**；id 那一侧已经不设前缀了，见上一条。）

## 命令行

```
moss :skill                       打用法 + 列表（**不开窗**；命令行/AI 调都走这条）
moss :skill gui                   打开管理器窗口（图标墙 / 详情抽屉 / 转为插件 / 删除）
moss :skill list / show <名字>     列出来 / 看详情（为什么造它 · 时间 · 文件）
moss :skill doc <名字>             **这只技能自己的说明书**（它目录里的 AGENT.md）
moss :skill run <名字> [k=v …]     跑一次（参数用 k=v）
moss :skill allow|revoke <名字>    允许 / 撤销（**必须人来做**）
moss :skill rm <名字>              删掉
moss :skill plan|promote <名字> [新id]  转插件之前先看冲突 / 真转
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

## 界面（`V-289` 拆成 Vue 3 一套；`V-290`~`V-293` 照参考稿做视觉；`V-295` 加调用次数；`V-296` 代码高亮 + 行号 + 复制）

```
ui/index.html       模板 + 挂载点（模板就在 #app 里面，垫片和 app.js 必须在后面）
ui/src/api.js       后端桥的**唯一入口**（window.SKILL_API，界面别直接碰 moss/pywebview）
ui/src/icons.js     界面自己的图标（细线 + 实心两套，手画的 svg；**不用图标字体 CDN**）
ui/src/paths.js     **把输出里的路径变成能点开的链接**（`V-301` 建；`V-346` 重写成两个动作）
ui/src/comp-*.js    四个组件：卡片 / 详情弹窗 / 确认框 / 提示条
ui/src/app.js       根组件 + 启动（★ 那段注释记着 V-283~V-287 踩过的坑，别删）
ui/style/*.css      tokens → base → layout → components（`<link>` 顺序即层叠顺序）
ui/vendor/          vue.global.prod.js（**全局版**：自带模板编译器）+
                    highlight.min.js / powershell.min.js / dos.min.js（代码高亮，跟主界面同一份）
```

★ 骨架（`V-293`，照用户给的新参考稿）：**大标题头部 + 自适应卡片网格 + 居中大弹窗**。
  · 头部：左边大标题「技能中心」，右边工具条（「待处理」开关 · 展开式搜索 · 刷新）。
    ★ 状态字（`#status`）**只在"还没读出来"时才写字**（正在读…… / 读不出来…），读出来了就留空
    （`V-296`：你说"那个 x 只技能在主页面显示没什么用"）；
  · 卡片 = 图标 + 标题 + 一排小标签 + 两行描述 + 底部「**N 次调用** / 悬停浮现的进入箭头」；
    **还没允许 / 进不了工具表的整张置灰**，写坏了的额外给一道红顶。标签（`.tag`）是**中性小圆片**
    （浅灰底 + 灰字：字号 `.75rem` / 内边距 `4px 10px` / 圆角 `20px` / 字重 `500`，不再一个色一个）；
  · 弹窗 = **居中大卡**（左 320px 身份与操作中枢 + 右数据与内容）：左边大图标/名字/标签，
    底部"状态开关（允许·撤销）+ 运行测试 / 转换为插件 / 删除"；右边数据概览（**调用次数** /
    入口文件 / 创建时间 / **最近调用时间**）/ 功能描述 / AI 行为指引 / 工作目录 /
    **文件清单**（点开看正文：**highlight.js 上色 + 左侧行号 + 行头一颗「复制内容」**）/
    **详细说明**（`#d-doc`，放**最下面**、**默认展开**，正文是它自己的 `AGENT.md`）；
  · 令牌走**鼠尾草绿 `#3B7A57`（主色）+ 赤陶橙 `#E06D06`（强调）**、冷白纸底；
    全站一条 spring 曲线，浅深两套镜像都在 `style/tokens.css`。
  ★ 参考稿用的是 FontAwesome 的 **CDN**、且「N 次调用」是假数据 —— 我们都换掉：
    图标**手画成内联 svg**（`src/icons.js`，离线；`arrowRight`/`chartLine`/`quote`/
    `chevronUp`/`chevronDown`/`externalLink`/`trash`/`puzzle`/`lock` 是这一版补的），
    "调用次数"换成本地真有的**文件数**（要真计数得动后端，另说）。

★★ **改这一页必看的坑**（全是真踩过的）：
  1. **`computed` 里不能放"要传参"的助手**（`V-291`）：模板里 `tagIcon(t)` 一调就
     `tagIcon is not a function`，**整块弹窗画不出来**；pro版 Vue 把错误吞掉，
     表现只是"点了没反应"。带参数的助手一律放 `methods`。
  2. **`v-html` 会把它所在元素的文字整块替换掉**（`V-291`）：图标必须包一层 span 再 `v-html`。
  3. **就地写的 DOM 模板里 `v-else-if` 链不保险**（`V-290`）：`<transition-group>` 后面接一串
     `v-else-if` 时，条件为 false 的那条也会留下来（墙上出着卡片、底下同时显示"还没有技能"）。
     现在三条空状态是**各自独立的 `v-if`**（`noMatch` / `noSkills` / `notReady`）。
  4. **技能自己的 svg / 文件类型图标都要显式定尺寸**：`icon_svg` 里 `width:100%` 会输给
     `.skill-icon-wrap` / `.detail-icon-wrap` 的 `display:grid`，图标会缩成一小点。
  5. **挂载要上锁 + 等 DOM**：`app.mount()` 返回 `undefined`，见 `src/app.js` 底下那段注释。
  6. **模板里叫的名字必须在 `data`/`methods` 里真有**（`V-292`）：模板三处 `@click="retry"`
     一直是悬空的（代码里只有 `retryLater`）—— 点「刷新」/「重试」抛 `retry is not a function`，
     Vue 的 prod 版把它吞掉，表现只是"点了没反应"。已补齐 `retry()`。
  7. **`#status` 必须是 `<p>`**：外部检查可能按 `</p>` 收尾读取文字。
     另外**别往里塞超长的内联提示** —— 错误态那句"自动重试…`moss :skill`"原来内联在这里，
     会把搜索/按钮挤换行；现在收进错误面板常驻（工具条只留「读不出来 —— 后端没上来。」）。

★「补回出厂样例」那颗按钮 / `moss :skill seed` / 自动回填**都已删**（`V-288`/`V-289`）。
  ★ `V-292` 起**没有分段控件了**（`V-293` 沿用）：它原来只有「全部技能 / 只看要处理的」两段，
  而第二段在"没有要处理的东西"时不出现 ⇒ 那颗「全部技能」就成了唯一选项、点了也没用。
  现在只留一颗**「待处理 N」开关**，且**只在真有待处理时才出现**。

## 界面协议（`ui/src/api.js` → 后端 `core.Api`）

| 方法 | 干什么 |
|---|---|
| `list` | 墙要的全部数据（技能 + 目录；**只有技能**，插件不出现，`V-284`） |
| `read {id}` | 某个技能里各文件的正文 |
| `doc {id}` | 这只技能**自己的说明书**（它目录里的 `AGENT.md`） |
| `plan {id, new_id?}` | 转插件之前的**只算不改**检查（id 冲突） |
| `promote {id, confirm, new_id?}` | 真转（搬目录 + 改 id + 授权跟着走） |
| `allow {id, yes}` / `rm {id, confirm}` | 允许 / 撤销 / 删除 |
| `run_once {id, args}` | 试跑一次（走的是 AI 那条一样的路：stdin JSON → stdout） |
| `reveal {dir}` | 在资源管理器里打开这个技能的目录 |
| `open_path {path, raw?, mode}` | **输出里那些路径链接走的它**（`V-301` 加、`V-346` 改成两种开法）：`mode="open"` = 直接打开（文件交给默认程序、目录就打开它）/ `mode="reveal"` = 在资源管理器里打开**它所在的文件夹**并选中它。`raw` 是**没修剪过的原样**候选，先拿它试（文件名里真带全角括号时能救回来）；不在就按标点从右往左退、再退到最长的存在祖先 |
| `sys_copy {text}` | 放进剪贴板（界面"复制路径"和"**复制文件内容**"都用它；`V-290` 加，tkinter 实现） |

★ **路径链接那两个动作**（`V-346`，`ui/src/paths.js`）：输出的每一处路径都渲染成
**路径本身**（`<a class="plink" data-act="open">`，点了直接打开）+ **紧跟一颗小文件夹图标**
（`<button class="plink-dir" data-act="reveal">`，点了开所在文件夹）。两者都走上面那个 `open_path`。
抠路径时尾巴上那段说明文字要剪干净（`…114021.png（7680×2160，9125074 字节）` 里的括号部分）——
但**名字里真带全角括号的不许剪**（`截图（1）.png`），判据和踩过的坑都写在 `paths.js` 文件头。
