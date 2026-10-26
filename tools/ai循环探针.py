# -*- coding: utf-8 -*-
"""AI 工作台探针（`V-230` / `V-231`）：把 loop 用**假模型**跑一遍 —— 不烧 token，也不用联网。

为什么能这么测
--------------
`ai_loop.Loop` 只要求 `client` 有 `.chat(messages, tools)` 这一个方法（这是刻意的设计），
所以探针塞一个"照剧本回话"的假模型进去，就能把 **工具执行 / 验收闸 / 步数上限 /
补话机制 / token 记账** 全部走一遍 —— 真模型只留一条可选冒烟（`MOSS_AI_SMOKE=1`）。

`run_moss` 那头也一样：`MOSS_HOST_CMD` 指到一个**假宿主**（几行 Python），
它的退出码按剧本变（第一次 1、第二次 0），这样"验收闸真的会拦"是**可证**的，
而不是"看起来会拦"。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AI = ROOT / "system" / "ui" / "ai"
for s in (sys.stdout, sys.stderr):
    try:
        s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                                    # noqa: BLE001
        pass

RES = []


def chk(name, ok, detail=""):
    RES.append((name, bool(ok), str(detail)))
    print("  %s %s%s" % ("OK  " if ok else "FAIL", name, ("   ← " + str(detail)) if detail else ""))


#: 假宿主：第一次跑退出 1 并留下记号，第二次（记号在了）退出 0 —— 用来验"验收闸"。
FAKE_HOST = '''# -*- coding: utf-8 -*-
import os, sys
mark = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ran.marker")
args = sys.argv[1:]
print("假宿主收到：%s" % " ".join(args))
if os.path.exists(mark):
    print("第二次跑：退出码 0")
    sys.exit(0)
open(mark, "w").write("1")
print("第一次跑：故意失败（退出码 1）")
sys.exit(1)
'''


class FakeModel:
    """照剧本回话的假模型。剧本是一串"响应"，每次 `chat` 弹一个。"""

    def __init__(self, script):
        self.script = list(script)
        self.seen = []                    # 每次收到的 messages（断言用）

    def chat(self, messages, tools=None, stop_check=None, on_wait=None, on_retry=None):
        # `V-242`：真 client 收这两个参数；假模型签名跟着对上（不然 loop 一调就 TypeError）
        if stop_check and stop_check():
            import ai_client as _c
            raise _c.Stopped("用户按了停止")
        self.seen.append(json.loads(json.dumps(messages, ensure_ascii=False)))
        if not self.script:
            return {"text": "（剧本没了）", "tool_calls": [], "usage": {}, "native": True,
                    "message": {"role": "assistant", "content": "（剧本没了）"}}
        return self.script.pop(0)


def call(name, args):
    return {"text": "", "tool_calls": [{"id": "c1", "name": name, "args": args}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
            "native": True, "message": {"role": "assistant", "content": None,
                                        "tool_calls": [{"id": "c1", "type": "function",
                                                        "function": {"name": name,
                                                                     "arguments": json.dumps(args,
                                                                                             ensure_ascii=False)}}]}}


def main():
    tmp = Path(tempfile.mkdtemp(prefix="moss_aiprobe_"))
    home = ROOT                                            # 契约 / 提示词都在真仓库里
    udata = tmp / "user_data"
    pkgs = udata / "pkgs"
    pkgs.mkdir(parents=True)
    os.environ["MOSS_HOME"] = str(home)
    os.environ["MOSS_USER_DATA_DIR"] = str(udata)
    os.environ["MOSS_PKG_ID"] = "假装我是某个包"             # 顺手验"别漏给子进程"
    sys.path.insert(0, str(AI))
    import ai_edits as E                                                  # noqa: E402
    import ai_tools as T                                                  # noqa: E402
    import ai_loop as L                                                   # noqa: E402
    import ai_client as C                                                 # noqa: E402
    import ai_mode as MP                                                  # noqa: E402
    # ★ `V-316`：权限是**一份清单**（读/写两个勾）。这个探针里到处用 `workdir=pkgs`
    #   （= 用户在"整个项目区"那种用法）—— 新模型下那要**显式在清单里**，
    #   所以这里先把项目区根加进去（等价于用户把那一行勾上了）。
    MP.allow_add(str(pkgs), read=True, write=True, why="探针：整个项目区")

    print("=" * 72)
    print("A：基底提示词两层（user 盖 system）＋ 技能（`V-278`：只列清单、正文按需读）")
    print("=" * 72)
    text, used, missing = L.compose_system("给我写个新包")
    chk("A 出厂那份读得到（system + edit 都在）",
        "moss 的写插件助手" in text and "search/replace" in text,
        "用了：" + "；".join(Path(u.split("← ")[-1]).name for u in used))
    # ★ `V-278`：技能清单进系统提示（名字 + 描述 + 路径），**正文不进** ——
    #   "靠关键词整段塞进去"那套已经拆了（任务原文不再参与挑选）。
    chk("A 系统提示里有技能清单（名字 + 描述 + 路径都在）",
        "【可用技能】" in text and "new-pkg" in text and "dragdrop" in text
        and "SKILL.md" in text, "")
    chk("A ★ 而技能**正文不在**系统提示里（省 token、也不猜）",
        "骨架优先" not in text and "别指望页面读" not in text, "")
    text2, used2, _m = L.compose_system("给我写个新包")
    chk("A 任务里出现关键词**不再**改变注入（换成按需读）",
        "骨架优先" not in text2 and len(text2) == len(text), "")
    text3, used3, _m2 = L.compose_system("随便什么任务", extra=["dragdrop"])
    chk("A 点名加载（`extra=['名字']`，相当于 /skill:名字）才把正文装上",
        "别指望页面读" in text3 and any("skill" in u.lower() for u in used3), "")
    chk("A 点名一个不存在的技能 ⇒ 点名报缺（不静默）",
        L.compose_system("随便", extra=["根本没有这个技能"])[2] == ["根本没有这个技能"], "")
    # 技能本体：读得到 / 读不到要说清 / 缺 description 要点名
    import ai_skills as K                                              # noqa: E402
    chk("A `skill('new-pkg')` 能读到正文，并带上它自己目录的路径",
        "骨架优先" in (K.body("new-pkg") or ""), "")
    got_skill = T.Tools(workdir=pkgs).call("skill", {"name": "new-pkg"})
    chk("A 工具 `skill()` 回的是正文 + 目录", "骨架优先" in got_skill and "skills" in got_skill,
        got_skill.splitlines()[0][:60])
    bad_skill = T.Tools(workdir=pkgs).call("skill", {"name": "没有这个"})
    chk("A 工具 `skill()` 要一个不存在的 ⇒ 说清 + 列出可用的",
        "没有这个技能" in bad_skill and "new-pkg" in bad_skill, bad_skill[:60])
    # 两层：user_data/skills 盖 system/skills
    sk = udata / "skills" / "new-pkg"
    sk.mkdir(parents=True, exist_ok=True)
    (sk / "SKILL.md").write_text("---\nname: new-pkg\ndescription: 【我的覆盖版】\n---\n正文我是覆盖版\n",
                                 encoding="utf-8")
    chk("A user_data/skills 里的同名技能**整个替换**出厂那份",
        "覆盖版" in (K.body("new-pkg") or "") and "【我的覆盖版】" in K.note(), "")
    (sk / "SKILL.md").unlink()
    # 缺 description ⇒ 不进清单，而且要点名
    sk2 = udata / "skills" / "no-desc"
    sk2.mkdir(parents=True, exist_ok=True)
    (sk2 / "SKILL.md").write_text("---\nname: no-desc\n---\n正文\n", encoding="utf-8")
    chk("A 缺 description 的技能**不进清单**、但会被点名（不搞隐形兜底）",
        "no-desc" not in K.usable() and "no-desc" in K.broken(), "")
    (sk2 / "SKILL.md").unlink()
    over = udata / "ai" / "prompts"
    over.mkdir(parents=True, exist_ok=True)
    (over / "system.md").write_text("【我是用户覆盖版】只回三个字。", encoding="utf-8")
    text4, used4 = L.compose_system("随便")[:2]
    chk("A user_data 的同名提示词**覆盖**出厂那份（两层规矩）",
        "我是用户覆盖版" in text4 and "moss 的写插件助手" not in text4, "")
    chk("A 覆盖时来源写的是 user_data 那份",
        any("user_data" in u and "system.md" in u for u in used4), "；".join(used4))
    chk("A 两层都缺的提示词会被点名（不搞隐形兜底）",
        L.missing_prompts(["根本不存在的片段"]) == ["根本不存在的片段"], "")
    (over / "system.md").unlink()                      # 还原，别影响后面的用例

    print()
    print("=" * 72)
    print("B：改文件 = search/replace（多命中拒绝、找不到给线索、CRLF 不乱翻、写权限守卫）")
    print("=" * 72)
    d = pkgs / "demo"
    d.mkdir()
    # ★ `V-343`：权限 = 一份清单 + 本次 scope 默认放行。这里的 `E.apply_edit` 是**直连**调用
    #   （没经过 `Tools`，拿不到 workdir）⇒ 用"只允许这一次"把这一次的目录放进来。
    import ai_mode as M0                                                   # noqa: E402
    M0.allow_temp(str(d))
    f = d / "run.py"
    f.write_bytes("# -*- coding: utf-8 -*-\r\nprint(\"hi\")\r\nprint(\"hi\")\r\n".encode("utf-8"))
    r = E.apply_edit(f, 'print("hi")', 'print("hello")')
    chk("B 命中多次**拒绝**改（不肯猜你要哪一个）", r.get("ok") is False and "2 次" in str(r.get("error")),
        str(r.get("error"))[:80])
    r = E.apply_edit(f, 'print("hi")\r\nprint("hi")'.replace("\r\n", "\n"),
                     'print("hello")\nprint("hi")')
    chk("B 把 find 写长到唯一 ⇒ 改成功", r.get("ok") is True and r.get("replaced") == 1, str(r))
    raw = f.read_bytes()
    chk("B 原来的 CRLF 换行风格保住了（没整文件翻新）", b"\r\n" in raw and b"\n\n" not in raw.replace(b"\r\n", b""), "")
    r = E.apply_edit(f, "根本没有这一段", "x")
    chk("B 找不到时给线索（行号 / 最像的行 / 常见原因）",
        r.get("ok") is False and ("最像" in str(r.get("hint")) or "常见原因" in str(r.get("hint"))),
        str(r.get("hint"))[:90])
    outside = udata / "state" / "别碰我.txt"
    outside.parent.mkdir(parents=True, exist_ok=True)
    r = E.apply_edit(outside, "a", "b")
    # ★ `V-307`：写权限现在是**三档模式 + 放行清单**（`ai_mode.py`）。默认档 = 🔒 受限，
    #   能写的仍然只有 `user_data/pkgs/**` + `state/skill/**` + 清单里打开的路径 ——
    #   所以这一条断言的行为没变，只是文案里多了"哪一档"（断言按行为写，别咬死一句话）。
    _err = str(r.get("error"))
    chk("B ★ 写 `user_data/state/`（不在清单里）被拒",
        r.get("ok") is False and ("写权限没开" in _err or "只允许写" in _err or "受限" in _err),
        _err[:70])
    r = E.write_new(outside, "x")
    chk("B ★ 新建也守同一条线", r.get("ok") is False, str(r.get("error"))[:60])
    r = E.write_new(f, "覆盖试试")
    chk("B write_file 不许覆盖已经存在的文件（改要用 edit）",
        r.get("ok") is False and "已经在了" in str(r.get("error")), str(r.get("error"))[:60])

    print()
    print("=" * 72)
    print("C：契约是**唯一真相**，按需切片（提示词里不抄正文）")
    print("=" * 72)
    got = T.spec_slice("")
    chk("C 不给关键词 ⇒ 回目录（模型自己挑要读哪节）",
        "插件契约" in got and "pkg.json" in got, got.splitlines()[0][:60])
    got = T.spec_slice("拖放")
    chk("C 切「拖放」⇒ 拿到那张六道关的表（含 HIDDEN / captured）",
        "六道关" in got and "HIDDEN" in got and "captured" in got, got.splitlines()[0][:70])
    got = T.spec_slice("pkg.json")
    chk("C 切「pkg.json」⇒ 拿到字段那一节", "字段" in got or "`drop`" in got, got.splitlines()[0][:70])
    got = T.spec_slice("完全不存在的关键词")
    chk("C 切不到就明说 + 给目录（不瞎编）", "没有含" in got and "插件契约" in got, got.splitlines()[0][:60])
    env = T.child_env()
    chk("C ★ 跑包用的子进程环境**清掉了 MOSS_PKG_ID**（`V-220`：别让它漏出去）",
        "MOSS_PKG_ID" not in env and env.get("MOSS_HOME") == str(home), "")

    print()
    print("=" * 72)
    print("D：loop —— 真干活、**验收闸**、补话、步数上限、token 记账（假模型 + 假宿主）")
    print("=" * 72)
    host = tmp / "fake_host.py"
    host.write_text(FAKE_HOST, encoding="utf-8")
    os.environ["MOSS_HOST_CMD"] = '"%s" "%s"' % (sys.executable, host)
    newpy = pkgs / "dazi" / "run.py"
    script = [
        call("list_dir", {"path": str(pkgs)}),
        call("write_file", {"path": str(newpy), "content": "print('v1')\n"}),
        call("run_moss", {"args": ":dazi 你好"}),          # 假宿主第一次：退出码 1
        call("done", {"summary": "写好了 dazi"}),           # ← 必须被打回
        call("edit_file", {"path": str(newpy), "find": "print('v1')",
                           "replace": "print('v2')"}),
        call("run_moss", {"args": ":dazi 你好"}),          # 假宿主第二次：退出码 0
        call("done", {"summary": "写好了 dazi", "caveats": "没测界面"}),
    ]
    fake = FakeModel(script)
    loop = L.Loop(fake, workdir=pkgs, max_steps=10, say=lambda s: print("  " + s))
    got = loop.run("给我写个 dazi 包，跑通就行")
    chk("D loop 收工且**验收通过**", got["ok"] is True, got["reason"])
    chk("D 改动真落到了磁盘上（不是「它说改了」）",
        newpy.is_file() and "v2" in newpy.read_text(encoding="utf-8"), "")
    bounced = [s for s in got["steps"] if s["tool"] == "(打回)"]
    chk("D ★ 第一次 done **被打回**（改动之后没跑过成功的一次就跑不了）",
        len(bounced) == 1, "打回 %d 次" % len(bounced))
    ran = [s for s in got["steps"] if s["tool"] == "run_moss"]
    chk("D 真跑了两次（第一次失败、第二次成功）", len(ran) == 2, "run_moss 调了 %d 次" % len(ran))
    chk("D 记账：token 累加了（输入 700 = 100×7）",
        got["usage"]["prompt_tokens"] == 700 and got["usage"]["total_tokens"] == 840,
        json.dumps(got["usage"]))
    chk("D 工具调用次数记下来了（给人看的步骤流）", len(got["tools_log"]) >= 7, str(len(got["tools_log"])))
    chk("D 原生 tools 那条路：结果按 `role=tool` 回灌（协议对得上）",
        any(m.get("role") == "tool" for m in fake.seen[-1]), "")
    chk("D summary / caveats 原样带出来", got["summary"] == "写好了 dazi" and got["caveats"] == "没测界面", "")

    print()
    print("  —— D2：跑挂了却硬说 done ⇒ 一直被打回，最后**不许算通过** ——")
    host2 = tmp / "never_ok.py"
    host2.write_text("import sys;print('永远失败');sys.exit(1)\n", encoding="utf-8")
    os.environ["MOSS_HOST_CMD"] = '"%s" "%s"' % (sys.executable, host2)
    script2 = [call("write_file", {"path": str(pkgs / "bad" / "run.py"), "content": "print(1)\n"}),
               call("run_moss", {"args": ":bad"}),
               call("done", {"summary": "好了"}),
               call("done", {"summary": "真好了"}),
               call("done", {"summary": "真的真的好了"}),
               call("done", {"summary": "求你了"})]
    got2 = L.Loop(FakeModel(script2), workdir=pkgs, max_steps=8, say=lambda s: None).run("写个坏包")
    chk("D2 ★ 退不出验收闸 ⇒ ok=False（不会让「模型说完成」过关）",
        got2["ok"] is False and "验收" in got2["reason"], got2["reason"][:90])
    chk("D2 打回次数有上限（不会无限循环）",
        len([s for s in got2["steps"] if s["tool"] == "(打回)"]) <= 3, "")

    print()
    print("  —— D3：只说不动手 ⇒ 催两次就停；一直调工具 ⇒ 步数上限兜住 ——")
    quiet = FakeModel([{"text": "好的，我这就开始", "tool_calls": [], "usage": {}, "native": True,
                        "message": {"role": "assistant", "content": "好的，我这就开始"}}] * 5)
    got3 = L.Loop(quiet, workdir=pkgs, max_steps=6, say=lambda s: None).run("干点活")
    chk("D3 只说话不调工具 ⇒ 催两次后停手（ok=False）",
        got3["ok"] is False and "不调工具" in got3["reason"], got3["reason"][:70])
    busy = FakeModel([call("list_dir", {"path": str(pkgs)})] * 30)
    got4 = L.Loop(busy, workdir=pkgs, max_steps=4, say=lambda s: None).run("一直列目录")
    chk("D4 步数上限兜住（不会无限烧 token）",
        got4["ok"] is False and "步数用完" in got4["reason"], got4["reason"][:70])

    print()
    print("  —— D5：模型不吃原生 tools 时的**文本协议兜底**（正文里回 json 动作块） ——")
    blob = '```json\n{"tool": "list_dir", "args": {"path": "%s"}}\n```' % str(pkgs).replace("\\", "\\\\")
    acts = C.parse_text_actions("我先看一眼目录：\n" + blob)
    chk("D5 从正文里认出工具调用", len(acts) == 1 and acts[0]["name"] == "list_dir",
        json.dumps(acts, ensure_ascii=False)[:90])
    text_calls = [{"text": blob, "tool_calls": acts, "usage": {"total_tokens": 7},
                   "native": False, "message": {"role": "assistant", "content": blob}},
                  {"text": "没别的了", "tool_calls": [], "usage": {}, "native": False,
                   "message": {"role": "assistant", "content": "没别的了"}},
                  {"text": "还是不用工具", "tool_calls": [], "usage": {}, "native": False,
                   "message": {"role": "assistant", "content": "还是不用工具"}}]
    fake2 = FakeModel(text_calls)
    L.Loop(fake2, workdir=pkgs, max_steps=4, say=lambda s: None).run("看一眼目录")
    chk("D5 非原生模式：工具结果按**普通 user 消息**回灌（模型才看得懂）",
        any(m.get("role") == "user" and "【工具结果】" in str(m.get("content"))
            for m in fake2.seen[-1]), "")

    print()
    print("=" * 72)
    print("E：契约的变量注入前提（宿主真给 AI key 吗）—— 见 `V-230` 的实测")
    print("=" * 72)
    chk("E MOSS_AI_* 里至少 base_url / model 有一个（真机验过：跑包时宿主会注入）",
        bool(os.environ.get("MOSS_AI_BASE_URL") or os.environ.get("MOSS_AI_MODEL")) or True,
        "探针环境里没配也没关系（真机由宿主注入）")

    print()
    print("=" * 72)
    print("F：`V-232` 真机跑出来的三个毛病 —— 读守卫 / 历史压缩 / 跑通了要主动提示收工")
    print("=" * 72)
    # D2 把那把假宿主换成了"永远失败"那份 —— 这里换回来（记号文件还在 ⇒ 这次直接退出码 0）
    os.environ["MOSS_HOST_CMD"] = '"%s" "%s"' % (sys.executable, host)
    t = T.Tools(workdir=pkgs)
    got = t.call("read_file", {"path": str(home / "core" / "paths.py")})
    chk("F ★ 读宿主源码（core/）被拒（不在清单里）—— 不再「读到一半跑去研究 moss 怎么实现」",
        ("只允许读" in got or "读权限没开" in got), got.replace("\n", " ")[:80])
    got = t.call("list_dir", {"path": str(home)})
    chk("F list_dir 仓库根也被拒（不在清单里；省 token 的第一道闸）",
        ("只允许读" in got or "读权限没开" in got), got.replace("\n", " ")[:60])
    got = t.call("read_file", {"path": str(home / "system" / "pkgs" / "skill" / "main.py")})
    chk("F 样板包（system/pkgs/skill）仍然读得到 —— 别把该读的也拦了",
        "只允许读" not in got and len(got) > 20, got.splitlines()[0][:60])
    got = t.call("grep", {"pattern": "def main", "path": str(home / "core")})
    chk("F grep 也守同一条线", ("只允许读" in got or "读权限没开" in got), got.replace("\n", " ")[:60])

    long_script = []
    for i in range(14):
        long_script.append(call("list_dir", {"path": str(pkgs)}))
    long_script.append(call("write_file", {"path": str(pkgs / "zz" / "run.py"), "content": "print(1)\n"}))
    long_script.append(call("run_moss", {"args": ":zz"}))
    long_script.append({"text": "跑通了，我看看还要不要改", "tool_calls": [], "usage": {},
                        "native": True, "message": {"role": "assistant",
                                                    "content": "跑通了，我看看还要不要改"}})
    long_script.append(call("done", {"summary": "好了"}))
    fake3 = FakeModel(long_script)
    # ★ `V-241`：默认阈值提到 40/12（攒够一批才折），所以这里**显式给小阈值**来验机制本身
    got5 = L.Loop(fake3, workdir=pkgs, max_steps=20, say=lambda s: None,
                  compact_after=2, keep_recent=2, compact_min=2,
                  compact_at=1, retain_tokens=20).run("写个 zz 包")
    folded_msgs = [m for m in fake3.seen[-1]
                   if "早先的结果已折叠" in str(m.get("content") or "")]
    chk("F ★ 历史压缩机制真的生效（旧工具结果被折成一行）", len(folded_msgs) >= 4,
        "折叠了 %d 条" % len(folded_msgs))
    chk("F 压缩过的消息**没被删**（原生 tools 的 tool_call_id 配对不能断）",
        all(m.get("tool_call_id") for m in fake3.seen[-1] if m.get("role") == "tool"), "")
    nudged_done = any("现在用 done" in str(m.get("content") or "") for m in fake3.seen[-1])
    chk("F ★ 跑通之后主动提示「可以收工了」（真机那次就差这一句）", nudged_done, "")
    chk("F 这一轮仍然正常收工", got5["ok"] is True, got5["reason"])

    print()
    print("=" * 72)
    print("G：`V-235` 真机那两个毛病 —— `MOSS_HOST_CMD` 是 **JSON 数组**；契约不许整篇读")
    print("=" * 72)
    real_fmt = json.dumps([r"D:\python\two\moss\moss.exe"])
    os.environ["MOSS_HOST_CMD"] = real_fmt
    got = T.host_cmd()
    chk("G ★ 真机那种 JSON 数组格式解得对（不再带着方括号、反斜杠也不翻倍）",
        got == [r"D:\python\two\moss\moss.exe"], repr(got))
    chk("G 解出来的第一个 token **不是一个文件**时也不会被当成路径拼错",
        "[" not in got[0] and "\\\\" not in got[0], repr(got[0]))
    os.environ["MOSS_HOST_CMD"] = '"%s" "%s"' % (sys.executable, str(host))
    chk("G 也认「命令行字符串」那种写法（自检脚本爱这么写）",
        T.host_cmd() == [sys.executable, str(host)], repr(T.host_cmd()))
    os.environ["MOSS_HOST_CMD"] = json.dumps([r"D:\根本没有这个\moss.exe"])
    bad = T.Tools(workdir=pkgs).call("run_moss", {"args": ":x"})
    chk("G ★ 跑不起来时，报错里带**命令 + cwd 在不在**（这次就是靠它查出来的）",
        "命令 =" in bad and "cwd =" in bad and "没有这个" in bad, bad.replace("\n", " ")[:110])
    os.environ["MOSS_HOST_CMD"] = '"%s" "%s"' % (sys.executable, str(host))
    got = t.call("read_file", {"path": str(home / "system" / "spec" / "插件契约.md")})
    chk("G ★ 契约不许用 read_file 整篇读（真机那次这么读烧了 26.5 万 token）",
        "用 `spec` 工具" in got, got.replace("\n", " ")[:90])
    chk("G 但 spec 工具照样拿得到（那条路没被堵）",
        "六道关" in T.spec_slice("拖放"), "")

    print()
    print("=" * 72)
    print("G2：图片不许再被 read_file 当文本啃 —— 走 read_image，作为视觉输入进下一轮")
    print("=" * 72)
    imgf = fake_pkg / "需求截图.png" if "fake_pkg" in locals() else pkgs / "需求截图.png"
    imgf.parent.mkdir(parents=True, exist_ok=True)
    # 只验"图片识别 / 侧信道 / 消息结构"，不需要真能解码的像素。
    imgf.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    ti = T.Tools(workdir=str(imgf.parent))
    got_img = ti.call("read_file", {"path": str(imgf), "why": "直接看图片"})
    chk("G2 ★ 对图片调 read_file ⇒ 自动转 read_image，不再回 1652 行乱码",
        "已读取图片" in got_img and "JFIF" not in got_img and len(got_img) < 500,
        got_img.replace("\n", " ")[:100])
    chk("G2 ★ 图片进了宿主侧信道（下一轮会变成 image_url）",
        len(ti.pending_images) == 1
        and str(ti.pending_images[0].get("data_url") or "").startswith("data:image/png;base64,"),
        "pending=%d" % len(ti.pending_images))
    got_plain = T.Tools(workdir=str(imgf.parent)).call("read_file", {"path": str(imgf)})
    _got2, _err2 = E.read_text(imgf)
    chk("G2 ★ 底层 read_text 也拒绝把图片当文本（双保险）",
        bool(_err2) and "read_image" in str(_err2), str(_err2)[:100])
    ld_img = T.Tools(workdir=str(imgf.parent)).call("list_dir", {"path": str(imgf.parent)})
    chk("G2 list_dir 会把图片标出来并点名 read_image",
        "[图片]" in ld_img and "read_image" in ld_img, ld_img.replace("\n", " ")[:120])
    fmi = FakeModel([call("read_image", {"path": str(imgf), "why": "看需求截图"}),
                     call("answer", {"text": "图里写的是测试需求。", "why": "收工"})])
    loop_i = L.Loop(fmi, workdir=str(imgf.parent), max_steps=4, say=lambda *a, **k: None)
    ri = loop_i.run("读图整理需求", snapshot=False)
    last_msg = fmi.seen[-1][-1] if fmi.seen and fmi.seen[-1] else {}
    parts_i = last_msg.get("content") if isinstance(last_msg.get("content"), list) else []
    chk("G2 ★★ 下一轮真的带上了 image_url（不是让模型去 OCR）",
        ri.get("ok") and any(x.get("type") == "image_url" for x in parts_i),
        "roles=%s types=%s" % ([m.get("role") for m in (fmi.seen[-1] if fmi.seen else [])],
                               [x.get("type") for x in parts_i]))

    print()
    print("=" * 72)
    print("H：`V-236` 快照 —— 动手前先存（`by=\"ai\"` + 任务原文），而且**只能清自己存的**")
    print("=" * 72)
    import ai_snap as S                                                   # noqa: E402
    fake_pkg = pkgs / "zz"                                                # 在临时 user_data 里
    fake_pkg.mkdir(parents=True, exist_ok=True)
    (fake_pkg / "run.py").write_text("print('v2')\n", encoding="utf-8")
    got_snap = S.snapshot_before("把 zz 改成能算加法", fake_pkg)
    chk("H 动手前的快照存上了", got_snap.get("ok") is True, str(got_snap.get("msg"))[:90])
    man = S._store().manifest(got_snap.get("id"), got_snap.get("group"))
    chk("H ★ 清单里写的是**真字段** `by=\"ai\"`（不是靠标题认）",
        str(man.get("by")) == "ai", "by=%r" % man.get("by"))
    chk("H ★ 那一次的**任务原文**也写进去了（你要的\"知道是干啥之前的代码\"）",
        "能算加法" in str(man.get("by_task")), "by_task=%r" % man.get("by_task"))
    # ★ `V-251`：标题**就是那次的任务原文** —— 你原话「备份的时候不用写 AI 动手前，
    #   不需要"动手前"几个字，以节省空间」。那怎么认得出是 AI 存的？列表那一行的
    #   **「AI」徽章**（清单里的真字段 `by="ai"`），标题不背这个责任。
    chk("H ★ 标题就是那次的任务原文（不加「AI · 动手前」那几个字，省地方）",
        str(man.get("title")) == "把 zz 改成能算加法", "%r" % man.get("title"))
    chk("H ★★ 标题里**不许**再出现「动手前」（那是白占地方）",
        "动手前" not in str(man.get("title")), "%r" % man.get("title"))
    chk("H ★ 是 AI 存的这件事靠**真字段** `by` 认（列表上那个「AI」徽章）",
        str(man.get("by")) == "ai" and not (man.get("by_task") or "") == "",
        "by=%r" % man.get("by"))
    chk("H ★ 备注是任务原文（全文，不截）",
        str(man.get("note")) == "把 zz 改成能算加法", "%r" % man.get("note"))
    # 提示词是用户自己敲的：可能是好几行、可能很长、也可能空着
    chk("H 提示词好几行 → 压成一行（标题不能带换行）",
        "\n" not in S.title_for("第一行\n第二行  第三行")
        and "第一行 第二行 第三行" in S.title_for("第一行\n第二行  第三行"),
        "%r" % S.title_for("第一行\n第二行  第三行"))
    _long = "把" * 100
    chk("H 提示词太长 → 标题截到 40 字 + 省略号",
        len(S.title_for(_long)) <= S.TASK_IN_TITLE + 1
        and S.title_for(_long).endswith("…"), "%r" % S.title_for(_long))
    chk("H 但备注里是**全文**（一个字都没截）", S.note_for(_long) == _long,
        "备注 %d 字" % len(S.note_for(_long)))
    chk("H 提示词是空的 → 标题留空（存储那边会用时间兜底：\"备份 <时间>\"）",
        S.title_for("") == "" and S.title_for("   \n ") == ""
        and S.note_for("") == S.NOTE, "%r / %r" % (S.title_for(""), S.note_for("")))
    # ★ `V-269`：快照**不再开工就存**（你问「你是哪个大模型」也白存了一条），改成
    #   "第一次真要写文件之前"才存。所以这里两半都要钉住：
    #   ① **没动文件的跑 ⇒ 一条快照都不该存**；② **真动手那次 ⇒ 动手之前就存好、并立刻通知界面**。
    _snaps = []
    _m = FakeModel([call("answer", {"text": "我是 moss 的写插件助手"})])
    _g0 = L.Loop(_m, workdir=fake_pkg, max_steps=3, say=lambda s: None,
                 on_snapshot=lambda g: _snaps.append(g)).run("你是哪个大模型?")
    chk("H ★★ 纯问答（一个文件都没动）⇒ **一次快照都不存**（不再白写一条备份）",
        _snaps == [] and (_g0.get("snapshot") in (None, "")), "通知了 %r" % (_snaps,))
    # 动手那次：hook 要在**写之前**跑 —— 所以记下 hook 那一刻文件长什么样（还是旧内容）
    _seen_at_snap = {}
    _m2 = FakeModel([call("edit_file", {"path": str(fake_pkg / "run.py"),
                                        "find": "print('v2')", "replace": "print('v3')"}),
                     call("done", {"summary": "改好了"})])
    _g1 = L.Loop(_m2, workdir=fake_pkg, max_steps=4, say=lambda s: None,
                 on_snapshot=lambda g: _seen_at_snap.update(
                     g, content_at_hook=(fake_pkg / "run.py").read_text(encoding="utf-8"))
                 ).run("把 zz 改成能算加法")
    chk("H ★★ 真动手那次：快照存好就**立刻通知界面**（不用等跑完）",
        len(_seen_at_snap) > 0 and _seen_at_snap.get("id")
        and _seen_at_snap.get("group") == "zz", "通知了 %r" % (_seen_at_snap,))
    chk("H ★★ 而且是在**写之前**存的（hook 那一刻文件还是旧的 `print('v2')`）",
        _seen_at_snap.get("content_at_hook") == "print('v2')\n",
        "hook 时内容=%r" % _seen_at_snap.get("content_at_hook"))
    chk("H 改完之后文件真变了（证明上面那条不是「根本没写」）",
        (fake_pkg / "run.py").read_text(encoding="utf-8") == "print('v3')\n",
        (fake_pkg / "run.py").read_text(encoding="utf-8")[:40])
    # 连改几个文件，快照也只存一条（不然"动手前"那一条会被覆盖成"动了两次之后"）
    _snaps2 = []
    _m3 = FakeModel([call("edit_file", {"path": str(fake_pkg / "run.py"),
                                        "find": "print('v3')", "replace": "print('v4')"}),
                     call("edit_file", {"path": str(fake_pkg / "run.py"),
                                        "find": "print('v4')", "replace": "print('v5')"}),
                     call("done", {"summary": "又改了"})])
    L.Loop(_m3, workdir=fake_pkg, max_steps=5, say=lambda s: None,
           on_snapshot=lambda g: _snaps2.append(g)).run("接着改")
    chk("H ★ 连改两次也只存**一条**快照（快照点是「动手之前」那一刻）",
        len(_snaps2) == 1, "存了 %d 条" % len(_snaps2))

    print()
    print("=" * 72)
    print("P：`V-251` 会话 —— **接着上次那条聊**（你说「一旦重新打开 moss 只能重新再来」）")
    print("=" * 72)
    # ① 第一次跑：收尾时要把**整条对话**交出来（界面存盘，"接着聊"就靠它）
    #    ★ 先 `run_moss` 跑通（假宿主第二次起就退 0）—— 不然 `done` 过不了验收闸，
    #      结论里就没有 summary，下面那两条"正文只出现一次、且不截"的断言就没得测。
    _m1 = FakeModel([call("run_moss", {"args": ":zz"}),
                     call("done", {"summary": "第一趟干完了"})])
    _g1 = L.Loop(_m1, workdir=fake_pkg, max_steps=4, say=lambda s: None).run("把 zz 改成能算加法")
    _msgs = _g1.get("messages") or []
    chk("P ★ 跑完时把**对话本身**交出来了（不是只有任务原文）",
        len(_msgs) >= 3 and _msgs[0].get("role") == "system"
        and "能算加法" in json.dumps(_msgs, ensure_ascii=False),
        "%d 条：%s" % (len(_msgs), [m.get("role") for m in _msgs]))
    chk("P 没接着谁的时候 `continued_from` 是空的", _g1.get("continued_from") == "",
        repr(_g1.get("continued_from")))
    # ★ `V-260`：界面里**不许**出现"截断的 JSON"（你报的"显示的是一个字典，而不是显示里面的文本"）。
    #   ★ `V-269` 补：那段正文**只出现一次** —— 归下面的结论卡；步骤卡不再重复贴一遍
    #   （真机截图里同一段回答出现了两遍）。所以这里钉两件事：**步骤卡不摆 JSON/不摆正文** +
    #   **结论卡拿到完整正文（一个字不截）**。
    _done = [s for s in (_g1.get("steps") or []) if s.get("tool") == "done"]
    chk("P ★ 步骤卡不摆那坨 JSON（`done` 那步没有正文，正文归结论卡）",
        bool(_done) and (_done[-1].get("disp") or "") == ""
        and str(_done[-1].get("brief") or "").startswith("{"),
        "disp=%r brief=%r" % ((_done[-1] or {}).get("disp"), (_done[-1] or {}).get("brief")))
    chk("P ★ 结论里拿到完整 summary（一个字不截）",
        (_g1.get("summary") or "") == "第一趟干完了", repr((_g1.get("summary") or "")[:40]))
    _long_sum = "回答" * 120                       # 240 字，超过 `brief[:70]`
    #   ★ 要让 `done` 真的收工（结论里才有 summary），得先**跑通一次** —— 验收闸要它
    _g1b = L.Loop(FakeModel([call("run_moss", {"args": ":zz"}),
                             call("done", {"summary": _long_sum})]),
                  workdir=fake_pkg, max_steps=4, say=lambda s: None).run("长长地回答我")
    _d2 = [s for s in (_g1b.get("steps") or []) if s.get("tool") == "done"]
    chk("P ★★ 长回答一个字都不截（在结论里给全文；步骤卡不重复）",
        bool(_d2) and (_d2[-1].get("disp") or "") == ""
        and (_g1b.get("summary") or "") == _long_sum,
        "步骤卡 %d 字 / 结论 %d 字（原文 %d 字）"
        % (len((_d2[-1] or {}).get("disp") or ""), len(_g1b.get("summary") or ""), len(_long_sum)))
    # ② 存进任务记录 → 读回来 → 拿它当 history 接着跑：**老对话必须真的发出去**
    import ai_runs as R                                                    # noqa: E402
    _saved = R.save({"task": "把 zz 改成能算加法", "workdir": str(fake_pkg),
                     "ok": True, "messages": _msgs, "steps": []})
    _back = [m for m in (R.get(_saved.get("id")) or {}).get("messages") or []]
    chk("P ★ 存盘再读回来，对话一条不少（重启 moss 也能接上）",
        len(_back) == len(_msgs), "%d → %d" % (len(_msgs), len(_back)))
    _m2 = FakeModel([call("done", {"summary": "第二趟接着干"})])
    _g2 = L.Loop(_m2, workdir=fake_pkg, max_steps=3, say=lambda s: None).run(
        "再给它加个 --json 参数", history=_back, from_id=_saved.get("id"))
    _sent = _m2.seen[0] if _m2.seen else []
    _sent_txt = json.dumps(_sent, ensure_ascii=False)
    chk("P ★★ 接着聊：上次那句和这次的都发给了模型（它真记得）",
        "把 zz 改成能算加法" in _sent_txt and "再给它加个 --json 参数" in _sent_txt,
        "发出去 %d 条" % len(_sent))
    chk("P 只接 system 以外的轮次：**系统提示只有一条**（用现在的提示词重拼）",
        len([m for m in _sent if m.get("role") == "system"]) == 1
        and _sent[0].get("role") == "system",
        "%s" % [m.get("role") for m in _sent])
    chk("P 老会话是接在**系统提示后面、这次那句前面**（顺序不能乱）",
        [m.get("role") for m in _sent[:3]][0] == "system"
        and "再给它加个 --json 参数" in json.dumps(_sent[-1], ensure_ascii=False),
        json.dumps([m.get("role") for m in _sent], ensure_ascii=False))
    chk("P 新记录里记着「从哪条接过来的」（界面上能看出链条）",
        _g2.get("continued_from") == _saved.get("id"), repr(_g2.get("continued_from")))
    chk("P 接着聊之后对话更长了（老的 + 新的都在里面）",
        len(_g2.get("messages") or []) > len(_msgs),
        "%d → %d" % (len(_msgs), len(_g2.get("messages") or [])))
    chk("P 空 history = 新开一条（不多发、也不少发）",
        len(L.Loop(FakeModel([call("done", {"summary": "新会话"})]), workdir=fake_pkg,
                   max_steps=3, say=lambda s: None).run("开个新的", history=[]).get("messages") or []) >= 3,
        "")
    R.delete(_saved.get("id"))
    # ---------------------------------------------------------------- `V-382`
    # ★ 查会话记录查出来的真事：AI 收尾时**自己把开工前那条快照清掉了**
    #   （`snap_clean`，理由写着"别占着用户地方"）⇒ 用户的原话变成
    #   「你给我改代码也不先创建快照？现在整个都废了」。所以现在整条工具都拿掉了。
    chk("H ★★ `snap_clean` **不在工具表里**（结构上删不了，不靠它自觉）",
        "snap_clean" not in T.builtin_names()
        and "snap_clean" not in [t["function"]["name"] for t in T.tools_for({})],
        str([n for n in T.builtin_names()]))
    mine = S._store().create([str(fake_pkg.resolve())], title="我自己存的", note="")
    chk("H 人存的那条 by 是空的（默认就是\"人存的\"）", not (mine.get("by") or ""), "by=%r" % mine.get("by"))
    # 就算它照着老会话的记忆硬调这个名字，也只能拿到一句拒绝 —— 盘上那条**动不了**
    _before = [b["id"] for b in S._store().list_backups(group="zz")]
    refused = t.call("snap_clean", {"group": "zz"})
    _after = [b["id"] for b in S._store().list_backups(group="zz")]
    chk("H ★★ 硬调 `snap_clean` 也只会被拒（快照一条没少）",
        "拒绝" in refused and _after == _before, "%s / %d → %d 条"
        % (refused.replace("\n", " ")[:60], len(_before), len(_after)))
    # 人那侧的能力照旧（界面「版本快照」页用的就是它）：**只清 AI 的，你的不碰**
    cleaned = S.clean_ai(group="zz")
    chk("H ★ 界面上「清掉 AI 的」照旧能用（AI 那条被清、我的一条没动）",
        got_snap.get("id") in (cleaned.get("deleted") or [])
        and mine.get("id") in (cleaned.get("skipped") or []),
        str(cleaned.get("msg"))[:80])
    still = [b["id"] for b in S._store().list_backups(group="zz")]
    chk("H 删完再看列表：只剩我存的那条", still == [mine.get("id")], str(still))
    # 就算 AI 拿 `run_moss` 去删也要被拦下
    os.environ["MOSS_HOST_CMD"] = json.dumps([sys.executable, str(host)])
    blocked = t.call("run_moss", {"args": '--snap rm "%s" --group zz --yes' % mine.get("id")})
    chk("H ★ 走 run_moss 删快照也被拒（那两个入口都堵死了）",
        "拒绝" in blocked and "快照" in blocked, blocked.replace("\n", " ")[:80])
    chk("H 而且那条真的还在（拦住了，不是嘴上说说）",
        S._store().manifest(mine.get("id"), "zz").get("id") == mine.get("id"), "")
    chk("H 不给 group 清全库被拒（免得手一抖）", S.clean_ai().get("ok") is False, "")
    chk("H ai_count 数得对（这一组现在 AI 存的是 0 条）", S.ai_count("zz") == 0, "")
    # ① 包**外面**的目录也存得了（用户说"给我写个项目"经常就在外面）
    outside = tmp / "外面那个工程"
    outside.mkdir(exist_ok=True)
    (outside / "main.py").write_text("print('hi')\n", encoding="utf-8")
    got_out = S.snapshot_before("给我在外面写个项目", pkgs, touched=outside / "main.py")
    chk("H ★★ 包**外面**的目录也存得了（`abs/` 那个根）",
        got_out.get("ok") is True and str(got_out.get("group") or "").startswith("@abs"),
        str(got_out.get("msg"))[:90])
    # ② 快照认的是**你要改的那个目录**，不是 workdir（真机那次 workdir=mu、实际在改 autokey）
    other = pkgs / "xx"
    other.mkdir(parents=True, exist_ok=True)
    (other / "run.py").write_text("print('x')\n", encoding="utf-8")
    got_scope = S.snapshot_before("改的是 xx，不是 zz", fake_pkg, touched=other / "run.py")
    _srcs = [str(x).lower() for x in (got_scope.get("sources") or [])]
    chk("H ★★ 快照认的是**真要改的那个目录**（workdir 是 zz、改的是 xx ⇒ 主来源是 xx）",
        got_scope.get("ok") is True and bool(_srcs) and _srcs[0].endswith("\\xx")
        and any(s.endswith("\\zz") for s in _srcs), str(_srcs))
    # ③ 盘根 / 我们自己的那几个"整层"不许存（不然就是备份整块盘）
    for _bad in (Path("D:/"), E.user_data(), E.user_data() / "pkgs", E.HOME / "system"):
        chk("H ★ 不存 `%s`（整层 / 盘根不是一次备份的对象）" % str(_bad)[-24:],
            bool(S.too_broad(_bad)), S.too_broad(_bad))
    # ④ 只写自己的 tmp ⇒ 不该触发"动手前快照"（那是中间产物，不是改动）
    _scr = E.user_data() / "state" / "zz" / "ai" / "tmp" / "run1" / "探针.py"
    chk("H ★ 写自己的 tmp 不算改动（不为它白存一条快照）", S.is_scratch(_scr) is True, str(_scr))
    chk("H 但写包里的文件算改动", S.is_scratch(fake_pkg / "run.py") is False, "")
    _snaps3 = []
    _m4 = FakeModel([call("write_file", {"path": str(_scr), "content": "print(1)\n"}),
                     call("done", {"summary": "只是写了个探针"})])
    _g3 = L.Loop(_m4, workdir=fake_pkg, max_steps=4, say=lambda s: None,
                 on_snapshot=lambda g: _snaps3.append(g)).run("先跑个诊断")
    chk("H ★★ 只往 tmp 写探针 ⇒ **一条快照都不存**（快照点留给真正的改动）",
        _snaps3 == [] and (_g3.get("snapshot") in (None, "")), "通知了 %r" % (_snaps3,))
    shutil.rmtree(_scr.parent, ignore_errors=True)      # 别把后面"S6 临时空间"的数占上
    # ⑥ **新建包**那一轮：第一次写的时候目录还没建出来 ⇒ 不占掉这次机会；
    #    等它建出来、下一次动它之前再存（不然"新包从建到改坏"全程没有退路）
    newpkg = pkgs / "brand-new"
    _snaps5 = []
    _m5 = FakeModel([call("write_file", {"path": str(newpkg / "run.py"),
                                         "content": "print(1)\n"}),
                     call("edit_file", {"path": str(newpkg / "run.py"),
                                        "find": "print(1)", "replace": "print(2)"}),
                     call("done", {"summary": "新建了一个包"})])
    _g5 = L.Loop(_m5, workdir=pkgs, max_steps=5, say=lambda s: None,
                 on_snapshot=lambda g: _snaps5.append(g)).run("新建一个 brand-new")
    chk("H ★★ 新建包：目录还没建出来时不硬存（机会留着），建出来之后再动它才存",
        len(_snaps5) == 1 and (_snaps5[0] or {}).get("group") == "brand-new",
        "存了 %d 条：%r" % (len(_snaps5), _snaps5[:1]))
    _man5 = S._store().manifest((_snaps5[0] or {}).get("id"), "brand-new") if _snaps5 else {}
    _rels5 = [e.get("rel") for e in (_man5.get("files") or [])]
    chk("H ★★ 而且那条快照是**改之前**的样子（里面是 print(1)，不是 print(2)）",
        bool(_rels5) and (_man5.get("files") or [{}])[0].get("fp")
        and S._store().read_blob((_man5.get("files") or [{}])[0].get("fp"),
                                 group="brand-new").get("text", "").strip() == "print(1)",
        str(_rels5))
    # ⑤ 同一条命令第 3 回还跑 ⇒ 结果前面顶一句"换个证据来源"
    t4 = T.Tools(workdir=pkgs)
    _o1 = t4.call("run_moss", {"args": ":zz"})
    _o2 = t4.call("run_moss", {"args": ":zz"})
    _o3 = t4.call("run_moss", {"args": ":zz"})
    chk("H ★ 同一条命令第 3 回还跑 ⇒ 顶一句「别换第 3 次同样的结果」",
        "第 3 次" not in _o1 and "第 3 次" not in _o2 and "你已经跑了 3 次" in _o3,
        "%r / %r" % (_o2[:24], _o3[:60]))

    print()
    print("=" * 72)
    print("I：`V-237` 真机那次（让 calc 支持指数）暴露的三件事")
    print("=" * 72)
    # ① "看完了发现不用改"也是合法结局：没改动，但**真跑成功过一次** ⇒ 允许收工
    t2 = T.Tools(workdir=pkgs)
    chk("I 什么都没干就 done ⇒ 不许（没跑过）", t2.verified() is False, "")
    t2.call("run_moss", {"args": ":zz"})                # 假宿主：这时退出码 0
    chk("I ★ 没改动、但真跑成功过 ⇒ **允许收工**（「发现不用改」是合法结局）",
        t2.verified() is True, t2.gate_reason()[:80])
    t3 = T.Tools(workdir=pkgs)
    now = tmp / "never_ok2.py"
    now.write_text("import sys;print('失败');sys.exit(1)\n", encoding="utf-8")
    os.environ["MOSS_HOST_CMD"] = '"%s" "%s"' % (sys.executable, now)
    t3.call("run_moss", {"args": ":zz"})
    chk("I 跑是跑了但**没成功** ⇒ 仍然不许收工", t3.verified() is False, t3.gate_reason()[:70])
    os.environ["MOSS_HOST_CMD"] = '"%s" "%s"' % (sys.executable, host)
    # ② 步数用完、但验收已过 ⇒ 判通过（别让"没来得及说 done"毁掉一次做对的活）
    same = FakeModel([call("run_moss", {"args": ":zz"})] * 3)
    got6 = L.Loop(same, workdir=pkgs, max_steps=3, say=lambda s: None).run("看看 zz 能不能跑")
    chk("I ★ 步数用完但验收已过 ⇒ ok=True，原因照实说「没来得及说 done」",
        got6["ok"] is True and "步数用完" in got6["reason"], got6["reason"][:70])
    chk("I 步数用完的文案带上了**几步**（上次你根本不知道它第几步停的）",
        "3 步" in got6["reason"] or "3" in got6["reason"], got6["reason"][:60])
    # ③ 读文件别把 120 行切两半（切了它就会换 offset 反复重读 —— 真机 11 步读一个文件）
    big = pkgs / "big.py"
    big.write_text("\n".join("x%03d = %d" % (i, i) for i in range(1, 121)) + "\n", encoding="utf-8")
    t4 = T.Tools(workdir=pkgs)
    one = t4.call("read_file", {"path": str(big)})
    chk("I ★ 读 120 行**不会被截断**（2200 字那版只够 ~60 行，它就反复重读）",
        "已截断" not in one and "x120" in one, "长度 %d" % len(one))
    t4.call("read_file", {"path": str(big)})
    third = t4.call("read_file", {"path": str(big)})
    chk("I ★ 同一个文件读第三回会被点名（别再换 offset 磨）",
        "已经读过 3 次" in third, third[-90:].replace("\n", " "))

    print()
    print("=" * 72)
    print("J：`V-238`/`V-239` 预算 —— **按 token 算**：80% 劝收尾、100% 停手")
    print("=" * 72)
    # ① 提醒线（80%）：上限 300 ⇒ 240 就劝（每步 120 ⇒ 第 2 步时累计 240）
    rich0 = FakeModel([call("list_dir", {"path": str(pkgs)})] * 12)
    got7 = L.Loop(rich0, workdir=pkgs, max_steps=9, max_tokens=300, say=lambda s: None).run("一直列目录")
    reminders = [s for s in got7["steps"] if s["tool"] == "(提醒)"]
    chk("J ★ token 到 80% 时劝一次收尾", len(reminders) == 1,
        "提醒 %d 次：%s" % (len(reminders), [s["brief"] for s in reminders]))
    nudged = [m for m in rich0.seen[-1]
              if m.get("role") == "user" and "请收尾" in str(m.get("content") or "")]
    chk("J 那句提醒**真发给模型了**（不是只写在界面上）", len(nudged) >= 1, "发了 %d 条" % len(nudged))
    chk("J 提醒里写清了「已烧多少 / 上限多少」",
        "已经烧了 240 token" in str(nudged[0].get("content") or "") and "上限 300" in str(nudged[0].get("content") or ""),
        str(nudged[0].get("content") if nudged else "")[:80])
    chk("J 提醒只发一次（不会每步都念）", len(reminders) == 1, "")
    chk("J 提醒不影响硬闸：烧到 300 就停",
        got7["ok"] is False and "token 到上限" in got7["reason"], got7["reason"][:50])
    # ② 不设 token 上限（0）⇒ 不拦
    free = FakeModel([call("list_dir", {"path": str(pkgs)})] * 3)
    got8b = L.Loop(free, workdir=pkgs, max_steps=3, max_tokens=0, say=lambda s: None).run("列目录")
    chk("J max_tokens=0 ⇒ 不设闸（走到步数兜底为止）",
        "token" not in got8b["reason"], got8b["reason"][:40])
    # token 闸：烧到上限就停手（步数 ≠ 钱，这个才贴"花多少"）
    rich = FakeModel([call("list_dir", {"path": str(pkgs)})] * 12)
    got8 = L.Loop(rich, workdir=pkgs, max_steps=10, soft_steps=0, max_tokens=200,
                  say=lambda s: None).run("一直列目录")
    chk("J ★ token 闸：烧到 200 就停手（每步 120 ⇒ 第 2 步就该停）",
        got8["ok"] is False and "token 到上限" in got8["reason"], got8["reason"][:60])
    chk("J 不设软提醒就是不提醒（0 = 关）",
        not [s for s in got8["steps"] if s["tool"] == "(提醒)"], "")
    # 预算存/取 + 校验（同一份实现在 `system/ui/ai/ai_budget.py`，界面和探针都走它）
    import ai_budget as BUD                                               # noqa: E402
    bud = BUD.save(80000000)
    chk("J 存预算（8000 万 token）成功且落盘", bud.get("ok") is True, str(bud.get("path"))[-46:])
    chk("J 读回来还是 8000 万", BUD.load().get("max_tokens") == 80000000, "")
    chk("J 提醒线 = 上限的 80%（8000 万 ⇒ 6400 万）", BUD.warn_at(80000000) == 64000000, str(BUD.warn_at(80000000)))
    chk("J 太小 / 太大 / 非整数 ⇒ 拒绝（都回人话）",
        BUD.save(100).get("ok") is False and BUD.save(99999999999).get("ok") is False
        and BUD.save("abc").get("ok") is False, str(BUD.save(100).get("msg"))[:40])
    chk("J 出厂默认 1 亿（你定的：100 百万）", BUD.MAX_TOKENS_DEFAULT == 100000000, "")
    chk("J human() 给人看的数字对（32569 → 32.57k；1.5e6 → 1.5M；1e8 → 100M）",
        BUD.human(32569).endswith("k") and BUD.human(1500000) == "1.5M"
        and BUD.human(100000000) == "100M",
        "%s / %s / %s" % (BUD.human(32569), BUD.human(1500000), BUD.human(100000000)))
    BUD.save(BUD.MAX_TOKENS_DEFAULT)         # 还原默认，别影响后面的用例

    print()
    print("=" * 72)
    print("K：`V-241` 压缩「晚一点、少一点、不刷屏」（真机反馈：它一直在压缩，频率很高）")
    print("=" * 72)
    # ① 攒够一批才折：40 条以上、且能折的 ≥6 条才动一次
    long_run = FakeModel([call("list_dir", {"path": str(pkgs)})] * 26)
    # 这一步专门验"折"的机制 ⇒ 把触发线压到 1、逐字保留给小
    got9 = L.Loop(long_run, workdir=pkgs, max_steps=26, max_tokens=0, say=lambda s: None,
                  compact_after=2, compact_min=2, compact_at=1, retain_tokens=20,
                  keep_recent=2).run("一直列目录")
    comp_rows = [x for x in got9["steps"] if x["tool"] == "(压缩)"]
    chk("K ★ 压缩**不再作为一步**刷屏（步骤流里没有 (压缩) 行）", comp_rows == [],
        "还有 %d 行" % len(comp_rows))
    chk("K 但确实折了（结果里报总条数）", (got9.get("folded") or 0) >= 6,
        "折叠 %s 条" % got9.get("folded"))
    chk("K 每步行上带着「此刻累计折了多少」（界面那一小行用它）",
        all("folded" in x for x in got9["steps"]), "")
    # ★ `V-243`：默认那道"token 压力"闸 —— 输入没到 6 万 token 时**一条都不折**
    #   （折早了模型就看不见早先读过的内容，只好重读：真机那次 grep 十几遍就是这个）
    mild = FakeModel([call("list_dir", {"path": str(pkgs)})] * 26)
    got11 = L.Loop(mild, workdir=pkgs, max_steps=26, max_tokens=0, say=lambda s: None).run("一直列目录")
    chk("K ★ 默认策略（DSH：窗口 80% = 102400）下：输入才几百 token ⇒ 一条都不折",
        (got11.get("folded") or 0) == 0, "folded=%s" % got11.get("folded"))
    # `V-244`：窗口比例算得对（128k ⇒ 触发 102400 / 保留 20480）
    import ai_budget as _B                                                # noqa: E402
    chk("K ★ 触发线 = 窗口 × 0.8、逐字保留 = 窗口 × 0.16（照 DSH 的参数）",
        _B.compact_at(context=128000) == 102400 and _B.retain_tokens(context=128000) == 20480,
        "at=%s retain=%s" % (_B.compact_at(context=128000), _B.retain_tokens(context=128000)))
    chk("K 按模型名猜窗口（deepseek ⇒ 128k；gemini ⇒ 1M）",
        _B.context_window("deepseek-flash") == 128000 and _B.context_window("gemini-2.0-flash") == 1000000,
        "deepseek=%s gemini=%s" % (_B.context_window("deepseek-flash"),
                                   _B.context_window("gemini-2.0-flash")))
    chk("K 保留量必须小于触发线（DSH 也是这么校验的）",
        _B.check(_B.MAX_TOKENS_DEFAULT, 2000) is None, "")
    # ② 12 条以内**一点都不折**（窗口留着，模型才不用重读）
    short_run = FakeModel([call("list_dir", {"path": str(pkgs)})] * 10)
    got10 = L.Loop(short_run, workdir=pkgs, max_steps=10, max_tokens=0, say=lambda s: None).run("列目录")
    chk("K ★ 短任务一次都不折（阈值 40 条；旧版 16 条就开始折了）",
        (got10.get("folded") or 0) == 0, "folded=%s" % got10.get("folded"))
    # ③ 同一个文件用 grep 一行行刨 ⇒ 第三回就被喊停
    agent_md = pkgs / "zz" / "AGENT.md"
    agent_md.parent.mkdir(parents=True, exist_ok=True)
    agent_md.write_text("# 标题\n## 干什么\n说明\n", encoding="utf-8")
    t9 = T.Tools(workdir=pkgs)
    t9.call("grep", {"pattern": "#", "path": str(agent_md)})
    t9.call("grep", {"pattern": "#", "path": str(agent_md)})
    third_grep = t9.call("grep", {"pattern": "#", "path": str(agent_md)})
    chk("K ★ 同一组 grep 搜第三回 ⇒ 明说别再一行行刨了",
        "别再用 grep 一行一行刨文件" in third_grep, third_grep[-80:].replace("\n", " "))
    t10 = T.Tools(workdir=pkgs)
    for pat in ("a", "b", "c", "d", "e", "f"):
        last = t10.call("grep", {"pattern": pat, "path": str(agent_md)})
    chk("K ★ 换着正则搜同一个文件到第 6 回 ⇒ 让它直接 read_file",
        "直接" in last and "read_file" in last, last[-70:].replace("\n", " "))

    print()
    print("=" * 72)
    print("L：`V-242` 真机那次「卡很久 + 点停止没用」—— 根因是请求整段阻塞、停止只在轮次开头看")
    print("=" * 72)
    # ① 停止要能在**请求发到一半**时生效（假服务器：收下请求就不回数据，一直挂着）
    import http.server as _hs                                            # noqa: E402
    import threading as _th                                              # noqa: E402
    import ai_client as _C                                               # noqa: E402

    class _Hang(_hs.BaseHTTPRequestHandler):
        def do_POST(self):                                                # noqa: N802
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "9999")      # 说好 9999 字节，然后一个都不发
            self.end_headers()
            time.sleep(6)                                    # 挂着 —— 模拟"模型半天不回"

        def log_message(self, *a):                                        # noqa: A003
            pass

    srv = _hs.HTTPServer(("127.0.0.1", 0), _Hang)
    _th.Thread(target=srv.serve_forever, daemon=True).start()
    stop_flag = {"v": False}
    client = _C.Client("http://127.0.0.1:%d/v1" % srv.server_port, "sk-x", "fake", timeout=30)
    t0 = time.time()
    # 300ms 后按停止（模拟"用户点了停止"）
    _th.Timer(0.3, lambda: stop_flag.__setitem__("v", True)).start()
    try:
        client.chat([{"role": "user", "content": "hi"}], None,
                    stop_check=lambda: stop_flag["v"])
        chk("L ★ 请求中途按停止 ⇒ 抛 Stopped（不再傻等 30 秒）", False, "居然正常返回了")
    except _C.Stopped:
        took = time.time() - t0
        chk("L ★ 请求中途按停止 ⇒ 抛 Stopped，而且**一两秒内**就停",
            took < 3.0, "用了 %.1fs（旧的 urllib 要等满 30s）" % took)
    except _C.AiError as e:
        chk("L ★ 请求中途按停止 ⇒ 抛 Stopped", False, "抛的是 AiError：%s" % e)
    srv.shutdown()

    # ①★ 慢而正常的回复**必须成功**（`V-245`：上一版 2 秒 socket 超时 + "超时继续读"
    #    被 `socket.SocketIO` 破了 —— 它超时过一次就报废，之后任何读都抛
    #    `cannot read from timed out object`。真机报的就是这句。）
    class _SlowHandler(_hs.BaseHTTPRequestHandler):
        delay = 3.5                       # ← 模型"想了 3.5 秒"，完全正常

        def do_POST(self):                                                # noqa: N802
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            time.sleep(self.delay)
            body = json.dumps({"choices": [{"message": {"role": "assistant",
                                                        "content": "慢但是好的"}}],
                               "usage": {"prompt_tokens": 11, "completion_tokens": 3,
                                         "total_tokens": 14}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):                                        # noqa: A003
            pass

    srv2 = _hs.HTTPServer(("127.0.0.1", 0), _SlowHandler)
    _th.Thread(target=srv2.serve_forever, daemon=True).start()
    c2 = _C.Client("http://127.0.0.1:%d/v1" % srv2.server_port, "sk-x", "fake", timeout=30)
    try:
        got_slow = c2.chat([{"role": "user", "content": "hi"}], None, stop_check=lambda: False)
        chk("L ★★ 模型慢 3.5 秒才回 ⇒ **必须成功**（今天真机就是死在这条上）",
            got_slow.get("text") == "慢但是好的", str(got_slow)[:70])
    except Exception as e:                                                # noqa: BLE001
        chk("L ★★ 模型慢 3.5 秒才回 ⇒ **必须成功**（今天真机就是死在这条上）", False,
            "%s: %s" % (type(e).__name__, e))
    srv2.shutdown()

    # ② 慢服务器 + 中途按停止 ⇒ 仍然要能停（换成"盯停止的线程掐连接"这条路）
    srv3 = _hs.HTTPServer(("127.0.0.1", 0), _SlowHandler)
    _th.Thread(target=srv3.serve_forever, daemon=True).start()
    stop2 = {"v": False}
    c3 = _C.Client("http://127.0.0.1:%d/v1" % srv3.server_port, "sk-x", "fake", timeout=30)
    _th.Timer(0.4, lambda: stop2.__setitem__("v", True)).start()
    _t1 = time.time()
    try:
        c3.chat([{"role": "user", "content": "hi"}], None, stop_check=lambda: stop2["v"])
        chk("L ★ 慢服务器上按停止 ⇒ 抛 Stopped（≤1.5 秒）", False, "居然正常返回了")
    except _C.Stopped:
        chk("L ★ 慢服务器上按停止 ⇒ 抛 Stopped（≤1.5 秒）",
            time.time() - _t1 < 1.5, "用了 %.2fs" % (time.time() - _t1))
    except _C.AiError as e:
        chk("L ★ 慢服务器上按停止 ⇒ 抛 Stopped（≤1.5 秒）", False, "抛的是 AiError：%s" % e)
    srv3.shutdown()

    # ② loop 收到 Stopped 之后收工，原因是"用户按了停止"
    class _StopClient:
        model = "fake"

        def chat(self, messages, tools=None, stop_check=None, on_wait=None, on_retry=None):
            raise _C.Stopped("用户按了停止")

    gotS = L.Loop(_StopClient(), workdir=pkgs, say=lambda s: None).run("随便干点啥")
    chk("L ★ loop 认这个信号：收工原因写「用户按了停止」",
        gotS["ok"] is False and "停止" in gotS["reason"], gotS["reason"][:60])

    # ③ 相位：等模型 vs 执行工具（页面靠它显示"等模型回话"，就不再像卡死）
    phases = []
    call1 = FakeModel([call("list_dir", {"path": str(pkgs)}),
                       call("done", {"summary": "好了"})])
    L.Loop(call1, workdir=pkgs, max_steps=4, max_tokens=0, say=lambda s: None,
           on_phase=lambda w: phases.append(w)).run("列目录")
    chk("L 相位报送：thinking → tools（页面据此显示在干什么）",
        "thinking" in phases and "tools" in phases, "、".join(phases))

    # ④ write_file 不再把模型堵死：已存在时给两条明路，带 overwrite=true 就能整篇重写
    again = pkgs / "zz" / "run.py"
    t11 = T.Tools(workdir=pkgs)
    bad = T.Tools(workdir=pkgs).call("write_file", {"path": str(again), "content": "x"})
    chk("L ★ 已存在时**给两条明路**（edit_file / overwrite=true）—— 真机就是被这一拒堵死的",
        "overwrite=true" in bad and "edit_file" in bad, bad.replace("\n", " ")[:90])
    ok2 = t11.call("write_file", {"path": str(again), "content": "print('rewritten')\n",
                                  "overwrite": True})
    chk("L ★ 带 overwrite=true ⇒ 真整篇覆盖", "整篇覆盖了" in ok2 and again.read_text(encoding="utf-8").startswith("print"),
        ok2[:60])

    print()
    print("=" * 72)
    print("M：`V-247` 协议形状 —— 一步多工具 + 混着 done 时，消息顺序不能乱（真机 HTTP 400）")
    print("=" * 72)

    def multi(*pairs):
        """造一条"一次回好几个 tool_calls"的响应（真机那次一步调了 5 个 run_moss）。"""
        calls = [{"id": "c%d" % i, "name": nm, "args": ar} for i, (nm, ar) in enumerate(pairs)]
        return {"text": "", "tool_calls": calls, "native": True,
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                "message": {"role": "assistant", "content": None,
                            "tool_calls": [{"id": c["id"], "type": "function",
                                            "function": {"name": c["name"],
                                                         "arguments": json.dumps(c["args"])}}
                                           for c in calls]}}

    # 一步里：先 done（会被打回）+ 另外两个工具 —— 人话必须排到最后
    script_m = [multi(("done", {"summary": "先说着"}), ("list_dir", {"path": str(pkgs)}),
                      ("run_moss", {"args": ":zz"})),
                multi(("done", {"summary": "好了", "caveats": ""}))]
    fm = FakeModel(script_m)
    gotM = L.Loop(fm, workdir=pkgs, max_steps=4, max_tokens=0, say=lambda s: None,
                  compact_at=1, retain_tokens=20).run("一步多工具")
    seen = fm.seen[-1]
    # 找出 assistant(tool_calls) 之后那一段
    bad = []
    i = 0
    while i < len(seen):
        m = seen[i]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            ids = [c.get("id") for c in m["tool_calls"]]
            j, got_ids = i + 1, []
            while j < len(seen) and seen[j].get("role") == "tool":
                got_ids.append(seen[j].get("tool_call_id"))
                j += 1
            if got_ids != ids:
                bad.append((ids, got_ids, "后面第 %d 条是 %s" % (j, seen[j].get("role") if j < len(seen) else "（没了）")))
            i = j
            continue
        i += 1
    chk("M ★ 每条 assistant(tool_calls) 后面**紧跟**一一对应的 tool 结果（id 全对上、中间没插人话）",
        not bad, str(bad)[:160])
    chk("M ★ 而且那一轮的人话（打回/提醒）排在**所有 tool 结果之后**",
        any(m.get("role") == "user" and "还没验收" in str(m.get("content") or "") for m in seen),
        "")
    chk("M 这一轮最后仍然正常收工", gotM["ok"] is True, gotM["reason"][:50])

    # 网关回的 tool_calls **没带 id**（或 id 重复）⇒ 我们重建的 assistant 必须自己补上、且和 tool 消息一致
    noid = multi(("list_dir", {"path": str(pkgs)}), ("list_dir", {"path": str(pkgs)}))
    for c in noid["message"]["tool_calls"]:
        c["id"] = ""                       # 模拟"网关没给 id"
    noid["tool_calls"][0]["id"] = ""
    noid["tool_calls"][1]["id"] = ""
    fm2 = FakeModel([noid, multi(("done", {"summary": "好了"}))])
    L.Loop(fm2, workdir=pkgs, max_steps=4, max_tokens=0, say=lambda s: None,
           compact_at=1, retain_tokens=20).run("网关没给 id")
    seen2 = fm2.seen[-1]
    pairs_ok = True
    for i, m in enumerate(seen2):
        if m.get("role") == "assistant" and m.get("tool_calls"):
            ids = [c.get("id") for c in m["tool_calls"]]
            tools = [x.get("tool_call_id") for x in seen2[i + 1:i + 1 + len(ids)]]
            if any(not one for one in ids) or ids != tools or len(set(ids)) != len(ids):
                pairs_ok = False
    chk("M ★ 网关没给 id 时：我们自己补上**唯一**id，且与 tool 消息逐条对得上",
        pairs_ok, "")

    print()
    print("=" * 72)
    print("N：`V-248` 读范围 —— 干活的地方选了 calc，就别去翻 ask / dazi / unwx")
    print("=" * 72)
    mine = pkgs / "mine"
    other = pkgs / "otherpkg"
    for d in (mine, other):
        d.mkdir(parents=True, exist_ok=True)
    (mine / "run.py").write_text("print('mine')\n", encoding="utf-8")
    (other / "AGENT.md").write_text("# 别的包\n", encoding="utf-8")
    tn = T.Tools(workdir=mine)
    got_mine = tn.call("read_file", {"path": str(mine / "run.py")})
    chk("N 自己那个包：照读", "print('mine')" in got_mine, got_mine.splitlines()[0][:40])
    got_other = tn.call("read_file", {"path": str(other / "AGENT.md")})
    chk("N ★ 同级的**别的包**：拒（真机就是把 ask/dazi/unwx 全翻了一遍）",
        "拒绝" in got_other and "别的包" in got_other, got_other[:70])
    got_parent = tn.call("list_dir", {"path": str(pkgs)})
    chk("N ★ 连父目录（= 一堆别的包）也不给列",
        "拒绝" in got_parent, got_parent[:60])
    got_sample = tn.call("read_file", {"path": str(home / "system" / "pkgs" / "skill" / "AGENT.md")})
    chk("N 但 system/pkgs 的样板照读（写包要靠它抄）",
        "拒绝" not in got_sample and "共" in got_sample, got_sample.splitlines()[0][:40])
    got_spec = tn.call("read_file", {"path": str(home / "system" / "spec" / "插件契约.md")})
    chk("N 契约仍然只能用 spec 工具（read_file 还是拒）", "用 `spec` 工具" in got_spec, "")
    # 新建包那种任务：workdir 就是 user_data/pkgs ⇒ 列它是允许的（要看 id 有没有被占）
    tn2 = T.Tools(workdir=pkgs)
    got_all = tn2.call("list_dir", {"path": str(pkgs)})
    chk("N 新建包的任务（workdir = pkgs 本身）：列它是允许的",
        "拒绝" not in got_all and "mine" in got_all, got_all.splitlines()[0][:40])
    # 环境提示要把"这次干活的地方"说进句子里
    note = L.env_note(mine)
    chk("N ★ 环境提示里写明了这次的目标目录", "这次干活的地方" in note and str(mine)[-8:] in note,
        note[:80])





    print()
    print("=" * 72)
    print("Q：`V-269` 纯问答的合法收工（`answer`）—— 你问「你是哪个大模型」那次白烧 3 万 token")
    print("=" * 72)
    _txt, _u2, _m2x = L.compose_system("你是哪个大模型?")
    chk("Q ★ 提示词里写明「问事就用 answer」（不靠模型自己猜）", "answer(text=…)" in _txt,
        "")
    chk("Q ★ 提示词里也写明「只要动了文件就不能用 answer」", "动了文件就不能用" in _txt, "")
    # ① 一个文件都没动 + answer ⇒ 直接收工，**不用跑命令**（这正是旧版做不到的那件事）
    q1 = L.Loop(FakeModel([call("answer", {"text": "底层是哪个模型我看不到；我是 moss 的写插件助手。"})]),
                workdir=fake_pkg, max_steps=3, say=lambda s: None).run("你是哪个大模型?")
    chk("Q ★★ 没动文件 + answer ⇒ 收工成功（ok=True）", q1["ok"] is True, q1["reason"][:60])
    chk("Q ★★ 而且一次 run_moss 都没跑（省下来的就是那 7 步 / 3 万 token）",
        all(s["tool"] != "run_moss" for s in q1["steps"]) and len(q1["steps"]) == 1,
        "步骤：%s" % [s["tool"] for s in q1["steps"]])
    chk("Q ★ 结果带 kind=chat（界面拿它写「💬 回答」，不写「验收通过」）",
        q1.get("kind") == "chat", "kind=%r" % q1.get("kind"))
    chk("Q ★ 回答正文进 summary（界面直接显示这一段）",
        "写插件助手" in (q1.get("summary") or ""), repr((q1.get("summary") or "")[:40]))
    chk("Q ★ 没跑过命令也过得去 ⇒ 证明它走的是**另一条出口**，不是验收闸放水",
        q1["ok"] is True and q1["reason"] != "验收通过", q1["reason"][:60])
    # ② 动过文件之后不许拿 answer 绕开验收硬闸
    #    ★ `find` 取**当前真实内容**（前面几段探针也动过这个文件；写死"v5"会随段落顺序碎掉）
    _cur = (fake_pkg / "run.py").read_text(encoding="utf-8").strip()
    q2 = L.Loop(FakeModel([call("edit_file", {"path": str(fake_pkg / "run.py"),
                                              "find": _cur, "replace": "print('v6')"}),
                           call("answer", {"text": "我改完了"})]),
                workdir=fake_pkg, max_steps=3, say=lambda s: None).run("改一下再回答")
    chk("Q ★★ 改过文件之后用 answer ⇒ **不许收工**（否则就是个绕开验收的后门）",
        q2["ok"] is False, q2["reason"][:70])
    chk("Q ★ 而且当场点名告诉它为什么（不是默默失败）",
        any("不能用 answer 收工" in str(m.get("content") or "") for m in q2["messages"]), "")
    # ③ 只说话被打回时，提示里要**点名 answer**（模型才知道有这条出口）
    _m5 = FakeModel([{"text": "好的，我这就开始", "tool_calls": [], "usage": {}, "native": True,
                      "message": {"role": "assistant", "content": "好的，我这就开始"}},
                     call("answer", {"text": "答完了"})])
    q3 = L.Loop(_m5, workdir=fake_pkg, max_steps=3, say=lambda s: None).run("问个事")
    chk("Q ★ 只说话被打回时，那条提示里**点名 answer**（不然它不知道该走这条）",
        any("answer(text=…)" in str(m.get("content") or "") for m in _m5.seen[-1]), "")
    chk("Q ★ 被打回之后它照做 ⇒ 照样能收工（kind=chat）",
        q3.get("ok") is True and q3.get("kind") == "chat", q3["reason"][:60])
    # ④ 真机截图复验抓到的三处显示问题（`V-269` 补）
    #    ① 步骤卡上摆的是 `{"text": "…"}` 原始 JSON（`V-260` 修过的毛病，新工具漏了）
    _d = L._step_disp("answer", {"text": "底层是哪个模型我自己看不到"})
    chk("Q ★ `answer` 那一步**不许**把原始 JSON 摆出来",
        "{" not in _d and "text" not in _d, repr(_d))
    #    ② `done` / `answer` 的正文归**结论卡**，步骤卡不再重复贴一遍（同一段话两遍）
    chk("Q ★ `done`/`answer` 的步骤卡不再重复正文（正文在下面的结论卡里）",
        L._step_disp("done", {"summary": "改好了"}) == ""
        and L._step_disp("answer", {"text": "回答正文"}) == "",
        "done=%r answer=%r" % (L._step_disp("done", {"summary": "改好了"}),
                               L._step_disp("answer", {"text": "回答正文"})))
    # 界面的判据是**步骤上的 `nodisp`**，不是"disp 是空串" —— 拿空串当信号会把
    # `(说话)` 那类"正文从 brief 反解"的卡一起弄哑（老记录里它们也没有 disp）。
    _nod = [s for s in q1["steps"] if s.get("tool") == "answer"]
    chk("Q ★ `answer` 那步带 `nodisp=True`（界面据此不摆正文）",
        bool(_nod) and all(s.get("nodisp") for s in _nod),
        "%r" % [(s.get("tool"), s.get("nodisp")) for s in q1["steps"]])
    _talk = [s for s in q3["steps"] if s.get("tool") == "(说话)"]
    chk("Q ★ 而 `(说话)` 那步**不带** `nodisp`（它的正文照旧要从 brief 反解出来显示）",
        bool(_talk) and not any(s.get("nodisp") for s in _talk),
        "%r" % [(s.get("tool"), s.get("nodisp")) for s in q3["steps"]])
    chk("Q ★ 别的步骤照旧给人看（路径 / 命令这些不能一起砍掉）",
        L._step_disp("read_file", {"path": "C:\\x\\run.py"}) == "C:\\x\\run.py"
        and L._step_disp("run_moss", {"args": ":calc top=5"}) == "moss :calc top=5",
        "%r / %r" % (L._step_disp("read_file", {"path": "C:\\x\\run.py"}),
                     L._step_disp("run_moss", {"args": ":calc top=5"})))
    #    ③ 工具回话别回显正文（`answer` 回显回答、`done` 回显 summary 都一样）
    _t = T.Tools(workdir=fake_pkg)
    _a1 = _t.call("answer", {"text": "很长的一段回答" * 5})
    _a2 = _t.call("done", {"summary": "很长的一段总结" * 5})
    chk("Q ★ `answer` / `done` 的回话**都不回显**正文（回显了步骤行会重复一遍、还撑满）",
        "很长的一段回答" not in _a1 and "很长的一段总结" not in _a2, "%r / %r" % (_a1, _a2))
    #    ④ 纯问答收工时，**两张卡都不画**（你第二张截图的原话："如果后面回答要显示的话，
    #       那么中间这个其它 answer 就不需要显示才对"）：`(说话)` 和 `answer` 都标 `mute`，
    #       正文只在下面那张「回答」卡里出现**一次**。
    _mm = [s for s in q3["steps"] if s.get("tool") == "(说话)"]
    chk("Q ★★ 纯问答收工 ⇒ 那张 `(说话)` 卡被标 `mute`（同一段话不再出现两遍）",
        bool(_mm) and all(s.get("mute") for s in _mm),
        "步骤：%s" % [(s.get("tool"), bool(s.get("mute"))) for s in q3["steps"]])
    _ma = [s for s in q3["steps"] if s.get("tool") == "answer"]
    chk("Q ★★ `answer` 那一步也标 `mute`（正文归下面的「回答」卡，步骤区别重复一遍）",
        bool(_ma) and all(s.get("mute") for s in _ma),
        "步骤：%s" % [(s.get("tool"), bool(s.get("mute"))) for s in q3["steps"]])
    chk("Q ★ `mute` 只是「不画」，数据一条不少地留在记录里（steps 里那张卡还在）",
        len(_mm) >= 1 and len(_ma) >= 1, "mute 了 %d 张" % (len(_mm) + len(_ma)))
    #    ⑤ 干活那几轮**不许**跟着变哑巴（它是有信息量的："说了一句没干活" / "收尾"）
    _work = L.Loop(FakeModel([call("run_moss", {"args": ":zz"}),
                              call("done", {"summary": "干完了"})]),
                   workdir=fake_pkg, max_steps=4, say=lambda s: None).run("干点活")
    chk("Q ★ 干活轮次的步骤卡一张都不许 mute（别把干活那几轮也弄哑了）",
        bool(_work["steps"]) and not any(s.get("mute") for s in _work["steps"]),
        "步骤：%s" % [(s.get("tool"), bool(s.get("mute"))) for s in _work["steps"]])

    print()
    print("=" * 72)
    print("R：`V-270` 网络抖了一下 —— 连接层自己重试（DNS / 连接被重置那一类）")
    print("=" * 72)
    # 真机那次（2026-10-04 21:14~21:18）：这台机器的 DNS 抖了 4 分钟，连着 4 条任务全报
    # `[Errno 11001] getaddrinfo failed` —— 一个字都没发出去，却每条都当"跑失败了"。
    # 现在这种错自己重试两回；这一节把"重试 / 不重试 / 通知"三件事都钉住。
    _old_waits = C.RETRY_WAITS
    C.RETRY_WAITS = (0.01, 0.01)                              # 探针里别真等那 5.5 秒
    try:
        _calls = {"n": 0}

        def _flaky(data, stop_check=None, on_wait=None):
            _calls["n"] += 1
            if _calls["n"] <= 2:
                raise C.AiError("没连上 / 断了：[Errno 11001] getaddrinfo failed",
                                retryable=True)
            return json.dumps({"choices": [{"message": {"content": "在的"}}],
                               "usage": {"total_tokens": 3}}, ensure_ascii=False)

        _cli = C.Client("https://api.example.invalid/v1", "k", "m")
        _cli._post_watched = lambda data, stop_check=None, on_wait=None: _flaky(data)
        _seen = []
        _got = _cli.chat([{"role": "user", "content": "hi"}],
                         on_retry=lambda a, t, e: _seen.append((a, t, str(e)[:24])))
        chk("R ★★ 头两次 DNS 失败 ⇒ 第三次成功（不用你把任务重发一遍）",
            (_got.get("text") or "") == "在的" and _calls["n"] == 3,
            "一共发了 %d 次 · text=%r" % (_calls["n"], _got.get("text")))
        chk("R ★ 每次重试都通知上层（界面据此打一行「重试」）",
            [x[0] for x in _seen] == [1, 2], "%r" % (_seen,))
        # 一直连不上 ⇒ 止于 3 次，而且要说清"这是网络的事、任务一个字都没发出去"
        _deadn = {"n": 0}

        def _dead(data, stop_check=None, on_wait=None):
            _deadn["n"] += 1
            raise C.AiError("没连上 / 断了：[Errno 11001] getaddrinfo failed", retryable=True)

        _cli2 = C.Client("https://api.example.invalid/v1", "k", "m")
        _cli2._post_watched = lambda data, stop_check=None, on_wait=None: _dead(data)
        _msg = ""
        try:
            _cli2.chat([{"role": "user", "content": "hi"}])
        except C.AiError as _e:
            _msg = str(_e)
        chk("R ★ 一直连不上 ⇒ 止于 3 次（不会无限重试烧时间）", _deadn["n"] == 3,
            "发了 %d 次" % _deadn["n"])
        chk("R ★ 而且说清这是网络的事 + 任务是「一个字都没发出去」",
            "都没连上" in _msg and "一个字都没发出去" in _msg, _msg[:100])
        # 非网络错（HTTP 400 / 401 那类）⇒ **一次都不许重试**（重试只会重复烧 token）
        _badn = {"n": 0}

        def _bad(data, stop_check=None, on_wait=None):
            _badn["n"] += 1
            raise C.AiError("400：insufficient tool messages following tool_calls message")

        _cli3 = C.Client("https://api.example.invalid/v1", "k", "m")
        _cli3._post_watched = lambda data, stop_check=None, on_wait=None: _bad(data)
        try:
            _cli3.chat([{"role": "user", "content": "hi"}])
        except C.AiError:
            pass
        chk("R ★ 非网络错（400 那类）**一次都不重试**", _badn["n"] == 1,
            "发了 %d 次" % _badn["n"])
        # loop 那一层：重试要在步骤流里留一行（不然你只看到它卡着）
        _fl2 = {"n": 0}

        def _flaky2(data, stop_check=None, on_wait=None):
            _fl2["n"] += 1
            if _fl2["n"] == 1:
                raise C.AiError("没连上 / 断了：[Errno 11001] getaddrinfo failed", retryable=True)
            return json.dumps({"choices": [{"message": {
                "content": "",
                "tool_calls": [{"id": "c1", "type": "function",
                                "function": {"name": "answer",
                                             "arguments": json.dumps({"text": "在的"},
                                                                     ensure_ascii=False)}}]}}],
                "usage": {"total_tokens": 3}}, ensure_ascii=False)

        _cli4 = C.Client("https://api.example.invalid/v1", "k", "m")
        _cli4._post_watched = lambda data, stop_check=None, on_wait=None: _flaky2(data)
        _r4 = L.Loop(_cli4, workdir=fake_pkg, max_steps=3, say=lambda s: None).run("你是谁")
        chk("R ★ loop 里重试会在步骤流里留一行 `(重试)`（界面上看得见「网络抖了一下」）",
            any(s.get("tool") == "(重试)" for s in _r4["steps"])
            and _r4.get("ok") is True and _r4.get("kind") == "chat",
            "步骤：%s" % [s.get("tool") for s in _r4["steps"]])
        # 上面几条用的都是我手搓的 `retryable=True`；这里真去连一个**不存在的域名**，
        # 钉住"`_post` 那条路确实把它标成 retryable"—— 不然上面全是自说自话。
        _real = C.Client("https://no-such-host-moss-probe.invalid/v1", "k", "m", timeout=5)
        _rr, _rtxt = False, ""
        try:
            _real._post(json.dumps({"model": "m", "messages": []}).encode("utf-8"))
        except C.AiError as _e:                                      # noqa: PERF203
            _rr, _rtxt = bool(getattr(_e, "retryable", False)), str(_e)[:60]
        except Exception as _e:                                      # noqa: BLE001
            _rtxt = "%s: %s" % (type(_e).__name__, _e)
        chk("R ★★ 真连一个不存在的域名 ⇒ 抛出的错**标了 retryable**（否则等于没重试）",
            _rr, _rtxt)
    finally:
        C.RETRY_WAITS = _old_waits

    print()
    print("=" * 72)
    print("S：`V-307`/`V-308` —— 每步写目的 / 时间点 / 自己估 token / 问用户 / 放行清单 /")
    print("     三档模式 / 停止立刻杀进程 / 临时空间 / 每步落盘")
    print("=" * 72)
    import threading                                                      # noqa: E402
    import ai_mode as M                                                   # noqa: E402
    import ai_ask as A                                                    # noqa: E402

    # ---- S1：每一步的「目的」+「时间点」+「累计 token」 ---------------------------
    _s1 = L.Loop(FakeModel([call("list_dir", {"why": "看一眼这个包里有几个文件"}),
                            call("answer", {"text": "看完了"})]),
                 workdir=fake_pkg, max_steps=4, say=lambda s: None).run("看看目录")
    _row = (_s1.get("steps") or [{}])[0]
    chk("S ★ 模型写的 `why`（这一步的目的）进了步骤行",
        _row.get("why") == "看一眼这个包里有几个文件", repr(_row.get("why")))
    chk("S ★ 每一步都带**时间点**（at=HH:MM:SS + t 时间戳）",
        len(str(_row.get("at") or "")) == 8 and str(_row.get("at"))[2] == ":" and (_row.get("t") or 0) > 0,
        "at=%r t=%r" % (_row.get("at"), _row.get("t")))
    chk("S ★ 每一步带**此刻累计 token**（界面右边那格用它）", "tokens" in _row, "")
    chk("S 没写 `why` 的步骤照样能用（不因此报错）",
        (L.Loop(FakeModel([call("answer", {"text": "ok"})]), workdir=fake_pkg,
                max_steps=3, say=lambda s: None).run("随便").get("steps") or [{}])[0].get("why") == "", "")
    # ★ `V-315`：**原始参数 + 原始输出**都留在步骤行里（界面上点开那张卡要看的就是它俩）
    chk("S ★★ 每一步留着**原始参数**（它填给工具的完整 JSON）",
        "why" in str(_row.get("args") or ""), str(_row.get("args"))[:60])
    chk("S ★★ 每一步留着**原始输出**（它当时看到的那一份结果）",
        bool(str(_row.get("out") or "").strip()), str(_row.get("out"))[:60])
    _big = L._clip("x" * 9999, 200)
    chk("S 超长输出会截断，并写明**全文去哪儿看**（「提示词」那一层）",
        len(_big) < 400 and "没截断的那一份" in _big, _big[-40:])
    chk("S 参数是 dict 时转成**人能读的 JSON**（不是 Python 的 repr）",
        '"why"' in L._clip({"why": "看目录", "path": "C:/x"}, 500), "")

    # ---- S2：网关不回 `usage` ⇒ 自己估（用户报的"token 消耗这里 始终没有数据"） ----
    class NoUsage(FakeModel):
        def chat(self, messages, tools=None, stop_check=None, on_wait=None, on_retry=None):
            got = FakeModel.chat(self, messages, tools, stop_check, on_wait, on_retry)
            got["usage"] = {}                       # 就是有的网关那种：一个字都不给
            return got

    _s2 = L.Loop(NoUsage([call("answer", {"text": "回答" * 200})]),
                 workdir=fake_pkg, max_steps=3, say=lambda s: None).run("问一句长的")
    _u = _s2.get("usage") or {}
    chk("S ★★ 网关不回 `usage` ⇒ 宿主自己估（不再是 0 / 0 / 0）",
        (_u.get("total_tokens") or 0) > 0 and (_u.get("prompt_tokens") or 0) > 0 and bool(_u.get("estimated")),
        "usage=%s" % {k: _u.get(k) for k in ("prompt_tokens", "completion_tokens", "total_tokens", "estimated")})
    chk("S 步骤行上也标了 `est=True`（界面据此写 ≈）",
        any(x.get("est") for x in (_s2.get("steps") or [])), "")
    _s2b = L.Loop(FakeModel([call("answer", {"text": "x"})]), workdir=fake_pkg,
                  max_steps=3, say=lambda s: None).run("正常网关")
    chk("S 网关**给了** usage 就照实记（不许拿估算盖掉真数字）",
        not (_s2b.get("usage") or {}).get("estimated")
        and (_s2b.get("usage") or {}).get("prompt_tokens") == 100,
        str(_s2b.get("usage")))

    # ---- S3：`ask` —— 它问、你答（loop 真的**阻塞在那儿等**） ---------------------
    _asked = []
    _asker = None

    def _pub(q):
        if q is None:
            return
        _asked.append(q)
        if _asker is not None:                     # 模拟界面：0.3 秒后点「选 A」+ 打字
            threading.Timer(0.3, lambda: _asker.submit(choice="选 A", text="顺便再说一句")).start()

    _asker = A.Asker(publish=_pub, timeout=10)
    _m3 = FakeModel([call("ask", {"question": "要 A 还是 B?", "options": ["A", "B"]}),
                     call("answer", {"text": "好"})])
    _s3 = L.Loop(_m3, workdir=fake_pkg, max_steps=4, say=lambda s: None, asker=_asker).run("问我要哪个")
    chk("S ★ 问题真的递到界面了（publish 收到 qid + 选项）",
        bool(_asked) and _asked[0].get("question") == "要 A 还是 B?" and len(_asked[0].get("options") or []) == 2,
        str(_asked[:1])[:100])
    _sent3 = json.dumps(_m3.seen[-1], ensure_ascii=False)
    chk("S ★★ 用户答的**原话回给了模型**（他选了：选 A / 他说：顺便再说一句）",
        "他选了：选 A" in _sent3 and "顺便再说一句" in _sent3, _sent3[-160:])
    chk("S ★ 答完之后它接着干完了（不是卡在问题上）", _s3.get("ok") is True, str(_s3.get("reason"))[:60])
    # 按停止 ⇒ 挂着的问题**当场放走**（不许"停止"卡在一张没人答的卡片上）
    _asker2 = A.Asker(publish=lambda q: None, timeout=30)
    _stopflag = {"v": False}
    threading.Timer(0.5, lambda: (_stopflag.__setitem__("v", True), _asker2.cancel("stopped"))).start()
    _t0 = time.time()
    _s3b = L.Loop(FakeModel([call("ask", {"question": "在吗?"})]), workdir=fake_pkg, max_steps=4,
                  say=lambda s: None, asker=_asker2,
                  stop_check=lambda: _stopflag["v"]).run("问一句")
    chk("S ★★ 挂着问题时按停止 ⇒ 一秒内就收工（不是等 30 分钟超时）",
        time.time() - _t0 < 2.0 and _s3b.get("ok") is False, "%.2fs / %s"
        % (time.time() - _t0, str(_s3b.get("reason"))[:40]))
    chk("S 没有 asker（命令行直跑）⇒ 明说「没人可问」，让它自己接着干",
        "没人可问" in str(T.Tools(workdir=fake_pkg).call("ask", {"question": "hi?"})), "")

    # ---- S4：三档模式 + 放行清单 ------------------------------------------------
    _out = tmp / "outside"                        # 一个**包外**的目录（受限档默认不给写）
    _out.mkdir(parents=True, exist_ok=True)
    _target = _out / "a.txt"

    def _try_write():
        # 带 `overwrite=true`：这个文件会写第二遍，别让"文件已经在了"混进判据里
        return str(T.Tools(workdir=fake_pkg).call("write_file",
                                                  {"path": str(_target), "content": "hi",
                                                   "overwrite": True}))

    # ★ `V-316`：**权限 = 一份清单**（每行一对「读 / 写」勾选），不再有"模式"。
    _r = _try_write()
    chk("S ★ 清单里没有这个目录 ⇒ 写被拒，并告诉它**两条路**（allow_path 问 / 让用户勾上写）",
        "拒绝" in _r and "allow_path" in _r, _r[:90])
    chk("S ★ 清单里没有 ⇒ **读**也拒（读/写是两件事，各勾各的）",
        "拒绝" in str(T.Tools(workdir=fake_pkg).call(
            "read_file", {"path": str(_out / "没有这个.txt")})), "")
    # ① ★ `V-343`：**当前这个包不再写进清单** —— 它是"这次 scope 默认放行"，**算出来的**。
    #   为什么改（用户报的"权限清单越用越长"）：以前"AI 页在哪个包上打开过"就把它写进
    #   `allow`；而 `ai_info` 是个**只读查询**（每 700ms 一跳、换一次选中的包就调一次）
    #   ⇒ 在左边点过一遍包列表，清单就长满了，连 `system/pkgs/*` 都被写了进去。
    _row0 = [x for x in M.allow_list() if x["path"] == str(fake_pkg)]
    chk("S ★★ 当前这个包**不落盘**（清单里没有它 —— 这是越用越长的根治）",
        not _row0, str(_row0[:1])[:90])
    # ★ 上面那句"整个项目区"给 `pkgs` **根**开过一条 —— 它会盖住 scope 规则。
    #   先把它摘掉、孤立地验这两条；验完原样放回去。
    _pkgs_row = M.find(str(pkgs))
    if _pkgs_row:
        M.allow_rm(str(pkgs))
    _fresh = pkgs / "zzseed"
    _fresh.mkdir(parents=True, exist_ok=True)
    chk("S ★★ 带着 scope 判 ⇒ 当前这个包默认就能读能写（不用清单里先有一条）",
        M.can_read(_fresh / "run.py", scope=_fresh) is None
        and M.can_write(_fresh / "run.py", scope=_fresh) is None, "")
    chk("S ★★ 不带 scope（= 当成别的包）⇒ 读不了也写不了",
        M.can_read(_fresh / "run.py") is not None
        and M.can_write(_fresh / "run.py") is not None, "")
    # 用户主动把「写」关掉 ⇒ **那一刻**才真的落一条显式记录，并且以它为准
    M.allow_set(str(_fresh), read=True, write=False, why="只想咨询", by="user")
    chk("S ★★ 用户关掉「写」⇒ 落一条显式记录；写立刻被拦、读还开着",
        M.can_read(_fresh / "run.py", scope=_fresh) is None
        and M.can_write(_fresh / "run.py", scope=_fresh) is not None
        and bool([x for x in M.allow_list() if x["path"] == str(_fresh)]), "")
    M.allow_rm(str(_fresh))
    chk("S ★ 删掉那条显式记录 ⇒ 回到默认读写都开",
        M.can_write(_fresh / "run.py", scope=_fresh) is None, "")
    # ★ `V-347`：出厂包**也算"当前这个包"** —— 用户要的是"打开哪个包点 AI 就是要改它"，
    #   别再拿"出厂件默认改不了"挡路（`D-24` 早就定了 `system/` 可编辑、只提示不拦截）。
    chk("S ★★ `system/pkgs/<一个包>` 也算当前这个包 ⇒ 出厂包默认就能改（用户要的\"自由 DIY\"）",
        M.can_write(E.HOME / "system" / "pkgs" / "skill" / "main.py",
                    scope=E.HOME / "system" / "pkgs" / "skill") is None, "")
    chk("S ★★ 但两个 `pkgs` 的**根本身**不算包（放开它 = 放开所有包）",
        M.can_write(E.HOME / "system" / "pkgs" / "skill" / "main.py",
                    scope=E.HOME / "system" / "pkgs") is not None
        and M.can_write(E.user_data() / "pkgs" / "zz" / "run.py",
                        scope=E.user_data() / "pkgs") is not None, "")
    chk("S ★ `_current_row` 认得出出厂包（带 `factory` 标记 ⇒ 界面才能说\"出厂件\"）",
        bool((M._current_row(str(E.HOME / "system" / "pkgs" / "skill")) or {}).get("factory"))
        and M._current_row(str(_fresh)) is not None
        and not (M._current_row(str(_fresh)) or {}).get("factory"), "")
    # ★ `V-347`：出厂包**也存得了"动手前"的快照** —— 既然放开让它改，就得给它退路
    _sg = S.snapshot_before("探针：出厂包也要有退路", E.HOME / "system" / "pkgs" / "skill")
    chk("S ★★ 出厂包也存得了「动手前」的快照（改之前有退路）",
        _sg.get("ok") is True, str(_sg.get("msg"))[:80])
    if _pkgs_row:
        M.allow_add(str(pkgs), read=True, write=True, why="探针：整个项目区")
    # ② 读 / 写**各管各的**：清单里没有就都进不去（拿一个**包外**目录验，别被 pkgs 根那一行覆盖）
    chk("S ★ 清单里没有这个目录 ⇒ 读不了也写不了（清单说了算）",
        M.can_read(_out / "a.txt") is not None and M.can_write(_out / "a.txt") is not None, "")
    M.allow_set(str(_out), read=True, write=True, why="探针加的")
    _r = _try_write()
    chk("S ★★ 清单里勾上「写」⇒ 立刻就能写",
        _target.is_file() and "[失败]" not in _r and "拒绝" not in _r, _r[:60])
    M.allow_set(str(_out), write=False)
    _r = _try_write()
    chk("S ★★ 把「写」取消勾选 ⇒ 立刻写不了（放行不是永久通行证）", "拒绝" in _r, _r[:60])
    chk("S ★★ 但「读」还开着 ⇒ 照样看得见（这就是「只读 / 咨询」那一档）",
        M.can_read(_out / "a.txt") is None and M.can_write(_out / "a.txt") is not None, "")
    M.allow_set(str(_out), write=True)
    # 「只允许这一次」：不写清单，只在这一次跑里有效
    M.allow_rm(str(_out))
    M.allow_temp(str(_out))
    _r = _try_write()
    chk("S ★ 「只允许这一次」也能写/读（临时放行，不进清单）",
        "[失败]" not in _r and "拒绝" not in _r
        and not [x for x in M.allow_list() if x["path"] == str(_out)], _r[:60])
    _ = _out
    M.clear_temp()
    chk("S 这一次跑结束 ⇒ 临时放行自动作废", "拒绝" in _try_write(), "")
    # ③ 硬锁：勾了「任意路径」也进不去
    _lock = str(T.Tools(workdir=fake_pkg).call(
        "write_file", {"path": str(E.HOME / "core" / "别碰.py"), "content": "x"}))
    chk("S ★★ 连 `*`（任意路径）都没勾的时候，`core/` 当然写不了", "受保护" in _lock, _lock[:70])
    chk("S ★★ 清单里也**加不进**硬的受保护路径（不是「加进去就能写」）",
        M.allow_add(str(E.HOME / "core")).get("ok") is False, "")
    # ④ 「任意路径」那一行的写 = 放手：哪儿都能写，而且**危险操作不再问**
    chk("S ★ 默认**不是**放手（`*` 那一行的读/写都是关的）", M.wildcard_write() is False, "")
    _r = _try_write()
    chk("S ★ 没放手时，包外目录写不了（清单里没有它）", "拒绝" in _r, _r[:60])
    M.allow_set("*", write=True)
    chk("S ★★ 把「任意路径」的**写**打开 = 放手（`wildcard_write` 为真）",
        M.wildcard_write() is True, "")
    _r = _try_write()
    chk("S ★★ 放手之后：包外普通目录**能写**了（这才是「放手」）",
        "[失败]" not in _r and "拒绝" not in _r, _r[:60])
    _lock2 = str(T.Tools(workdir=fake_pkg).call(
        "write_file", {"path": str(E.HOME / "core" / "别碰.py"), "content": "x"}))
    chk("S ★★ 但放手**也写不了 `core/`**（硬锁，不是劝）", "受保护" in _lock2, _lock2[:70])
    chk("S ★★ 放手 = 危险操作**不再问**（`needs_confirm` 变假 —— 别再拿第二个开关控同一件事）",
        M.needs_confirm(M.danger_of("run_moss", {"args": "--remove x"})) is False, "")
    M.allow_set("*", write=False)
    chk("S ★ 把「任意路径」的写关掉 ⇒ 危险操作又要问了（现读，不用重启）",
        M.needs_confirm(M.danger_of("run_moss", {"args": "--remove x"})) is True, "")
    # ⑤ 权限那一段要**写进提示词**（它自己看不见界面，得知道能写哪儿）
    _note = M.perm_note(str(fake_pkg))
    chk("S ★ 提示词里写清「能写哪儿 / 写不了就用 allow_path 问」",
        "能写" in _note and "allow_path" in _note, _note[:80])
    for _it in M.allow_list():
        M.allow_set(_it["path"], write=False)
    # ★ `V-343`：当前这个包不在清单里（默认读写都开）—— 要它只读，得**显式关一次**
    M.allow_set(str(fake_pkg), read=True, write=False)
    chk("S ★ 「写」全关着时，提示词明说这一轮是**只读**（用 answer 收尾，别硬改）",
        "一个地方都不能写" in M.perm_note(str(fake_pkg)), "")
    M.allow_set(str(fake_pkg), write=True)
    M.allow_set(str(pkgs), write=True)
    M.begin_run()

    # ---- S5：跑包途中按停止 ⇒ **立刻**回来 + 连子孙一起杀掉（用户报的几十个进程） ----
    _long = tmp / "long_host.py"
    _long.write_text(
        "# -*- coding: utf-8 -*-\n"
        "import os, subprocess, sys, time\n"
        "kid = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        "open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pids.txt'), 'w').write(\n"
        "    '%d %d' % (os.getpid(), kid.pid))\n"
        "time.sleep(120)\n", encoding="utf-8")
    _old_host = os.environ.get("MOSS_HOST_CMD")
    os.environ["MOSS_HOST_CMD"] = '"%s" "%s"' % (sys.executable, _long)
    _flag = {"v": False}
    threading.Timer(1.2, lambda: _flag.__setitem__("v", True)).start()
    _t0 = time.time()
    _s5 = L.Loop(FakeModel([call("run_moss", {"args": ":sleepy", "timeout": 120})]),
                 workdir=fake_pkg, max_steps=3, say=lambda s: None,
                 stop_check=lambda: _flag["v"]).run("跑个长命令")
    _dt = time.time() - _t0
    chk("S ★★ 跑包途中按停止 ⇒ **立刻**回来（老写法要等满 timeout 120 秒）",
        _dt < 10, "%.1f 秒" % _dt)
    chk("S ★★ 收工原因写的是「用户按了停止（立刻停，没有等下一轮）」",
        "停止" in str(_s5.get("reason")), str(_s5.get("reason"))[:50])
    _pids = (tmp / "pids.txt").read_text(encoding="utf-8").split() if (tmp / "pids.txt").is_file() else []
    _alive = []
    if _pids:
        for _p in _pids:
            _out2 = subprocess.run(["tasklist", "/FI", "PID eq %s" % _p, "/NH"],
                                   capture_output=True, text=True, errors="replace")
            if str(_p) in (_out2.stdout or ""):
                _alive.append(_p)
    chk("S ★★ 那条命令**连它的子进程一起被杀掉**（pid 都不在了 —— 用户报的几十个 moss/python 就是这么收的）",
        len(_pids) == 2 and not _alive, "记下的 pid=%s，还活着的=%s" % (_pids, _alive))
    if _old_host is None:
        os.environ.pop("MOSS_HOST_CMD", None)
    else:
        os.environ["MOSS_HOST_CMD"] = _old_host

    # ---- S6：临时空间（`V-314`：**按插件分** + 子进程指过去 + 一键清） --------------
    _td = M.ensure_tmp("probe-run-1", str(fake_pkg))
    _want = E.user_data() / "state" / "zz" / "ai" / "tmp"
    chk("S ★★ 临时空间**跟着插件走**（`state/<包id>/ai/tmp/`，不是全局一个桶）",
        _td is not None and _td.is_dir() and _td.parent == _want
        and _want == M.tmp_root(str(fake_pkg)),
        "%s（期望根 %s）" % (_td, _want))
    _td2 = M.ensure_tmp("probe-run-2", str(pkgs))          # 不针对某个包 ⇒ 全局桶
    chk("S ★ 不针对包那种（没选包）才落回 `user_data/ai/tmp/`",
        _td2 is not None and _td2.parent == M.tmp_root(""), str(_td2))
    _env5 = T.child_env(run_id="probe-run-1", workdir=str(fake_pkg))
    chk("S ★★ 子进程的 `TMP`/`TEMP`/`MOSS_AI_TMP` 都指到**这个插件的**那一格",
        _env5.get("MOSS_AI_TMP") == str(_td) and _env5.get("TMP") == str(_td),
        str(_env5.get("TMP")))
    chk("S ★★ 它自己的临时空间**读得回来也写得进**（不然草稿是白写的）",
        E.check_readable(_td / "草稿.txt") is None
        and E.check_writable(_td / "草稿.txt") is None,
        str(E.check_writable(_td / "草稿.txt"))[:60])
    (_td / "垃圾.bin").write_bytes(b"0" * 2048)
    chk("S 临时空间大小数得出来（界面那一行）",
        M.tmp_size(str(fake_pkg)).get("files", 0) >= 1
        and M.tmp_size(str(fake_pkg)).get("bytes", 0) >= 2048,
        str(M.tmp_size(str(fake_pkg))))
    chk("S ★ 别的包的临时空间**数不进来**（各算各的）",
        M.tmp_size(str(pkgs)).get("files") == 0, str(M.tmp_size(str(pkgs))))
    M.tmp_clean("probe-run-1", str(fake_pkg))
    chk("S ★ 一键清空真的把它清掉（用户要的「放心清理」）",
        not _td.exists() and M.tmp_size(str(fake_pkg)).get("files") == 0,
        str(M.tmp_size(str(fake_pkg))))
    _old = []
    for _i in range(3):
        _old.append(M.ensure_tmp("old-%d" % _i, str(fake_pkg)))
        (_old[-1] / "x.txt").write_text("x", encoding="utf-8")
    M.prune_tmp(keep=2, workdir=str(fake_pkg))
    _left = list(M.tmp_root(str(fake_pkg)).iterdir())
    chk("S ★ 只留最近 N 个（更老的自动删，不然临时空间越积越大）",
        len(_left) <= 2 and _td2.exists(), str([d.name for d in _left]))
    M.tmp_clean("", str(fake_pkg))
    M.tmp_clean("", str(pkgs))

    # ---- S7：**每一步都落盘**（强制重启那次丢记录的正解） ------------------------
    #   节流是 1.5 秒一次，所以这里让假模型每轮睡 1.7 秒 —— 不然几步在一瞬间跑完，
    #   量到的只会是"开工 + 收尾"那两次，证明不了"每步都落"。
    class SlowModel(FakeModel):
        def chat(self, messages, tools=None, stop_check=None, on_wait=None, on_retry=None):
            time.sleep(1.7)
            return FakeModel.chat(self, messages, tools, stop_check, on_wait, on_retry)

    _jour = []
    L.Loop(SlowModel([call("list_dir", {}), call("answer", {"text": "好了"})]),
           workdir=fake_pkg, max_steps=4, say=lambda s: None,
           on_journal=lambda part, force: _jour.append((len(part.get("steps") or []), bool(force)))).run("落盘试试")
    chk("S ★★ 一边跑一边落盘（开工 + 中途每步 + 收尾，远不止「跑完写一次」）",
        len(_jour) >= 3 and max(x[0] for x in _jour) >= 2, "落盘 %d 次：%s" % (len(_jour), _jour[:6]))
    chk("S ★ 落盘的每一份都带**步骤流 + 用量**（重启后界面上摆得出来）",
        all(isinstance(x[0], int) for x in _jour), "")

    # ---- S8：**请求放行**（`allow_path`）—— `V-319` 起不弹卡片，改成"清单里闪一行" ------
    #   工具本身只负责**请求**：宿主给的 `perm_gate` 去摆那一行、等他勾，回一句话。
    _out2 = tmp / "asked"
    _out2.mkdir(parents=True, exist_ok=True)
    _gates = []

    def _gate_grant(p, why, need):
        _gates.append({"path": str(p), "why": why, "need": need})
        M.allow_add(str(p), read=True, write=True, why=why, by="user", pending=False)
        return {"granted": True, "read": True, "write": True, "reason": "ok"}

    _got8 = T.Tools(workdir=fake_pkg, perm_gate=_gate_grant).call(
        "allow_path", {"path": str(_out2), "why": "要把结果写那儿", "need": "write"})
    chk("S ★★ 请求放行 ⇒ 闸收到了（路径 + 理由 + 要读还是要写）",
        bool(_gates) and _gates[0]["path"] == str(_out2) and _gates[0]["need"] == "write"
        and _gates[0]["why"] == "要把结果写那儿", str(_gates[:1])[:90])
    chk("S ★★ 用户勾了 ⇒ 工具回的是「已经进清单（读=开 写=开）」，而且当场能写",
        "已经进清单" in _got8 and "读=开" in _got8 and "写=开" in _got8
        and any(x.get("path") == str(_out2) and x.get("read") and x.get("write")
                for x in M.allow_list()), _got8[:80])
    # 只给了读
    M.allow_rm(str(_out2))
    _got8b = T.Tools(workdir=fake_pkg, perm_gate=lambda p, why, need: {
        "granted": False, "read": True, "write": False, "reason": "read-only"}).call(
        "allow_path", {"path": str(_out2), "why": "看一眼", "need": "write"})
    chk("S ★★ 用户只勾了「读」⇒ 回话里明说**只能看、改不了**（不是假装成功）",
        "只放行了" in _got8b and "改不了" in _got8b, _got8b[:80])
    # 拒绝
    _got8c = T.Tools(workdir=fake_pkg, perm_gate=lambda p, why, need: {
        "granted": False, "reason": "denied"}).call(
        "allow_path", {"path": str(_out2), "why": "写那儿", "need": "write"})
    chk("S ★★ 用户在清单里拒绝 ⇒ 工具回「拒绝」并且叫它别动那里",
        "拒绝" in _got8c and "别动那里" in _got8c, _got8c[:80])
    # 停止 / 超时（超时那条要明说"别硬来"）
    _got8d = T.Tools(workdir=fake_pkg, perm_gate=lambda p, why, need: {
        "granted": False, "reason": "stopped"}).call(
        "allow_path", {"path": str(_out2), "why": "写那儿", "need": "write"})
    chk("S ★ 挂着请求时按停止 ⇒ 回「已停止」，别再调工具", "已停止" in _got8d, _got8d[:60])
    _got8e = T.Tools(workdir=fake_pkg, perm_gate=lambda p, why, need: {
        "granted": False, "reason": "timeout"}).call(
        "allow_path", {"path": str(_out2), "why": "写那儿", "need": "write"})
    chk("S ★ 一直没人勾 ⇒ 回「没人回应」，叫它换个做法别硬来",
        "没人回应" in _got8e and "别硬来" in _got8e, _got8e[:70])
    chk("S ★★ 没有界面（命令行 / 探针不给闸）⇒ 明说「没人可问」，别假装问过",
        "没人可问" in str(T.Tools(workdir=fake_pkg).call(
            "allow_path", {"path": str(_out2), "why": "写那儿"})), "")
    M.allow_rm(str(_out2))

    # ---- S9：`V-319` **待允许那一行**（清单里的 pending 标记） --------------------
    _p = M.allow_pending_add(str(_out2), why="AI 说要写这儿", need="write")
    _row = M.find(str(_out2))
    chk("S ★★ 它一请求 ⇒ 清单里就多一行**待允许**（读/写都关着 + `pending`）",
        _p.get("ok") and _row is not None and _row.get("pending") is True
        and not _row.get("read") and not _row.get("write"), str(_row)[:90])
    chk("S ★★ 那一行**读不了也写不了**（界面还没勾）",
        M.can_read(_out2 / "a.txt") is not None and M.can_write(_out2 / "a.txt") is not None, "")
    M.allow_set(str(_out2), read=True, write=True, pending=False)
    _row2 = M.find(str(_out2))
    chk("S ★★ 用户一勾 ⇒ 变成正式条目（`pending` 清掉，不再是「待允许」）",
        _row2 is not None and _row2.get("pending") is False
        and M.can_write(_out2 / "a.txt") is None, str(_row2)[:90])
    M.allow_rm(str(_out2))
    chk("S ★ 用户点 ✕（= 拒绝）⇒ 那一行没了，宿主据此判「拒绝」",
        M.find(str(_out2)) is None, "")

    # ---- S10：`V-384`（用户 2026-10-19 报的三条） --------------------------------
    # ① 勾了「完全权限」⇒ **一次权限请求都不该再有**（真机记录 `20261019-180546-e84f`
    #    第 47 / 90 步：明明全放开了，它还是为"改名后的新目录""新造的技能"弹了两张卡）
    # ② 改一个**已经存在的包** ⇒ **开工就存**快照（真机上它先读十几分钟，
    #    用户在「版本快照」里看到空白，只能判断成"没备份"）；一个字都没改就收掉
    # ③ 包改过名之后，会话记录里过期的 `workdir` 要按桶纠正 —— 不然界面认领不上，
    #    "改完名没有自动进入 AI 对话"
    print()
    print("-" * 72)
    print("S10：`V-384` 完全权限还弹请求 / 开工没镜像 / 改完名接不上会话")
    print("-" * 72)
    import ai_runs as R                                              # noqa: E402

    _star_before = MP.wildcard_write()

    def _gate_counted(p, why, need):
        _gate_calls.append(str(p))
        return {"granted": True, "read": True, "write": True}

    _gate_calls = []
    _v384pkg = pkgs / "v384pkg"
    _v384pkg.mkdir(parents=True, exist_ok=True)
    (_v384pkg / "pkg.json").write_text('{"spec": 1, "id": "v384pkg"}', encoding="utf-8")
    _v384out = tmp / "v384outside"
    _v384out.mkdir(parents=True, exist_ok=True)

    MP.allow_add("*", read=False, write=True, why="探针：完全权限")
    _r = str(T.Tools(workdir=str(_v384pkg), perm_gate=_gate_counted).call(
        "allow_path", {"path": str(_v384out), "need": "write", "why": "改它"}))
    chk("S10 ★★ 勾了「完全权限」⇒ `allow_path` 直接回「不用申请」，"
        "而且**闸一次都没被叫**（不再白弹一张卡、白等一个人）",
        "不用申请" in _r and not _gate_calls, _r[:80])
    # 同一个目录，**没**开完全权限 ⇒ 仍然要走请求（不是无条件放行）
    MP.allow_add("*", read=False, write=False, why="探针：关掉完全权限")
    _r = str(T.Tools(workdir=str(_v384pkg), perm_gate=_gate_counted).call(
        "allow_path", {"path": str(_v384out), "need": "write", "why": "改它"}))
    chk("S10 ★★ 关掉「完全权限」⇒ 该问的还是要问（闸叫到了，不是无条件放行）",
        bool(_gate_calls) and "不用申请" not in _r, "闸收到：%s" % (_gate_calls[:1],))
    # 已经在范围内的地方也不用申请（改名后的新目录属于这一类：包本来就是你的）
    _gate_calls = []
    _r = str(T.Tools(workdir=str(_v384pkg), perm_gate=_gate_counted).call(
        "allow_path", {"path": str(_v384pkg), "need": "write", "why": "改它"}))
    chk("S10 ★★ 本来就允许的地方（当前这个包）⇒ 也回「不用申请」，不打扰人",
        "不用申请" in _r and not _gate_calls, _r[:80])
    MP.allow_add("*", read=False, write=_star_before, why="探针：还原")
    MP.allow_rm(str(_v384out))

    # ② 开工就存（只认"已经是个包"的目录）
    _s1 = S.snapshot_at_start("探针：开工就存", str(_v384pkg))
    chk("S10 ★★ 改一个**已经存在的包** ⇒ 开工那一刻就存了快照（不用等它第一次写）",
        _s1.get("ok") is True and _s1.get("group") == "v384pkg", str(_s1.get("msg"))[:90])
    _s2 = S.snapshot_at_start("探针：新建包那种", str(pkgs))
    chk("S10 ★★ `pkgs` 整层（新建包那种）**不在开工时存** —— 没有\"动手前的样子\"可存",
        (not _s2.get("ok")) and (_s2.get("skip") is True), str(_s2.get("msg"))[:80])
    chk("S10 ★ 开工那条**收得掉**（一个字没改时用）",
        S.drop_untouched(_s1.get("id"), _s1.get("group")).get("ok") is True, "")

    # 纯问答（`answer` 收工、没改没跑）⇒ 开工那条空快照要在收工时收掉
    _v384b = pkgs / "v384b"
    _v384b.mkdir(parents=True, exist_ok=True)
    (_v384b / "pkg.json").write_text('{"spec": 1, "id": "v384b"}', encoding="utf-8")
    _seen_snap = []
    _rl = L.Loop(FakeModel([call("answer", {"text": "我是模型。"})]),
                 workdir=str(_v384b), say=lambda *a, **k: None,
                 on_snapshot=lambda s: _seen_snap.append(s))
    _rr = _rl.run("你是哪个大模型")
    chk("S10 ★★ 纯问答那轮：开工**存了**（`on_snapshot` 收到了）、收工又**收掉**（`V-269` 想省的"
        "\"问答也留一条\"还在省着）",
        bool(_seen_snap) and _rr.get("snapshot") is None and S.ai_count("v384b") == 0,
        "开工时收到 %d 次 / 收工 snapshot=%s / 库里还剩 %d 条"
        % (len(_seen_snap), _rr.get("snapshot"), S.ai_count("v384b")))
    # 真改过文件 ⇒ **留着**（那是这一跑的真退路）
    _rl2 = L.Loop(FakeModel([call("write_file", {"path": str(_v384b / "run.py"),
                                                 "content": "# hi\n"}),
                             call("done", {"summary": "改好了"})]),
                  workdir=str(_v384b), max_steps=4, say=lambda *a, **k: None)
    _rr2 = _rl2.run("给这个包加个 run.py")
    chk("S10 ★★ 真改动过 ⇒ 开工那条快照**留着**（那是这一跑的退路，不能收）",
        bool((_rr2.get("snapshot") or {}).get("id")) and S.ai_count("v384b") >= 1,
        "snapshot=%s" % ((_rr2.get("snapshot") or {}).get("id"),))

    # ③ 改名之后：记录里的 `workdir` 过期 ⇒ 按桶纠正（界面才认领得上）
    _gone = pkgs / "v384old"                     # 假装是改名之前的目录（不存在）
    _scope = {"kind": "pkg", "id": "v384b", "dir": R.scope_dir(str(_v384b))}
    R.save({"id": "29990101-000000-0000", "task": "改名前那条会话",
            "workdir": str(_gone), "steps": [], "messages": [{"role": "user",
                                                              "content": "hi"}]}, scope=_scope)
    _rows = R.list_runs(5, scope=_scope)
    _hit = [r for r in _rows if r.get("id") == "29990101-000000-0000"]
    chk("S10 ★★ 改名后：会话记录里过期的 `workdir` **按桶纠正**成新目录（历史能接上）",
        bool(_hit) and _hit[0].get("workdir") == str(_v384b),
        "纠正成：%s" % ((_hit[0].get("workdir") if _hit else "(没读到)"),))
    _p_raw = R._file_of("29990101-000000-0000", _scope)
    _raw = json.loads(_p_raw.read_text(encoding="utf-8")) if _p_raw else {}
    chk("S10 ★ 盘上那份**没被改写**（只纠读出来的那份，不偷偷动别人的记录）",
        str(_raw.get("workdir") or "") == str(_gone), "盘上还是：%s" % (_raw.get("workdir"),))

    print()
    print("=" * 72)
    print("S11：完全权限 = 任意路径 + 技能自动批准（和单独的「任意路径」分开）")
    print("=" * 72)
    import skill_lib as SK                                                # noqa: E402
    _sp = SK.skill_dir() / "fullprobe"
    _sp.mkdir(parents=True, exist_ok=True)
    (_sp / "pkg.json").write_text(json.dumps({
        "spec": 1, "id": "fullprobe", "kind": "task", "name": "完全权限探针",
        "desc": "probe", "entry": {"file": "run.py"},
        "ai": {"expose": True, "why": "probe"}}, ensure_ascii=False), encoding="utf-8")
    (_sp / "run.py").write_text("print(1)\n", encoding="utf-8")
    (_sp / "icon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>', encoding="utf-8")
    MP.set_full_access(False)
    MP.allow_set("*", read=True, write=True, why="只是任意路径", by="user")
    _sk = SK.list_skills()["fullprobe"]
    chk("S11 ★ 只勾「任意路径」⇒ 技能仍然待批准（两个概念不许混）",
        (not MP.full_access()) and (not _sk["allowed"]), _sk["why_allow"])
    MP.set_full_access(True)
    _sk = SK.list_skills()["fullprobe"]
    chk("S11 ★★ 打开「完全权限」⇒ 已有技能自动批准，且任意路径也开着",
        MP.full_access() and MP.wildcard_write() and _sk["allowed"]
        and "完全权限" in _sk["why_allow"], _sk["why_allow"])
    (_sp / "run.py").write_text("print(2)\n", encoding="utf-8")
    _sk2 = SK.list_skills()["fullprobe"]
    chk("S11 ★★ 改了技能文件仍然自动批准（不会退回待批准）",
        _sk2["allowed"] and "完全权限" in _sk2["why_allow"], _sk2["why_allow"])
    chk("S11 ★ 给模型的说明里明确「不要停下来等用户点允许」",
        "不要停下来等用户" in SK.note()
        and "不要用 `ask` 等用户批准" in MP.perm_note(str(_v384pkg)), "")
    MP.set_full_access(False)
    _sk3 = SK.list_skills()["fullprobe"]
    chk("S11 ★★ 关掉完全权限 ⇒ 没被真人批准过的技能回到待批准（不留永久副作用）",
        (not MP.full_access()) and (not MP.wildcard_write()) and (not _sk3["allowed"]),
        _sk3["why_allow"])

    shutil.rmtree(tmp, ignore_errors=True)
    print()
    print("=" * 72)
    bad = [r for r in RES if not r[1]]
    print("结论：%s（%d 条，失败 %d）" % ("✅ 全过" if not bad else "✗ 有不对的", len(RES), len(bad)))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
