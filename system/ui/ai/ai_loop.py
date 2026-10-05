# -*- coding: utf-8 -*-
"""AI 工作台的 **loop**（`V-230` / `V-231`）—— 能**直接在命令行跑**，先不碰界面。

    system\\runtimes\\python\\3.12\\python.exe system\\ui\\ai\\ai_loop.py "给我写个 dazi 包"

为什么先做"没有界面的 loop"（你选的 B①）
----------------------------------------
难度和风险**九成在 loop 里**：工具给得对不对、上下文裁得够不够、**怎么算"做完了"**。
界面只是它的显示器。所以在命令行里先把它跑通、把 `usage` 打出来看清楚，再给它一张脸。

三条设计（都来自 `V-230` 的结论）
----------------------------------
1. **提示词是数据文件，两层**：`system/ui/ai/prompts/*.md` 是出厂默认，
   `user_data/ai/prompts/*.md` 同名覆盖（守你定的 `user > system`）。
   改提示词 = 改一个 md + 重启 moss，不用碰 py、更不用重打包。
   **契约正文不抄进来** —— 要用就由 `spec` 工具**当场从契约文件里切**（唯一真相只有一份）。
2. **结束条件是硬闸**：`done` 之前必须有过一次"最后一次改动之后、退出码 0"的运行，
   否则把话打回去让它继续（`ai_tools.Tools.verified()`）。**不是**"模型说完成了"。
3. **每步记 token**（`usage`）：把"啰嗦/费"从感觉变成数字 —— 这也是将来跟 DSH 对比的尺子。
"""
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import ai_client as C                                                 # noqa: E402
import ai_edits as E                                                  # noqa: E402
import ai_selftools as ST                                             # noqa: E402  (V-280：它自己造的工具)
import ai_skills as K                                                 # noqa: E402  (V-278：技能)
import ai_tools as T                                                  # noqa: E402

#: 每次都要装的两份（人格与硬规矩 / 改文件的格式约定）
BASE_PROMPTS = ("system", "edit")

# ★ `V-278`：原来这里有一张"按任务关键词整段注入片段"的表（`FRAGMENT_RULES` +
#   `pick_fragments`）—— 任务里出现"写/新/建"就把 `new_pkg.md` 全文塞进系统提示。
#   问题：**靠猜**（关键词命中 ≠ 需要它）、**不好扩展**（加一门只能改 Python 这张表）、
#   **带不了东西**（技能目录里该能放样板/骨架）。现在改成 Pi 那套：系统提示里**只列
#   "名字 + 描述 + 路径"**，正文由模型自己 `skill(名字)` 读（实现见 `ai_skills.py`）。


def _parse_skill_placeholder():        # 占位：真正的技能逻辑在 `ai_skills.py`（`V-278`）
    return None


def prompts_dirs():
    """**基底提示词**的两层：**后面的覆盖前面的**（user > system）。

    ★ `V-278`：这里只剩"每次都要装"的那两份（`system.md` 人格+硬规矩、`edit.md` 改文件
      的格式与收尾闸）；"写新包 / 收拖入"这类**方法论**搬去了 `system/skills/`，
      **按需读**（见 `ai_skills.py`）。
    """
    return [E.HOME / "system" / "ui" / "ai" / "prompts",
            E.user_data() / "ai" / "prompts"]


def find_prompt(name):
    """找一个提示词文件（**后写的层赢**：`user_data` 盖 `system`）。回 `(文本, 来源路径)`。"""
    for d in reversed(prompts_dirs()):
        p = d / (name + ".md")
        if p.is_file():
            try:
                return p.read_text(encoding="utf-8", errors="replace"), p
            except OSError:
                continue
    return "", None


def missing_prompts(names):
    """哪些提示词**两层都找不到**（界面要拿它报错 —— 不搞隐形兜底，否则用户只觉得"AI 变笨了"）。"""
    return [n for n in names if not find_prompt(n)[1]]


#: `V-260`：`disp` 最长给多少（`done` 的 summary 可能是一整段回答，别无限大）
DISP_MAX = 4000


