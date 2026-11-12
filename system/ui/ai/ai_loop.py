import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import ai_client as C
import ai_edits as E
import ai_skills as K
import ai_tools as T

_SK = str(E.HOME / "system" / "ai")
if _SK not in sys.path:
    sys.path.insert(0, _SK)
import skill_lib as ST

BASE_PROMPTS = ("system", "edit")

def _parse_skill_placeholder():
    return None

def prompts_dirs():
    return [E.HOME / "system" / "ui" / "ai" / "prompts",
            E.user_data() / "ai" / "prompts"]

def find_prompt(name):
    for d in reversed(prompts_dirs()):
        p = d / (name + ".md")
        if p.is_file():
            try:
                return p.read_text(encoding="utf-8", errors="replace"), p
            except OSError:
                continue
    return "", None

def missing_prompts(names):
    return [n for n in names if not find_prompt(n)[1]]

DISP_MAX = 4000
ARG_MAX = 4000
OUT_MAX = 6000

def _clip(v, n):
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
    a = args or {}
    if name in ("done", "answer"):
        return ""
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

def compose_system(task, extra=(), self_tools=None, workdir=""):
    names = list(BASE_PROMPTS)
    parts, used, missing = [], [], []
    for n in dict.fromkeys(names):
        text, where = find_prompt(n)
        if not where:
            missing.append(n)
            continue
        used.append("%s ← %s" % (n, where))
        parts.append(text.strip())
    for n in dict.fromkeys(list(extra or ())):
        got = K.list_skills().get(str(n))
        if not got or not got["body"]:
            missing.append(str(n))
            continue
        used.append("技能 %s ← %s" % (n, got["path"]))
        parts.append(got["body"])
    note = K.note()
    if note:
        parts.append(note)
        used.append("技能清单（%d 个：%s）" % (len(K.usable()), "、".join(K.names()) or "无"))
    mine = ST.note(self_tools, workdir=workdir)
    if mine:
        parts.append(mine)
        used.append("技能（%d 个：%s）" % (len(self_tools or {}), "、".join(sorted(self_tools or {}))))
    return "\n\n---\n\n".join(parts), used, missing

def env_note(workdir=None, perm="", tmp="", allow=()):
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
    out += ("\n【备份是宿主做的，不许你动】第一次改文件之前，宿主会**自动**存一条"
            "「动手前」快照（`by=ai`，标题就是这次的任务原文）。所以：\n"
            "  · **不用**自己 `--snap save`（重复存只是浪费，也不会更安全）；\n"
            "  · **不许删**（没有任何删快照的工具；`--snap rm/gc` 会被拒）—— 那是用户的退路；\n"
            "  · 收工时在 summary 里写一句「快照 = <id>，要回退到「文件管理 → 版本快照」」。\n"
            "  · 如果宿主说「没存上」，那这次改动**没有退路** —— 收工时必须照实写出来。")
    return out

ATTACH_TEXT_CAP = 120000
ATTACH_IMAGE_CAP = 12 * 1024 * 1024

