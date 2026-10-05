# -*- coding: utf-8 -*-
"""AI 的手和脚（`V-230`）：**进程内**直接干的那些活 —— 读 / 列 / 搜 / 改 / 跑包 / 切契约。

为什么是"进程内直接干"而不是"让 AI 自己敲命令"
----------------------------------------------
它待的地方是**宿主界面进程**（`system/ui/`），包列表、运行状态、命令行输出这些全在这一侧。
真让它 `shell` 去敲，等于把已经拿到手的东西再绕一圈，而且**每绕一圈都要模型多花 token**。
唯一必须绕回 `moss.exe` 的只有"真跑一个包"（和用户手敲走同一条路，界面不另开执行通道）。

★ 验收闸（你选的 B① 的硬条件）：**loop 的结束条件不是"模型说完成了"**，而是
  `done` 之前**有过一次成功的运行**，且那次运行**发生在最后一次改动之后**。
  这条在这儿记账（`edit_seq` / `run_seq` 两个计数器），由 loop 判断。
"""
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import ai_edits as E                                                  # noqa: E402

NO_WINDOW = 0x08000000
#: 回给模型的东西**一律截断**（全量留在「命令行」页给人看）—— 这是省 token 的第 5 条
TAIL_LINES = 60
TAIL_CHARS = 4000

#: 契约就在这儿（唯一真相）。提示词里**不抄**它的正文，要用就当场切一段。
def spec_path():
    return E.HOME / "system" / "spec" / "插件契约.md"


TOOLS = [
    {"type": "function", "function": {
        "name": "list_dir", "description": "列一个目录（只看一层）。找文件先用它。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "绝对路径；不填 = 当前任务的工作目录"}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": ("读一个文本文件（带行号）。**一次最多回 20000 字符**（约 400~500 行）"
                        "—— 想一次读完整个源文件就 `limit=400`；**别把同一个文件分好几次读**"
                        "（第三次再读同一个文件时会把整篇给它）。"),
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "offset": {"type": "integer", "description": "从第几行开始，默认 1"},
            "limit": {"type": "integer", "description": "读多少行，默认 200；读整个文件填 400"}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "grep", "description": "在目录里按正则搜文本，回「文件:行号: 内容」。",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string"},
            "path": {"type": "string", "description": "目录或文件；默认工作目录"},
            "limit": {"type": "integer", "description": "最多回多少条，默认 40"}},
            "required": ["pattern"]}}},
    {"type": "function", "function": {
        "name": "edit_file",
        "description": ("改文件：把 find 那段原样换成 replace。find **必须和文件里一个字都不差**"
                        "（含缩进）。命中多次会拒绝，除非 replace_all=true。"),
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "find": {"type": "string"},
            "replace": {"type": "string"},
            "replace_all": {"type": "boolean"}},
            "required": ["path", "find", "replace"]}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": ("写文件。新建直接写；**已存在的默认拒绝**（改几行请用 edit_file）—— "
                        "真要**整篇重写**就显式带 overwrite=true。"),
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"},
            "overwrite": {"type": "boolean", "description": "整篇覆盖已存在的文件（慎重）"}},
            "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "spec",
        "description": ("读插件契约（唯一的规矩来源）。section 给标题里的关键词（如 "
                        "「拖放」「pkg.json」「界面」）；给空串则列出所有小节标题。"),
        "parameters": {"type": "object", "properties": {
            "section": {"type": "string"}}, "required": []}}},
    {"type": "function", "function": {
        "name": "run_moss",
        "description": ("跑一条 moss 命令（和用户在终端里敲完全一样），回退出码 + 输出末尾。"
                        "改完必须用它证明「真的能跑」：例如 args=\":新包名 示例参数\"。"),
        "parameters": {"type": "object", "properties": {
            "args": {"type": "string", "description": "moss 后面的那串，例如 \":dazi 你好 3\""},
            "timeout": {"type": "integer", "description": "秒，默认 120"}},
            "required": ["args"]}}},
    {"type": "function", "function": {
        "name": "snap_clean",
        "description": ("清掉**你自己**存过的快照（开工前自动存的那种）。"
                        "**碰不到用户自己存的快照** —— 那些一律跳过，这是设计好的闸。"
                        "run_moss 里删快照的命令会被拒（只能用它）。"),
        "parameters": {"type": "object", "properties": {
            "group": {"type": "string", "description": "包 id（不填 = 当前这次任务的那个包）"},
            "id": {"type": "string", "description": "只清这一条（可选）"}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "answer",
        "description": ("**只是回答问题**时用它收工（问你是谁、问某个包怎么用、问契约里怎么写…）："
                        "一个文件都不用改，所以**不要求跑命令**。答案写在 text 里。"
                        "★ 只要动了文件（哪怕一次）就不能用它，得 run_moss 跑通之后 done。"),
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string", "description": "给用户看的回答（要能直接读，别写文件清单）"},
            "caveats": {"type": "string", "description": "拿不准的、没查的，写在这儿（可选）"}},
            "required": ["text"]}}},
    {"type": "function", "function": {
        "name": "skill",
        "description": ("读一份**技能**（写法指导）：写新包 / 收拖入 这类「方法论」。"
                        "系统提示里列了有哪些（名字 + 描述），**需要哪份就读哪份**"
                        "—— 读一次就够，别反复读。正文里提到的样板 / 文件都在技能目录里，"
                        "回话里会带上目录的绝对路径。"),
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "技能名，例如 new-pkg / dragdrop"}},
            "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "done", "description": ("收工。前提：最后一次改动之后**跑过一次且退出码 0**，"
                                        "否则会被打回来。summary 里写清改了什么、怎么验的。"),
        "parameters": {"type": "object", "properties": {
            "summary": {"type": "string"},
            "caveats": {"type": "string", "description": "没验到的、拿不准的，写在这儿"}},
            "required": ["summary"]}}},
]