def _step_disp(name, args):
    """这一步**给人看**的内容（完整、不截 JSON）。

    ★ 为什么要在宿主这边拼：界面只拿到 `brief[:70]`（那是**给一行摘要**用的），
      JSON 被截断 ⇒ `JSON.parse` 失败 ⇒ 只能把 `{"summary": "……` 这种原始串摆给用户
      （`V-260` 用户原话："像是一个字典，而不是显示里面的文本"、"回复长了看不全"）。
      宿主手里有**完整参数**，就在这儿拼好，界面直接显示。
    """
    a = args or {}
    # ★ `V-269` 补（真机截图）：`done` / `answer` 的正文**不再重复贴进步骤卡** ——
    #   它马上就出现在下面那张结论卡（✅ 验收通过 / 💬 回答）里，两处都贴 = 同一段话
    #   在屏幕上出现两遍（你截图里那段回答就是这么重复的）。步骤卡只留"干了什么"。
    if name in ("done", "answer"):
        return ""
    if a.get("path"):
        return str(a["path"])
    if a.get("args"):
        return "moss " + str(a["args"])
    if a.get("section"):
        return "契约：" + str(a["section"])
    if a.get("id"):
        return str(a["id"])
    try:
        return json.dumps(a, ensure_ascii=False)[:DISP_MAX]
    except (TypeError, ValueError):
        return str(a)[:DISP_MAX]


def compose_system(task, extra=(), self_tools=None):
    """拼出这次的系统提示：两份基底 + **技能清单**（正文不进！）+ 点名要装的技能正文。

    回 `(文本, 用了哪些, 缺了哪些)`。

    ★ `V-278`：`extra` 是**点名要加载的技能**（相当于 Pi 的 `/skill:名字`）—— 平时留空，
      正文由模型自己 `skill(名字)` 按需读；清单里只放"名字 + 描述 + 路径"。
    ★ 任务原文（`task`）不再参与挑选：以前靠关键词猜，现在不猜了。
    ★ `V-280`：`self_tools` 是**这次跑已经允许它用的自制工具** —— 只在**真有**的时候加一段
      （"你已经有哪些手"），一只都没有就一个字都不加（不加噪音）。
    """
    names = list(BASE_PROMPTS)
    parts, used, missing = [], [], []
    for n in dict.fromkeys(names):                                   # 去重且保序
        text, where = find_prompt(n)
        if not where:
            missing.append(n)
            continue
        used.append("%s ← %s" % (n, where))
        parts.append(text.strip())
    # 点名的技能：正文直接装上（`extra`）
    for n in dict.fromkeys(list(extra or ())):
        got = K.list_skills().get(str(n))
        if not got or not got["body"]:
            missing.append(str(n))
            continue
        used.append("技能 %s ← %s" % (n, got["path"]))
        parts.append(got["body"])
    # 清单：**只有名字 + 描述 + 路径**（正文不进系统提示 —— 这是整套设计的关键）
    note = K.note()
    if note:
        parts.append(note)
        used.append("技能清单（%d 个：%s）" % (len(K.usable()), "、".join(K.names()) or "无"))
    # `V-280`：它自己的手（有才写）
    mine = ST.note(self_tools)
    if mine:
        parts.append(mine)
        used.append("自制工具（%d 个：%s）" % (len(self_tools or {}), "、".join(sorted(self_tools or {}))))
    return "\n\n---\n\n".join(parts), used, missing


def env_note(workdir=None):
    """给模型几句"它现在在哪"的事实（进程内拿得到，别让它去猜）。

    ★ `V-248`：真机上它把同级的别的包（`ask`/`dazi`/`unwx`）全翻了一遍，用户的原话是
      "我选的干活的地方是 calc，它怎么疯狂的读取一堆其他的内容" —— 所以这里**把目标写进句子里**，
      并明说"样板看 `system/pkgs/bmi`，别翻别的包"（读守卫也会拦，见 `check_readable(scope=…)`）。
    """
    tgt = str(workdir or E.write_root())
    return ("【环境】moss 安装根 = %s；**这次干活的地方 = %s**。"
            "只看这个目录（加上契约和 `system/pkgs/bmi` 那个样板）—— **别去翻别的包**。"
            "要写只能写 `%s` 下面；跑包用 run_moss（等价于用户在终端敲 moss）；"
            "契约按需读**相关那一节**就够（`spec(\"关键词\")`），别通读。契约文件 = %s"
            % (E.HOME, tgt, E.write_root(), T.spec_path()))