def _read_attachment(a):
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
    def __init__(self, client, workdir=None, max_steps=0, on_step=None, say=print,
                 compact_after=6, keep_recent=12, compact_min=3,
                 compact_at=102400, retain_tokens=20480, stop_check=None,
                 soft_steps=0, max_tokens=100000000, on_phase=None, on_snapshot=None,
                 asker=None, mode_fn=None, on_journal=None, run_id="", tmp_dir=None,
                 perm_gate=None, on_stream=None):
        self.client = client
        self.on_stream = on_stream
        self._st_c, self._st_r = [], []
        self._st_cn, self._st_rn = 0, 0
        self._st_at = 0.0
        self._st_n = 1
        try:
            import inspect as _inspect
            _params = _inspect.signature(client.chat).parameters
            self.stream_kw = ("on_delta" in _params) or any(
                p.kind == p.VAR_KEYWORD for p in _params.values())
        except (TypeError, ValueError):
            self.stream_kw = False
        self.snapshot = None
        self._snap_at_start = ""
        self.snapshot_note = ""
        self.want_snapshot = True
        self.task = ""
        self.run_id = str(run_id or "")
        self.tmp_dir = str(tmp_dir or "")
        self.mode_fn = mode_fn or T.mode_now
        self.on_journal = on_journal
        self._journal_t = 0.0
        try:
            self.self_tools = ST.usable(workdir=str(workdir or ""))
        except Exception:
            self.self_tools = {}
        self.tool_table = T.tools_for(self.self_tools)
        self.tools_tokens = self._est(json.dumps(self.tool_table, ensure_ascii=False))
        self.tools = T.Tools(workdir=workdir, before_write=self._before_first_write,
                             self_tools=self.self_tools,
                             stop_check=stop_check, asker=asker, mode_fn=self.mode_fn,
                             run_id=self.run_id, perm_gate=perm_gate, client=client)
        self.on_phase = on_phase
        self.on_snapshot = on_snapshot
        self.wait_note = 0.0
        self.cur_n = 0
        self.max_steps = int(max_steps or 0)
        self.soft_steps = int(soft_steps or 0)
        self.max_tokens = int(max_tokens or 0)
        self.warned_token = False
        self.on_step = on_step
        self.say = say
        self.stop_check = stop_check
        self.compact_after = int(compact_after)
        self.keep_recent = int(keep_recent)
        self.compact_min = int(compact_min)
        self.compact_at = int(compact_at or 0)
        self.retain_tokens = int(retain_tokens or 0)
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self.steps = []
        self.folded = 0
        self.messages = []
        self.continued_from = ""

    def _compact(self, messages):
        if len(messages) <= self.compact_after:
            return 0
        if self.compact_at and (self.usage.get("prompt_tokens") or 0) < self.compact_at:
            return 0
        import ai_budget as B
        keep_from = len(messages)
        budget = self.retain_tokens
        while keep_from > 2:
            m = messages[keep_from - 1]
            cost = B.est_tokens(self._text_of(m.get("content"))) + 12
            if budget - cost < 0 and keep_from < len(messages):
                break
            budget -= cost
            keep_from -= 1
        cut = min(len(messages) - self.keep_recent, keep_from)
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
        text = Loop._text_of(text)
        try:
            import ai_budget as B
            return B.est_tokens(text)
        except Exception:
            return max(1, int(len(str(text or "")) / 3))

    def _add_usage(self, u, messages=None, resp=None):
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
        self.wait_note = seconds
        if self.on_phase:
            self.on_phase("waiting")

    STREAM_TAIL = 6000
    STREAM_EVERY = 0.2

    def _stream_reset(self, n):
        self._st_c, self._st_r = [], []
        self._st_cn, self._st_rn = 0, 0
        self._st_at = 0.0
        self._st_n = int(n or 1)

    def _stream_trim(self):
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
            return
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
        except Exception:
            pass

    def _stream_content(self, seg):
        self._stream_feed("c", seg)

    def _stream_think(self, seg):
        self._stream_feed("r", seg)

    def _stream_clear(self):
        self._st_c, self._st_r = [], []
        self._st_cn, self._st_rn = 0, 0
        self._stream_push(clear=True)

    def _on_retry(self, attempt, times, err):
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
                             "snapshot_note": str(getattr(self, "snapshot_note", "") or "")},
                            bool(force))
        except Exception:
            pass

    def _step(self, n, tool, brief, note="", ms=0, disp="", nodisp=False, why="",
              args=None, out=""):
        row = {"n": n, "tool": tool, "brief": brief, "note": note, "ms": int(ms or 0),
               "disp": disp,
               "nodisp": bool(nodisp),
               "why": str(why or ""),
               "t": time.time(),
               "at": time.strftime("%H:%M:%S"),
               "args": _clip(args, ARG_MAX),
               "out": _clip(out, OUT_MAX),
               "tokens": self.usage["total_tokens"], "folded": self.folded,
               "ptok": int(self.usage.get("last_prompt") or 0),
               "est": bool(self.usage.get("estimated"))}
        self.steps.append(row)
        self.say("  [%d] %-10s %s%s" % (n, tool, brief, ("  " + note) if note else ""))
        if self.on_step:
            try:
                self.on_step(row)
            except Exception:
                pass
        self._journal()
        return row

    def note(self, tool, brief, why="", args=None, out=""):
        n = len(self.steps) + 1
        return self._step(n, tool, brief, disp=brief, nodisp=True, why=why, args=args, out=out)

    def _snapshot_at_start(self):
        import ai_snap as S
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
            except Exception:
                pass
        return self._snap_at_start

    def _before_first_write(self, touched=None):
        if not self.want_snapshot or self.snapshot:
            return "done"
        import ai_snap as S
        got = S.snapshot_before(self.task, self.tools.workdir, touched=touched)
        if got.get("ok"):
            self.snapshot = {"id": got.get("id"), "group": got.get("group")}
            self.say("动手前存了快照：%s（分组 %s）" % (got.get("id"), got.get("group")))
            if self.on_snapshot:
                try:
                    self.on_snapshot(self.snapshot)
                except Exception:
                    pass
            return "done"
        if got.get("retry"):
            self.say("（这次先不存快照：%s —— 等它建出来再存）" % got.get("msg"))
            return "later"
        self.say("（没存动手前的快照：%s）" % got.get("msg"))
        self.snapshot_note = str(got.get("msg") or "")
        return "done"

    def _stopped(self):
        try:
            return bool(self.stop_check and self.stop_check())
        except Exception:
            return False

    def cleanup(self, why="收工"):
        got = {"killed": 0, "pids": [], "ms": 0.0}
        try:
            got = self.tools.kill_children(why)
        except Exception:
            pass
        if got.get("killed"):
            self.say("（收摊：杀掉了 %d 个还在跑的子进程）" % got["killed"])
        return got

    def run(self, task, extra_fragments=(), snapshot=True, history=None, from_id="", attachments=None):
        try:
            return self._run(task, extra_fragments=extra_fragments, snapshot=snapshot,
                             history=history, from_id=from_id, attachments=attachments)
        finally:
            self.cleanup("跑完了 / 停了 / 出错了")

    def _run(self, task, extra_fragments=(), snapshot=True, history=None, from_id="", attachments=None):
        sys_text, used, missing = compose_system(task, extra_fragments, self.self_tools,
                                                  workdir=str(self.tools.workdir))
        self.task = str(task or "")
        self.want_snapshot = bool(snapshot)
        old = [m for m in (history or []) if str(m.get("role")) != "system"]
        try:
            import ai_mode as M
            _perm = M.perm_note(str(self.tools.workdir))
            _allow = [it.get("path") for it in M.allow_list(str(self.tools.workdir))
                      if (it.get("read") or it.get("write")) and it.get("path") != "*"]
        except Exception:
            _perm, _allow = "", []
        _env_text = env_note(self.tools.workdir, perm=_perm, tmp=self.tmp_dir, allow=_allow)
        user_content = build_user_content(task, _env_text, attachments)
        messages = [{"role": "system", "content": sys_text}] + old + \
                   [{"role": "user", "content": user_content}]
        self.messages = messages
        self.continued_from = str(from_id or "")
        self._journal(force=True)
        if old:
            self.say("接着上次那条聊：它还记得之前 %d 条对话" % len(old))
        self.say("提示词：%s%s" % ("；".join(used),
                                 ("；**缺**：" + "、".join(missing)) if missing else ""))
        self.snapshot = None
        self.snapshot_note = ""
        self._snap_at_start = ""
        if self.want_snapshot:
            self._snapshot_at_start()
        nudges, result = 0, {"ok": False, "reason": "还没收工就停了"}
        n = 0
        while True:
            n += 1
            if self.max_steps and n > self.max_steps:
                result = {"ok": False, "reason": "步数用完了（%d 步）" % self.max_steps}
                break
            if self.stop_check and self.stop_check():
                return self._finish(False, "用户按了停止", used, missing)
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
                                 "★ 已经第 %d 步了%s。**请收尾**："
                                 "要么现在 done(summary=…) 说清你改了什么、怎么验的；"
                                 "要么一句话说清卡在哪、还需要什么 —— 别再做新的探索性读取了。"
                                 % (n - 1,
                                    ("（这次任务的硬顶是 %d 步）" % self.max_steps)
                                    if self.max_steps else "")})
            folded = self._compact(messages)
            if folded:
                self.folded += folded
                self.say("（历史压缩：折叠了 %d 条旧结果，省输入 token）" % folded)
            try:
                if self.on_phase:
                    self.on_phase("thinking")
                self.cur_n = n
                self._stream_reset(n)
                _chat_kw = dict(stop_check=self.stop_check, on_wait=self._on_wait,
                                on_retry=self._on_retry)
                if self.stream_kw:
                    _chat_kw["on_delta"] = self._stream_content
                    _chat_kw["on_reasoning"] = self._stream_think
                resp = self.client.chat(messages, self.tool_table, **_chat_kw)
            except C.Stopped:
                return self._finish(False, "用户按了停止", used, missing)
            except C.AiError as e:
                return self._finish(False, "模型那边出错：%s" % e, used, missing)
            finally:
                self._stream_clear()
            self._add_usage(resp.get("usage"), messages, resp)
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
                if name != "ask":
                    self._step(n, name, brief[:70], note, ms=_ms,
                               disp=_step_disp(name, call.get("args") or {}),
                               nodisp=name in ("done", "answer"),
                               why=str((call.get("args") or {}).get("why") or ""),
                               args=call.get("args") or {}, out=str(out))
                if self.tools.stopped():
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
                    pending_notes.append(msg)
                elif name == "ask" and len(calls) > 1:
                    pending_notes.append(
                        "同一批工具调用里包含多个 ask。一次只能处理一个问题；"
                        "请先等待并使用第一个问题的回答，再决定是否追问。")
                elif name == "answer":
                    if self.tools.edit_seq == 0:
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
                    pending_notes.append(
                        "已经跑通（退出码 0），而且这次运行**满足验收条件**"
                        "（改动之后跑的，或者你本来就没改、只是验证它能跑）。"
                        "如果这就是你要的结果，现在用 done(summary=…) 收工 —— "
                        "summary 里把「怎么用」也写清楚（用户要的是这个）。")
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
                for _note in pending_notes:
                    messages.append({"role": "user", "content": _note})
        if not result["ok"] and self.tools.verified():
            return self._finish(True, "步数用完了（%d 步），但改动已经跑通验证（它没来得及收尾）"
                                      % self.max_steps,
                                used, missing,
                                summary="（它没来得及写 summary —— 看上面的步骤流：%s）"
                                        % "、".join(s["tool"] for s in self.steps[-4:]),
                                caveats="收尾没有正常结束（步数用完），结论以跑过的命令为准。")
        return self._finish(result["ok"], result["reason"], used, missing)

    def _drop_untouched_snapshot(self):
        bid = str(getattr(self, "_snap_at_start", "") or "")
        if not bid or not getattr(self, "snapshot", None):
            return False
        try:
            if self.tools.edit_seq or self.tools.changed or self.tools.run_seq:
                return False
        except Exception:
            return False
        import ai_snap as S
        got = S.drop_untouched(bid, (self.snapshot or {}).get("group") or "")
        if not got.get("ok"):
            self.say("（开工那条空快照没收回：%s）" % got.get("msg"))
            return False
        self.say("这一跑没动过任何东西 ⇒ 把开工那条空快照收掉了（问答不留垃圾）")
        self.snapshot = None
        self._snap_at_start = ""
        return True

    def _finish(self, ok, reason, used, missing, summary="", caveats="", kind="work"):
        self._drop_untouched_snapshot()
        got = {"ok": bool(ok), "reason": reason, "summary": summary, "caveats": caveats,
               "kind": str(kind or "work"),
               "steps": self.steps, "usage": dict(self.usage),
               "prompts": used, "missing_prompts": missing, "tools_log": self.tools.log,
               "files": list(self.tools.changed), "folded": self.folded,
               "snapshot": getattr(self, "snapshot", None),
               "snapshot_note": str(getattr(self, "snapshot_note", "") or ""),
               "messages": self.messages,
               "continued_from": getattr(self, "continued_from", ""),
               "run_id": self.run_id, "tmp_dir": self.tmp_dir,
               "mode": str(self.mode_fn()), "procs_killed": list(self.tools.killed),
               "edited": self.tools.edit_seq}
        self._journal(force=True)
        return got

def run_cli(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        print("用法：ai_loop.py \"<任务>\" [--workdir 目录] [--max-steps N（0 = 不限，默认）] "
              "[--soft-steps N] [--max-tokens N] [--model 模型] [--mode consult|limited|free]")
        return 0 if argv else 2
    task, workdir, max_steps, soft_steps, max_tokens, model = argv[0], None, 0, 0, None, None
    mode = ""
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--workdir" and i + 1 < len(argv):
            workdir = argv[i + 1]; i += 2
        elif a == "--mode" and i + 1 < len(argv):
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
    if max_tokens is None:
        try:
            import ai_budget as _B
            max_tokens = int(_B.load().get("max_tokens") or 0)
        except Exception:
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
