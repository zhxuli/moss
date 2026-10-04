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
        FakeClient.INSTANCES.append(self)
        # ★ `V-252`：第三个参数是**模型名**（宿主 `Client(base_url, key, model)`）——
        #   以前这里写死 "fake-model"，于是"顶栏选了别的模型"这条根本验不出来。
        self.model = args[2] if len(args) > 2 else (kw.get("model") or "fake-model")
        self.base_url = args[0] if args else kw.get("base_url", "")
        self.api_key = args[1] if len(args) > 1 else kw.get("api_key", "")

    @classmethod
    def from_env(cls, **kw):
        return cls()

    def chat(self, messages, tools=None, stop_check=None, on_wait=None):
        # `V-242`：签名跟真 client 对上（多出来的两个参数是"能不能中途停"用的）
        self.seen.append(1)
        self.msgs.append(json.loads(json.dumps(messages, ensure_ascii=False)))
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
        def chat(self, messages, tools=None, stop_check=None, on_wait=None):
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

    shutil.rmtree(tmp, ignore_errors=True)
    print()
    print("=" * 72)
    badN = [r for r in RES if not r[1]]
    print("结论：%s（%d 条，失败 %d）" % ("✅ 全过" if not badN else "✗ 有不对的", len(RES), len(badN)))
    return 0 if not badN else 1


if __name__ == "__main__":
    sys.exit(main())