class Loop:
    """一个任务一次 loop。`client` 只要有 `.chat(messages, tools)` 这个方法就行（探针会塞假模型进来）。"""

    def __init__(self, client, workdir=None, max_steps=200, on_step=None, say=print,
                 compact_after=6, keep_recent=12, compact_min=3,
                 compact_at=102400, retain_tokens=20480, stop_check=None,
                 soft_steps=0, max_tokens=100000000, on_phase=None, on_snapshot=None):
        self.client = client
        # ★ `V-269`：快照**不再开工就存**，改成"第一次真要写文件之前"存（`_before_first_write`）。
        #   原话那次的教训：你问一句「你是哪个大模型」，它也给你存了一条备份。
        self.snapshot = None
        self.want_snapshot = True
        self.task = ""
        # ★ `V-280`：**这一次跑**的工具表在开工这一刻定死 —— 内置那些 + 已经允许它用的自制工具。
        #   它这一次新造的手**下一次**才进表（也正好卡在"用户还没点允许"那一步）。
        try:
            self.self_tools = ST.usable(avoid=T.builtin_names())
        except Exception:                                              # noqa: BLE001
            self.self_tools = {}
        self.tool_table = T.tools_for(self.self_tools)
        self.tools = T.Tools(workdir=workdir, before_write=self._before_first_write,
                             self_tools=self.self_tools)
        #: 现在在干什么（`V-242`：界面上显示"等模型回话 12s / 执行工具"，
        #  免得"模型在想"看起来像"卡死了"）
        self.on_phase = on_phase
        #: ★ `V-250`：开工前那条快照**存好就立刻喊一声** —— 界面（版本快照边栏）要跟着
        #  刷新，不然你切过去看不见它刚存的那条（真机就是这么漏的）。
        #   以前只有跑完才从 `result.snapshot` 里看得到，而快照其实是**第一步之前**就存了的。
        self.on_snapshot = on_snapshot
        self.wait_note = 0.0
        #: `V-270`：现在这一轮的序号（重试那行要用它）—— `_on_retry` 里读
        self.cur_n = 0
        # ★ `V-239`（你定的）：预算**按 token 算**，不再让你算步数。
        #   步数那两样（`soft_steps` 软提醒 / `max_steps` 硬顶）**退居幕后当兜底** ——
        #   防的是"一直调工具但几乎不烧 token"那种死循环，不是你要调的旋钮。
        #   `max_tokens` 才是主闸：到 80% 劝收尾、到 100% 停手汇报。
        self.max_steps = int(max_steps or 200)
        self.soft_steps = int(soft_steps or 0)
        self.max_tokens = int(max_tokens or 0)
        self.warned_token = False
        self.on_step = on_step
        self.say = say
        #: 界面按「停止」时用它（每一轮开头问一次，不用打断正在跑的那次请求）
        self.stop_check = stop_check
        #: 历史压缩（`V-232` / `V-241`）：消息攒够 `compact_after` 条、且能折的**至少
        #: `compact_min` 条**时才动一次；最近 `keep_recent` 条逐字留着。
        self.compact_after = int(compact_after)
        self.keep_recent = int(keep_recent)
        self.compact_min = int(compact_min)
        #: ★★ `V-244`：**照 DSH 的参数**（`dsh-compaction-basic`）——
        #: `compact_at` ≈ 上下文窗口 × 0.8（到这儿才开始压）、
        #: `retain_tokens` ≈ 窗口 × 0.16（最新的这些**逐字保留**，一个字不动）。
        #: 触发用的 `prompt_tokens` 是 **API 回来的真实值**（不是估的）。
        self.compact_at = int(compact_at or 0)
        self.retain_tokens = int(retain_tokens or 0)
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self.steps = []
        self.folded = 0
        #: ★ `V-251`：这条会话的消息表（收尾时交给界面存盘 —— "接着聊"靠它）
        self.messages = []
        self.continued_from = ""

    def _compact(self, messages):
        """上下文压缩：**照 DSH 那套策略，但只做"本地修剪"这一级**。

        原理（一句话）：这类 API **不带记忆** —— 每一轮都要把「系统提示 + 工具说明 +
        迄今为止的全部历史 + 这一步的新结果」**重新发一遍**。所以"上下文"就是历史的长度，
        它会一直涨；涨到窗口装不下就报错，涨得越大越贵（而且缓存没命中时是**每条都重算**）。

        什么时候压（`V-244`，DSH 的 `thresholdRatio = 0.8`）：
            上一轮**实际发出去**的 `prompt_tokens` ≥ `compact_at` 才开始压。
            不到这条线**一条都不折** —— 便宜，而且模型看得见全部历史，不会重读。

        留多少（DSH 的 `retainRatio = 0.16`）：
            从**最新**往回数，累计到 `retain_tokens` 为止的这段**逐字保留**；
            比它更早的工具结果只留**第一行**（本地修剪，**不发模型调用**）。

        跟 DSH 的两点差别（都在诚实账上）：
          · DSH 修剪完若仍高于阈值，会**再发一次模型请求写摘要**（`maxTokens 8192`）替换掉那段；
            我们**不做摘要**（那要多花一次调用），所以极端长任务里"更早的历史"只剩一行标题。
          · 它的 token 是精确计量的（`dsh-token-meter` + tokenizer）；我们的"保留量"是**估算**
            （`ai_budget.est_tokens`，len/3）。**触发**用的是真实 `prompt_tokens`，所以准。

        ★ 为什么不能折太勤（真机踩过两次）：折掉的内容模型就看不见了 ⇒ 它**重读**
          （实测把一个文件 grep 了十几遍），省下的 token 又从重读里花回去。
        """
        if len(messages) <= self.compact_after:
            return 0
        if self.compact_at and (self.usage.get("prompt_tokens") or 0) < self.compact_at:
            return 0                                    # 压力没到 —— 一条都不动
        # 从最新往回数，保留 retain_tokens 那么长的"逐字尾部"
        import ai_budget as B                                            # noqa: PLC0415
        keep_from = len(messages)
        budget = self.retain_tokens
        while keep_from > 2:
            m = messages[keep_from - 1]
            cost = B.est_tokens(m.get("content")) + 12          # 12 ≈ 每条消息的固定开销
            if budget - cost < 0 and keep_from < len(messages):
                break
            budget -= cost
            keep_from -= 1
        cut = min(len(messages) - self.keep_recent, keep_from)   # 至少留 keep_recent 条兜底
        targets = []
        for m in messages[2:max(2, cut)]:
            role, content = m.get("role"), str(m.get("content") or "")
            if content.startswith("[早先") or content.startswith("【工具结果】[早先"):
                continue
            if role == "tool" or (role == "user" and content.startswith("【工具结果】")):
                targets.append(m)
        if len(targets) < self.compact_min:
            return 0
        for m in targets:
            content = str(m.get("content") or "")
            head = content.strip().splitlines()[0][:80] if content.strip() else ""
            if m.get("role") == "tool":
                m["content"] = "[早先的结果已折叠] " + head
            else:
                m["content"] = "【工具结果】[早先的已折叠] " + head
        return len(targets)

    def _add_usage(self, u):
        """累加 token 用量，并记住"这一轮实际发出去多少输入 token"（压缩的触发条件）。"""
        for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
            try:
                self.usage[k] += int((u or {}).get(k) or 0)
            except (TypeError, ValueError):
                pass
        try:
            self.usage["last_prompt"] = int((u or {}).get("prompt_tokens") or 0)
        except (TypeError, ValueError):
            pass

    def _on_wait(self, seconds):
        """请求等了一会儿还没数据（`V-242`）：把"等了多久"报给界面，别让它看起来像死机。

        （重写 `_compact` 时我把这个方法一起切掉了 —— 探针当场报
          `'Loop' object has no attribute '_on_wait'`，这就是"改完必须跑一遍"的价值。）
        """
        self.wait_note = seconds
        if self.on_phase:
            self.on_phase("waiting")

    def _on_retry(self, attempt, times, err):
        """`V-270`：网络抖了一下、这条请求**根本没发出去**，正在重发 —— 说出来。

        ★ 为什么要占一行步骤：真机那次 DNS 抖了 4 分钟，连着 4 条任务全报
          `[Errno 11001] getaddrinfo failed`，界面上只有一句"模型那边出错"，看不出是网络
          还是我们坏了。现在它会自己重试两回，重试这件事也让你看得见。
        """
        self._step(self.cur_n or 1, "(重试)",
                   "没连上：%s" % str(err)[:70],
                   "%s后重发（第 %d 次，共 %d 次）"
                   % (("%.1f 秒" % C.RETRY_WAITS[min(attempt - 1, len(C.RETRY_WAITS) - 1)]),
                      attempt, times))
        self.say("  网络抖了一下（%s）—— 正在重发（第 %d/%d 次）" % (err, attempt, times))

    def _step(self, n, tool, brief, note="", ms=0, disp="", nodisp=False):
        row = {"n": n, "tool": tool, "brief": brief, "note": note, "ms": int(ms or 0),
               # ★ `V-260`：给人看的那一份（完整的路径 / 完整的 summary）—— 界面优先用它
               "disp": disp,
               # ★ `V-269` 补：`nodisp=True` = **这一步没有正文可摆**（`done` / `answer` 的正文
               #   归下面的结论卡）。为什么单独一个键、不拿"disp 是空串"当信号：
               #   `(说话)` / `(打回)` / `(重试)` 这几张本来就没有 `disp`、正文是从 `brief`
               #   反解出来的（老记录也这样）—— 混用会把它们的正文一起弄没。
               "nodisp": bool(nodisp),
               "tokens": self.usage["total_tokens"], "folded": self.folded,
               # `V-244`：这一轮真实发出去的输入 token（= 现在上下文多长）—— 界面据此显示
               "ptok": int(self.usage.get("last_prompt") or 0)}
        self.steps.append(row)
        self.say("  [%d] %-10s %s%s" % (n, tool, brief, ("  " + note) if note else ""))
        if self.on_step:
            try:
                self.on_step(row)
            except Exception:                                        # noqa: BLE001
                pass

    # ------------------------------------------------------------------ 主循环
    def _before_first_write(self):
        """第一次真要写文件之前：存"动手前"的快照（`V-269`，从开工就存改过来的）。

        ★ 为什么由 `Tools` 来喊：只有它知道"这一刻要动盘了"。快照必须在**写之前**落盘
          —— 存"已经改了一半"的样子等于没存。
        ★ `V-250` 那条不变：**存好就立刻通知界面**（版本快照那一列要刷新出来），
          不然你要等跑完才看得见它刚存的那条。
        """
        if not self.want_snapshot or self.snapshot:
            return
        import ai_snap as S                                              # noqa: PLC0415
        got = S.snapshot_before(self.task, self.tools.workdir)
        if got.get("ok"):
            self.snapshot = {"id": got.get("id"), "group": got.get("group")}
            self.say("动手前存了快照：%s（分组 %s）" % (got.get("id"), got.get("group")))
            if self.on_snapshot:
                try:
                    self.on_snapshot(self.snapshot)
                except Exception:                                        # noqa: BLE001
                    pass
        else:
            self.say("（没存动手前的快照：%s）" % got.get("msg"))

    def run(self, task, extra_fragments=(), snapshot=True, history=None, from_id=""):
        """跑一次任务。

        `history`（`V-251`）：**接着上次那条会话聊** —— 上一次跑完时留下的对话
        （`ai_runs` 里存着）。给了它就把那些轮次接在系统提示后面，这次的任务作为
        **新的一句**追加在后面。★ 只接 `system` 以外的轮次：系统提示每次都用**现在的**
        契约/提示词重拼（不然改完提示词、老会话还带着老规矩）。
        ★ 空会话（`[]`）和没给一样 —— 别把"新开一条"变成"少发一条用户消息"。
        `from_id`：这条会话是从哪条记录接过来的（写进新记录，界面上能看出链条）。
        """
        sys_text, used, missing = compose_system(task, extra_fragments, self.self_tools)
        self.task = str(task or "")
        self.want_snapshot = bool(snapshot)
        old = [m for m in (history or []) if str(m.get("role")) != "system"]
        messages = [{"role": "system", "content": sys_text}] + old + \
                   [{"role": "user", "content": "%s\n\n%s" % (task, env_note(self.tools.workdir))}]
        # ★ `V-251`：这个列表就是"这条会话" —— 全程只 append/就地改（底下没有重新赋值），
        #   所以收尾时（`_finish`）把它原样交出去，界面存盘、下次接着聊。
        self.messages = messages
        self.continued_from = str(from_id or "")
        if old:
            self.say("接着上次那条聊：它还记得之前 %d 条对话" % len(old))
        self.say("提示词：%s%s" % ("；".join(used),
                                 ("；**缺**：" + "、".join(missing)) if missing else ""))
        # ★ `V-236`：**动手前先给这个包存一条快照**（`by="ai"` + 这次的任务原文）。
        #   改坏了要能一键回去；存不上也照干（只是没退路，而且会如实说）。
        # ★ `V-269`：**什么时候存**改了 —— 原来是这一行（开工就存），现在挂到
        #   `Tools.before_write` 上，等**第一次真的要写文件**时才存：
        #     · 纯问答（"你是哪个大模型"）不再白写一条备份；
        #     · 快照点也更准（贴着你真正要改的那一刻）。
        #   参数 `snapshot=False` 照旧能整个关掉。
        self.snapshot = None
        nudges, result = 0, {"ok": False, "reason": "步数用完了（还没验收通过）"}
        for n in range(1, self.max_steps + 1):
            if self.stop_check and self.stop_check():
                return self._finish(False, "用户按了停止", used, missing)
            # ★ `V-239`：**先劝后拦**（都按 token 算）。
            #   ① 到上限的 80% 劝一次收尾（DSH 那个 `agent/turn-stopping` 的介入点：
            #      用一句"该收了"去引导，而不是硬杀）；
            #   ② 烧到上限就停手汇报 —— 步数不好换算成钱，token 才是钱。
            total = self.usage.get("total_tokens") or 0
            if self.max_tokens and total >= self.max_tokens:
                return self._finish(self.tools.verified(),
                                    "token 到上限了（已烧 %d，上限 %d）" % (total, self.max_tokens),
                                    used, missing)
            if (self.max_tokens and not self.warned_token
                    and total >= self.max_tokens * 0.8):
                self.warned_token = True
                self._step(n, "(提醒)", "已烧 %d / %d token —— 催它收尾"
                            % (total, self.max_tokens), "token 提醒线")
                messages.append({"role": "user", "content":
                                 "★ 这次任务已经烧了 %d token（上限 %d，到顶就停）。**请收尾**："
                                 "要么现在 done(summary=…) 说清你改了什么、怎么验的；"
                                 "要么一句话说清卡在哪、还需要什么 —— 别再做新的探索性读取了。"
                                 % (total, self.max_tokens)})
            if self.soft_steps and n > 1 and (n - 1) % self.soft_steps == 0:
                self._step(n, "(提醒)", "已经第 %d 步了 —— 催它收尾" % (n - 1), "软提醒")
                messages.append({"role": "user", "content":
                                 "★ 已经第 %d 步了（这次任务的硬顶是 %d 步）。**请收尾**："
                                 "要么现在 done(summary=…) 说清你改了什么、怎么验的；"
                                 "要么一句话说清卡在哪、还需要什么 —— 别再做新的探索性读取了。"
                                 % (n - 1, self.max_steps)})
            folded = self._compact(messages)
            if folded:
                # 不再当成"一步"打进步骤流（`V-241`）：它是后台整理，不是 AI 干的活。
                # 只在**真折了一批**的时候说一句，次数累计给界面看。
                self.folded += folded
                self.say("（历史压缩：折叠了 %d 条旧结果，省输入 token）" % folded)
            try:
                if self.on_phase:
                    self.on_phase("thinking")
                self.cur_n = n
                resp = self.client.chat(messages, self.tool_table, stop_check=self.stop_check,
                                        on_wait=self._on_wait, on_retry=self._on_retry)
            except C.Stopped:
                # ★ `V-242`：请求**发到一半**按的停止 —— 立刻收工，不再等它把话说完。
                return self._finish(False, "用户按了停止", used, missing)
            except C.AiError as e:
                return self._finish(False, "模型那边出错：%s" % e, used, missing)
            self._add_usage(resp.get("usage"))
            native = bool(resp.get("native"))
            calls = resp.get("tool_calls") or []
            text = (resp.get("text") or "").strip()
            if not calls:
                # 它只是在说话（或说完了但没调工具）—— 催一次，最多两回
                nudges += 1
                self._step(n, "(说话)", text[:80] or "（空的）", "没调工具")
                if nudges > 2:
                    return self._finish(False, "模型连着 %d 次不调工具，停手：%s" % (nudges - 1, text[:200]),
                                        used, missing)
                messages.append({"role": "assistant", "content": text})
                messages.append({"role": "user", "content":
                                 "别只说话：要么调工具干活，要么干完了用 done(summary=…) 收工；"
                                 "**如果你只是在回答用户的问题、一个文件都不用改，就把你上面那段话"
                                 "原样写进 answer(text=…) 收工**（它不要求跑命令，别再重写一遍）。"})
                continue
            # ★ `V-247`：**按我们自己的 id 重建**这条 assistant 消息（别原样回灌）。
            #   原样回灌时，万一网关回的 tool_calls 没带 id（或 id 重复），我们这边发 tool 结果
            #   用的是"自己编的 id" ⇒ 两边对不上 ⇒ HTTP 400 "insufficient tool messages"。
            #   重建之后，assistant 里每个 tool_call 的 id 与下面每条 tool 消息**一一对应**。
            if native:
                seen = set()
                for _i, _c in enumerate(calls):
                    if not _c.get("id") or _c["id"] in seen:
                        _c["id"] = "call_%d_%d" % (n, _i)
                    seen.add(_c["id"])
                messages.append({"role": "assistant",
                                 "content": (resp.get("message") or {}).get("content") or None,
                                 "tool_calls": [
                                     {"id": c["id"], "type": "function",
                                      "function": {"name": c["name"],
                                                   "arguments": json.dumps(c.get("args") or {},
                                                                           ensure_ascii=False)}}
                                     for c in calls]})
            else:
                messages.append({"role": "assistant", "content": text or "（用文本协议调工具）"})
            # ★ 要给模型看的"人话"（打回 / 提醒）先攒着 —— **必须等这一轮所有 tool 结果都发完**
            #   才能追加，否则就会插在 tool 结果中间（就是那个 HTTP 400）。
            pending_notes = []
            for call in calls:
                if self.on_phase:
                    self.on_phase("tools")
                name = call.get("name")
                brief = json.dumps(call.get("args") or {}, ensure_ascii=False)
                _t0 = time.time()
                out = self.tools.call(name, call.get("args") or {})
                _ms = int((time.time() - _t0) * 1000)
                note = str(out).splitlines()[0][:70] if out else ""
                # ★ `V-260`：`brief[:70]` 是**给一行摘要**用的，可它把 JSON 截断了 ⇒
                #   界面 `JSON.parse` 失败、只能把 `{"summary": "……` 这种原始串摆给你看
                #   （你报的"像是一个字典，而不是显示里面的文本"，还有"回复长了看不全"）。
                #   这里另给一份 `disp`：**给人看的、完整的**（`done` 的 summary 一个字不截）。
                self._step(n, name, brief[:70], note, ms=_ms,
                           disp=_step_disp(name, call.get("args") or {}),
                           # `V-269` 补：这两个工具的正文归下面的结论卡，步骤卡不重复贴
                           nodisp=name in ("done", "answer"))
                if native:
                    messages.append({"role": "tool", "tool_call_id": call.get("id") or name,
                                     "content": str(out)})
                else:
                    messages.append({"role": "user",
                                     "content": "【工具结果】%s\n%s" % (name, out)})
                if name == "done":
                    if self.tools.verified():
                        return self._finish(True, "验收通过", used, missing,
                                            summary=str((call.get("args") or {}).get("summary") or ""),
                                            caveats=str((call.get("args") or {}).get("caveats") or ""))
                    nudges += 1
                    self._step(n, "(打回)", "done 但没验收", self.tools.gate_reason()[:70])
                    if nudges >= 3:
                        return self._finish(False, "说了几次都不去验收：" + self.tools.gate_reason(),
                                            used, missing)
                    msg = ("**还没验收**：" + self.tools.gate_reason() +
                           "（硬规矩：**要么改完之后跑通一次，要么确认不用改但真跑成功过**。）")
                    # ★ `V-247`：先攒着 —— 等这一轮所有 tool 结果发完再追加（见下面 pending_notes）
                    pending_notes.append(msg)
                elif name == "answer":
                    # ★ `V-269`：**纯问答的合法收工**（你问「你是哪个大模型」那次，它答完了却被
                    #   "别只说话"打回去、只好去翻目录跑命令 —— 白烧 3 万 token）。
                    #   规矩：**一个文件都没动过**才准走这条；动过文件的必须 run_moss + done，
                    #   否则这道口子就成了"绕开验收硬闸"的后门。
                    if self.tools.edit_seq == 0:
                        # ★ `V-269` 补（两张真机截图）：纯问答这轮**步骤卡一张都不画** ——
                        #   `(说话)` 那张是"它先说了一句"，`answer` 那张的正文又和下面的
                        #   「回答」卡**一模一样**（你原话："如果后面回答要显示的话，那么中间
                        #   这个其它 answer 就不需要显示才对"）。所以两张都标 `mute`。
                        #   ★ 数据**一条不少**地留在记录里（`steps` 仍带 `mute`）—— 只是不摆到脸上；
                        #     token / 步数照实记，干活那几轮照旧显示（那边是有信息量的）。
                        for _s in self.steps:
                            if _s.get("tool") in ("(说话)", "answer"):
                                _s["mute"] = True
                        return self._finish(
                            True, "问答收工（没动文件，不用跑命令）", used, missing,
                            summary=str((call.get("args") or {}).get("text") or ""),
                            caveats=str((call.get("args") or {}).get("caveats") or ""),
                            kind="chat")
                    pending_notes.append(
                        "你这次**已经改过文件**了（第 %d 次），不能用 answer 收工 —— "
                        "answer 只给\"一个字都没改\"的问答用。现在去 run_moss 跑通（退出码 0），"
                        "再用 done(summary=…) 收尾。" % self.tools.edit_seq)
                elif name == "run_moss" and str(out).startswith("退出码 0") and self.tools.verified():
                    # ★ `V-232`：真跑通了就**主动说一声**。第一次真跑时它跑通之后没来得及
                    #   再调 done（轮次用完），差的就是这一句。
                    # ★ `V-237`：没改动也适用 —— "看完了发现不用改"同样是合法结局。
                    pending_notes.append(
                        "已经跑通（退出码 0），而且这次运行**满足验收条件**"
                        "（改动之后跑的，或者你本来就没改、只是验证它能跑）。"
                        "如果这就是你要的结果，现在用 done(summary=…) 收工 —— "
                        "summary 里把「怎么用」也写清楚（用户要的是这个）。")
            # ★ `V-247`：这一轮所有 tool 结果发完之后，再追加"人话"（顺序反了就是 HTTP 400）
            for _note in pending_notes:
                messages.append({"role": "user", "content": _note})
            result = {"ok": False, "reason": "步数用完了（%d 步）" % self.max_steps}
        # ★ `V-237`：**步数用完 ≠ 失败**。要是它其实已经验收通过（最后一次改动之后跑通过，
        #   或者没改动但真跑成功过），只是没来得及说 `done` —— 那就照实判通过，
        #   并在原因里写清"它没来得及收工"。真机那次（`calc` 本来就支持指数）就卡在这儿。
        if not result["ok"] and self.tools.verified():
            return self._finish(True, "步数用完了（%d 步），但**验收已经通过**（它没来得及说 done）"
                                      % self.max_steps,
                                used, missing,
                                summary="（它没来得及写 summary —— 看上面的步骤流：%s）"
                                        % "、".join(s["tool"] for s in self.steps[-4:]),
                                caveats="收尾没有正常结束（步数用完），结论以跑过的命令为准。")
        return self._finish(result["ok"], result["reason"], used, missing)

    # ------------------------------------------------------------------ 收尾
    def _finish(self, ok, reason, used, missing, summary="", caveats="", kind="work"):
        return {"ok": bool(ok), "reason": reason, "summary": summary, "caveats": caveats,
                # ★ `V-269`：`kind="chat"` = 这次只是**回答**（没动文件、不用验收）——
                #   界面拿它把结论卡写成「💬 回答」而不是「✅ 验收通过」。
                "kind": str(kind or "work"),
                "steps": self.steps, "usage": dict(self.usage),
                "prompts": used, "missing_prompts": missing, "tools_log": self.tools.log,
                "files": list(self.tools.changed), "folded": self.folded,
                "snapshot": getattr(self, "snapshot", None),
                # ★ `V-251`：**把这一整条对话留下来** —— 界面存进任务记录，
                #   下次点「接着聊」就把它接上去（不然重启 moss 只能从头再来）。
                #   存的是**收尾时**的消息表（`_compact` 已经折过的那些，所以不算大）。
                "messages": self.messages,
                "continued_from": getattr(self, "continued_from", "")}


