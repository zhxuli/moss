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
import ai_skills as K                                                 # noqa: E402  (V-278：写法指南)
import ai_tools as T                                                  # noqa: E402

# ★ `V-281`：技能（能干活的那些）的规矩住在 `system/ai/skill_lib.py` —— 宿主和 `:skill` 插件共用。
_SK = str(E.HOME / "system" / "ai")
if _SK not in sys.path:
    sys.path.insert(0, _SK)
import skill_lib as ST                                                # noqa: E402

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
#: `V-315`：**每一步的原始参数与原始输出**各留多少字（用户要"能点开看它到底干了什么"）
#:   —— 为什么要有上限：一条记录要留 60 条（`ai_runs.KEEP`），`read_file` 一次能回 20000 字，
#:   不截的话单条记录就能到几百 KB。**没截断的那一份在「提示词」那一层里**（`messages` 里
#:   存的是原样发给模型的内容），所以这里截了也不会真的丢掉线索。
ARG_MAX = 4000
OUT_MAX = 6000


def _clip(v, n):
    """把"要给人点开看"的东西截到一个上限（超了就在末尾写明截了多少）。

    `v` 可以是 str（原样）或 dict/list（转成 JSON 文本）。空值回 `""`。
    """
    if v is None or v == "":
        return ""
    if isinstance(v, (dict, list)):
        try:
            s = json.dumps(v, ensure_ascii=False, indent=1)
        except (TypeError, ValueError):
            s = str(v)
    else:
        s = str(v)
    if len(s) <= n:
        return s
    return s[:n] + "\n……（已截到 %d 字；**没截断的那一份在「提示词」里**）" % n


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
    # ★ `V-308`：问用户那一步要把它**问的什么 / 答的什么**摆出来（这是最有信息量的一步）
    if name == "ask":
        return str(a.get("question") or "")
    if name == "allow_path":
        return str(a.get("path") or "")
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
    ★ `V-280`/`V-281`：`self_tools` 是**这次跑已经允许它用的技能** —— 只在**真有**的时候加一段
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
        used.append("技能（%d 个：%s）" % (len(self_tools or {}), "、".join(sorted(self_tools or {}))))
    return "\n\n---\n\n".join(parts), used, missing


def env_note(workdir=None, perm="", tmp="", allow=()):
    """给模型几句"它现在在哪 / 能读能写哪儿"的事实（进程内拿得到，别让它去猜）。

    ★ `V-248`：真机上它把同级的别的包（`ask`/`dazi`/`unwx`）全翻了一遍，用户的原话是
      "我选的干活的地方是 calc，它怎么疯狂的读取一堆其他的内容" —— 所以这里**把目标写进句子里**，
      并明说"样板看 `system/pkgs/skill`，别翻别的包"（读守卫也会拦）。
    ★ `V-316`：权限那一段现在是**用户勾出来的清单**（`ai_mode.perm_note`）—— 直接贴进来，
      它才知道哪几处能写、写不了该用 `allow_path` 问谁。
    """
    tgt = str(workdir or E.write_root())
    out = ("【环境】moss 安装根 = %s；**这次干活的地方 = %s**。"
           "只看这个目录（加上契约和 `system/pkgs/skill` 那个出厂插件样板）—— **别去翻别的包**。"
           "跑包用 run_moss（等价于用户在终端敲 moss）；"
           "契约按需读**相关那一节**就够（`spec(\"关键词\")`），别通读。契约文件 = %s"
           % (E.HOME, tgt, T.spec_path()))
    if perm:
        out += "\n【权限】" + str(perm)
    if allow:
        out += "\n【清单里另外勾了读/写的】%s" % "；".join(str(x) for x in allow[:8])
    if tmp:
        out += ("\n【临时空间】你自己的临时目录 = `%s`（你跑的子进程 `TMP`/`TEMP` 也指到它）。"
                "要落中间文件、解压、生成草稿就写这儿 —— 用户会定期清理它，"
                "**别往系统临时目录或包目录里丢垃圾**。" % tmp)
    out += ("\n【每一步都要写 why】调任何工具都带上 `why=\"…\"`（一句话说清这一步的目的）—— "
            "用户看 `run_moss` 这种工具名看不懂你要干嘛。\n"
            "【拿不准就问】要动的东西有歧义、有不止一种做法、要删/覆盖东西 —— "
            "**先用 `ask` 工具问用户**（可以给选择题），别自己猜着往下冲。")
    out += ("\n【图片】需要看 png/jpg/gif/webp/bmp 时用 `read_image`，它会作为视觉输入直接交给模型；"
            "**不要用 read_file 读图片，也不要把 OCR 当第一选择**。列表里带 [图片] 的就是可以直接看的图。")
    # ★ `V-382`：把"备份"这件事作为**事实**告诉它 —— 以前提示词里一个字都没有，
    #   于是它（a）以为没备份、慌了去手动 `--snap save`；（b）收尾时把自动存的那条
    #   当垃圾清掉（`snap_clean` → "别占着用户地方"）。两头都是同一个坑：它不知道有退路。
    out += ("\n【备份是宿主做的，不许你动】第一次改文件之前，宿主会**自动**存一条"
            "「动手前」快照（`by=ai`，标题就是这次的任务原文）。所以：\n"
            "  · **不用**自己 `--snap save`（重复存只是浪费，也不会更安全）；\n"
            "  · **不许删**（没有任何删快照的工具；`--snap rm/gc` 会被拒）—— 那是用户的退路；\n"
            "  · 收工时在 summary 里写一句「快照 = <id>，要回退到「文件管理 → 版本快照」」。\n"
            "  · 如果宿主说「没存上」，那这次改动**没有退路** —— 收工时必须照实写出来。")
    return out


#: 附件正文上限：太长就截断，避免一个拖入文件把整次请求撑爆。
ATTACH_TEXT_CAP = 120000
ATTACH_IMAGE_CAP = 12 * 1024 * 1024