def tail(text, lines=TAIL_LINES, chars=TAIL_CHARS):
    s = str(text or "")
    if not s:
        return "（没有输出）"
    ls = s.splitlines()
    cut = len(ls) > lines or len(s) > chars
    if len(ls) > lines:
        s = "\n".join(ls[-lines:])
    if len(s) > chars:
        s = s[-chars:]
    return ("……（前面还有 %d 行，已省略）\n" % (len(ls) - lines) if len(ls) > lines else "") + \
           ("……（已截到末尾 %d 字）\n" % chars if cut and len(s) >= chars else "") + s


def host_cmd():
    """真正跑包用的宿主命令。

    ★★ `V-235` 真机踩到：`MOSS_HOST_CMD` 是 **JSON 数组**（`'["D:\\\\python\\\\two\\\\moss\\\\moss.exe"]'`），
      不是"命令行字符串"。第一版我用 `shlex.split` 去拆 ⇒ 得到
      `['[D:\\python\\two\\moss\\moss.exe]']` 这种带方括号、反斜杠还翻倍的怪 token
      ⇒ `subprocess` 报 **`[WinError 2] 系统找不到指定的文件`** —— 而那个 exe 明明在。
      （界面的日志里那句"宿主命令：[D:\\...\\moss.exe]"就是把方括号一起打出来了，我当时看漏了。）
      所以：**先按 JSON 解**，不是 JSON 才退回"命令行字符串"那种写法（自检脚本爱这么写）。
    兜底顺序：JSON/字符串 → `MOSS_HOME/moss.exe` → `python moss.py`（源码跑）。
    """
    env = (os.environ.get("MOSS_HOST_CMD") or "").strip()
    if env:
        try:
            got = json.loads(env)
            if isinstance(got, list) and got:
                return [str(x) for x in got]
            if isinstance(got, str) and got.strip():
                return shlex.split(got)
        except ValueError:
            return shlex.split(env)
    exe = E.HOME / "moss.exe"
    if exe.is_file():
        return [str(exe)]
    return [sys.executable, str(E.HOME / "moss.py")]


def child_env():
    """给子进程一套**干净**的环境：清掉 `MOSS_*` 里的"我是谁的儿子"那一族。

    ★ `V-220` 的血教训：`MOSS_PKG_ID` / `MOSS_PKG_PARAMS` 会顺着子进程漏下去，
      漏出去的进程会被宿主当成"这个包还在跑"（严重时点「停止」把 explorer 关掉）。
      只保留 MOSS_HOME / MOSS_USER_DATA_DIR（不然子进程会去别的地方找包和数据）。
    """
    keep = {"MOSS_HOME", "MOSS_USER_DATA_DIR"}
    env = {k: v for k, v in os.environ.items()
           if not (k.startswith("MOSS_") and k not in keep)}
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