# ---------------------------------------------------------------------- 命令行
def run_cli(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        print("用法：ai_loop.py \"<任务>\" [--workdir 目录] [--max-steps N] [--soft-steps N] "
              "[--max-tokens N] [--model 模型]")
        return 0 if argv else 2
    task, workdir, max_steps, soft_steps, max_tokens, model = argv[0], None, 200, 50, 0, None
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--workdir" and i + 1 < len(argv):
            workdir = argv[i + 1]; i += 2
        elif a == "--max-steps" and i + 1 < len(argv):
            max_steps = int(argv[i + 1]); i += 2
        elif a == "--soft-steps" and i + 1 < len(argv):
            soft_steps = int(argv[i + 1]); i += 2
        elif a == "--max-tokens" and i + 1 < len(argv):
            max_tokens = int(argv[i + 1]); i += 2
        elif a == "--model" and i + 1 < len(argv):
            model = argv[i + 1]; i += 2
        else:
            print("不认识这个参数：%s" % a)
            return 2
    try:
        client = C.Client.from_env(model=model)
    except C.AiError as e:
        print("[错误] %s" % e)
        return 2
    print("模型：%s（%s）" % (client.model, client.base_url))
    print("任务：%s" % task)
    print("预算：硬顶 %d 步、每 %d 步提醒一次%s"
          % (max_steps, soft_steps, ("、token 闸 %d" % max_tokens) if max_tokens else ""))
    t0 = time.time()
    got = Loop(client, workdir=workdir, max_steps=max_steps, soft_steps=soft_steps,
               max_tokens=max_tokens).run(task)
    print()
    print("=" * 68)
    print("%s —— %s" % ("💬 回答" if got.get("kind") == "chat"
                        else ("✅ 验收通过" if got["ok"] else "✗ 没通过"), got["reason"]))
    if got.get("summary"):
        print("它说改了什么：%s" % got["summary"])
    if got.get("caveats"):
        print("它自己标的不确定：%s" % got["caveats"])
    u = got["usage"]
    print("步数 %d（%d 次工具调用）· 用时 %.1f 秒 · token：输入 %d / 输出 %d / 合计 %d"
          % (len(got["steps"]), len(got["tools_log"]), time.time() - t0,
             u["prompt_tokens"], u["completion_tokens"], u["total_tokens"]))
    if got.get("missing_prompts"):
        print("⚠ 提示词缺失（两层都没有）：%s" % "、".join(got["missing_prompts"]))
    return 0 if got["ok"] else 1


if __name__ == "__main__":
    sys.exit(run_cli())