def _read_attachment(a):
    """把一条附件变成 `(kind, name, payload, mime)`。

    `kind`：`image` = `payload` 是 data: URL；`text` = 正文；`note` = 只给模型一句说明。
    ★ 路径附件在**工作线程里现读**，不放到界面进程；这样大文件读取不卡界面。
    """
    import base64
    import mimetypes
    kind = str((a or {}).get("kind") or "")
    name = str((a or {}).get("name") or "附件")
    mime = str((a or {}).get("mime") or "").lower()
    if kind == "text":
        text = str((a or {}).get("text") or "")
        if len(text) > ATTACH_TEXT_CAP:
            text = text[:ATTACH_TEXT_CAP] + "\n……（附件太长，截到 %d 字）" % ATTACH_TEXT_CAP
        return "text", name, text, mime or "text/plain"
    if kind == "data":
        data_url = str((a or {}).get("data_url") or "")
        if mime.startswith("image/") or data_url.startswith("data:image/"):
            return "image", name, data_url, mime or "image/png"
        return "note", name, "（附件 %s 是二进制数据，暂时只支持图片内嵌。）" % name, mime
    if kind == "path":
        p = Path(str((a or {}).get("path") or ""))
        try:
            if not p.is_file():
                return "note", name, "（附件文件不存在：%s）" % p, mime
            guess = (mimetypes.guess_type(str(p))[0] or mime or "").lower()
            size = p.stat().st_size
            if guess.startswith("image/"):
                if size > ATTACH_IMAGE_CAP:
                    return "note", name, "（图片太大，没有内嵌：%s）" % p, guess
                b64 = base64.b64encode(p.read_bytes()).decode("ascii")
                return "image", name, "data:%s;base64,%s" % (guess, b64), guess
            # 非图片：只读开头一段来判断/截断，别把几百 MB 的二进制整个读进内存。
            blob_cap = ATTACH_TEXT_CAP * 4 + 8192
            with p.open("rb") as fh:
                raw = fh.read(blob_cap + 1)
            truncated = len(raw) > blob_cap
            if truncated:
                raw = raw[:blob_cap]
            looks_text = (guess.startswith("text/") or guess in
                          ("application/json", "application/xml", "application/javascript")
                          or b"\x00" not in raw[:4096])
            if not looks_text:
                return "note", name, "（二进制附件 %s，没有内嵌；需要时用工具读它：%s）" % (name, p), guess
            text = raw.decode("utf-8", "replace")
            if truncated or len(text) > ATTACH_TEXT_CAP:
                text = text[:ATTACH_TEXT_CAP] + "\n……（附件太长，截到 %d 字）" % ATTACH_TEXT_CAP
            return "text", name, text, guess or "text/plain"
        except OSError as e:
            return "note", name, "（附件读不出来：%s）" % e, mime
    return "note", name, "（不认识的附件类型）", mime


def build_user_content(task, env_text, attachments=None):
    """任务 + 环境说明 + 附件 → OpenAI 兼容的 content（纯文本或图文数组）。"""
    text_bits = [str(task or ""), str(env_text or "")]
    images = []
    for a in (attachments or []):
        if not isinstance(a, dict):
            continue
        kind, name, payload, _mime = _read_attachment(a)
        if kind == "image":
            images.append({"type": "image_url", "image_url": {"url": payload}})
            text_bits.append("【附件图片】%s" % name)
        elif kind == "text":
            text_bits.append("【附件：%s】\n%s" % (name, payload))
        else:
            text_bits.append("【附件：%s】%s" % (name, payload))
    text = "\n\n".join([x for x in text_bits if x])
    if images:
        return [{"type": "text", "text": text}] + images
    return text