class Tools:
    """工具执行器。`workdir` 是这次任务的默认目录（通常是那个包的目录）。

    `before_write`（`V-269`）：**第一次真要写文件之前**喊一声 —— 用来"动手前存快照"。
    ★ 为什么挂在这儿而不是开工就存：你问「你是哪个大模型」那种**纯问答**也开工就存，
      等于白写一条备份（还占列表一格）；而且快照点越贴近改动越准。
    """

    def __init__(self, workdir=None, before_write=None):
        self.workdir = Path(workdir) if workdir else E.write_root()
        self.before_write = before_write    # `V-269`：第一次写文件之前叫一次
        self._wrote = False                 # 只叫一次（失败重试也不重复存）
        self.edit_seq = 0          # 第几次成功改动
        self.run_seq = 0           # 第几次跑
        self.last_ok_run_seq = -1  # 最后一次"退出码 0"的跑，发生在第几回合
        self.log = []              # [(工具名, 摘要)]，给人看的步骤流
        self.changed = []          # 这次任务**真动过**的文件（界面要拿它列"改了哪些"）
        self.reads = {}            # 每个文件读了几次（`V-237`：读第三回就提醒别再磨）
        self.greps = {}            # 每组 (路径, 正则) 搜了几次（`V-241`：同一组搜三回就喊停）
        self.grep_files = {}       # 每个文件被搜了几次（换正则也算 —— 那是"一行行刨文件"）

    # ------------------------------------------------------------------ 派发
    def call(self, name, args):
        fn = getattr(self, "_t_" + str(name or ""), None)
        if fn is None:
            return "[错误] 没有这个工具：%s（可用：%s）" % (
                name, "、".join(t["function"]["name"] for t in TOOLS))
        # ★ `V-269`：写文件之前先让 loop 存快照（`before_write` 里做的事**必须**在
        #   `fn(...)` 之前跑完 —— 不然存下来的就是"已经改了一半"的样子）。
        #   只认第一次：同一轮里连改三个文件也只存一条。存不上不影响改（loop 那边自己会记）。
        if not self._wrote and name in ("edit_file", "write_file") and self.before_write:
            self._wrote = True
            try:
                self.before_write()
            except Exception as e:                                   # noqa: BLE001
                self.log.append(("(快照)", "动手前存快照失败：%s" % e))
        try:
            out = fn(args or {})
        except Exception as e:                                       # noqa: BLE001
            return "[工具自己炸了] %s: %s" % (type(e).__name__, e)
        self.log.append((name, str(out).replace("\n", " ")[:110]))
        return out

    def _path(self, args, key="path"):
        raw = str((args or {}).get(key) or "").strip()
        return Path(raw) if raw else self.workdir

    # ------------------------------------------------------------------ 各个工具
    def _t_list_dir(self, args):
        p = self._path(args)
        bad = E.check_readable(p, scope=self.workdir)
        if bad:
            return bad
        if not p.is_dir():
            return "不是目录：%s" % p
        rows = []
        for it in sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
            if it.is_dir():
                rows.append("  [目录] %s/" % it.name)
            else:
                rows.append("  %8d  %s" % (it.stat().st_size, it.name))
        return "%s\n%s" % (p, "\n".join(rows) or "（空）")

    #: 一次 read_file 最多回多少字符（`V-243`：2200 只够 ~60 行、6000 只够 ~130 行，
    #  一个 400 行的源文件要分 3~4 次读 —— 这正是它"不停读同一个文件"的一半原因。
    #  现在给到 20000 字符 ≈ 400~500 行：**一个源文件基本能一次读完**。）
    READ_CHARS = 20000

    def _t_read_file(self, args):
        p = self._path(args)
        # 默认 200 行 / 单次最多 20000 字符（够读完一个源文件）。
        # ★ 读同一个文件到**第三回**时：干脆把整篇给它（到上限为止）—— 与其让它继续换
        #   offset 磨，不如一次给全（`V-243`）。
        key0 = str(p)
        third = self.reads.get(key0, 0) >= 2
        limit = 2000 if third else (args.get("limit") or 200)
        bad = E.check_readable(p, scope=self.workdir)
        if bad:
            return bad
        got, err = E.read_text(p, args.get("offset") or 1, limit)
        if err:
            return err
        key = str(p)
        self.reads[key] = self.reads.get(key, 0) + 1
        note = ""
        if third:
            note = ("\n\n★ 这个文件你已经读过 %d 次了 —— 上面这一份是**整个文件**（到 20000 字符为止），"
                    "别再分次读了：直接改（edit_file），或者开始干活。" % (self.reads[key]))
        if len(got) > self.READ_CHARS:
            return (got[:self.READ_CHARS]
                    + "\n……（已截到 %d 字符；真要后面那段就用 offset=）" % self.READ_CHARS) + note
        return got + note

    def _t_grep(self, args):
        pat = str(args.get("pattern") or "")
        if not pat:
            return "pattern 不能空"
        try:
            rx = re.compile(pat)
        except re.error as e:
            return "正则写错了：%s" % e
        root = self._path(args)
        bad = E.check_readable(root, scope=self.workdir)
        if bad:
            return bad
        # ★ `V-241`：真机那次它把 `ask/AGENT.md` 用 grep **一行一行搜了十几遍**
        #   （一眼看去像"一直在压缩"，其实是它在原地打转）。两条：
        #   ① 同一组 (文件, 正则) 重复 ≥3 次 ⇒ 明说"别这么搜了"；
        #   ② 同一个文件不管什么正则搜到 ≥6 次 ⇒ 让它直接读那个文件。
        key = "%s||%s" % (root, pat)
        self.greps[key] = self.greps.get(key, 0) + 1
        self.grep_files[str(root)] = self.grep_files.get(str(root), 0) + 1
        note = ""
        if self.greps[key] >= 3:
            note = ("\n\n★ 同一组搜索你已经做过 %d 次了 —— 别再用 grep 一行一行刨文件了："
                    "`read_file` 直接看那个文件（`offset`/`limit` 精确定位），"
                    "或者干脆开始改（edit_file）。" % self.greps[key])
        elif self.grep_files[str(root)] >= 6:
            note = ("\n\n★ 这个文件你已经搜了 %d 次 —— 直接 `read_file` 读它，别一条条搜。"
                    % self.grep_files[str(root)])
        limit = int(args.get("limit") or 40)
        files = [root] if root.is_file() else [f for f in root.rglob("*") if f.is_file()]
        hits, scanned = [], 0
        for f in files:
            if len(hits) >= limit:
                break
            try:
                if f.stat().st_size > 2_000_000:
                    continue
                blob = f.read_bytes()
            except OSError:
                continue
            if b"\x00" in blob[:2048]:
                continue
            scanned += 1
            for i, ln in enumerate(blob.decode("utf-8", "replace").splitlines(), 1):
                if rx.search(ln):
                    hits.append("%s:%d: %s" % (f, i, ln.strip()[:160]))
                    if len(hits) >= limit:
                        break
        body = "\n".join(hits) or ("（%d 个文件里没搜到）" % scanned)
        return body + note      # ★ 括号别省：`a or b + note` 会变成 `a or (b+note)`，有命中时提示就丢了

    def _t_edit_file(self, args):
        r = E.apply_edit(self._path(args), args.get("find"), args.get("replace"),
                         bool(args.get("replace_all")))
        if r.get("ok"):
            self.edit_seq += 1
            self._remember(self._path(args))
            return "改好了：换了 %d 处（第 %d 次改动）" % (r.get("replaced") or 1, self.edit_seq)
        return "[失败] %s%s" % (r.get("error") or "", ("\n提示：" + r["hint"]) if r.get("hint") else "")

    def _t_write_file(self, args):
        r = E.write_new(self._path(args), args.get("content"), bool(args.get("overwrite")))
        if r.get("ok"):
            self.edit_seq += 1
            self._remember(self._path(args))
            return "%s：%s（%d 字节，第 %d 次改动）" % (
                "整篇覆盖了" if r.get("overwrote") else "写好了",
                self._path(args), r["bytes"], self.edit_seq)
        return "[失败] %s" % r.get("error")

    def _t_spec(self, args):
        want = str(args.get("section") or "").strip()
        return spec_slice(want)

    def _t_run_moss(self, args):
        line = str(args.get("args") or "").strip()
        if not line:
            return "args 不能空（比如 \":我的包 参数\"）"
        # ★ `V-236` 的硬闸：**删快照这条命令不给走**。
        #   要清就用 `snap_clean`（它只删 `by == "ai"` 的，结构上碰不到用户存的）。
        low = line.lower()
        if "--snap" in low and any(w in low for w in (" rm", " del", " delete", " drop", " gc")):
            return ("[拒绝] 删快照不许用 run_moss —— 用 `snap_clean` 工具（它**只**删你自己存的，"
                    "用户自己存的那些一律跳过）。这是设计好的闸，不是提示。")
        cmd = host_cmd() + shlex.split(line)
        self.run_seq += 1
        cwd = str(E.HOME) if os.path.isdir(str(E.HOME)) else None
        proc, err = None, ""
        for use_cwd in (cwd, None):                  # 先按安装根跑；不行再退回"继承当前目录"
            try:
                proc = subprocess.run(cmd, cwd=use_cwd, env=child_env(),
                                      capture_output=True, text=True, encoding="utf-8",
                                      errors="replace", timeout=int(args.get("timeout") or 120),
                                      creationflags=NO_WINDOW)
                break
            except subprocess.TimeoutExpired:
                return "[超时] 跑超过 %s 秒 —— 交互式包（等你敲键的那种）在这儿跑不了。" % (
                    args.get("timeout") or 120)
            except OSError as e:
                err = "%s（cwd=%r，存在=%s）" % (e, use_cwd, os.path.isdir(str(use_cwd)) if use_cwd else "继承")
        if proc is None:
            # ★ 报错里必须带上**到底跑了什么命令、cwd 在不在**（`V-235` 就是靠这个查出来的：
            #   命令里那个方括号、和"exe 明明在却报找不到"这两条线索缺一不可）
            return ("[跑不起来] %s\n  命令 = %r\n  cwd = %r\n  用的宿主 = %r\n"
                    "  （提醒：`MOSS_HOST_CMD` 是 JSON 数组，不是命令行字符串；"
                    "自己写探针时别用 shlex 拆它）"
                    % (err, cmd, cwd, os.environ.get("MOSS_HOST_CMD") or "（没设，按安装根推）"))
        code = proc.returncode
        if code == 0:
            self.last_ok_run_seq = self.edit_seq
        out = tail("$ %s\n%s%s" % (" ".join(cmd[1:]), proc.stdout or "", proc.stderr or ""))
        return "退出码 %d（第 %d 次运行）\n%s" % (code, self.run_seq, out)

    def _t_skill(self, args):
        """读一份技能（`V-278`）。**名字必须在清单里**（不许拿它当任意文件读取的口子）。

        ★ 为什么要走工具而不是让它 `read_file`：读守卫按"干活目录"放行（`E.check_readable`），
          `system/skills/**` 不在那里面 —— 而且技能目录里的样板/骨架**本来就不该**进
          "能随便读"的范围；由这里按名字取，一条不多一条不少。
        """
        import ai_skills as K                                          # noqa: PLC0415
        want = str((args or {}).get("name") or "").strip()
        got = K.usable().get(want)
        if not got:
            bad = K.broken().get(want)
            if bad:
                return "技能「%s」有问题、没进清单：%s\n可用的：%s" % (
                    want, "；".join(bad["problems"]), "、".join(K.names()) or "（没有）")
            return "没有这个技能：%r\n可用的：%s" % (want, "、".join(K.usable()) or "（没有）")
        return ("# 技能：%s\n（这份在 %s；正文里提到的样板 / 文件都在这个目录下）\n\n%s"
                % (got["name"], got["path"].parent, got["body"]))

    def _t_done(self, args):
        """★ 别回显 `summary`（`V-269` 补）：那一行会原样出现在步骤卡右边，而 summary
        马上又出现在结论卡里 ⇒ 同一段话两遍。这里只回一句"收到"。"""
        return "收到。"
        """纯问答收工（`V-269`）。工具本身不做判断 —— **闸在 loop 里**：
        只有"一个文件都没动过"才准用它收工（动过文件的必须走 `done` + 跑一遍）。

        ★ 别把 `text` 回显进来（第一版就是 `…。text=<整段回答>`）：那一行会原样出现在
          步骤卡的右边（`note`），于是同一段回答在界面上出现两遍，还把那一行撑满
          —— 真机截图里就是这样，你一眼就看出多余。
        """
        return "收到（这次是回答，没动文件）。"

    def _t_snap_clean(self, args):
        """清自己存的快照（`V-236`）。**只能删 `by == "ai"` 的** —— 闸在 `delete_ai()` 里。"""
        import ai_snap as S                                              # noqa: PLC0415
        group = str((args or {}).get("group") or "").strip()
        if not group:
            # 不填就按"这次干活的那个包目录"猜（`user_data/pkgs/<id>` ⇒ id）
            try:
                rel = os.path.relpath(str(self.workdir), str(E.write_root()))
                group = rel.split(os.sep)[0] if rel and not rel.startswith("..") else ""
            except ValueError:
                group = ""
        got = S.clean_ai(group=group, bid=str((args or {}).get("id") or ""))
        if not got.get("ok"):
            return "[失败] %s" % got.get("msg")
        return "%s（清掉 %d 条，跳过你存的 %d 条）" % (
            got.get("msg"), len(got.get("deleted") or []), len(got.get("skipped") or []))

    # ------------------------------------------------------------------ 验收闸
    def _remember(self, p):
        """记下"这次真动过的文件"（界面要拿它列"改了哪些"；同一个文件只记一次）。"""
        s = str(p)
        if s not in self.changed:
            self.changed.append(s)

    def verified(self):
        """能不能收工。

        ★ `V-237` 修的那条：**"看完了发现不用改"也是合法结局**。
          真机那次任务（让 `calc` 支持指数/开方）本来就支持 —— 模型读了一圈、跑了两条命令
          （退出码 0）证明"它会算"，然后步数用完。原来这道闸要求"必须有改动"，
          于是这种任务**永远过不了**（哪怕它做对了）。
          现在的规矩：**跑过一次、而且成功**就够；有改动时仍然要求"改动之后跑过"。
          （"什么都不干只跑一次就说完成"会被 step 预算和 `done` 里的 summary 审出来 ——
           而且这比"做对了却判失败"划算。）
        """
        if self.edit_seq == 0:
            return self.run_seq > 0 and self.last_ok_run_seq >= 0
        return self.last_ok_run_seq >= self.edit_seq

    def gate_reason(self):
        if self.edit_seq == 0:
            if self.run_seq == 0:
                return ("一次都没跑过 —— 光看不算验收：改完（或者确认不用改之后）"
                        "用 run_moss 真跑一次、退出码 0，再来说收工。")
            return ("跑过了但**没有一次成功**（现在是第 %d 次），把失败原因读明白再改。"
                    % self.run_seq)
        return ("最后一次改动（第 %d 次）之后**没有成功的运行**（最近一次成功在第 %d 次时）。"
                "先 `run_moss` 跑一次、退出码 0，再来说收工。" % (self.edit_seq, self.last_ok_run_seq))


