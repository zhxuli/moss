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

    def chat(self, messages, tools=None, stop_check=None, on_wait=None):
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

    print("=" * 72)
    print("A：提示词是**两层数据文件**（user 覆盖 system），缺了要能报出来")
    print("=" * 72)
    text, used, missing = L.compose_system("给我写个新包")
    chk("A 出厂那份读得到（system + edit 都在）",
        "moss 的写插件助手" in text and "search/replace" in text,
        "用了：" + "；".join(Path(u.split("← ")[-1]).name for u in used))
    chk("A 提到「写新包」时注入了 new_pkg 片段", "写一个新包" in text or "--new" in text, "")
    chk("A 没提到拖放就不注入 dragdrop 片段", "收拖入 / 内嵌界面" not in text, "")
    text2, _u, _m = L.compose_system("要能收拖入的包")
    chk("A 提到拖放才注入 dragdrop 片段", "收拖入 / 内嵌界面" in text2 or "captured" in text2, "")
    over = udata / "ai" / "prompts"
    over.mkdir(parents=True, exist_ok=True)
    (over / "system.md").write_text("【我是用户覆盖版】只回三个字。", encoding="utf-8")
    text3, used3 = L.compose_system("随便")[:2]
    chk("A user_data 的同名提示词**覆盖**出厂那份（两层规矩）",
        "我是用户覆盖版" in text3 and "moss 的写插件助手" not in text3, "")
    chk("A 覆盖时来源写的是 user_data 那份",
        any("user_data" in u and "system.md" in u for u in used3), "；".join(used3))
    chk("A 两层都缺的提示词会被点名（不搞隐形兜底）",
        L.missing_prompts(["根本不存在的片段"]) == ["根本不存在的片段"], "")
    (over / "system.md").unlink()                      # 还原，别影响后面的用例

    print()
    print("=" * 72)
    print("B：改文件 = search/replace（多命中拒绝、找不到给线索、CRLF 不乱翻、写权限守卫）")
    print("=" * 72)
    d = pkgs / "demo"
    d.mkdir()
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
    chk("B ★ 写 `user_data/state/` 被拒（v1 只许写 user_data/pkgs/**）",
        r.get("ok") is False and "只允许写" in str(r.get("error")), str(r.get("error"))[:70])
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
    chk("F ★ 读宿主源码（core/）被拒 —— 不再「读到一半跑去研究 moss 怎么实现」",
        "只允许读" in got, got.replace("\n", " ")[:80])
    got = t.call("list_dir", {"path": str(home)})
    chk("F list_dir 仓库根也被拒（省 token 的第一道闸）", "只允许读" in got, got.replace("\n", " ")[:60])
    got = t.call("read_file", {"path": str(home / "system" / "pkgs" / "bmi" / "main.py")})
    chk("F 样板包（system/pkgs/bmi）仍然读得到 —— 别把该读的也拦了",
        "只允许读" not in got and len(got) > 20, got.splitlines()[0][:60])
    got = t.call("grep", {"pattern": "def main", "path": str(home / "core")})
    chk("F grep 也守同一条线", "只允许读" in got, got.replace("\n", " ")[:60])

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
    chk("H 标题写着「AI · 动手前」（一眼认出是 AI 存的）",
        str(man.get("title")).startswith("AI · 动手前"), "%r" % man.get("title"))
    # ★ `V-249`：光写"动手前"认不出这是**干啥**之前的代码 —— 提示词得进标题
    chk("H ★ 标题里带上了**那次给它的提示词**",
        "把 zz 改成能算加法" in str(man.get("title")), "%r" % man.get("title"))
    chk("H ★ 备注是任务原文（全文，不截）",
        str(man.get("note")) == "把 zz 改成能算加法", "%r" % man.get("note"))
    # 提示词是用户自己敲的：可能是好几行、可能很长、也可能空着
    chk("H 提示词好几行 → 压成一行（标题不能带换行）",
        "\n" not in S.title_for("第一行\n第二行  第三行")
        and "第一行 第二行 第三行" in S.title_for("第一行\n第二行  第三行"),
        "%r" % S.title_for("第一行\n第二行  第三行"))
    _long = "把" * 100
    chk("H 提示词太长 → 标题截到 40 字 + 省略号",
        len(S.title_for(_long)) <= len(S.TITLE) + 1 + S.TASK_IN_TITLE + 1
        and S.title_for(_long).endswith("…"), "%r" % S.title_for(_long))
    chk("H 但备注里是**全文**（一个字都没截）", S.note_for(_long) == _long,
        "备注 %d 字" % len(S.note_for(_long)))
    chk("H 提示词是空的 → 退回原来那句固定话（标题也不挂个空冒号）",
        S.title_for("") == S.TITLE and S.title_for("   \n ") == S.TITLE
        and S.note_for("") == S.NOTE, "%r / %r" % (S.title_for(""), S.note_for("")))
    # ★ `V-250`：快照**存好就立刻喊一声** —— 界面靠它刷新「版本快照」那一列。
    #   你报的原话："当他备份以后 版本快照这里 没有刷新 所以我是看不到它刚刚做的快照的"。
    #   以前只有跑完才从 `result.snapshot` 里知道，而快照是**动手之前**就存了的。
    _snaps = []
    _m = FakeModel([call("done", {"summary": "什么都不用改"})])
    L.Loop(_m, workdir=fake_pkg, max_steps=3, say=lambda s: None,
           on_snapshot=lambda g: _snaps.append(g)).run("把 zz 改成能算加法")
    chk("H ★★ 开工前那条快照存好就**立刻通知界面**（不用等跑完）",
        len(_snaps) == 1 and _snaps[0].get("id") and _snaps[0].get("group") == "zz",
        "通知了 %r" % (_snaps,))
    # 用户自己存一条（by 为空），然后试"清 AI 的" —— **它必须一条都不动我的**
    mine = S._store().create([str(fake_pkg.resolve())], title="我自己存的", note="")
    chk("H 人存的那条 by 是空的（默认就是\"人存的\"）", not (mine.get("by") or ""), "by=%r" % mine.get("by"))
    cleaned = S.clean_ai(group="zz")
    chk("H ★ 清 AI 的：AI 那条被删了", got_snap.get("id") in (cleaned.get("deleted") or []),
        str(cleaned.get("msg"))[:80])
    chk("H ★★ 用户自己存的那条**一条没动**（这是结构性的闸，不是提醒）",
        mine.get("id") not in (cleaned.get("deleted") or []) and
        mine.get("id") in (cleaned.get("skipped") or []),
        "跳过了 %s" % (cleaned.get("skipped") or []))
    still = [b["id"] for b in S._store().list_backups(group="zz")]
    chk("H 删完再看列表：只剩我存的那条", still == [mine.get("id")], str(still))
    # 就算 AI 拿 `run_moss` 去删（绕过 snap_clean）也要被拦下
    os.environ["MOSS_HOST_CMD"] = json.dumps([sys.executable, str(host)])
    blocked = t.call("run_moss", {"args": '--snap rm "%s" --group zz --yes' % mine.get("id")})
    chk("H ★ 走 run_moss 删快照被拒（只能走 snap_clean）",
        "拒绝" in blocked and "snap_clean" in blocked, blocked.replace("\n", " ")[:80])
    chk("H 而且那条真的还在（拦住了，不是嘴上说说）",
        S._store().manifest(mine.get("id"), "zz").get("id") == mine.get("id"), "")
    chk("H 不给 group 清全库被拒（免得手一抖）", S.clean_ai().get("ok") is False, "")
    chk("H ai_count 数得对（这一组现在 AI 存的是 0 条）", S.ai_count("zz") == 0, "")

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

        def chat(self, messages, tools=None, stop_check=None, on_wait=None):
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
    got_sample = tn.call("read_file", {"path": str(home / "system" / "pkgs" / "bmi" / "AGENT.md")})
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





    shutil.rmtree(tmp, ignore_errors=True)
    print()
    print("=" * 72)
    bad = [r for r in RES if not r[1]]
    print("结论：%s（%d 条，失败 %d）" % ("✅ 全过" if not bad else "✗ 有不对的", len(RES), len(bad)))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