class Loop:
    """一个任务一次 loop。`client` 只要有 `.chat(messages, tools)` 这个方法就行（探针会塞假模型进来）。"""

    def __init__(self, client, workdir=None, max_steps=0, on_step=None, say=print,
                 compact_after=6, keep_recent=12, compact_min=3,
                 compact_at=102400, retain_tokens=20480, stop_check=None,
                 soft_steps=0, max_tokens=100000000, on_phase=None, on_snapshot=None,
                 asker=None, mode_fn=None, on_journal=None, run_id="", tmp_dir=None,
                 perm_gate=None, on_stream=None):
        self.client = client
        #: ★ `V-389`：**边收边推**（你原话："既然已经做了流式了，那流式的数据拿到就开始渲染呀"）。
        #:   `on_stream(第几步, 正文尾巴, 思考尾巴)` —— 宿主把它放进 `ai_poll` 的 `partial`，
        #:   界面就一边收一边画。空串 = "这一轮收完了，把那颗气泡收掉"。
        #:   为什么要分两路：带思考的模型前几十秒**正文一个字都没有**（实测那次 60.2 秒），
        #:   只报正文的话界面还是干等 —— 思考尾巴也得能看见。
        self.on_stream = on_stream
        self._st_c, self._st_r = [], []          # 正文 / 思考的增量片段
        self._st_cn, self._st_rn = 0, 0          # 各自累计了多少字（截尾用）
        self._st_at = 0.0                        # 上次推送的时刻（节流）
        self._st_n = 1                           # 这是第几步在收字
        #: ★ `V-389`：**客户端认不认流式回调**（`on_delta` / `on_reasoning`）。
        #:   `Loop` 的契约一直是"client 只要有 `.chat(messages, tools)` 就行"（探针塞假模型），
        #:   所以不能硬塞新参数 —— 开工前看一眼签名：认就带上，不认就照老样子调（少个"边写边看"，
        #:   但跑得通）。`**kwargs` 的客户端一律当真（多给参数它自己会吞掉）。
        try:
            import inspect as _inspect
            _params = _inspect.signature(client.chat).parameters
            self.stream_kw = ("on_delta" in _params) or any(
                p.kind == p.VAR_KEYWORD for p in _params.values())
        except (TypeError, ValueError):                                  # 内建函数之类
            self.stream_kw = False
        # ★ `V-384`：快照**开工就存**（改一个已经存在的包的时候）；新建包那种还是
        #   等"第一次真要写之前"。`V-269` 想省的"问一句也留一条"由收工时那条
        #   `drop_untouched`（一个字都没改就收掉）兜住。
        self.snapshot = None
        #: ★ `V-384`：开工那条快照的 id（收工时判断要不要收掉）
        self._snap_at_start = ""
        #: ★ `V-382`：快照**没存上**的原因（空 = 存上了 / 压根没触发）。收工报告要照实说。
        self.snapshot_note = ""
        self.want_snapshot = True
        self.task = ""
        #: ★ `V-307`：这次跑的 id / 临时目录 / 权限模式的**现读**入口
        #:   （模式要能跑到一半改，所以是个 callable，不是常量）
        self.run_id = str(run_id or "")
        self.tmp_dir = str(tmp_dir or "")
        #: 权限模式**现读**（不给就交给 `Tools` 自己读 `ai_mode` —— 探针/命令行那条路）
        self.mode_fn = mode_fn or T.mode_now
        #: 每一步/每一小段落盘（`V-307`：强制重启那次丢记录，就是因为只在收尾写一次）
        self.on_journal = on_journal
        self._journal_t = 0.0
        #: ★ `V-280`/`V-281`：**这一次跑**的工具表在开工这一刻定死 —— 内置那些 + 已经允许它用的技能。
        #:   它这一次新造的技能**下一次**才进表（也正好卡在"用户还没点允许"那一步）。
        try:
            self.self_tools = ST.usable()
        except Exception:                                              # noqa: BLE001
            self.self_tools = {}
        self.tool_table = T.tools_for(self.self_tools)
        #: `V-307`：工具表本身占多少 token（估算用量时要算上它）
        self.tools_tokens = self._est(json.dumps(self.tool_table, ensure_ascii=False))
        self.tools = T.Tools(workdir=workdir, before_write=self._before_first_write,
                             self_tools=self.self_tools,
                             stop_check=stop_check, asker=asker, mode_fn=self.mode_fn,
                             run_id=self.run_id, perm_gate=perm_gate, client=client)
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
        # ★ `V-425`（你定的）：**步数闸整个取消** —— 你的原话："都有 token 上限了，
        #   这么设置毫无意义"。真机那一跑就是被它掐死的：17.4M / 100M token（才一成七）
        #   干到第 200 步突然判"没通过"，而活其实做到一半。
        #   现在 `max_steps=0` = **不限**（界面 / 命令行都走这条），唯一的主闸是 `max_tokens`：
        #   到 80% 劝一次收尾、到 100% 停手汇报；其余出口照旧（用户按停止 / done / answer /
        #   连着不调工具）。
        #   正数还留着 —— 探针要"有限步"的确定性（`max_steps=3` 那种），只有显式传才生效。
        self.max_steps = int(max_steps or 0)
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
            cost = B.est_tokens(self._text_of(m.get("content"))) + 12  # 12 ≈ 每条消息的固定开销
            if budget - cost < 0 and keep_from < len(messages):
                break
            budget -= cost
            keep_from -= 1
        cut = min(len(messages) - self.keep_recent, keep_from)   # 至少留 keep_recent 条兜底
        targets = []
        for m in messages[2:max(2, cut)]:
            role, content = m.get("role"), self._text_of(m.get("content"))
            if content.startswith("[早先") or content.startswith("【工具结果】[早先"):
                continue
            if role == "tool" or (role == "user" and content.startswith("【工具结果】")):
                targets.append(m)
        if len(targets) < self.compact_min:
            return 0
        for m in targets:
            content = self._text_of(m.get("content"))
            head = content.strip().splitlines()[0][:80] if content.strip() else ""
            if m.get("role") == "tool":
                m["content"] = "[早先的结果已折叠] " + head
            else:
                m["content"] = "【工具结果】[早先的已折叠] " + head
        return len(targets)

    @staticmethod
    def _text_of(content):
        """把 OpenAI 的 content 压成一段纯文本（纯字符串 / 图文数组都认）—— 估算和压缩共用。

        ★ 图文消息 list 里如果直接 `str()` 会变成 Python repr，既估不准 token，压缩时还会
          把整个图片 part 的 base64 当正文（又长又没意义）。所以统一从这里取文字。
        """
        if isinstance(content, list):
            bits = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    bits.append(str(part.get("text") or ""))
                elif part.get("type") == "image_url":
                    bits.append("[图片]")
            return " ".join(bits)
        return str(content or "")

    @staticmethod
    def _est(text):
        """估一段文本多少 token（`ai_budget.est_tokens` 的薄包装，import 失败也不炸）。"""
        text = Loop._text_of(text)
        try:
            import ai_budget as B                                        # noqa: PLC0415
            return B.est_tokens(text)
        except Exception:                                                # noqa: BLE001
            return max(1, int(len(str(text or "")) / 3))

    def _add_usage(self, u, messages=None, resp=None):
        """累加 token 用量，并记住"这一轮实际发出去多少输入 token"（压缩的触发条件）。

        ★ `V-307`：**API 不给数字就自己估**。用户报的"token 消耗这里 始终没有数据"就是这个 ——
          有些网关（尤其自建的 OpenAI 兼容层）回包里根本不带 `usage`，于是界面上永远是
          `— / — / —`，那条"token 上限"也就形同虚设。所以退一步：**真实数字优先**，
          没有就按字符数估（和压缩那条线同一个口径），并在 `usage["estimated"]` 里如实标出来
          （界面写成 `≈`）。宁可给个"约等于"，也不给一排横杠。
        """
        u = u or {}
        est = False

        def _i(v):
            try:
                return int(v or 0)
            except (TypeError, ValueError):
                return 0

        pt, ct, tt = _i(u.get("prompt_tokens")), _i(u.get("completion_tokens")), _i(u.get("total_tokens"))
        if not pt and messages:
            pt = self.tools_tokens + sum(self._est(m.get("content") or "") + 12 for m in messages)
            est = True
        if not ct and resp:
            ct = (self._est(resp.get("text") or "")
                  + self._est(json.dumps(resp.get("tool_calls") or [], ensure_ascii=False)))
            est = True
        if not tt:
            tt = pt + ct
        self.usage["prompt_tokens"] += pt
        self.usage["completion_tokens"] += ct
        self.usage["total_tokens"] += tt
        self.usage["last_prompt"] = pt
        if est:
            self.usage["estimated"] = True
        return {"prompt": pt, "completion": ct, "total": tt, "estimated": est}

    def _on_wait(self, seconds):
        """请求等了一会儿还没数据（`V-242`）：把"等了多久"报给界面，别让它看起来像死机。

        （重写 `_compact` 时我把这个方法一起切掉了 —— 探针当场报
          `'Loop' object has no attribute '_on_wait'`，这就是"改完必须跑一遍"的价值。）
        """
        self.wait_note = seconds
        if self.on_phase:
            self.on_phase("waiting")

    # ---- ★ `V-389`：流式增量 → 界面（节流推送，别把轮询压垮） ----------------------
    #: 只推"尾巴"这么多字：界面是跟着读的，全文最后由那一步的步骤卡给全。
    STREAM_TAIL = 6000
    #: 最快每多少秒推一次（0.2 秒 ≈ 5 帧/秒，看着就是"在打字"）
    STREAM_EVERY = 0.2

    def _stream_reset(self, n):
        self._st_c, self._st_r = [], []
        self._st_cn, self._st_rn = 0, 0
        self._st_at = 0.0
        self._st_n = int(n or 1)

    def _stream_trim(self):
        """只留尾巴 —— 长回答别在内存里攒两份全文（一份给界面、一份给收尾的步骤卡）。"""
        if self._st_cn > 6 * self.STREAM_TAIL:
            _t = "".join(self._st_c)[-self.STREAM_TAIL:]
            self._st_c, self._st_cn = [_t], len(_t)
        if self._st_rn > 6 * self.STREAM_TAIL:
            _t = "".join(self._st_r)[-self.STREAM_TAIL:]
            self._st_r, self._st_rn = [_t], len(_t)

    def _stream_feed(self, kind, seg):
        if not self.on_stream or not seg:
            return
        if kind == "c":
            self._st_c.append(seg)
            self._st_cn += len(seg)
        else:
            self._st_r.append(seg)
            self._st_rn += len(seg)
        now = time.time()
        if now - self._st_at < self.STREAM_EVERY:
            return                      # 节流：一秒钟最多推 5 次，别把 700ms 的轮询压死
        self._st_at = now
        self._stream_trim()
        self._stream_push()

    def _stream_push(self, clear=False):
        if not self.on_stream:
            return
        try:
            self.on_stream(self._st_n,
                           "" if clear else "".join(self._st_c)[-self.STREAM_TAIL:],
                           "" if clear else "".join(self._st_r)[-self.STREAM_TAIL:],
                           self._st_cn, self._st_rn)
        except Exception:                                              # noqa: BLE001
            pass                        # 推送失败绝不能把这一跑弄死

    def _stream_content(self, seg):
        self._stream_feed("c", seg)

    def _stream_think(self, seg):
        self._stream_feed("r", seg)

    def _stream_clear(self):
        """这一轮收完了（成功 / 出错 / 被停）—— 把界面那颗"正在生成"收掉。"""
        self._st_c, self._st_r = [], []
        self._st_cn, self._st_rn = 0, 0
        self._stream_push(clear=True)

    def _on_retry(self, attempt, times, err):
        """`V-270`：这条请求要重发一次 —— 说出来，并且**说清是哪一种**。

        ★ 为什么要占一行步骤：真机那次 DNS 抖了 4 分钟，连着 4 条任务全报
          `[Errno 11001] getaddrinfo failed`，界面上只有一句"模型那边出错"，看不出是网络
          还是我们坏了。现在它会自己重试，重试这件事也让你看得见。
        ★ `V-388`：现在有两种重发 —— ① **根本没连上**（DNS/重置，一个字都没发出去）；
          ② **一个字节都没收到**（请求发出去了，对面一直没声音；11-02 那两次"假超时"就是这种）。
          两者都得说清楚，否则永远分不清"网络断了"还是"模型被掐了"。
        """
        wait = C.retry_wait(attempt)
        is_timeout = bool(getattr(err, "timeout", False))
        self._step(self.cur_n or 1, "(重试)",
                   ("没收到数据：" if is_timeout else "没连上：") + str(err)[:70],
                   "%.1f 秒后重发（第 %d 次，共 %d 次）" % (wait, attempt, times),
                   out=str(err))
        self.say("  %s —— 正在重发（第 %d/%d 次）"
                 % (("等了半天一个字节都没来（%s）" % err) if is_timeout
                    else ("网络抖了一下（%s）" % err), attempt, times))

    def _journal(self, force=False, **extra):
        """**每一步都落盘**（`V-307`）。用户那次强制重启丢的正是这条记录。

        节流：最快 1.5 秒写一次（`force=True` 时立刻写 —— 开工 / 收尾 / 提问 / 停止）。
        存不下不影响干活（宿主那边自己会记一句）。
        """
        if not self.on_journal:
            return
        now = time.time()
        if not force and now - self._journal_t < 1.5:
            return
        self._journal_t = now
        try:
            self.on_journal({"steps": list(self.steps), "usage": dict(self.usage),
                             "messages": self.messages, "phase": "…",
                             "files": list(self.tools.changed),
                             "tools_log": list(self.tools.log),
                             "procs": list(self.tools.procs.keys()),
                             "killed": list(self.tools.killed),
                             "snapshot": getattr(self, "snapshot", None),
                             # ★ `V-382`：没存上的原因也要落盘（界面据此告警）
                             "snapshot_note": str(getattr(self, "snapshot_note", "") or "")},
                            bool(force))
        except Exception:                                                # noqa: BLE001
            pass

    def _step(self, n, tool, brief, note="", ms=0, disp="", nodisp=False, why="",
              args=None, out=""):
        row = {"n": n, "tool": tool, "brief": brief, "note": note, "ms": int(ms or 0),
               # ★ `V-260`：给人看的那一份（完整的路径 / 完整的 summary）—— 界面优先用它
               "disp": disp,
               # ★ `V-269` 补：`nodisp=True` = **这一步没有正文可摆**（`done` / `answer` 的正文
               #   归下面的结论卡）。为什么单独一个键、不拿"disp 是空串"当信号：
               #   `(说话)` / `(打回)` / `(重试)` 这几张本来就没有 `disp`、正文是从 `brief`
               #   反解出来的（老记录也这样）—— 混用会把它们的正文一起弄没。
               "nodisp": bool(nodisp),
               # ★ `V-307`：**每一步的目的**（模型自己写的 `why`）+ **这一步的时间点**。
               #   用户原话："它没有显示每个步骤的时间点"、"跑一遍 run_moss 我仅凭这个
               #   无法判断它的目的" —— 这两样都记在步骤行里（老记录没有这两个键，界面兜底）。
               "why": str(why or ""),
               "t": time.time(),
               "at": time.strftime("%H:%M:%S"),
               # ★ `V-315`：**原始参数 + 原始输出**（用户原话："它的动作 产出的日志 或者文本
               #   我希望我能点击查看 … 它不应该是黑箱操作"）。界面上点一下那张步骤卡就摊开这两样。
               "args": _clip(args, ARG_MAX),
               "out": _clip(out, OUT_MAX),
               "tokens": self.usage["total_tokens"], "folded": self.folded,
               # `V-244`：这一轮真实发出去的输入 token（= 现在上下文多长）—— 界面据此显示
               "ptok": int(self.usage.get("last_prompt") or 0),
               # `V-307`：这个数字是 API 给的还是我们自己估的（界面写 `≈`）
               "est": bool(self.usage.get("estimated"))}
        self.steps.append(row)
        self.say("  [%d] %-10s %s%s" % (n, tool, brief, ("  " + note) if note else ""))
        if self.on_step:
            try:
                self.on_step(row)
            except Exception:                                            # noqa: BLE001
                pass
        self._journal()
        return row

    def note(self, tool, brief, why="", args=None, out=""):
        """插一条**不是工具调用**的记录行（`V-333`：权限请求 / 问答**也是会话的一部分**）。

        用户原话："申请权限 和复选框和用户交互的部分 直接在聊天记录上进行渲染交互 …
        我选择以后 后续我翻看聊天记录 也能看我之前的选择"。
        ★ 所以请求/问答不再只挂在 `AI["state"]` 里（那玩意儿答完就没了、也不落盘），
          而是**走进步骤流**：界面把它画成一条"它说的"气泡，答完把结果写在同一条上，
          轮询带得走、`_journal` 也落得盘 —— 翻旧会话照样看得见你当时选了什么。
        ★ 回那一行本身：宿主拿到它，等用户答完**原地更新**（`answer` / `out` / `done`）。
        """
        n = len(self.steps) + 1
        return self._step(n, tool, brief, disp=brief, nodisp=True, why=why, args=args, out=out)

    # ------------------------------------------------------------------ 主循环
    def _snapshot_at_start(self):
        """**开工就存**（`V-384`）—— 只对"已经在某个包目录里"的活。

        ★ 为什么要它：你在真机上等了十几分钟，点开「版本快照」看见的是空的 ⇒
          只能判断成"它压根没备份"。开工就存，"退路"这件事一眼就看得见。
        ★ 为什么还要 `drop_untouched`：这条的代价是"问答也留一条"（`V-269` 修过的
          那条）。用一条更准的判据挡住 —— **这一跑既没改文件、也没跑过命令**就收掉。
        """
        import ai_snap as S                                              # noqa: PLC0415
        got = S.snapshot_at_start(self.task, self.tools.workdir)
        if not got.get("ok"):
            if not got.get("skip"):
                self.say("（开工这条快照没存上：%s —— 等第一次写之前再试）" % got.get("msg"))
            return ""
        self.snapshot = {"id": got.get("id"), "group": got.get("group")}
        self._snap_at_start = str(got.get("id") or "")
        self.say("开工先存了一条快照：%s（%s）" % (got.get("id"), got.get("msg")))
        if self.on_snapshot:
            try:
                self.on_snapshot(self.snapshot)
            except Exception:                                            # noqa: BLE001
                pass
        return self._snap_at_start

    def _before_first_write(self, touched=None):
        """第一次真要写文件之前：存"动手前"的快照（`V-269`，从开工就存改过来的）。

        ★ 为什么由 `Tools` 来喊：只有它知道"这一刻要动盘了"。快照必须在**写之前**落盘
          —— 存"已经改了一半"的样子等于没存。
        ★ `V-250` 那条不变：**存好就立刻通知界面**（版本快照那一列要刷新出来），
          不然你要等跑完才看得见它刚存的那条。
        ★ `V-382`：`touched` 是**第一处要写的那个文件**。以前这里只传 workdir，
          于是"workdir 是 A、实际在改 B"的时候存下来的是 A 的空壳（真机记录里就有）。
        回 `"later"` = 这次没存成、但**别把这个机会用掉**（要改的东西还没建出来，比如新建包）——
        `Tools` 拿它决定下一次写文件之前再试一次；其余情况它只用一次。

        为什么"新建"要允许重试：一个新包从建目录、写文件到改坏，全程一条快照都没有的话，
        用户能回退的只有"删掉它"。等它真建出来、下一次动它之前再存一条，才是那个"动手前"。
        """
        if not self.want_snapshot or self.snapshot:
            return "done"
        import ai_snap as S                                              # noqa: PLC0415
        got = S.snapshot_before(self.task, self.tools.workdir, touched=touched)
        if got.get("ok"):
            self.snapshot = {"id": got.get("id"), "group": got.get("group")}
            self.say("动手前存了快照：%s（分组 %s）" % (got.get("id"), got.get("group")))
            if self.on_snapshot:
                try:
                    self.on_snapshot(self.snapshot)
                except Exception:                                        # noqa: BLE001
                    pass
            return "done"
        if got.get("retry"):
            self.say("（这次先不存快照：%s —— 等它建出来再存）" % got.get("msg"))
            return "later"
        self.say("（没存动手前的快照：%s）" % got.get("msg"))
        # ★ `V-382`：**存不上要留痕** —— 不然收工报告里看起来"一切正常"，
        #   用户以为有退路，其实没有（他找你的时候就是这么发现的）。
        self.snapshot_note = str(got.get("msg") or "")
        return "done"

    def _stopped(self):
        """用户按了停止没有（`stop_check` 可能没有 / 可能抛 —— 都当"没停"）。"""
        try:
            return bool(self.stop_check and self.stop_check())
        except Exception:                                                # noqa: BLE001
            return False

    def cleanup(self, why="收工"):
        """收摊：**把它起过的子进程全部杀掉**（`V-307`）。

        ★ 为什么要在这一层兜：用户原话"它似乎有可能不关闭 导致我的电脑 出现了几十个
          moss 和 python 进程"。`_finish` 之前任一条返回路径（停止 / 出错 / 步数用完 /
          验收通过）都可能留下一个还在跑的子进程，所以在 `run()` 的 `finally` 里统一收。
        """
        got = {"killed": 0, "pids": [], "ms": 0.0}
        try:
            got = self.tools.kill_children(why)
        except Exception:                                                # noqa: BLE001
            pass
        if got.get("killed"):
            self.say("（收摊：杀掉了 %d 个还在跑的子进程）" % got["killed"])
        return got

    def run(self, task, extra_fragments=(), snapshot=True, history=None, from_id="", attachments=None):
        """跑一次任务（**外面这层只管收摊** —— 真正的活在同名的 `_run` 里）。

        `V-307`：不管它是正常收工、被停止、还是自己炸了，出来的时候**子进程一个不留**。
        """
        try:
            return self._run(task, extra_fragments=extra_fragments, snapshot=snapshot,
                             history=history, from_id=from_id, attachments=attachments)
        finally:
            self.cleanup("跑完了 / 停了 / 出错了")

    def _run(self, task, extra_fragments=(), snapshot=True, history=None, from_id="", attachments=None):
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
        try:
            import ai_mode as M                                          # noqa: PLC0415
            _perm = M.perm_note(str(self.tools.workdir))
            _allow = [it.get("path") for it in M.allow_list()
                      if (it.get("read") or it.get("write")) and it.get("path") != "*"]
        except Exception:                                                # noqa: BLE001
            _perm, _allow = "", []
        _env_text = env_note(self.tools.workdir, perm=_perm, tmp=self.tmp_dir, allow=_allow)
        user_content = build_user_content(task, _env_text, attachments)
        messages = [{"role": "system", "content": sys_text}] + old + \
                   [{"role": "user", "content": user_content}]
        # ★ `V-251`：这个列表就是"这条会话" —— 全程只 append/就地改（底下没有重新赋值），
        #   所以收尾时（`_finish`）把它原样交出去，界面存盘、下次接着聊。
        self.messages = messages
        self.continued_from = str(from_id or "")
        self._journal(force=True)                 # `V-307`：开工先落一条（这时还没有步骤）
        if old:
            self.say("接着上次那条聊：它还记得之前 %d 条对话" % len(old))
        self.say("提示词：%s%s" % ("；".join(used),
                                 ("；**缺**：" + "、".join(missing)) if missing else ""))
        # ★ `V-236`：**动手前先给这个包存一条快照**（`by="ai"` + 这次的任务原文）。
        #   改坏了要能一键回去；存不上也照干（只是没退路，而且会如实说）。
        # ★ `V-384`：**开工就存**（改一个已经存在的包的时候）。`V-269` 曾经把这一步
        #   挪到"第一次真要写文件之前"，理由是不想"问一句也存一条"；真机上它的代价是
        #   **前十几分钟看着像"根本没备份"**（18:05 开工、18:16 才第一次写）。
        #   现在两头都要：开工先存（看得见），这一跑真没改任何东西就在收工时收掉
        #   （`_finish` → `drop_untouched`）。新建包那种还是等第一次写之前再存。
        #   参数 `snapshot=False` 照旧能整个关掉。
        self.snapshot = None
        self.snapshot_note = ""
        self._snap_at_start = ""
        if self.want_snapshot:
            self._snapshot_at_start()
        nudges, result = 0, {"ok": False, "reason": "还没收工就停了"}
        # ★ `V-425`：不再"数到 200 就停" —— `max_steps=0` 时这一圈是 `while True`，
        #   靠 token 闸 / 用户停止 / 它自己收工来结束；只有显式给了正数才当硬顶（探针用）。
        n = 0
        while True:
            n += 1
            if self.max_steps and n > self.max_steps:
                result = {"ok": False, "reason": "步数用完了（%d 步）" % self.max_steps}
                break
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
                # `V-425`：没有硬顶时别提"硬顶是多少步"（那是 0，看着像 bug）
                self._step(n, "(提醒)", "已经第 %d 步了 —— 催它收尾" % (n - 1), "软提醒")
                messages.append({"role": "user", "content":
                                 "★ 已经第 %d 步了%s。**请收尾**："
                                 "要么现在 done(summary=…) 说清你改了什么、怎么验的；"
                                 "要么一句话说清卡在哪、还需要什么 —— 别再做新的探索性读取了。"
                                 % (n - 1,
                                    ("（这次任务的硬顶是 %d 步）" % self.max_steps)
                                    if self.max_steps else "")})
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
                self._stream_reset(n)          # ★ `V-389`：这一轮的增量从头攒
                _chat_kw = dict(stop_check=self.stop_check, on_wait=self._on_wait,
                                on_retry=self._on_retry)
                if self.stream_kw:             # 客户端认流式回调才带（老客户端/假模型照旧）
                    _chat_kw["on_delta"] = self._stream_content
                    _chat_kw["on_reasoning"] = self._stream_think
                resp = self.client.chat(messages, self.tool_table, **_chat_kw)
            except C.Stopped:
                # ★ `V-242`：请求**发到一半**按的停止 —— 立刻收工，不再等它把话说完。
                return self._finish(False, "用户按了停止", used, missing)
            except C.AiError as e:
                return self._finish(False, "模型那边出错：%s" % e, used, missing)
            finally:
                # ★ `V-389`：不管怎么收场（成功 / 出错 / 被停），界面上那颗
                #   "正在生成"都要收掉，否则它会一直挂在那儿假装还在打字。
                self._stream_clear()
            self._add_usage(resp.get("usage"), messages, resp)
            # ★ 思考过程：有就原样记一条**可折叠**的步骤卡（只给人看，不回灌给模型）。
            #   默认卡片只显示第一行，点开「眼睛」才摊开全文 —— 思考完自动保持折叠。
            _reason = str(resp.get("reasoning") or "").strip()
            if _reason:
                _rlines = _reason.splitlines()
                _rfirst = (_rlines[0].strip() if _rlines else "")[:80]
                self._step(n, "(思考)", _rfirst or "思考过程", "思考过程", out=_reason)
            native = bool(resp.get("native"))
            calls = resp.get("tool_calls") or []
            print("[AI-DIAG] step=%s calls=%s" % (n, ",".join(str(c.get("name")) for c in calls)), file=sys.stderr, flush=True)
            text = (resp.get("text") or "").strip()
            if not calls:
                # 它只是在说话（或说完了但没调工具）—— 催一次，最多两回
                nudges += 1
                self._step(n, "(说话)", text[:80] or "（空的）", "没调工具", out=text)
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
                if name == "ask":
                    _qa = call.get("args") or {}
                    print("[AI-DIAG] ask question=%r options=%r" % (str(_qa.get("question") or "")[:200], _qa.get("options")), file=sys.stderr, flush=True)
                brief = json.dumps(call.get("args") or {}, ensure_ascii=False)
                _t0 = time.time()
                out = self.tools.call(name, call.get("args") or {})
                _ms = int((time.time() - _t0) * 1000)
                note = str(out).splitlines()[0][:70] if out else ""
                # ★ `V-260`：`brief[:70]` 是**给一行摘要**用的，可它把 JSON 截断了 ⇒
                #   界面 `JSON.parse` 失败、只能把 `{"summary": "……` 这种原始串摆给你看
                #   （你报的"像是一个字典，而不是显示里面的文本"，还有"回复长了看不全"）。
                #   这里另给一份 `disp`：**给人看的、完整的**（`done` 的 summary 一个字不截）。
                # ask already adds its interactive step through on_ask(); adding a generic
                # tool step here duplicated the prompt (the generic row has no qid).
                if name != "ask":
                    self._step(n, name, brief[:70], note, ms=_ms,
                               disp=_step_disp(name, call.get("args") or {}),
                               # `V-269` 补：这两个工具的正文归下面的结论卡，步骤卡不重复贴
                               nodisp=name in ("done", "answer"),
                               # ★ `V-307`：模型自己写的**这一步的目的**（界面拿它当标题）
                               why=str((call.get("args") or {}).get("why") or ""),
                               # ★ `V-315`：原始参数 + 原始输出（点开那张卡看的东西）
                               args=call.get("args") or {}, out=str(out))
                if self.tools.stopped():
                    # ★ `V-307`：**停止立刻生效** —— 不再"等下一轮"。正在跑的子进程已经
                    #   被 `run_moss` 自己杀干净了，这里直接收工（`run()` 的 finally 再兜一遍）。
                    if native:
                        messages.append({"role": "tool", "tool_call_id": call.get("id") or name,
                                         "content": str(out)})
                    else:
                        messages.append({"role": "user",
                                         "content": "【工具结果】%s\n%s" % (name, out)})
                    return self._finish(False, "用户按了停止", used, missing)
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
                    self._step(n, "(打回)", "done 但没验收", self.tools.gate_reason()[:70],
                               out=self.tools.gate_reason())
                    if nudges >= 3:
                        return self._finish(False, "说了几次都不去验收：" + self.tools.gate_reason(),
                                            used, missing)
                    msg = ("**还没验收**：" + self.tools.gate_reason() +
                           "（硬规矩：**要么改完之后跑通一次，要么确认不用改但真跑成功过**。）")
                    # ★ `V-247`：先攒着 —— 等这一轮所有 tool 结果发完再追加（见下面 pending_notes）
                    pending_notes.append(msg)
                elif name == "ask" and len(calls) > 1:
                    # This batch contains multiple blocking questions. Only the first
                    # question can be surfaced reliably by the single-question UI.
                    pending_notes.append(
                        "同一批工具调用里包含多个 ask。一次只能处理一个问题；"
                        "请先等待并使用第一个问题的回答，再决定是否追问。")
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
            # ★ `read_image` 的图片走宿主侧信道：tool 消息只能是字符串，图片必须作为
            #   下一条 user 多模态消息追加。它一定排在所有 tool 结果之后，不会破坏
            #   assistant(tool_calls) → tool 的配对（否则网关会报 HTTP 400）。
            imgs = self.tools.take_images()
            if imgs:
                bits = ["【你刚刚读取的图片】下面是视觉输入，直接看图里的内容继续。",
                        "不要再说自己没有视觉能力，不要调用 OCR，也不要用 read_file 读图片。"]
                bits.extend("图片 %d：%s（%s）" % (i + 1, im.get("name"), im.get("path"))
                            for i, im in enumerate(imgs))
                bits.extend(pending_notes)
                parts = [{"type": "text", "text": "\n".join(bits)}]
                parts.extend({"type": "image_url",
                              "image_url": {"url": im.get("data_url") or ""}}
                             for im in imgs if im.get("data_url"))
                messages.append({"role": "user", "content": parts})
            else:
                # ★ `V-247`：这一轮所有 tool 结果发完之后，再追加"人话"（顺序反了就是 HTTP 400）
                for _note in pending_notes:
                    messages.append({"role": "user", "content": _note})
        # ★ `V-237`：**步数用完 ≠ 失败**（`V-425` 之后只有显式设了步数硬顶才走得到这儿）。
        #   要是它其实已经验收通过（最后一次改动之后跑通过，
        #   或者没改动但真跑成功过），只是没来得及说 `done` —— 那就照实判通过，
        #   并在原因里写清"它没来得及收工"。真机那次（`calc` 本来就支持指数）就卡在这儿。
        if not result["ok"] and self.tools.verified():
            # `V-367`：这句话显示在结论卡上（**不走 markdown**）⇒ 不许带 `**`；
            #   也别把内部工具名 `done` 摆给用户看
            return self._finish(True, "步数用完了（%d 步），但改动已经跑通验证（它没来得及收尾）"
                                      % self.max_steps,
                                used, missing,
                                summary="（它没来得及写 summary —— 看上面的步骤流：%s）"
                                        % "、".join(s["tool"] for s in self.steps[-4:]),
                                caveats="收尾没有正常结束（步数用完），结论以跑过的命令为准。")
        return self._finish(result["ok"], result["reason"], used, missing)

    # ------------------------------------------------------------------ 收尾
    def _drop_untouched_snapshot(self):
        """这一跑**一个字都没改** ⇒ 把开工那条空快照收掉（`V-384`）。

        判据刻意收得很紧：**没改过文件**（`edit_seq == 0`、`changed` 空）**而且一条命令
        都没跑过**（`run_seq == 0`）。少一条都不收 —— 跑过命令就可能改过盘（比如它
        自己的包/脚本），那条快照就是真退路，不能因为"没调 edit_file"就当成空的。
        """
        bid = str(getattr(self, "_snap_at_start", "") or "")
        if not bid or not getattr(self, "snapshot", None):
            return False
        try:
            if self.tools.edit_seq or self.tools.changed or self.tools.run_seq:
                return False
        except Exception:                                                # noqa: BLE001
            return False
        import ai_snap as S                                              # noqa: PLC0415
        got = S.drop_untouched(bid, (self.snapshot or {}).get("group") or "")
        if not got.get("ok"):
            # 收不掉也别硬来：留着不影响，顶多多一条空快照。
            self.say("（开工那条空快照没收回：%s）" % got.get("msg"))
            return False
        self.say("这一跑没动过任何东西 ⇒ 把开工那条空快照收掉了（问答不留垃圾）")
        self.snapshot = None
        self._snap_at_start = ""
        return True

    def _finish(self, ok, reason, used, missing, summary="", caveats="", kind="work"):
        self._drop_untouched_snapshot()
        got = {"ok": bool(ok), "reason": reason, "summary": summary, "caveats": caveats,
               # ★ `V-269`：`kind="chat"` = 这次只是**回答**（没动文件、不用验收）——
               #   界面拿它把结论卡写成「💬 回答」而不是「✅ 验收通过」。
               "kind": str(kind or "work"),
               "steps": self.steps, "usage": dict(self.usage),
               "prompts": used, "missing_prompts": missing, "tools_log": self.tools.log,
               "files": list(self.tools.changed), "folded": self.folded,
               "snapshot": getattr(self, "snapshot", None),
               # ★ `V-382`：**没存上**的原因（存上了就是空串）。界面据此在结论卡上告一句
               #   "这次改动没有退路"，免得用户以为有备份。
               "snapshot_note": str(getattr(self, "snapshot_note", "") or ""),
               # ★ `V-251`：**把这一整条对话留下来** —— 界面存进任务记录，
               #   下次点「接着聊」就把它接上去（不然重启 moss 只能从头再来）。
               #   存的是**收尾时**的消息表（`_compact` 已经折过的那些，所以不算大）。
               "messages": self.messages,
               "continued_from": getattr(self, "continued_from", ""),
               # ★ `V-307`：这次跑的"账" —— 临时目录 / 权限模式 / 杀掉了哪些进程。
               #   `procs_killed` 是给用户看的证据：不再有孤儿进程堆在任务管理器里。
               "run_id": self.run_id, "tmp_dir": self.tmp_dir,
               "mode": str(self.mode_fn()), "procs_killed": list(self.tools.killed),
               "edited": self.tools.edit_seq}
        self._journal(force=True)
        return got