# ---------------------------------------------------------------------- 契约切片
_HEAD = re.compile(r"^(#{1,4})\s+(.*)$", re.M)


def spec_index():
    """契约的目录（标题 + 行号），给模型一个"我该读哪一节"的入口。"""
    if not spec_path().is_file():
        return "契约文件不在：%s" % spec_path()
    text = spec_path().read_text(encoding="utf-8", errors="replace")
    rows = []
    for m in _HEAD.finditer(text):
        level = len(m.group(1))
        if level <= 3:
            rows.append("%s%s（%d 行）" % ("  " * (level - 1), m.group(2).strip(),
                                          text[:m.start()].count("\n") + 1))
    return "插件契约 %s\n%s" % (spec_path(), "\n".join(rows))


def spec_slice(section, max_lines=220):
    """按标题关键词切一段契约出来（**唯一真相还是那个文件**，这里只是"递给模型看"）。"""
    if not section:
        return spec_index()
    if not spec_path().is_file():
        return "契约文件不在：%s" % spec_path()
    text = spec_path().read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    heads = [(i, len(m.group(1)), m.group(2).strip())
             for i, ln in enumerate(lines) for m in [_HEAD.match(ln)] if m]
    want = section.strip()
    hit = [(i, lv, title) for (i, lv, title) in heads if want in title]
    if not hit:
        near = [t for (_i, _lv, t) in heads if any(ch in t for ch in want[:2])][:8]
        return "契约里没有含「%s」的小节。%s\n\n可用的目录：\n%s" % (
            want, ("你是想找：" + " / ".join(near)) if near else "", spec_index())
    start, level, title = hit[0]
    end = len(lines)
    for (i, lv, _t) in heads:
        if i > start and lv <= level:
            end = i
            break
    body = lines[start:min(end, start + max_lines)]
    more = "\n……（这一段还有 %d 行没给，需要就再要一次别的关键词）" % (end - start - len(body)) \
        if end - start > len(body) else ""
    return "《%s》（契约第 %d 行起）\n%s%s" % (title, start + 1, "\n".join(body), more)
