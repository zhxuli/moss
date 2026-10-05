# -*- coding: utf-8 -*-
"""AI 工作台**宿主那一半**的探针（`V-233`）：`Api.ai_info / ai_start / ai_poll / ai_stop`。

为什么单独测这一层
------------------
页面那一半由 `tools/界面预览.py ai-pane` 验（假后端）；loop 本身由 `tools/ai循环探针.py` 验
（假模型）。中间这一层是**宿主把两者接起来**的地方 —— 起线程、把每一步写进状态、轮询给页面、
按停止，还有"AI 模块坏了不许把界面拖下水"这条。这一段以前没人管，最容易悄悄坏。

★ 用**假模型 + 假宿主**跑完整的 start→poll→result 流程：不联网、不烧 token。
★ `import system/ui/main.py` 的手法抄 `tools/窗口记忆探针.py`：只 import 不 `webview.start()`
  ⇒ 不开窗；数据目录指到临时目录 ⇒ 不碰真配置。
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "system" / "ui"
for s in (sys.stdout, sys.stderr):
    try:
        s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                                    # noqa: BLE001
        pass

RES = []


def chk(name, ok, detail=""):
    RES.append((name, bool(ok), str(detail)))
    print("  %s %s%s" % ("OK  " if ok else "FAIL", name, ("   ← " + str(detail)) if detail else ""))


FAKE_HOST = '''# -*- coding: utf-8 -*-
import os, sys
mark = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ok.marker")
print("假宿主：%s" % " ".join(sys.argv[1:]))
if os.path.exists(mark):
    sys.exit(0)
open(mark, "w").write("1")
sys.exit(1)
'''


class FakeClient:
    """照剧本回话的假模型（脚本在下面按场景给）。

    ★ 它的 `__init__` 得能接住 `Client(base_url, api_key, model)` 那种构造
      （`V-234` 之后宿主是**直接构造** Client，不再走 `from_env`）。
    ★ `INSTANCES`（`V-251`）：宿主是在 `ai_start` 里**自己** new 一个 client 的，
      测试拿不到那个实例 —— 所以构造时自己往表里塞一份，验"接着聊"时读它发出去的 messages。
    """
    INSTANCES = []

    def __init__(self, *args, **kw):
        self.script = list(SCRIPT)
        self.seen = []
        #: ★ `V-251`：把每次发出去的 messages 也留一份（验"接着聊"时老对话有没有真的发出去）
        self.msgs = []
        #: ★ `V-280`：工具表也留一份（验"自制工具点允许之后下一次跑才进表"）
        self.tools_seen = []
        FakeClient.INSTANCES.append(self)
        # ★ `V-252`：第三个参数是**模型名**（宿主 `Client(base_url, key, model)`）——
        #   以前这里写死 "fake-model"，于是"顶栏选了别的模型"这条根本验不出来。
        self.model = args[2] if len(args) > 2 else (kw.get("model") or "fake-model")
        self.base_url = args[0] if args else kw.get("base_url", "")
        self.api_key = args[1] if len(args) > 1 else kw.get("api_key", "")

    @classmethod
    def from_env(cls, **kw):
        return cls()

    def chat(self, messages, tools=None, stop_check=None, on_wait=None, on_retry=None):
        # `V-242`：签名跟真 client 对上（多出来的两个参数是"能不能中途停"用的）
        self.seen.append(1)
        self.msgs.append(json.loads(json.dumps(messages, ensure_ascii=False)))
        self.tools_seen.append(json.loads(json.dumps(tools or [], ensure_ascii=False)))
        if not self.script:
            return {"text": "（没了）", "tool_calls": [], "usage": {}, "native": True,
                    "message": {"role": "assistant", "content": "（没了）"}}
        return self.script.pop(0)


def call(name, args):
    return {"text": "", "tool_calls": [{"id": "c", "name": name, "args": args}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 7, "total_tokens": 57},
            "native": True,
            "message": {"role": "assistant", "content": None,
                        "tool_calls": [{"id": "c", "type": "function",
                                        "function": {"name": name,
                                                     "arguments": json.dumps(args, ensure_ascii=False)}}]}}


SCRIPT = []


def _man_ok(S, snap):
    """这条快照的清单还读得出来吗（读不出来就当它没了）—— 只给 `V-279` 那段用。"""
    try:
        return bool(S._store().manifest(snap["id"], snap.get("group")))
    except Exception:                                                     # noqa: BLE001
        return False


def main():
    tmp = Path(tempfile.mkdtemp(prefix="moss_aipane_"))
    udata = tmp / "user_data"
    pkgs = udata / "pkgs"
    pkgs.mkdir(parents=True)
    host = tmp / "fake_host.py"
    host.write_text(FAKE_HOST, encoding="utf-8")
    os.environ["MOSS_HOME"] = str(ROOT)
    os.environ["MOSS_USER_DATA_DIR"] = str(udata)
    os.environ["MOSS_HOST_CMD"] = '"%s" "%s"' % (sys.executable, host)
    for k in ("MOSS_AI_BASE_URL", "MOSS_AI_API_KEY", "MOSS_AI_MODEL"):
        os.environ.pop(k, None)
    payload = {"home": str(ROOT), "user_data": str(udata), "host_cmd": [str(ROOT / "moss.exe")],
               "launch_kind": "probe", "icon_exts": [".svg"], "packages": []}
    pfile = tmp / "payload.json"
    pfile.write_text(json.dumps(payload), encoding="utf-8")
    os.environ["MOSS_UI_DATA"] = str(pfile)

    sys.path.insert(0, str(UI / "ai"))
    for m in ("ai_edits", "ai_tools", "ai_loop", "ai_client"):
        sys.modules.pop(m, None)
    import ai_client                                                      # noqa: E402
    import ai_edits                                                       # noqa: E402
    import ai_snap                                                        # noqa: E402

    spec = importlib.util.spec_from_file_location("moss_ui_main_aipane", UI / "main.py")
    M = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(M)
    api = M.Api()

    print("=" * 72)
    print("A：AI 参数从**宿主**来（`V-234`：界面自己没有 `MOSS_AI_*`）")
    print("=" * 72)
    # 假宿主扮演 `moss --ai-config-reveal`：打一份 JSON 出来（格式和真的一样）
    cfg_ok = tmp / "fake_cfg.py"
    cfg_ok.write_text(
        "import json\nprint(json.dumps({'ok': True, 'active': '假组', 'profile': '假组',\n"
        "  'params': {'base_url': 'https://fake.example/v1', 'api_key': 'sk-假的key',\n"
        "             'model': ['fake-model', 'fake-model-2']}, 'profiles': ['假组']}))\n",
        encoding="utf-8")
    cfg_bad = tmp / "fake_cfg_bad.py"
    cfg_bad.write_text("print('[执行] 这行是横幅，不是 JSON')\n", encoding="utf-8")
    M.HOST = [sys.executable, str(cfg_ok)]
    M._AI_CFG.update({"t0": 0.0, "got": None})            # 别吃上一轮的缓存
    info = api.ai_info(str(pkgs), True)
    chk("A 回 ok 且有 write_root", info.get("ok") is True and info.get("write_root"), str(info.get("msg") or ""))
    chk("A 写范围指向**临时** user_data（没碰真目录）",
        str(udata) in str(info.get("write_root")), str(info.get("write_root")))
    chk("A ★ 界面回头问宿主拿到了模型（不再显示\"还没配 AI\"）",
        info.get("model") == "fake-model" and info.get("key_from") == "宿主",
        "model=%r 来源=%r" % (info.get("model"), info.get("key_from")))
    chk("A key 也拿到了（能真发请求）", info.get("has_key") is True, "")
    # ★ `V-252`：顶栏那个模型下拉要的"这家配了哪些模型"
    chk("A ★ 这一家配的模型列表给到了（顶栏下拉用它）",
        (info.get("models") or [])[:2] == ["fake-model", "fake-model-2"],
        json.dumps(info.get("models"), ensure_ascii=False))
    # ★ `V-252`：界面上那一行"上下文 xx / yy"以前**永远是默认值** —— 因为
    #   `ai_info` 里算它的那段用了一个还没赋值的局部变量，`except: pass` 把它吞了。
    chk("A ★★ 上下文窗口 / 压缩线也带上了（以前被一个未赋值的变量吞掉过）",
        (info.get("compact_at") or 0) > 0 and (info.get("context") or 0) > 0,
        "context=%r compact_at=%r" % (info.get("context"), info.get("compact_at")))
    chk("A base_url 取到了", info.get("base_url") == "https://fake.example/v1", str(info.get("base_url")))
    chk("A 提示词读到了（system/edit 都在）",
        "system.md" in (info.get("prompts") or []) and "edit.md" in (info.get("prompts") or []),
        str(info.get("prompts")))
    chk("A 缺提示词会点名（这里应该不缺）", info.get("missing_prompts") == [], str(info.get("missing_prompts")))
    # 宿主那份回不出来（比如还没配）时：**如实说为什么**，不许假装
    M.HOST = [sys.executable, str(cfg_bad)]
    M._AI_CFG.update({"t0": 0.0, "got": None})
    bad = api.ai_info(str(pkgs), True)
    chk("A 宿主回的不是 JSON 时，明说\"读不到\"（不是默默说没配）",
        bad.get("has_key") is False and "读不到" in str(bad.get("why")), str(bad.get("why"))[:80])
    M.HOST = [sys.executable, str(cfg_ok)]
    M._AI_CFG.update({"t0": 0.0, "got": None})

    print()
    print("=" * 72)
    print("B：交任务的基本规矩 —— 空任务拒绝、没配好时说清原因")
    print("=" * 72)
    chk("B 空任务被拒（不浪费一次调用）", api.ai_start("")["ok"] is False, "")
    M.HOST = [sys.executable, str(cfg_bad)]
    M._AI_CFG.update({"t0": 0.0, "got": None})
    msg = str(api.ai_start("写个包")["msg"])
    chk("B 读不到配置时说清原因（不是一句笼统的失败）", "读不到" in msg or "还没配" in msg, msg[:70])
    M.HOST = [sys.executable, str(cfg_ok)]
    M._AI_CFG.update({"t0": 0.0, "got": None})

    print()
    print("=" * 72)
    print("C：**整条链路**（假模型 + 假宿主）：ai_start → 页面轮询 → 结果落地")
    print("=" * 72)
    os.environ["MOSS_AI_BASE_URL"] = "https://example.invalid/v1"
    os.environ["MOSS_AI_API_KEY"] = "sk-假的"
    os.environ["MOSS_AI_MODEL"] = "fake-model"
    ai_client.Client = FakeClient                                        # 换掉真模型
    target = pkgs / "zz" / "run.py"
    SCRIPT[:] = [call("write_file", {"path": str(target), "content": "print('v1')\n"}),
                 call("run_moss", {"args": ":zz"}),                    # 第一次：退出码 1
                 call("done", {"summary": "写好了"}),                    # 会被打回
                 call("edit_file", {"path": str(target), "find": "print('v1')",
                                    "replace": "print('v2')"}),
                 call("run_moss", {"args": ":zz"}),                    # 第二次：退出码 0
                 call("done", {"summary": "写好了 zz", "caveats": "没测参数"})]
    started = api.ai_start("写个 zz 包", str(pkgs), 100000000)
    chk("C ai_start 起来了", started.get("ok") is True and started.get("model") == "fake-model",
        json.dumps(started, ensure_ascii=False)[:120])
    deadline, got, last = time.time() + 40, None, None
    while time.time() < deadline:
        last = api.ai_poll()
        if last and not last.get("running") and last.get("result"):
            got = last
            break
        time.sleep(0.3)
    chk("C 轮询等到了结果（页面就是这么拿的）", got is not None,
        "最后一步：%s" % json.dumps((last or {}).get("steps", [])[-1:], ensure_ascii=False)[:140])
    if got:
        res = got["result"]
        chk("C ★ 结果 ok=True（验收闸过了）", res.get("ok") is True, res.get("reason"))
        chk("C 步骤流给到了页面（含 edit_file / run_moss）",
            any(s["tool"] == "edit_file" for s in got["steps"]) and
            any(s["tool"] == "run_moss" for s in got["steps"]),
            "、".join(s["tool"] for s in got["steps"]))
        chk("C token 记到了（usage 累加）", (res.get("usage") or {}).get("total_tokens", 0) > 0,
            json.dumps(res.get("usage"), ensure_ascii=False))
        chk("C 改了哪些文件也带出来了",
            any(str(target) == f for f in (res.get("files") or [])), str(res.get("files"))[:90])
        chk("C ★ 文件真的落到磁盘上了（不是它说改了）",
            target.is_file() and "v2" in target.read_text(encoding="utf-8"), "")
        chk("C summary / caveats 透传", res.get("summary") == "写好了 zz" and res.get("caveats") == "没测参数", "")
        # `V-236`：动手前那条快照，要能从结果里带回到页面（页面靠它显示"回退到开工前"）
        snap = res.get("snapshot") or {}
        chk("C ★ 结果里带回了「开工前快照」的 id（页面拿它画回退按钮）",
            bool(snap.get("id")), json.dumps(snap, ensure_ascii=False)[:90])
        if snap.get("id"):
            try:
                man = ai_snap._store().manifest(snap["id"], snap.get("group"))
                chk("C ★ 那条快照的清单里 `by=ai` + 任务原文都在",
                    str(man.get("by")) == "ai" and "zz" in str(man.get("by_task")),
                    "by=%r by_task=%r" % (man.get("by"), str(man.get("by_task"))[:40]))
            except Exception as exc:                                      # noqa: BLE001
                chk("C ★ 那条快照的清单里 `by=ai` + 任务原文都在", False, "%s: %s" % (type(exc).__name__, exc))
    chk("C 数据目录还是临时的（整轮没碰真 user_data）",
        str(ai_edits.write_root()).startswith(str(udata)), str(ai_edits.write_root()))

    print()
    print("=" * 72)
    print("C2：`V-251` 会话 —— 宿主这一半也要真的**接着上次那条聊**")
    print("=" * 72)
    # 上一轮（C）跑完已经落了一条记录；现在按"重启 moss 之后接着聊"这条路走一遍：
    # 界面把**那条记录的 id** 交回来，宿主自己去读对话、喂给 loop。
    import ai_runs as _runs                                                # noqa: E402
    _rows = _runs.list_runs(5)
    _rid = (_rows[0] or {}).get("id") if _rows else ""
    chk("C2 上一轮的任务记录落盘了（重启 moss 看得见）", bool(_rid), "%r" % (_rid,))
    chk("C2 ★ 列表里标了「这条能接着聊」+ 对话条数（页面据此画那颗按钮）",
        bool(_rows) and _rows[0].get("cont") is True and (_rows[0].get("msgs") or 0) >= 3,
        json.dumps({k: _rows[0].get(k) for k in ("cont", "msgs", "task")} if _rows else {},
                   ensure_ascii=False)[:120])
    # 「看」那条记录时**不许**把整条对话塞给页面（几百 KB），只给个标记
    _one = api.ai_run(_rid or "")
    chk("C2 ★ 点「看」不带 `messages` 给页面（只带 cont/msgs）",
        _one.get("ok") is True and "messages" not in (_one.get("run") or {})
        and (_one.get("run") or {}).get("cont") is True,
        json.dumps(sorted((_one.get("run") or {}).keys()), ensure_ascii=False)[:120])
    # ★ `V-269`：列表那一行靠 `kind` 决定画 ✅ 还是 💬 —— 干活那次是 work、问答那次是 chat，
    #   两个方向都钉一下（只钉一边的话，"字段根本没存"也会绿）。
    chk("C2 ★ 列表带 `kind`，干活那次是 work（界面据此画 ✅）",
        _rows[0].get("kind") == "work", repr(_rows[0].get("kind")))
    _cid = (_runs.save({"task": "你是哪个大模型?", "ok": True, "kind": "chat",
                        "reason": "问答收工（没动文件，不用跑命令）",
                        "summary": "我是 moss 的写插件助手", "usage": {}, "files": [],
                        "snapshot": None, "steps": [], "messages": []}) or {}).get("id")
    _crow = [r for r in _runs.list_runs(5) if r.get("id") == _cid]
    chk("C2 ★★ 纯问答那次列表里 `kind=chat`（界面据此画「💬 你是哪个大模型?」）",
        bool(_crow) and _crow[0].get("kind") == "chat",
        json.dumps(_crow[0] if _crow else {}, ensure_ascii=False)[:130])
    _runs.delete(_cid)                       # 清掉这条合成的，别影响后面的用例
    SCRIPT[:] = [call("run_moss", {"args": ":zz"}),                  # 跑通（验收闸要它）
                 call("done", {"summary": "接着改完了"})]
    _n_before = len(FakeClient.INSTANCES)
    started2 = api.ai_start("接着把 zz 的退出码也改一下", str(pkgs), 100000000, _rid)
    chk("C2 接着聊那条起来了", started2.get("ok") is True, str(started2.get("msg") or "")[:80])
    deadline, got2, last2 = time.time() + 40, None, None
    while time.time() < deadline:
        last2 = api.ai_poll()
        if last2 and not last2.get("running") and last2.get("result"):
            got2 = last2
            break
        time.sleep(0.3)
    chk("C2 跑完了", got2 is not None, json.dumps((last2 or {}).get("result") or {}, ensure_ascii=False)[:90])
    _inst = FakeClient.INSTANCES[-1] if len(FakeClient.INSTANCES) > _n_before else None
    sent = json.dumps((_inst.msgs or [{}])[0] if (_inst and _inst.msgs) else [], ensure_ascii=False)
    chk("C2 ★★ 发给模型的第一条请求里**既有上次那句、也有这次这句**（它真记得）",
        "写个 zz 包" in sent and "接着把 zz 的退出码也改一下" in sent,
        "发出 %d 条消息" % len((_inst.msgs or [{}])[0] if (_inst and _inst.msgs) else []))
    if got2:
        _new = _runs.get((got2.get("result") or {}).get("run_id") or "")
        chk("C2 ★ 新记录里写着从哪条接过来的（界面上能看出链条）",
            str((_new or {}).get("continued_from")) == _rid,
            "continued_from=%r（上一轮 %r）" % ((_new or {}).get("continued_from"), _rid))
        # ★ `V-259`：**"接着没有"要能回到界面**（你报的"每次输入都当新指令"就是因为它不吭声）
        _res2 = got2.get("result") or {}
        chk("C2 ★★ 结果里带着「这次接着没有」那句话（界面显示在那一轮上）",
            "接着上次那条聊" in str(_res2.get("continue_note")) and
            str(_res2.get("asked_continue")) == _rid,
            "note=%r asked=%r" % (_res2.get("continue_note"), _res2.get("asked_continue")))
        chk("C2 新记录的 `asked_continue` 也记着（查盘就能定案）",
            str((_new or {}).get("asked_continue")) == _rid,
            "asked_continue=%r" % ((_new or {}).get("asked_continue"),))
        # ★ `V-262`：**整条会话要能被读回来** —— 你报的"重启以后前面的会话没显示"、
        #   "标题变成最后那个问题"都是因为界面只拿到最后一条记录。
        _th = api.ai_thread(str((_new or {}).get("id") or ""))
        _turns = (_th or {}).get("turns") or []
        chk("C2 ★★ 能把**整条会话**读回来（链头 → 这条，2 轮都在）",
            _th.get("ok") is True and len(_turns) == 2,
            "turns=%d 尾巴=%r" % (len(_turns), (_th or {}).get("tail")))
        chk("C2 ★ 链头在前（第一轮的指令就是**第一句**，标题该用它）",
            bool(_turns) and "写个 zz 包" in str(_turns[0].get("task")),
            "第一轮=%r" % ((_turns[0] if _turns else {}).get("task"),))
        chk("C2 ★ 也不用把几百 KB 的对话塞给页面（每轮只带步骤流 + 结论）",
            all("messages" not in t for t in _turns) and
            bool(_turns) and bool(_turns[0].get("steps")),
            "键=%s" % (sorted(_turns[0].keys()) if _turns else []))
        chk("C2 新记录的对话比上一轮长（老的留在里面了）",
            len((_new or {}).get("messages") or []) > (_rows[0].get("msgs") or 0),
            "%d 条" % len((_new or {}).get("messages") or []))
    # 接不上时（记录被清了 / id 写错）：**照样干活，但要说清楚这次是新会话**
    SCRIPT[:] = [call("done", {"summary": "新会话跑完了"})]
    api.ai_start("这次当新会话跑", str(pkgs), 100000000, "这条记录根本不存在")
    time.sleep(1.2)
    _say = " ".join((api.ai_poll().get("say") or []))
    chk("C2 ★ 接不上就说清楚（**点名没找到**，然后按新会话跑），别让人以为它还记着",
        "没找到" in _say and "新会话" in _say, _say[-160:])
    deadline = time.time() + 30
    while time.time() < deadline:
        if not (api.ai_poll() or {}).get("running"):
            break
        time.sleep(0.3)

    # ★ `V-252`：顶栏那个模型下拉 —— 选哪个就用哪个（连带换上下文窗口）
    SCRIPT[:] = [call("run_moss", {"args": ":zz"}), call("done", {"summary": "换模型跑的"})]
    _n_before = len(FakeClient.INSTANCES)
    started3 = api.ai_start("换个模型跑一遍", str(pkgs), 100000000, "", "fake-model-2")
    chk("C2 指定模型的这次起来了", started3.get("ok") is True,
        json.dumps(started3, ensure_ascii=False)[:90])
    chk("C2 ★ 宿主用的就是**下拉里选的那个**模型（不是配置里第一个）",
        started3.get("model") == "fake-model-2", "model=%r" % started3.get("model"))
    _inst3 = FakeClient.INSTANCES[-1] if len(FakeClient.INSTANCES) > _n_before else None
    chk("C2 ★ 真发给网关的也是它（Client 是用这个模型建的）",
        bool(_inst3) and getattr(_inst3, "model", "") == "fake-model-2",
        "client.model=%r" % getattr(_inst3, "model", None))
    deadline = time.time() + 30
    while time.time() < deadline:
        if not (api.ai_poll() or {}).get("running"):
            break
        time.sleep(0.3)

    print()
    print("=" * 72)
    print("D：按「停止」—— 下一轮就收工，而且是**好好地**结束（不是崩）")
    print("=" * 72)
    # ★ 用"卡住不回的假模型"来制造"跑着的时候按停止"这个时刻：
    #   靠 sleep 猜时机的话，模型快一点就变成"已经跑完了"（第一版就是这么假红的）。
    import threading                                                      # noqa: E402
    release = threading.Event()

    class SlowClient(FakeClient):
        def chat(self, messages, tools=None, stop_check=None, on_wait=None, on_retry=None):
            release.wait(timeout=30)                     # 一直等，直到测试放行
            return call("list_dir", {"path": str(pkgs)})

    ai_client.Client = SlowClient                                        # 换掉模型（同样按类换）
    api.ai_start("列个目录", str(pkgs), 100000000)
    time.sleep(0.8)
    mid = api.ai_poll()
    chk("D 先确认真在跑（线程起来了、没结束）", mid.get("running") is True, "running=%s" % mid.get("running"))
    stopped = api.ai_stop()
    chk("D ai_stop 回了一句人话", stopped.get("ok") is True and "下一轮" in str(stopped.get("msg")),
        str(stopped.get("msg"))[:60])
    release.set()                                        # 放行：下一轮开头就该收工
    deadline, done = time.time() + 40, None
    while time.time() < deadline:
        p = api.ai_poll()
        if p and not p.get("running"):
            done = p
            break
        time.sleep(0.3)
    chk("D ★ 停止之后真的收工了", done is not None, "")
    if done:
        chk("D 收工原因写的是「用户按了停止」（页面能照实说）",
            "停止" in str((done.get("result") or {}).get("reason")), str((done.get("result") or {}).get("reason")))

    print()
    print("=" * 72)
    print("E：AI 模块坏了**不许把界面拖下水**")
    print("=" * 72)
    sys.modules.pop("ai_loop", None)
    real = M.Api._ai_mods
    M.Api._ai_mods = lambda self: (_ for _ in ()).throw(ImportError("假装 ai_loop 坏了"))
    bad = api.ai_info()
    chk("E ai_info 出问题时**回一句人话**而不是抛异常（页面照常能开）",
        bad.get("ok") is False and "起不来" in str(bad.get("msg")), str(bad.get("msg"))[:80])
    bad2 = api.ai_start("随便")
    chk("E ai_start 同理（回 ok:false，不冒泡）", bad2.get("ok") is False, str(bad2.get("msg"))[:60])
    M.Api._ai_mods = real

    print()
    print("=" * 72)
    print("F：`V-239` 预算（宿主那层封装）—— **按 token 上限**：默认 20 万、能存能读、不合理会拒")
    print("=" * 72)
    b0 = api.ai_budget()
    chk("F 不给 save ⇒ 读当前预算（含提醒线）",
        b0.get("ok") is True and b0.get("max_tokens") == 100000000 and b0.get("warn") == 80000000,
        json.dumps(b0, ensure_ascii=False)[:70])
    b1 = api.ai_budget(save=80000000)
    chk("F 存 8000 万成功", b1.get("ok") is True and b1.get("max_tokens") == 80000000,
        json.dumps(b1, ensure_ascii=False)[:70])
    chk("F 再读回来是 8000 万", api.ai_budget().get("max_tokens") == 80000000, "")
    chk("F 提醒线自动给（8000 万 ⇒ 6400 万）", api.ai_budget().get("warn") == 64000000,
        str(api.ai_budget().get("warn")))
    chk("F 不合理（太小）⇒ 回 ok:false + 人话",
        api.ai_budget(save=100).get("ok") is False, str(api.ai_budget(save=100).get("msg"))[:60])
    chk("F ai_set_budget 是同一个口子（界面那一格走它）",
        api.ai_set_budget(100000000).get("ok") is True and api.ai_budget().get("max_tokens") == 100000000, "")
    info2 = api.ai_info(str(pkgs), True)
    chk("F ai_info 把预算一起给页面（上限 + 提醒线两个数）",
        info2.get("max_tokens") == 100000000 and info2.get("warn_tokens") == 80000000,
        "max=%s warn=%s" % (info2.get("max_tokens"), info2.get("warn_tokens")))

    print()
    print("=" * 72)
    print("G：`V-243` 任务记录**落盘**（你说的「历史记录不保存是不行的」）")
    print("=" * 72)
    # C 段跑过一次任务 ⇒ 应该已经落了一条
    got_runs = api.ai_runs(10)
    chk("G 跑完的任务记录下来了（重启 moss 也还在）",
        got_runs.get("ok") is True and len(got_runs.get("runs") or []) >= 1,
        "有 %d 条；C 段的 save_error=%r" % (len(got_runs.get("runs") or []),
                                          (locals().get("res") or {}).get("save_error")))
    # 最新的那条可能是后面那些"故意失败"的用例 ⇒ 挑一条**成功的**来验字段
    _runs = got_runs.get("runs") or []
    first = next((r for r in _runs if r.get("ok")), _runs[0] if _runs else {})
    chk("G 记录里有：任务原文 / 结论 / 花了多少 token / 几步",
        bool(first.get("task")) and first.get("ok") is True and
        (first.get("usage") or {}).get("total_tokens") and first.get("steps"),
        "task=%r ok=%s steps=%s" % (str(first.get("task"))[:24], first.get("ok"), first.get("steps")))
    got_one = api.ai_run(first.get("id") or "")
    chk("G 点「看」能拿到完整那条（含步骤流）",
        got_one.get("ok") is True and len((got_one.get("run") or {}).get("steps") or []) >= 1,
        "steps=%s" % len((got_one.get("run") or {}).get("steps") or []))
    chk("G 记录真的在盘上（user_data/ai/runs/）",
        (tmp / "user_data" / "ai" / "runs").is_dir() and
        len(list((tmp / "user_data" / "ai" / "runs").glob("*.json"))) >= 1,
        str(tmp / "user_data" / "ai" / "runs"))
    chk("G 删一条也通", api.ai_run_forget(first.get("id") or "").get("ok") is True, "")
    chk("G 清空也通（只清记录，不动包）", api.ai_run_forget("", True).get("ok") is True, "")
    chk("G 清完列表就空了", api.ai_runs(10).get("runs") == [], "")

    print()
    print("=" * 72)
    print("H：`V-279` 会话的**改 / 删** —— 只删后缀 + 回退到那一轮的开工快照")
    print("=" * 72)
    # ★ 现场自己造（全在临时 user_data 里）：三条链式记录，每轮开工前一条 AI 快照。
    #   断言里那条"文件回到 v1 而不是 v0"是关键 —— 它证明回退用的是**那一轮自己的**快照，
    #   不是"反正退到最早"那种蒙对的写法。
    # ★ 注意：G 段把 `_runs` 这个名字**覆盖成了列表**（那是记录列表），这里得把模块重新拿回来。
    import ai_runs as _runs                                                # noqa: E402, F811
    wd = pkgs / "sess"
    wd.mkdir(parents=True, exist_ok=True)
    f1 = wd / "a.txt"
    _T = [1000.0]

    def _mkrun(task, prev, snap, at, files=None, kind="work"):
        _T[0] += 10.0
        return (_runs.save({
            "task": task, "workdir": str(wd), "kind": kind, "ok": True,
            "reason": "验收通过", "summary": task,
            "files": ([str(f1)] if files is None else files),
            "usage": {}, "steps": [],
            "snapshot": ({"id": snap["id"], "group": snap["group"]} if snap else None),
            "messages": [{"role": "user", "content": task}],
            "continued_from": prev or "", "finished": _T[0], "started_text": at}) or {}).get("id")

    f1.write_text("v0\n", encoding="utf-8")
    SA = ai_snap.snapshot_before("第一轮：建个文件", wd)
    r1 = _mkrun("第一轮：建个文件", "", SA, "2026-01-01 10:00:00")
    f1.write_text("v1\n", encoding="utf-8")
    SB = ai_snap.snapshot_before("第二轮：改成 v1", wd)
    r2 = _mkrun("第二轮：改成 v1", r1, SB, "2026-01-01 10:05:00")
    # ★ 我自己存的那条（`by` 不是 ai）—— 清理**碰都不许碰**
    SU = ai_snap._store().create([str(wd)], title="我自己存的", note="手动", by="")
    f1.write_text("v2\n", encoding="utf-8")
    SC = ai_snap.snapshot_before("第三轮：改成 v2", wd)
    r3 = _mkrun("第三轮：改成 v2", r2, SC, "2026-01-01 10:10:00")
    # 另一条会话（不接着谁）：同一个包、**更晚**也改过一次 —— 回退会连它一起撤掉
    SD = ai_snap.snapshot_before("另一条会话：加个 readme", wd)
    _mkrun("另一条会话：加个 readme", "", SD, "2026-01-01 10:20:00")
    chk("H 现场搭好了（三轮链 + 一条别人的会话）",
        all([r1, r2, r3]) and _runs.get(r3) is not None, "%r %r %r" % (r1, r2, r3))

    p2 = api.ai_session_plan(r2)
    chk("H 计划算得出来（**只算不改**）", p2.get("ok") is True, str(p2.get("msg") or "")[:90])
    chk("H ★★ 只允许从链尾往回连续删 ⇒ 删第二轮 = 第二轮 + 第三轮（第一轮留下）",
        (p2.get("delete_ids") or []) == [r2, r3], json.dumps(p2.get("delete_ids")))
    chk("H 计划里带着要删那几轮的任务原文（确认框要摆给用户看）",
        len(p2.get("delete_tasks") or []) == 2 and "第二轮" in str((p2.get("delete_tasks") or [""])[0]),
        json.dumps(p2.get("delete_tasks"), ensure_ascii=False)[:110])
    chk("H ★★ 回退到**它自己**开工前那条快照（不是更早那条）",
        (p2.get("target") or {}).get("id") == SB.get("id") and p2.get("fallback") is None,
        "target=%r fallback=%r" % ((p2.get("target") or {}).get("id"), p2.get("fallback")))
    chk("H 上一轮 id 带出来了（改完从上一轮接着往下走）", p2.get("prev_id") == r1, repr(p2.get("prev_id")))
    chk("H ★★ 跨链告警：另一条会话更晚改过同一个包，回退会连它一起撤 —— 必须说出来",
        any("其它会话" in w for w in (p2.get("warnings") or [])),
        json.dumps(p2.get("warnings"), ensure_ascii=False)[:170])
    chk("H 连删好几轮也明说（不是偷偷多删）",
        any("一起删掉" in w for w in (p2.get("warnings") or [])),
        json.dumps(p2.get("warnings"), ensure_ascii=False)[:130])

    # ★ 红的一半：**不给 confirm 就一个字节都不许动**（"先看事实再动手"那道闸）
    dry = api.ai_session_truncate(r2)
    chk("H ★★ confirm 不传 ⇒ 拒绝动手，只把计划回给你",
        dry.get("ok") is False and dry.get("need_confirm") is True,
        json.dumps(dry, ensure_ascii=False)[:110])
    chk("H ★★ 假做之后盘上**一个字节没动**（记录还在、文件还是 v2、快照还在）",
        _runs.get(r3) is not None and _runs.get(r2) is not None and
        f1.read_text(encoding="utf-8") == "v2\n" and bool(ai_snap._store().manifest(SB["id"], SB["group"])),
        "a.txt=%r r3=%s" % (f1.read_text(encoding="utf-8"), _runs.get(r3) is not None))

    done2 = api.ai_session_truncate(r2, True)
    chk("H 真删成功", done2.get("ok") is True, str(done2.get("msg") or "")[:90])
    chk("H ★★ 文件回到了**第二轮开工前**（撤销第二、三轮改的东西，不是退回 v0）",
        f1.read_text(encoding="utf-8") == "v1\n", repr(f1.read_text(encoding="utf-8")))
    chk("H ★ 记录删了第二/三轮，**第一轮还在**",
        _runs.get(r1) is not None and _runs.get(r2) is None and _runs.get(r3) is None,
        "r1=%s r2=%s r3=%s" % (_runs.get(r1) is not None, _runs.get(r2) is not None, _runs.get(r3) is not None))
    chk("H ★★ 回退要用的那条快照**保留**（不然这一步不可逆）",
        done2.get("kept_snapshot") == SB.get("id") and
        bool(ai_snap._store().manifest(SB["id"], SB["group"])),
        "kept=%r dropped=%r" % (done2.get("kept_snapshot"), done2.get("dropped_snapshots")))
    chk("H ★ 被删那两轮自己的快照清掉了（第三轮那条）",
        SC.get("id") in (done2.get("dropped_snapshots") or []) and
        not _man_ok(ai_snap, SC), "dropped=%r" % (done2.get("dropped_snapshots"),))
    chk("H ★★ 我自己存的那条快照**一条没动**",
        bool(ai_snap._store().manifest(SU["id"], SU.get("group"))), repr(SU.get("id")))
    gate = ai_snap.clean_ai(group=SU.get("group") or "", bid=SU["id"])
    chk("H ★★ 清理那道闸是**拦**不是劝：拿用户快照的 id 去 `clean_ai`，它直接拒绝",
        gate.get("ok") is True and (gate.get("skipped") or []) == [SU["id"]] and
        not (gate.get("deleted") or []) and bool(ai_snap._store().manifest(SU["id"], SU.get("group"))),
        json.dumps(gate, ensure_ascii=False)[:110])

    p1 = api.ai_session_plan(r1)
    chk("H 删到只剩一轮时，链也塌成一条（计划跟着变小）",
        p1.get("ok") is True and p1.get("chain_n") == 1 and (p1.get("delete_ids") or []) == [r1],
        "chain_n=%r delete=%r" % (p1.get("chain_n"), p1.get("delete_ids")))
    d1 = api.ai_session_truncate(r1, True)
    chk("H ★ 删链头 = 这条会话没了：回到第一轮开工前 + 记录清零",
        d1.get("ok") is True and f1.read_text(encoding="utf-8") == "v0\n" and _runs.get(r1) is None,
        "a.txt=%r msg=%s" % (f1.read_text(encoding="utf-8"), str(d1.get("msg"))[:60]))

    # ★ 纯问答那轮：没动过文件 ⇒ **不该回退**（回退反而会把别人后来的改动撤掉）
    rc = _mkrun("你是哪个大模型?", "", None, "2026-01-01 11:00:00", files=[], kind="chat")
    pc = api.ai_session_plan(rc)
    chk("H ★★ 纯问答那轮：不用回退（没改过文件），只删记录",
        pc.get("ok") is True and pc.get("chat_only") is True and pc.get("target") is None and
        any("没改过文件" in w for w in (pc.get("warnings") or [])),
        json.dumps({"chat_only": pc.get("chat_only"), "target": pc.get("target"),
                    "warnings": pc.get("warnings")}, ensure_ascii=False)[:150])
    f1.write_text("keep\n", encoding="utf-8")
    dc = api.ai_session_truncate(rc, True)
    chk("H ★★ 纯问答那轮删了，磁盘上**什么都没被回退**",
        dc.get("ok") is True and dc.get("restored_from") == "" and
        f1.read_text(encoding="utf-8") == "keep\n" and _runs.get(rc) is None,
        "restored=%r a.txt=%r" % (dc.get("restored_from"), f1.read_text(encoding="utf-8")))

    # ★ 自己那条快照没了（被清过 / 当时就没存上）⇒ 退到**再往前最近那条**，而且必须告警
    f1.write_text("m0\n", encoding="utf-8")
    SF = ai_snap.snapshot_before("有快照的一轮", wd)
    rf = _mkrun("有快照的一轮", "", SF, "2026-01-01 12:00:00")
    f1.write_text("m1\n", encoding="utf-8")
    rb = _mkrun("快照丢了的那轮", rf, {"id": "20200101-000000-0000",
                                       "group": SF.get("group") or ""}, "2026-01-01 12:05:00")
    pb = api.ai_session_plan(rb)
    chk("H ★★ 自己那条快照没了 ⇒ 退到**再往前最近那条**，并且把代价讲明白",
        (pb.get("target") or {}).get("id") == SF.get("id") and bool(pb.get("fallback")) and
        any("快照没了" in w for w in (pb.get("warnings") or [])),
        json.dumps({"target": (pb.get("target") or {}).get("id"), "fallback": bool(pb.get("fallback")),
                    "warnings": pb.get("warnings")}, ensure_ascii=False)[:160])
    # 连一条可用的镜像都没有（新建包那种）⇒ 明说"只能删记录"，不许假装回退了
    rn = _mkrun("连前面也没快照", "", None, "2026-01-01 13:00:00")
    pn = api.ai_session_plan(rn)
    chk("H ★★ 一条可回退的镜像都没有 ⇒ 明说只能删记录（不许假装回退了）",
        pn.get("ok") is True and pn.get("target") is None and pn.get("chat_only") is False and
        any("找不到任何可回退的镜像" in w for w in (pn.get("warnings") or [])),
        json.dumps(pn.get("warnings"), ensure_ascii=False)[:150])
    pbad = api.ai_session_plan("这条根本不存在")
    chk("H 找不到那条会话时明说（不是默默成功）",
        pbad.get("ok") is False and "找不到" in str(pbad.get("msg")), str(pbad.get("msg"))[:70])
    api.ai_session_truncate(rn, True)
    chk("H 收尾：现场清干净（临时目录最后整个删掉）", _runs.get(rn) is None, "")

    print()
    print("=" * 72)
    print()
    print("=" * 72)
    print("I：`V-281` 技能 = 一个包（`--` 开头、住 `:skill` 的数据目录）+ 要人点头 + 绑指纹")
    print("=" * 72)
    _SK = str(ROOT / "system" / "ai")
    if _SK not in sys.path:
        sys.path.insert(0, _SK)
    import skill_lib as ST                                                # noqa: E402
    import ai_tools as _tl                                                # noqa: E402
    import json as _json                                                  # noqa: E402
    import subprocess as _sp                                              # noqa: E402
    SKDIR = udata / "state" / "skill"          # 技能本体（= `:skill` 插件的数据目录）
    SEED = ROOT / "system" / "pkgs" / "skill" / "seed"

    def _skill(sid, pkg, entry="run.py", code="import json, sys\nprint('hi')\n",
               icon="<svg viewBox='0 0 24 24'><circle cx='12' cy='12' r='6'/></svg>",
               extra=None):
        d = SKDIR / sid
        d.mkdir(parents=True, exist_ok=True)
        if pkg is not None:
            (d / "pkg.json").write_text(
                pkg if isinstance(pkg, str) else _json.dumps(pkg, ensure_ascii=False, indent=1),
                encoding="utf-8")
        if entry:
            (d / entry).write_text(code, encoding="utf-8")
        if icon is not None:
            (d / "icon.svg").write_text(icon, encoding="utf-8")
        for fn, body in (extra or {}).items():
            (d / fn).write_text(body, encoding="utf-8")
        return d

    def _pkg(sid, desc="测试技能", why="因为测试要它", **kw):
        got = {"spec": 1, "id": sid, "kind": "task", "version": "1.0.0",
               "name": {"zh-CN": "测试 " + sid}, "desc": {"zh-CN": desc},
               "runner": "python", "entry": {"file": "run.py"},
               "params": [{"name": "x", "type": "string", "desc": "随便说点什么"}],
               "ai": {"expose": True, "why": why, "risk": "low", "timeout": 30}}
        for k, v in kw.items():
            if k in ("params", "ai", "entry", "kind", "runner"):
                got[k] = v
            else:
                got.setdefault("ai", {})[k] = v
        return got

    # ---- I-α：播种 + 扫描（技能就是一个包）
    _first = ST.ensure_seed()                    # 别的段跑 ai_start 时可能已经顺带播过
    import shutil as _sh
    _sh.rmtree(str(SKDIR / "--shot"), ignore_errors=True)
    (SKDIR / "--shot").mkdir(parents=True, exist_ok=True)   # 留个空壳，验"补缺"
    _back = ST.ensure_seed()
    chk("I ★ 出厂样例**播种**进技能目录（删了还能补回来，只补缺的）",
        "--shot" in _back and (SKDIR / "--shot" / "pkg.json").is_file()
        and (SEED / "--shot" / "pkg.json").is_file() and (SKDIR / "--shot" / "run.py").is_file(),
        "第一次=%s 补回来=%s" % (_first, _back))
    _all = ST.list_skills()
    _shot = _all.get("--shot") or {}
    chk("I ★★ 技能读的就是插件那套字段（pkg.json：name/desc/params/entry/runner/icon）",
        _shot.get("desc") and _shot.get("entry") == "run.py"
        and [p.get("name") for p in (_shot.get("params") or [])] == ["target", "out"]
        and bool(_shot.get("icon_svg")) and _shot.get("problems") == [],
        "desc=%r entry=%r 图标=%s 毛病=%s" % ((_shot.get("desc") or "")[:16], _shot.get("entry"),
                                            bool(_shot.get("icon_svg")), _shot.get("problems")))
    chk("I ★★ 详情页要的「为什么造它」在 `ai.why` 里（不是猜的）",
        "留证据" in (_shot.get("why") or ""), (_shot.get("why") or "")[:40])
    chk("I 技能 id 带 `--`、模型看到的名字是去掉 `--` 的那个",
        _shot.get("id") == "--shot" and _shot.get("name") == "shot", "%r / %r"
        % (_shot.get("id"), _shot.get("name")))
    chk("I ★ 播种来的**顺手带上授权**（否则装完就「待批准」，用户点不着）",
        _shot.get("allowed") is True and _shot.get("origin") == "seed",
        "allowed=%s origin=%s" % (_shot.get("allowed"), _shot.get("origin")))
    chk("I 时间/文件列表都给到了（详情页那几行）",
        bool(_shot.get("created")) and len(_shot.get("files") or []) >= 3
        and not any("__pycache__" in f["rel"] for f in _shot.get("files") or []),
        "创建=%s 文件=%s" % (_shot.get("created"),
                            [f["rel"] for f in _shot.get("files") or []]))

    # ---- I-β：插件那一层（`ai.expose = true` 的才进工具表）
    _names = sorted(ST.usable())
    chk("I ★★ 插件里声明了 `ai.expose: true` 的**自动进工具表**（账本 §16.3 那条）",
        "md5" in _names and "ip" in _names and "tree" in _names and "shot" in _names,
        "能用的：%s" % _names)
    chk("I ★ 没声明 expose 的插件**一个都不进**（装了 100 个包不该 100 个都能被 AI 调）",
        "bmi" not in _names and "exec" not in _names and "skill" not in _names,
        "bmi/exec/skill 都不在：%s" % _names)
    chk("I ★ 没声明 expose 的插件也**不算写坏**（不然技能页会列一堆「坏」的出厂插件）",
        not ({"bmi", "exec", "skill"} & set(ST.broken())),
        "broken 里有：%s" % sorted(ST.broken())[:8])
    chk("I 出厂插件（system 层）默认可用，技能撞名的那套不适用",
        (_all.get("md5") or {}).get("layer") == "system"
        and (_all.get("md5") or {}).get("allowed") is True, "")

    # ---- I-γ：写坏的东西要点名（哪一条都不许静默）
    _skill("badid", _pkg("badid"))                      # 不带 --
    _skill("--badkind", _pkg("--badkind", kind="app"))
    _skill("--noentry", _pkg("--noentry"), entry=None)
    _skill("--badjson", "{ 这不是 json")
    _skill("--html", _pkg("--html", runner="html", entry={"file": "index.html"}),
           entry="index.html", code="<html></html>")
    _skill("--scripty", _pkg("--scripty"),
           icon="<svg><script>alert(1)</script></svg>")
    _bad = ST.broken()
    chk("I ★★ id 不带 `--` 的**进不了工具表**（这是「不许污染插件 id」那条的落点）",
        "badid" in _bad and any("`--`" in p for p in _bad["badid"]["problems"]),
        "；".join(_bad.get("badid", {}).get("problems") or [])[:70])
    chk("I ★ kind 必须是 task（app 会开窗，AI 的手不该开窗）",
        any("kind" in p for p in _bad.get("--badkind", {}).get("problems") or []),
        "；".join(_bad.get("--badkind", {}).get("problems") or [])[:70])
    chk("I 入口不在 / JSON 写坏 / runner=html 都要点名",
        any("入口文件不在" in p for p in _bad.get("--noentry", {}).get("problems") or []) and
        any("JSON" in p for p in _bad.get("--badjson", {}).get("problems") or []) and
        any("当不了" in p for p in _bad.get("--html", {}).get("problems") or []),
        "｜".join((_bad.get(k, {}).get("problems") or ["?"])[0]
                  for k in ("--noentry", "--badjson", "--html"))[:110])
    _scr = ST.list_skills().get("--scripty") or {}
    chk("I ★★ 图标里的 `<script>` 会被洗掉（图标是它写的文件，界面要 innerHTML 进去）",
        _scr.get("icon_svg") == "" and any("icon.svg" in w for w in _scr.get("warns") or []),
        "icon_svg=%r 提醒=%s" % (_scr.get("icon_svg"), _scr.get("warns")))

    # ---- I-δ：要人点头 + 绑指纹
    _skill("--pending", _pkg("--pending", desc="还没允许的一只"))
    chk("I ★★ 没点头的**进不了工具表**、躺在「待批准」里",
        "pending" not in ST.usable() and "--pending" in ST.pending(),
        "usable=%s pending=%s" % (sorted(ST.usable()), sorted(ST.pending())))
    chk("I 点「允许」才进表（而且是按**模型看到的名字**进）",
        ST.allow("--pending").get("ok") is True and "pending" in ST.usable(), "")
    (SKDIR / "--pending" / "run.py").write_text("import json, sys\nprint('改过了')\n",
                                               encoding="utf-8")
    chk("I ★★★ 它事后改了入口 ⇒ 授权**自动作废**（不然批准就是永久通行证）",
        "pending" not in ST.usable() and "--pending" in ST.pending()
        and "又改过" in ST.list_skills()["--pending"]["why_allow"],
        ST.list_skills()["--pending"]["why_allow"])
    ST.allow("--pending")

    # ---- I-ε：真跑（参数 / cwd / 兄弟 import / 环境变量 / 炸掉 / 超时）
    _skill("--adder", _pkg("--adder", desc="把 a 和 b 加起来",
                           params=[{"name": "a", "type": "int", "desc": "第一个"},
                                   {"name": "b", "type": "int", "desc": "第二个"}]),
           code=("import json, sys, os\n"
                 "a = json.loads(sys.stdin.read() or '{}')\n"
                 "print('%d|%s' % (int(a.get('a') or 0) + int(a.get('b') or 0), os.path.basename(os.getcwd())))\n"))
    _skill("--sib", _pkg("--sib", desc="验同目录兄弟模块"),
           code="import helper\nprint('兄弟=' + helper.NAME)\n",
           extra={"helper.py": "NAME = '同目录也能 import'\n"})
    _skill("--boom", _pkg("--boom", desc="故意炸"), code="import sys\nprint('我不干了')\nsys.exit(3)\n")
    _skill("--slow", _pkg("--slow", desc="故意卡住", timeout=5),
           code="import time\nprint('开始等')\ntime.sleep(30)\n")
    for _n in ("--adder", "--sib", "--boom", "--slow"):
        ST.allow(_n)
    _o1 = ST.run("adder", {"a": "2", "b": "3"})
    chk("I ★★ 真跑起来了：参数进得去（stdin JSON）+ stdout 回到模型那边 + cwd = 技能目录",
        "退出码 0" in _o1 and "5|--adder" in _o1, repr(_o1)[:110])
    _o2 = ST.run("sib", {})
    chk("I ★ 自带运行时经 bootstrap ⇒ 技能里能 import 同目录的兄弟文件（跟包一个待遇）",
        "同目录也能 import" in _o2, repr(_o2)[:90])
    _o3 = ST.run("boom", {})
    chk("I ★ 技能自己炸了 ⇒ 回人话 + 退出码，不冒泡", "退出码 3" in _o3 and "我不干了" in _o3,
        repr(_o3)[:90])
    _o4 = ST.run("slow", {})
    chk("I ★ 卡住会被杀（超时那个数来自它 `ai.timeout`）", "超时" in _o4, repr(_o4)[:80])
    ST.allow("--adder", False)
    chk("I ★★ 撤销之后当场调不动（同意是**拦**不是提醒）",
        "没允许" in ST.run("adder", {"a": "1", "b": "1"}), "")
    ST.allow("--adder")
    _tools = _tl.Tools(workdir=str(pkgs), self_tools=ST.usable())
    chk("I ★★ 技能的参数类型照 pkg.json 来（int → integer，不再是清一色 string）",
        [t for t in _tl.tools_for(ST.usable()) if t["function"]["name"] == "adder"][0]
        ["function"]["parameters"]["properties"]["a"]["type"] == "integer", "")
    chk("I ★ 派发那条路也通（模型说 adder，宿主真去跑那只技能）",
        "9|--adder" in str(_tools.call("adder", {"a": "4", "b": "5"})),
        str(_tools.call("adder", {"a": "4", "b": "5"}))[:60])

    # ---- I-ζ：跑法照 runner 表（自带运行时那条链）
    _argv = (_all.get("--shot") or {}).get("argv") or []
    chk("I ★★ 跑法跟插件**同一张表**（system/runners.json）：自带运行时 + bootstrap 垫片",
        len(_argv) == 3 and "runtimes" in _argv[0] and _argv[0].endswith("python.exe")
        and _argv[1].endswith("bootstrap.py") and _argv[2].endswith("run.py"),
        "argv=%s" % _argv)
    chk("I ★ `{runtime}` 指的是 `runtimes/python/<版本>/`（第一版拼成 runtimes/python 就退化到系统 Python 了）",
        ST.runtime_dir("python").endswith("3.12") and
        (ROOT / "system" / "runtimes" / "python" / "3.12" / "python.exe").is_file(),
        ST.runtime_dir("python"))

    # ---- I-η：转成插件（**去掉 `--` 之后查冲突**，冲突了让用户自己起名字）
    _skill("--md5", _pkg("--md5", desc="故意和现有插件撞名"))
    _p1 = ST.promote_plan("--md5")
    chk("I ★★ 转插件：去掉 `--` 之后**先查 id 冲突**，撞了就明说、让用户自己起名字",
        _p1.get("can") is False and any("已经被占了" in p and "想一个新的" in p
                                        for p in _p1.get("problems") or []),
        "；".join(_p1.get("problems") or [])[:90])
    _p2 = ST.promote_plan("--md5", "md5-tool")
    chk("I 用户起的新名字（合法又没撞）⇒ 可以转", _p2.get("can") is True, "")
    _p3 = ST.promote_plan("--adder", "Bad Id!!")
    chk("I 新名字不合法（大写/空格）也要拦", _p3.get("can") is False, "；".join(_p3["problems"])[:60])
    _did = ST.promote("--adder", True, "adder-tool")
    _newdir = udata / "pkgs" / "adder-tool"
    chk("I ★★★ 真转过去了：目录搬到 user_data/pkgs、`pkg.json` 的 id 改成去掉 `--` 的新名字",
        _did.get("ok") is True and (_newdir / "pkg.json").is_file()
        and not (SKDIR / "--adder").exists()
        and _json.loads((_newdir / "pkg.json").read_text(encoding="utf-8"))["id"] == "adder-tool",
        str(_did.get("msg"))[:80])
    chk("I ★★ 转过去之后 AI **照样能用它**（它是插件了，但授权跟着走、expose 还在）",
        "adder-tool" in ST.usable() and "--adder" not in ST.list_skills(),
        "能用的：%s" % sorted(ST.usable()))
    _rmp = ST.rm("md5", True)
    chk("I ★★ 技能层**不删插件**（卸插件是 `moss --remove` 的事）——插件行拦下",
        _rmp.get("ok") is False and "插件" in str(_rmp.get("msg"))
        and (ROOT / "system" / "pkgs" / "md5" / "pkg.json").is_file(),
        str(_rmp.get("msg"))[:70])
    chk("I ★ 播种来的 `--shot` 是**你的**（能改能删能转），只是详情里标着「出厂样例」",
        ST.promote_plan("--shot").get("can") is True
        and (ST.list_skills().get("--shot") or {}).get("origin") == "seed",
        "plan.can=%s origin=%s" % (ST.promote_plan("--shot").get("can"),
                                   (ST.list_skills().get("--shot") or {}).get("origin")))

    # ---- I-θ：`:skill` 插件本身（命令行 + 内嵌协议）
    _env = dict(os.environ)
    _env.update({"MOSS_HOME": str(ROOT), "MOSS_USER_DATA_DIR": str(udata),
                 "MOSS_PLUGIN_DATA_DIR": str(SKDIR), "PYTHONIOENCODING": "utf-8"})
    _env.pop("MOSS_UI_EMBED", None)
    for _k in ("MOSS_PKG_PARAMS", "MOSS_ARGS", "MOSS_PKG_ID"):
        _env.pop(_k, None)
    _py = str(ROOT / "system" / "runtimes" / "python" / "3.12" / "python.exe")
    _main = str(ROOT / "system" / "pkgs" / "skill" / "main.py")
    _boot = str(ROOT / "system" / "bootstrap.py")
    _r = _sp.run([_py, _boot, _main, "list"], capture_output=True, text=True,
                 encoding="utf-8", errors="replace", env=_env, timeout=120)
    chk("I ★★ `moss :skill list` 能跑（终端里也能用，不只是界面）",
        _r.returncode == 0 and "--shot" in (_r.stdout or "") and "--pending" in (_r.stdout or ""),
        ((_r.stdout or "") + (_r.stderr or ""))[:110].replace("\n", " "))
    _r2 = _sp.run([_py, _boot, _main, "show", "--shot"], capture_output=True, text=True,
                  encoding="utf-8", errors="replace", env=_env, timeout=120)
    chk("I ★ 详情那几行（为什么造它 / 状态 / 时间 / 文件数）命令行里也给",
        "为什么" in (_r2.stdout or "") and "创建" in (_r2.stdout or "")
        and "文件" in (_r2.stdout or ""), (_r2.stdout or "").splitlines()[:2])
    _env2 = dict(_env, MOSS_UI_EMBED="1")
    _r3 = _sp.run([_py, _boot, _main], input='{"id":7,"method":"list","params":{}}\n',
                  capture_output=True, text=True, encoding="utf-8", errors="replace",
                  env=_env2, timeout=120)
    _line = [l for l in (_r3.stdout or "").splitlines() if l.strip().startswith("{")]
    _got3 = _json.loads(_line[0]) if _line else {}
    chk("I ★★ 内嵌模式（宿主「界面」选项卡那条路）说的是 JSON 行协议",
        _got3.get("id") == 7 and _got3.get("ok") is True
        and isinstance((_got3.get("result") or {}).get("skills"), list),
        (_line[0][:100] if _line else (_r3.stderr or "")[:100]))
    _r4 = _sp.run([_py, _boot, _main], input='{"id":8,"method":"nope","params":{}}\n',
                  capture_output=True, text=True, encoding="utf-8", errors="replace",
                  env=_env2, timeout=120)
    chk("I 内嵌协议里瞎调一个方法 ⇒ 明说没有这个方法（不是静默）",
        "没有这个方法" in (_r4.stdout or ""), (_r4.stdout or "")[:90])

    # ---- I-ι：那两道闸
    _gate = _tl.Tools(workdir=str(pkgs))
    _g1 = str(_gate.call("run_moss", {"args": ":skill allow --pending"}))
    chk("I ★★★ `run_moss(\":skill allow …\")` **被拒**（不然 AI 能自己批准自己的技能）",
        "拒绝" in _g1 and ":skill" in _g1, _g1[:100])
    for _verb in ("rm --pending", "promote --pending", "revoke --pending"):
        if "拒绝" not in str(_gate.call("run_moss", {"args": ":skill " + _verb})):
            chk("I `:skill %s` 也该被拒" % _verb, False, "")
    chk("I ★ 但 `:skill list` / `show` 这类不含「决定」的照旧随便用",
        "拒绝" not in str(_gate.call("run_moss", {"args": ":skill list"})), "")
    chk("I ★★ 写权限只多开这一处：技能目录能写、出厂插件目录和 core 写不了",
        ai_edits.check_writable(SKDIR / "--x" / "pkg.json") is None and
        ai_edits.check_writable(ROOT / "system" / "pkgs" / "skill" / "core.py") is not None and
        "只允许写" in str(ai_edits.check_writable(ROOT / "core" / "cli.py")), "")
    chk("I 能**读**自己的技能（不然没法改它）",
        ai_edits.check_readable(SKDIR / "--shot" / "pkg.json") is None, "")

    # ---- I-κ：界面那一份数据（AI 页那行 + `:skill` 界面都用它）
    _sum = ST.summary()
    chk("I ★ 界面要的三堆都给全了（skills / from_pkgs / broken + 目录 + 能用的数量）",
        set(["ok", "skills", "from_pkgs", "broken", "dirs", "n_usable", "n_pending"])
        <= set(_sum) and _sum["n_pending"] >= 1, "键=%s 待批准=%s" % (sorted(_sum), _sum["n_pending"]))
    _row = [r for r in _sum["skills"] if r["id"] == "--shot"][0]
    chk("I ★ 每只技能都带图标正文（墙上那排彩色图标）+ 为什么造它 + 时间 + 文件列表",
        bool(_row["icon_svg"]) and bool(_row["why"]) and bool(_row["created"])
        and isinstance(_row["files"], list) and len(_row["files"]) >= 3, "")

    shutil.rmtree(tmp, ignore_errors=True)
    print()
    print("=" * 72)
    badN = [r for r in RES if not r[1]]
    print("结论：%s（%d 条，失败 %d）" % ("✅ 全过" if not badN else "✗ 有不对的", len(RES), len(badN)))
    return 0 if not badN else 1


if __name__ == "__main__":
    sys.exit(main())