# ---------------------------------------------------------------------- 命令行
def run_cli(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        print("用法：ai_loop.py \"<任务>\" [--workdir 目录] [--max-steps N（0 = 不限，默认）] "
              "[--soft-steps N] [--max-tokens N] [--model 模型] [--mode consult|limited|free]")
        return 0 if argv else 2
    # ★ `V-425`：命令行也**默认不限步数**；token 闸没给就按界面那份预算（`budget.json`）——
    #   总得留一道闸，而那道闸是钱（token），不是步数。
    task, workdir, max_steps, soft_steps, max_tokens, model = argv[0], None, 0, 0, None, None
    mode = ""
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--workdir" and i + 1 < len(argv):
            workdir = argv[i + 1]; i += 2
        elif a == "--mode" and i + 1 < len(argv):        # `V-307`：consult/limited/free
            mode = argv[i + 1]; i += 2
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
    if max_tokens is None:              # `V-425`：默认用界面那份 token 上限（唯一的闸）
        try:
            import ai_budget as _B                                        # noqa: PLC0415
            max_tokens = int(_B.load().get("max_tokens") or 0)
        except Exception:                                                 # noqa: BLE001
            max_tokens = 0
    try:
        client = C.Client.from_env(model=model)
    except C.AiError as e:
        print("[错误] %s" % e)
        return 2
    print("模型：%s（%s）" % (client.model, client.base_url))
    print("任务：%s" % task)
    print("预算：%s、步数%s"
          % (("token 闸 %d" % max_tokens) if max_tokens else "不设 token 闸",
             ("硬顶 %d 步（每 %d 步提醒一次）" % (max_steps, soft_steps)) if max_steps
             else "不限（只有 token 这一道闸）"))
    t0 = time.time()
    if mode:
        print("权限模式：%s（临时：`ai_mode.set_mode` 覆盖）" % mode)
    _fn = (lambda: mode) if mode else None
    got = Loop(client, workdir=workdir, max_steps=max_steps, soft_steps=soft_steps,
               max_tokens=max_tokens, mode_fn=_fn).run(task)
    print()
    print("=" * 68)
    print("%s —— %s" % ("💬 回答" if got.get("kind") == "chat"
                        else ("✅ 验收通过" if got["ok"] else "✗ 没通过"), got["reason"]))
    if got.get("summary"):
        print("它说改了什么：%s" % got["summary"])
    if got.get("caveats"):
        print("它自己标的不确定：%s" % got["caveats"])
    u = got["usage"]
    print("步数 %d（%d 次工具调用）· 用时 %.1f 秒 · token%s：输入 %d / 输出 %d / 合计 %d"
          % (len(got["steps"]), len(got["tools_log"]), time.time() - t0,
             "（估算）" if u.get("estimated") else "",
             u["prompt_tokens"], u["completion_tokens"], u["total_tokens"]))
    if got.get("procs_killed"):
        print("杀掉还在跑的子进程：%s" % "、".join(str(p) for p in got["procs_killed"]))
    if got.get("tmp_dir"):
        print("临时空间：%s" % got["tmp_dir"])
    if got.get("missing_prompts"):
        print("⚠ 提示词缺失（两层都没有）：%s" % "、".join(got["missing_prompts"]))
    return 0 if got["ok"] else 1


if __name__ == "__main__":
    sys.exit(run_cli())
