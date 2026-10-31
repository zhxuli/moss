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
import subprocess
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
    import ai_mode as MO0                                                 # noqa: E402
    import ai_snap                                                        # noqa: E402

    spec = importlib.util.spec_from_file_location("moss_ui_main_aipane", UI / "main.py")
    M = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(M)
    api = M.Api()
    # ★ `V-316`：权限是**一份清单**（读/写两个勾）。这个探针里好几个用例拿 `pkgs` 根当
    #   "干活的地方"（原来那种"整个项目区"用法）—— 新模型下那要**显式在清单里**，
    #   所以先把它加进去（等价于用户把那一行勾上了）。
    MO0.allow_add(str(pkgs), read=True, write=True, why="探针：整个项目区")

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

    # ★ `V-386`：用户真报的那个 —— **配了两家，AI 页的模型下拉却永远只有第一家的**。
    #   根因：`ai_info` 只问宿主"当前那组"，而宿主那份 JSON 其实**早就**把每组的摘要
    #   （`summary`）一起给了。现在从它把**每一组**的模型都带出来（下拉按家分组）。
    cfg_two = tmp / "fake_cfg_two.py"
    cfg_two.write_text(
        "import json\nprint(json.dumps({'ok': True, 'active': '假组', 'profile': '假组',\n"
        "  'params': {'base_url': 'https://fake.example/v1', 'api_key': 'sk-假的key',\n"
        "             'model': ['fake-model', 'fake-model-2']}, 'profiles': ['假组', '假二组'],\n"
        "  'summary': {\n"
        "    '假组': {'base_url': 'https://fake.example/v1', 'model': ['fake-model'],\n"
        "             'has_key': True},\n"
        "    '假二组': {'base_url': 'https://other.example/v1', 'model': ['other-model'],\n"
        "               'has_key': False}}}))\n",
        encoding="utf-8")
    M.HOST = [sys.executable, str(cfg_two)]
    M._AI_CFG.update({"t0": 0.0, "got": None})
    two = api.ai_info(str(pkgs), True)
    names = [p.get("name") for p in (two.get("providers") or [])]
    chk("A ★★ 配了两家时两家的模型都给到了（以前只给当前那家，下拉永远只有第一家）",
        names == ["假组", "假二组"],
        json.dumps(two.get("providers"), ensure_ascii=False))
    chk("A 当前那组排最前、并被 profile 标出来（下拉第一眼就是正在用的那家）",
        (two.get("providers") or [{}])[0].get("name") == "假组"
        and two.get("profile") == "假组",
        "profile=%r" % two.get("profile"))
    chk("A 没填 key 的那家也照样列（optgroup 上标「没填 key」，不是藏起来）",
        any(p.get("name") == "假二组" and p.get("has_key") is False
            for p in (two.get("providers") or [])), "")
    M.HOST = [sys.executable, str(cfg_ok)]
    M._AI_CFG.update({"t0": 0.0, "got": None})

    print()
    print("=" * 72)
    print("A2：`V-387`「让 AI 定一个包」—— id / 名字 / 介绍 / 第一句任务")
    print("=" * 72)
    # ★ 这一段比下面 C 段早，所以得**先把假模型换上**（`ai_client.Client = FakeClient`
    #   在 C 段才做）—— 否则这几次调用会真的往 `fake.example` 发请求。
    api._ai_mods()
    sys.modules["ai_client"].Client = FakeClient
    # 假模型照"我们要的格式"回一段 JSON（真模型偶尔会包一层 ```，所以下面还测了那种）
    SCRIPT[:] = [{"text": '{"id":"shot-archive","name":"截图归档",'
                          '"desc":"把剪贴板里的截图按日期存起来，顺手把路径复制回来",'
                          '"task":"做一个截图归档包：按日期分目录保存，并复制路径"}',
                  "tool_calls": [], "usage": {}, "native": True,
                  "message": {"role": "assistant", "content": None}}]
    sug = api.ai_suggest_pkg("把剪贴板截图按日期归档")
    chk("A2 一句话就换回四样（id / 名字 / 介绍 / 任务）",
        sug.get("ok") and sug.get("id") == "shot-archive" and sug.get("name") == "截图归档"
        and "按日期" in str(sug.get("desc")) and sug.get("task"),
        "%s / %s" % (sug.get("id"), sug.get("name")))
    chk("A2 它是**一次最小请求**（不带工具、不建 loop）",
        not FakeClient.INSTANCES[-1].tools_seen[-1],
        "tools=%s" % (FakeClient.INSTANCES[-1].tools_seen[-1],))
    # id 撞了要自动加后缀（不然建包当场失败）
    _real_taken = api._pkg_ids_taken
    api._pkg_ids_taken = lambda: {"shot-archive"}
    sug2 = api.ai_suggest_pkg("再来一个一样的")
    chk("A2 id 撞了自动加后缀", sug2.get("id") == "shot-archive-2", sug2.get("id"))
    api._pkg_ids_taken = _real_taken
    # V-424: 24-char base must still get a real suffix.
    _long_id = "a" * 24
    SCRIPT[:] = [{"text": '{"id":"%s","name":"long","desc":"test","task":"do it"}' % _long_id,
                  "tool_calls": [], "usage": {}, "native": True,
                  "message": {"role": "assistant", "content": None}}]
    api._pkg_ids_taken = lambda: {_long_id}
    _sug_long = api.ai_suggest_pkg("long id collision")
    api._pkg_ids_taken = _real_taken
    # V-424: factory package ids must count as taken even if the payload table is stale.
    _sys_ids = set()
    _sys_root = ROOT / "system" / "pkgs"
    if _sys_root.is_dir():
        for _d in _sys_root.iterdir():
            try:
                _man = json.loads((_d / "pkg.json").read_text(encoding="utf-8"))
                if isinstance(_man, dict) and _man.get("id"):
                    _sys_ids.add(str(_man["id"]).lower())
            except Exception:
                pass
    _taken_now = set(api._pkg_ids_taken())
    chk("A2 ★★ 已有 system 包 id 也算被占用（新建不能静默遮蔽出厂包）",
        bool(_sys_ids) and _sys_ids.issubset(_taken_now),
        "system=%d missing=%s" % (len(_sys_ids), sorted(_sys_ids - _taken_now)[:5]))
    chk("A2 ★★ 24 字符 id 撞了也必须真的加后缀（不能截掉后返回原 id）",
        _sug_long.get("ok") and _sug_long.get("id") != _long_id
        and _sug_long.get("id") not in {_long_id},
        "%r -> %r" % (_long_id, _sug_long.get("id")))
    # 模型给的是中文 / 大写 / 带空格 —— 必须掰成合法 id（不能直接信它）
    SCRIPT[:] = [{"text": '```json\n{"id":"我的 截图工具","name":"截图工具","desc":"存图","task":"做它"}\n```',
                  "tool_calls": [], "usage": {}, "native": True,
                  "message": {"role": "assistant", "content": None}}]
    sug3 = api.ai_suggest_pkg("随便")
    _id3 = str(sug3.get("id") or "")
    _id_ok = (bool(_id3) and _id3[0].isalpha() and _id3[0].islower()
              and all(c.islower() or c.isdigit() or c in "-_" for c in _id3))
    chk("A2 模型给中文 id 时当场掰成合法 id（还从 ``` 里抠得出 JSON）",
        sug3.get("ok") and _id_ok, sug3.get("id"))
    # 没配 AI 时说清原因，不许假装成功
    M.HOST = [sys.executable, str(cfg_bad)]
    M._AI_CFG.update({"t0": 0.0, "got": None})
    bad_sug = api.ai_suggest_pkg("做个东西")
    chk("A2 没配 AI / 读不到配置时如实说（不假装定了）",
        bad_sug.get("ok") is False and str(bad_sug.get("msg")), bad_sug.get("msg"))
    M.HOST = [sys.executable, str(cfg_ok)]
    M._AI_CFG.update({"t0": 0.0, "got": None})
    # ---- 建包：`new_pkg` 必须把 id / 名字 / 介绍 都交给宿主（列表式 argv，不跟引号较劲）----
    #   ★ 断言落在**宿主真收到的 argv** 上（假宿主把它写进一个 UTF-8 文件），而不是回读
    #     控制台文字 —— 那要跟子进程的 stdout 编码较劲（cp936 / UTF-8 一错就假红）。
    host_new = tmp / "fake_new.py"
    host_new.write_text(
        "import json, sys\n"
        "sys.stdout.reconfigure(encoding='utf-8')\n"
        "open(__file__ + '.args', 'w', encoding='utf-8').write("
        "json.dumps(sys.argv[1:], ensure_ascii=False))\n"
        "print('OK')\n", encoding="utf-8")
    M.HOST = [sys.executable, str(host_new)]
    nr = api.new_pkg("demo-pkg", "截图归档", "一句话介绍")
    _args = []
    try:
        _args = json.loads(Path(str(host_new) + ".args").read_text(encoding="utf-8"))
    except Exception as exc:                                              # noqa: BLE001
        _args = ["(读不到宿主收到的 argv: %s)" % exc]
    chk("A2 建包把 id / 名字 / 介绍 一起给了宿主（argv 列表，中文原样）",
        nr.get("ok") and _args[:2] == ["--new", "demo-pkg"]
        and "name=截图归档" in _args and "desc=一句话介绍" in _args, _args)
    er = api.new_pkg("", "x", "y")
    chk("A2 没 id 时不瞎跑（直接回一句人话）", er.get("ok") is False and er.get("msg"), er.get("msg"))
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
    _rows = _runs.list_runs(5, everywhere=True)
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
    _crow = [r for r in _runs.list_runs(5, everywhere=True) if r.get("id") == _cid]
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
    # ★ `V-307`：停止**不再是「停在下一轮」**（用户报的「点了停止还卡二十分钟」就是它）——
    #   现在回的话必须说清「已停止 / 立刻」，而且断言的**行为**在下面两条（真收工 + 真杀掉子进程）。
    chk("D ai_stop 回了一句人话（说清「已停止」，不再说「停在下一轮」）",
        stopped.get("ok") is True and "停止" in str(stopped.get("msg")),
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
    print()
    print("=" * 72)
    print("I：`V-281`/`V-284` 技能 = 一个包（住 `:skill` 的数据目录）+ 要人点头 + 绑指纹")
    print("=" * 72)
    _SK = str(ROOT / "system" / "ai")
    if _SK not in sys.path:
        sys.path.insert(0, _SK)
    import skill_lib as ST                                                # noqa: E402
    import ai_tools as _tl                                                # noqa: E402
    import json as _json                                                  # noqa: E402
    import subprocess as _sp                                              # noqa: E402
    SKDIR = udata / "state" / "skill"
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

    # ---- I-α：老名字迁移 + 扫描（`V-288`：出厂样例**不再自动播种**了）
    import shutil as _sh
    _sh.rmtree(str(SKDIR / "shot"), ignore_errors=True)
    (SKDIR / "--old").mkdir(parents=True, exist_ok=True)     # 老一轮留下的带 `--` 的目录
    (SKDIR / "--old" / "pkg.json").write_text(
        _json.dumps(_pkg("--old", desc="老名字"), ensure_ascii=False), encoding="utf-8")
    (SKDIR / "--old" / "run.py").write_text("print('old')\n", encoding="utf-8")
    _mig = ST.migrate_dashes()
    chk("I ★★ 老的 `--名字` 会被**改名**成不带前缀的（你说不用加 `--` 了，已有的得跟着走）",
        any("--old" in x for x in _mig) and (SKDIR / "old" / "pkg.json").is_file()
        and not (SKDIR / "--old").exists(),
        "迁移：%s" % _mig)
    # ★★ `V-288`（你 2026-10-05 定的）：**「补回出厂样例」这个功能三处一起删了** ——
    #    界面那颗按钮、`moss :skill seed`、以及"列技能时自动把缺的补回来"。
    #    样例只留在 `system/pkgs/skill/seed/shot/`，当"照它抄"的样板。
    #    所以这里**手动抄一份**进数据目录来当活样板，然后钉住"删了就是删了、不会自己回来"。
    chk("I ★★ 「补回出厂样例」这个功能**真的没了**（`skill_lib` 里不再有 `ensure_seed`）",
        not hasattr(ST, "ensure_seed"), "还有 ensure_seed 吗＝%s" % hasattr(ST, "ensure_seed"))
    _sh.copytree(str(SEED / "shot"), str(SKDIR / "shot"), dirs_exist_ok=True)
    ST.allow("shot", True)                          # 抄来的也算你的：得允许才进工具表
    _am = ST.allowed_map()
    _am.setdefault("shot", {})["from"] = "seed"     # 标一下来路（详情页那颗「出厂样例」标签）
    ST._save_allow(_am)
    _sh.rmtree(str(SKDIR / "shot"), ignore_errors=True)   # 删了再列一次：不许自己回来
    _back = "shot" in ST.list_skills()
    _sh.copytree(str(SEED / "shot"), str(SKDIR / "shot"), dirs_exist_ok=True)
    chk("I ★★★ 删掉的样例**不会**被自动补回来（`list_skills()` 里那句自动播种已经去掉）",
        not _back and (SKDIR / "shot" / "pkg.json").is_file()
        and (SEED / "shot" / "pkg.json").is_file(),
        "删完再列一遍，它回来了吗＝%s（应当 False）" % _back)
    _all = ST.list_skills()
    _shot = _all.get("shot") or {}
    chk("I ★★ 技能读的就是插件那套字段（pkg.json：name/desc/params/entry/runner/icon）",
        _shot.get("desc") and _shot.get("entry") == "run.py"
        and [p.get("name") for p in (_shot.get("params") or [])] == ["target", "out"]
        and bool(_shot.get("icon_svg")) and _shot.get("problems") == [],
        "desc=%r entry=%r 图标=%s 毛病=%s" % ((_shot.get("desc") or "")[:14], _shot.get("entry"),
                                            bool(_shot.get("icon_svg")), _shot.get("problems")))
    chk("I ★★ 详情页要的「为什么造它」在 `ai.why` 里；时间/文件列表也给到了",
        "留证据" in (_shot.get("why") or "") and bool(_shot.get("created"))
        and len(_shot.get("files") or []) >= 3
        and not any("__pycache__" in f["rel"] for f in _shot.get("files") or []),
        "why=%s 创建=%s 文件=%s" % ((_shot.get("why") or "")[:18], _shot.get("created"),
                                   [f["rel"] for f in _shot.get("files") or []]))
    chk("I ★ 允许过 / 标了来路（`origin`）的技能才进工具表；详情页那颗「出厂样例」标签靠它",
        _shot.get("allowed") is True and _shot.get("origin") == "seed",
        "allowed=%s origin=%s" % (_shot.get("allowed"), _shot.get("origin")))

    # ---- I-β：**技能和插件两个圈子不互相出现**（`V-284`）
    _names = sorted(ST.usable())
    _sum_keys = sorted(ST.summary())
    chk("I ★★★ 插件**不再进 AI 的工具表**（AI 想用插件走 `run_moss(\":包名 …\")` 那条老路）",
        "md5" not in _names and "ip" not in _names and "tree" not in _names
        and "shot" in _names,
        "能用的：%s" % _names)
    chk("I ★★ `summary()` 里也**没有** `from_pkgs` 了（插件不出现在技能那一页）",
        "from_pkgs" not in _sum_keys and "skills" in _sum_keys,
        "键=%s" % _sum_keys)
    chk("I ★ AI 照样能调插件 —— 那是 `run_moss` 的事（跟工具表无关）",
        "run_moss" in [t["function"]["name"] for t in _tl.TOOLS], "")

    # ---- I-γ：写坏的东西要点名
    _skill("Bad_Id", _pkg("Bad_Id"))                    # 大写开头：id 不合法
    _skill("badkind", _pkg("badkind", kind="app"))
    _skill("noentry", _pkg("noentry"), entry=None)
    _skill("badjson", "{ 这不是 json")
    _skill("html", _pkg("html", runner="html", entry={"file": "index.html"}),
           entry="index.html", code="<html></html>")
    _skill("scripty", _pkg("scripty"), icon="<svg><script>alert(1)</script></svg>")
    _bad = ST.broken()
    chk("I ★★ id 不合法（大写/数字开头）进不了工具表（跟插件 id 同一规格）",
        "Bad_Id" in _bad and any("小写字母开头" in p for p in _bad["Bad_Id"]["problems"]),
        "；".join(_bad.get("Bad_Id", {}).get("problems") or [])[:70])
    chk("I ★ kind 必须是 task（app 会开窗，AI 的手不该开窗）",
        any("kind" in p for p in _bad.get("badkind", {}).get("problems") or []),
        "；".join(_bad.get("badkind", {}).get("problems") or [])[:70])
    chk("I 入口不在 / JSON 写坏 / runner=html 都要点名",
        any("入口文件不在" in p for p in _bad.get("noentry", {}).get("problems") or []) and
        any("JSON" in p for p in _bad.get("badjson", {}).get("problems") or []) and
        any("当不了" in p for p in _bad.get("html", {}).get("problems") or []),
        "｜".join((_bad.get(k, {}).get("problems") or ["?"])[0]
                  for k in ("noentry", "badjson", "html"))[:110])
    _scr = ST.list_skills().get("scripty") or {}
    chk("I ★★ 图标里的 `<script>` 会被洗掉（图标是它写的文件，界面要 innerHTML 进去）",
        _scr.get("icon_svg") == "" and any("icon.svg" in w for w in _scr.get("warns") or []),
        "icon_svg=%r 提醒=%s" % (_scr.get("icon_svg"), _scr.get("warns")))

    # ---- I-δ：要人点头 + 绑指纹
    _skill("pending", _pkg("pending", desc="还没允许的一只"))
    chk("I ★★ 没点头的**进不了工具表**、躺在「待批准」里",
        "pending" not in ST.usable() and "pending" in ST.pending(),
        "usable=%s pending=%s" % (sorted(ST.usable()), sorted(ST.pending())))
    ST.allow("pending")
    chk("I 点「允许」才进表", "pending" in ST.usable(), "")
    (SKDIR / "pending" / "run.py").write_text("import json, sys\nprint('改过了')\n",
                                             encoding="utf-8")
    chk("I ★★★ 它事后改了入口 ⇒ 授权**自动作废**（不然批准就是永久通行证）",
        "pending" not in ST.usable() and "pending" in ST.pending()
        and "又改过" in ST.list_skills()["pending"]["why_allow"],
        ST.list_skills()["pending"]["why_allow"])
    ST.allow("pending")

    # ---- I-ε：真跑（参数 / cwd / 兄弟 import / 炸掉 / 超时）
    _skill("adder", _pkg("adder", desc="把 a 和 b 加起来",
                         params=[{"name": "a", "type": "int", "desc": "第一个"},
                                 {"name": "b", "type": "int", "desc": "第二个"}]),
           code=("import json, sys, os\n"
                 "a = json.loads(sys.stdin.read() or '{}')\n"
                 "print('%d|%s' % (int(a.get('a') or 0) + int(a.get('b') or 0), os.path.basename(os.getcwd())))\n"))
    _skill("sib", _pkg("sib", desc="验同目录兄弟模块"),
           code="import helper\nprint('兄弟=' + helper.NAME)\n",
           extra={"helper.py": "NAME = '同目录也能 import'\n"})
    _skill("boom", _pkg("boom", desc="故意炸"), code="import sys\nprint('我不干了')\nsys.exit(3)\n")
    _skill("slow", _pkg("slow", desc="故意卡住", timeout=5),
           code="import time\nprint('开始等')\ntime.sleep(30)\n")
    for _n in ("adder", "sib", "boom", "slow"):
        ST.allow(_n)
    _o1 = ST.run("adder", {"a": "2", "b": "3"})
    chk("I ★★ 真跑起来了：参数进得去（stdin JSON）+ stdout 回到模型那边 + cwd = 技能目录",
        "退出码 0" in _o1 and "5|adder" in _o1, repr(_o1)[:110])
    _o2 = ST.run("sib", {})
    chk("I ★ 自带运行时经 bootstrap ⇒ 技能里能 import 同目录的兄弟文件（跟包一个待遇）",
        "同目录也能 import" in _o2, repr(_o2)[:90])
    _o3 = ST.run("boom", {})
    chk("I ★ 技能自己炸了 ⇒ 回人话 + 退出码，不冒泡", "退出码 3" in _o3 and "我不干了" in _o3,
        repr(_o3)[:90])
    _o4 = ST.run("slow", {})
    chk("I ★ 卡住会被杀（超时那个数来自它 `ai.timeout`）", "超时" in _o4, repr(_o4)[:80])
    ST.allow("adder", False)
    chk("I ★★ 撤销之后当场调不动（同意是**拦**不是提醒）",
        "没允许" in ST.run("adder", {"a": "1", "b": "1"}), "")
    ST.allow("adder")
    _tools = _tl.Tools(workdir=str(pkgs), self_tools=ST.usable())
    chk("I ★★ 技能的参数类型照 pkg.json 来（int → integer，不再是清一色 string）",
        [t for t in _tl.tools_for(ST.usable()) if t["function"]["name"] == "adder"][0]
        ["function"]["parameters"]["properties"]["a"]["type"] == "integer", "")
    chk("I ★ 派发那条路也通（模型说 adder，宿主真去跑那只技能）",
        "9|adder" in str(_tools.call("adder", {"a": "4", "b": "5"})),
        str(_tools.call("adder", {"a": "4", "b": "5"}))[:60])
    _argv = (_all.get("shot") or {}).get("argv") or []
    chk("I ★★ 跑法跟插件**同一张表**（runners.json）：自带运行时 + bootstrap 垫片",
        len(_argv) == 3 and "runtimes" in _argv[0] and _argv[0].endswith("python.exe")
        and _argv[1].endswith("bootstrap.py") and _argv[2].endswith("run.py"),
        "argv=%s" % _argv)

    # ---- I-ζ：转成插件（查 id 冲突）
    _skill("md5", _pkg("md5", desc="故意和现有插件撞名"))
    _p1 = ST.promote_plan("md5")
    chk("I ★★ 转插件：**先查 id 冲突**，撞了就明说、让用户自己起名字",
        _p1.get("can") is False and any("已经被占了" in p and "想一个新的" in p
                                        for p in _p1.get("problems") or []),
        "；".join(_p1.get("problems") or [])[:90])
    chk("I 用户起的新名字（合法又没撞）⇒ 可以转",
        ST.promote_plan("md5", "md5-tool").get("can") is True, "")
    chk("I 新名字不合法（大写/空格）也要拦",
        ST.promote_plan("adder", "Bad Id!!").get("can") is False, "")
    _did = ST.promote("adder", True, "adder-tool")
    _newdir = udata / "pkgs" / "adder-tool"
    chk("I ★★★ 真转过去了：目录搬到 user_data/pkgs、`pkg.json` 的 id 改成新名字",
        _did.get("ok") is True and (_newdir / "pkg.json").is_file()
        and not (SKDIR / "adder").exists()
        and _json.loads((_newdir / "pkg.json").read_text(encoding="utf-8"))["id"] == "adder-tool",
        str(_did.get("msg"))[:80])
    chk("I ★★ 转过去之后它**不再是技能**（技能这一页只剩技能；AI 要用它走 run_moss）",
        "adder-tool" not in ST.list_skills() and "adder" not in ST.usable(),
        "技能：%s" % sorted(ST.list_skills()))

    # ---- I-η：`:skill` 插件（命令行 + 内嵌协议）
    _env = dict(os.environ)
    _env.update({"MOSS_HOME": str(ROOT), "MOSS_USER_DATA_DIR": str(udata),
                 "MOSS_PLUGIN_DATA_DIR": str(SKDIR), "PYTHONIOENCODING": "utf-8"})
    for _k in ("MOSS_UI_EMBED", "MOSS_PKG_PARAMS", "MOSS_ARGS", "MOSS_PKG_ID",
               "MOSS_INTERACTIVE"):
        _env.pop(_k, None)
    _py = str(ROOT / "system" / "runtimes" / "python" / "3.12" / "python.exe")
    _main = str(ROOT / "system" / "pkgs" / "skill" / "main.py")
    _boot = str(ROOT / "system" / "bootstrap.py")

    def _cli(*args, env=None):
        """跑一次 `:skill` 的命令行。

        ★ 超时要**当成一条 FAIL 报出来**，不能让它把整个探针崩掉：不带参数那条路以前会
          `core.gui()` 去开窗口（探针里就会一直挂到超时）—— 那正是"AI 一调就弹窗口"那个 bug，
          得看得见、说得清（第一版就是在这里崩的，整段结论都没打出来）。
        """
        try:
            return _sp.run([_py, _boot, _main] + list(args), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=env or _env, timeout=60)
        except _sp.TimeoutExpired:
            return _sp.CompletedProcess(args=list(args), returncode=-9,
                                        stdout="（超时没回 —— 它大概去开窗口了）", stderr="")

    _r = _cli()
    chk("I ★★★ **不带参数就是打用法 + 列表**（命令行/AI 调这一下**不开窗** —— 你报的「一调就弹窗口」）",
        _r.returncode == 0 and "moss :skill" in (_r.stdout or "")
        and "skill" in (_r.stdout or "") and "用法" in (_r.stdout or ""),
        ((_r.stdout or "") + (_r.stderr or "")).splitlines()[:1])
    _r2 = _cli("help")
    chk("I ★ `moss :skill help` 也打那一份（`--help` 同理）",
        "用法" in (_r2.stdout or "") and "doc" in (_r2.stdout or ""), "")
    _r3 = _cli("doc", "shot")
    chk("I ★★ `moss :skill doc <名字>` = 这只技能**自己的说明书**（AI 靠它看怎么用）",
        _r3.returncode == 0 and "shot" in (_r3.stdout or ""), (_r3.stdout or "")[:60])
    _r4 = _cli("run", "shot", "target=这个窗口不存在---")
    chk("I ★★ `run <名字> k=v …` 参数真进得去（跟 AI 调它走同一条路）",
        _r4.returncode == 0 and "这个窗口不存在---" in (_r4.stdout or ""),
        ((_r4.stdout or "").splitlines() or [""])[0][:60])
    _r5 = _cli("show", "shot")
    chk("I ★ 详情那几行（为什么造它 / 状态 / 时间 / 文件数 / 看说明的提示）命令行里也给",
        "为什么" in (_r5.stdout or "") and "创建" in (_r5.stdout or "")
        and "doc" in (_r5.stdout or ""), (_r5.stdout or "").splitlines()[:1])
    _env2 = dict(_env, MOSS_UI_EMBED="1")
    _r6 = _sp.run([_py, _boot, _main], input='{"id":7,"method":"list","params":{}}\n',
                  capture_output=True, text=True, encoding="utf-8", errors="replace",
                  env=_env2, timeout=120)
    _line = [l for l in (_r6.stdout or "").splitlines() if l.strip().startswith("{")]
    _got6 = _json.loads(_line[0]) if _line else {}
    chk("I ★★ 内嵌模式（宿主「界面」选项卡那条路）说的是 JSON 行协议，且**只有技能**",
        _got6.get("id") == 7 and _got6.get("ok") is True
        and isinstance((_got6.get("result") or {}).get("skills"), list)
        and "from_pkgs" not in (_got6.get("result") or {}),
        (_line[0][:90] if _line else (_r6.stderr or "")[:90]))

    # ---- I-θ：那两道闸
    _gate = _tl.Tools(workdir=str(pkgs))
    _g1 = str(_gate.call("run_moss", {"args": ":skill allow pending"}))
    chk("I ★★★ `run_moss(\":skill allow …\")` **被拒**（不然 AI 能自己批准自己的技能）",
        "拒绝" in _g1 and ":skill" in _g1, _g1[:100])
    for _verb in ("rm pending", "promote pending", "revoke pending"):
        if "拒绝" not in str(_gate.call("run_moss", {"args": ":skill " + _verb})):
            chk("I `:skill %s` 也该被拒" % _verb, False, "")
    chk("I ★ 但 `:skill list` / `doc` / `run` 这类不含「决定」的照旧随便用",
        "拒绝" not in str(_gate.call("run_moss", {"args": ":skill list"}))
        and "拒绝" not in str(_gate.call("run_moss", {"args": ":skill doc shot"})), "")
    # ★ `V-307`：写权限变成**三档模式 + 放行清单**，判据搬到 `ai_mode.writable()`。
    #   行为没变：技能目录能写、出厂插件目录不能写；`core/` 从"普通拒绝"升级成**硬锁**
    #   （放手模式也写不了）—— 所以那句文案从「只允许写」变成「受保护路径（硬锁）」。
    _core_err = str(ai_edits.check_writable(ROOT / "core" / "cli.py"))
    chk("I ★★ 写权限只多开这一处：技能目录能写、出厂插件目录和 core 写不了",
        ai_edits.check_writable(SKDIR / "x" / "pkg.json") is None and
        ai_edits.check_writable(ROOT / "system" / "pkgs" / "skill" / "core.py") is not None and
        ("只允许写" in _core_err or "受保护" in _core_err), _core_err[:60])
    chk("I 能**读**自己的技能（不然没法改它）",
        ai_edits.check_readable(SKDIR / "shot" / "pkg.json") is None, "")

    # ---- I-ι：给界面那一份数据
    _sum = ST.summary()
    chk("I ★ 界面要的三堆都给全了（skills / broken + 目录 + 能用的数量，**没有插件**）",
        set(["ok", "skills", "broken", "dirs", "n_usable", "n_pending"]) <= set(_sum)
        and "from_pkgs" not in _sum and _sum["n_pending"] >= 1,
        "键=%s 待批准=%s" % (sorted(_sum), _sum["n_pending"]))
    _row = [r for r in _sum["skills"] if r["id"] == "shot"][0]
    chk("I ★ 每只技能都带图标正文（墙上那排彩色图标）+ 为什么造它 + 时间 + 文件列表",
        bool(_row["icon_svg"]) and bool(_row["why"]) and bool(_row["created"])
        and isinstance(_row["files"], list) and len(_row["files"]) >= 3, "")

    # ================================================================
    print()
    print("=" * 72)
    print("J：`V-307`/`V-308` 宿主那一半 —— 会话按「干活的地方」分桶 / 每步落盘 /")
    print("     看提示词 / 三档权限 / 放行清单 / 提问回话 / 临时空间 / 停止杀进程")
    print("=" * 72)
    import ai_ask as A                                                    # noqa: E402
    import ai_mode as MO                                                  # noqa: E402
    import ai_runs as RUN                                                 # noqa: E402

    # ---- J-α：**历史按包分桶**（用户原话："我在 github 可视化助手这里使用了 ai……
    #           在历史这里 按说 它应该只要显示这个模块下的历史就可以了"）----------------
    _pkgA = pkgs / "aaa"
    _pkgB = pkgs / "bbb"
    for _p in (_pkgA, _pkgB):
        _p.mkdir(parents=True, exist_ok=True)
    _recA = RUN.save({"task": "A 的活", "workdir": str(_pkgA), "ok": True,
                      "steps": [], "messages": [{"role": "user", "content": "A 问"}]})
    _recB = RUN.save({"task": "B 的活", "workdir": str(_pkgB), "ok": True, "steps": []})
    chk("J ★★ 两个包的会话**落在各自的插件数据目录里**（`state/<包id>/ai/runs/`）",
        (udata / "state" / "aaa" / "ai" / "runs" / (_recA["id"] + ".json")).is_file()
        and (udata / "state" / "bbb" / "ai" / "runs" / (_recB["id"] + ".json")).is_file(),
        str(_recA.get("dir")))
    _lA = api.ai_runs(30, str(_pkgA))
    _lB = api.ai_runs(30, str(_pkgB))
    chk("J ★★ 在 A 包的历史里**只看得到 A 的会话**（B 的一条都不露）",
        [r["id"] for r in _lA["runs"]] == [_recA["id"]]
        and [r["id"] for r in _lB["runs"]] == [_recB["id"]],
        "A=%d 条 B=%d 条" % (len(_lA["runs"]), len(_lB["runs"])))
    chk("J ★ 界面拿得到「这条会话算谁的」（顶栏/标题要显示）",
        _lA.get("scope", {}).get("id") == "aaa", str(_lA.get("scope")))
    chk("J ★ 按 id 照样读得到（不管它在哪个桶里）",
        (api.ai_run(_recA["id"]).get("run") or {}).get("task") == "A 的活", "")
    # 改名/搬家：数据目录跟着包走这件事由 `moss --rename` 负责（这里只钉住"按 id 找得到"）
    chk("J ★ 全清**只清这个桶**（不会顺手把别的包的会话删了）",
        api.ai_run_forget("", True, str(_pkgA)).get("removed") == 1
        and (udata / "state" / "bbb" / "ai" / "runs" / (_recB["id"] + ".json")).is_file(), "")
    # ★ `V-307`：**出厂包**（`system/pkgs/<id>`）也按它自己分桶 —— 在它的 AI 页聊的
    #   不该混进"整个项目区"那一桶（用户原话是"只要显示这个模块下的历史就可以了"）。
    _syspkg = ROOT / "system" / "pkgs" / "md5"
    _recS = RUN.save({"task": "出厂包里的活", "workdir": str(_syspkg), "ok": True, "steps": []})
    chk("J ★ 出厂包（system/pkgs/<id>）的会话也落在它自己的桶里",
        RUN.scope_of(str(_syspkg)).get("id") == "md5"
        and [r["id"] for r in api.ai_runs(30, str(_syspkg))["runs"]] == [_recS["id"]],
        str(RUN.scope_of(str(_syspkg))))
    RUN.delete(_recS["id"], str(_syspkg))

    # ★ `V-314`：**目录名和 id 不一致**时以清单里的 id 为准（`D-27`：两者互不相干，
    #   而数据目录是按 id 算的；不这么做的话 `moss --rename` 搬不走这些会话）。
    _odd = pkgs / "ccc-dir"
    _odd.mkdir(parents=True, exist_ok=True)
    (_odd / "pkg.json").write_text('{"id": "ccc", "name": "目录名和 id 不一样"}', encoding="utf-8")
    _recC = RUN.save({"task": "名字对不上的那个包", "workdir": str(_odd), "ok": True, "steps": []})
    chk("J ★★ 目录名和 id 不一样时，会话按**清单里的 id** 落盘（不然改名搬不走）",
        RUN.scope_of(str(_odd)).get("id") == "ccc"
        and (udata / "state" / "ccc" / "ai" / "runs" / (_recC["id"] + ".json")).is_file(),
        str(RUN.scope_of(str(_odd)).get("id")))
    RUN.delete(_recC["id"], str(_odd))

    # ---- J-β：**每步落盘**：跑一半被强关，记录还在（标着「上次没跑完」） ----------
    _live = RUN.save_live({"id": "probe-live-0001", "task": "跑一半被强关的活",
                           "workdir": str(_pkgB), "steps": [{"n": 1, "tool": "list_dir"}],
                           "usage": {"total_tokens": 12}, "messages": []})
    _row = [r for r in api.ai_runs(30, str(_pkgB))["runs"] if r["id"] == "probe-live-0001"]
    chk("J ★★ 跑到一半的记录**已经落盘了**（不用等跑完 —— 你那次强制重启丢的就是它）",
        bool(_live.get("ok")) and bool(_row) and _row[0].get("interrupted") is True,
        str(_row[:1])[:120])
    chk("J ★ 那条被明确标成「没跑完」（界面据此画 ⚠，不许看成跑完了）",
        bool(_row) and _row[0].get("running") is True, "")
    RUN.delete("probe-live-0001", str(_pkgB))

    # ---- J-γ：**看这条会话喂给它的提示词**（用户要的那个"点开看历史"） -------------
    _msgs = [{"role": "system", "content": "你是 moss 的助手"},
             {"role": "user", "content": "把 zz 改成能算加法"},
             {"role": "assistant", "content": None,
              "tool_calls": [{"id": "c1", "type": "function",
                              "function": {"name": "read_file", "arguments": "{}"}}]},
             {"role": "tool", "tool_call_id": "c1", "content": "（文件内容）"}]
    _rm = RUN.save({"task": "看提示词", "workdir": str(_pkgB), "ok": True, "steps": [],
                    "messages": _msgs})
    _got = api.ai_session_messages(_rm["id"])
    chk("J ★★ 点开一条会话能拿到**整份提示词历史**（系统提示 + 我问的 + 它答的 + 工具结果）",
        _got.get("ok") and _got.get("count") == 4
        and [m["role"] for m in _got["messages"]] == ["system", "user", "assistant", "tool"],
        "count=%s" % _got.get("count"))
    chk("J ★ 老记录（没存对话）如实说「这条没有」，不装作有",
        api.ai_session_messages("根本没有这条").get("ok") is False, "")
    RUN.delete(_rm["id"], str(_pkgB))

    # ---- J-δ：**权限清单（读/写两个勾）**（宿主 API，`V-316`） --------------------
    _s0 = api.ai_mode_get(str(_pkgB))
    chk("J ★★ 当前这个包**自动进清单**，读 + 写都默认开着（打开插件点 AI = 我就是要改它）",
        any(x["path"] == str(_pkgB) and x["read"] and x["write"]
            for x in (_s0.get("allow") or [])), str(_s0.get("allow"))[:120])
    chk("J ★ 清单里**永远有一行「任意路径」**（勾上写 = 放手；删不掉）",
        any(x["path"] == "*" for x in (_s0.get("allow") or [])), "")
    chk("J ★ 默认**不是**放手（`wildcard` 为假）", _s0.get("wildcard") is False, "")
    _out = tmp / "allowed_dir"
    _out.mkdir(parents=True, exist_ok=True)
    _a = api.ai_allow(str(_out), True, True, "探针加的", "add")
    chk("J ★ 加一条（清单里带**读 / 写两个勾** + 为什么）",
        _a.get("ok") and any(x["path"] == str(_out) and x["read"] and x["write"]
                             for x in _a["summary"]["allow"]), str(_a.get("msg")))
    _a2 = api.ai_allow(str(_out), True, False, "", "set")
    chk("J ★★ 把「写」取消勾选 ⇒ 那一行立刻变成只读（读还在）",
        any(x["path"] == str(_out) and x["read"] and not x["write"]
            for x in _a2["summary"]["allow"]), "")
    chk("J ★★ 后端也认这个状态：读得过、写不过",
        MO.can_read(_out / "a.txt") is None and MO.can_write(_out / "a.txt") is not None, "")
    _a3 = api.ai_allow(str(_out), None, None, "", "rm")
    chk("J ★ 删掉那条 ⇒ 读写都不通了",
        not any(x["path"] == str(_out) for x in _a3["summary"]["allow"])
        and MO.can_read(_out / "a.txt") is not None, "")
    # 「任意路径」勾上写 = 放手：哪儿都能写，而且危险操作不再问
    _a4 = api.ai_allow("*", False, True, "", "set")
    chk("J ★★ 把「任意路径」的写打开 = 放手（`ai_info` 里 wildcard 变真）",
        _a4.get("ok") and api.ai_info(str(_pkgB)).get("wildcard") is True, "")
    chk("J ★★ 放手之后：包外目录能写，而且**危险操作不再问**（`needs_confirm` 为假）",
        MO.can_write(_out / "b.txt") is None
        and MO.needs_confirm(MO.danger_of("run_moss", {"args": "--remove x"})) is False, "")
    _a5 = api.ai_allow("*", False, False, "", "set")
    chk("J ★ 关掉「任意路径」⇒ 又变回「要问」（现读，不用重启）",
        _a5.get("ok") and api.ai_info(str(_pkgB)).get("wildcard") is False
        and MO.needs_confirm(MO.danger_of("run_moss", {"args": "--remove x"})) is True, "")
    chk("J ★ 硬锁路径**加不进**清单（`core/` 永远是拒绝）",
        api.ai_allow(str(ROOT / "core"), True, True, "", "add").get("ok") is False, "")

    # ---- J-ε：它问、你答（宿主这一半的桥） --------------------------------------
    # ★ `V-386`（修探针）：`publish` 必须像宿主 `on_ask()` 那样把问题挂进 `AI["state"]["ask"]`
    #   —— `ai_answer` 会拿它核对 qid（"这个问题过期了吗"）。原来 `publish=lambda q: None`，
    #   等于问题从没挂出来，界面（和这里）根本拿不到 qid，所以这条一直是红的。
    def _publish_ask(q):
        with M.AI_LOCK:
            st = M.AI.get("state")
            if st is not None:
                st["ask"] = q

    _asker = A.Asker(publish=_publish_ask, timeout=5)
    _api_ask = {"ok": True}
    with M.AI_LOCK:
        M.AI["asker"] = _asker
        M.AI["state"] = M.AI.get("state") or {}
    _import_thread = None

    def _ask_later():
        # 像界面那样**等那张卡出现**（`ai_poll` 拿到 ask 的 qid），再拿着它回答。
        _q = ""
        for _ in range(60):
            time.sleep(0.1)
            _q = str(((M.AI.get("state") or {}).get("ask") or {}).get("qid") or "")
            if _q:
                break
        _api_ask.update(api.ai_answer(_q, "就按 B 来", "B") or {})

    import threading as _th                                                 # noqa: E402
    _import_thread = _th.Thread(target=_ask_later, daemon=True)
    _import_thread.start()
    _ans = _asker.ask("要 A 还是 B?", options=["A", "B"])
    chk("J ★★ 界面那一下 `ai_answer` 真的**放走了它**（回话里带着答案）",
        _ans.get("answered") is True and _ans.get("text") == "就按 B 来", str(_ans)[:80])
    with M.AI_LOCK:
        M.AI["asker"] = None

    # ---- J-θ：`V-319` **权限请求走清单**（不弹卡片）+ 「已经等了 N 秒」有数 ----------
    with M.AI_LOCK:
        M.AI["stop"] = False        # 前面 D 段按过「停止」，这里先清掉（真流程里 ai_start 会清）
    _pd = tmp / "perm_dir"
    _pd.mkdir(parents=True, exist_ok=True)
    MO.allow_rm(str(_pd))
    _res = {}
    _th2 = _th.Thread(target=lambda: _res.update(
        api._ai_perm_wait(_pd, "探针要写这里", "write", timeout=15) or {}), daemon=True)
    _th2.start()
    _row = None
    for _i in range(30):
        _row = MO.find(str(_pd))
        if _row and _row.get("pending"):
            break
        time.sleep(0.1)
    chk("J ★★ 它一请求 ⇒ 清单里就多一行**待允许**（界面上那一行会闪），这会儿读写都不通",
        bool(_row) and _row.get("pending") is True
        and MO.can_read(_pd / "x.txt") is not None and MO.can_write(_pd / "x.txt") is not None,
        str(_row)[:90])
    _poll = api.ai_poll()
    chk("J ★★ `ai_poll` 把这条请求带给界面（带路径 + 已经等了多久）",
        (_poll.get("perm") or {}).get("path") == str(_pd)
        and (_poll.get("perm") or {}).get("asking", 0) > 0, str(_poll.get("perm"))[:90])
    api.ai_allow(str(_pd), True, True, "", "add")          # 用户在清单里勾「写」
    _th2.join(6)
    chk("J ★★ 用户一勾 ⇒ 闸**放行**（granted），那一行同时变成正式条目（不再 pending）",
        _res.get("granted") is True and _res.get("write") is True
        and not (MO.find(str(_pd)) or {}).get("pending"), str(_res)[:90])
    chk("J ★ 放行之后当场能写", MO.can_write(_pd / "x.txt") is None, "")

    # 只给读 ⇒ 闸要如实说 read-only（它要的是写）
    MO.allow_rm(str(_pd))
    _res2 = {}
    _th3 = _th.Thread(target=lambda: _res2.update(
        api._ai_perm_wait(_pd, "要写", "write", timeout=15) or {}), daemon=True)
    _th3.start()
    for _i in range(30):
        if (MO.find(str(_pd)) or {}).get("pending"):
            break
        time.sleep(0.1)
    api.ai_allow(str(_pd), True, False, "", "add")         # 用户只勾「读」
    _th3.join(6)
    chk("J ★★ 用户只勾「读」⇒ 闸回 read-only（不是含糊的「允许了」）",
        _res2.get("reason") == "read-only" and _res2.get("granted") is False, str(_res2)[:80])

    # 拒绝（点 ✕ = 那条没了）⇒ denied
    MO.allow_rm(str(_pd))
    _res3 = {}
    _th4 = _th.Thread(target=lambda: _res3.update(
        api._ai_perm_wait(_pd, "要写", "write", timeout=15) or {}), daemon=True)
    _th4.start()
    for _i in range(30):
        if (MO.find(str(_pd)) or {}).get("pending"):
            break
        time.sleep(0.1)
    api.ai_allow(str(_pd), None, None, "", "rm")           # 用户点 ✕
    _th4.join(6)
    chk("J ★★ 用户点 ✕（拒绝）⇒ 闸回 denied（它会收到「别动那里」）",
        _res3.get("reason") == "denied" and _res3.get("granted") is False, str(_res3)[:80])

    # 「已经等了 N 秒」不许是空数字（老 bug：publish 那一份没有 asking）
    # ★ `V-386`（修探针）：这条测的是 `ai_poll` 的**退路** —— "asker 已经收工，但
    #   `state["ask"]` 还在" 时也要把秒数算出来。`ai_poll` 的口径是 **asker 为准**，
    #   所以这里必须让 asker 是 None；原来挂了个空 asker，它手上没题 ⇒ 永远拿到空。
    with M.AI_LOCK:
        M.AI["asker"] = None
        M.AI["state"] = {"ask": {"qid": "q-sec", "question": "在吗？", "options": [],
                                 "allow_text": True, "kind": "ask", "why": "", "detail": "",
                                 "at": time.time() - 7}}
    _p3 = (api.ai_poll().get("ask") or {})
    chk("J ★★ 「已经等了 N 秒」有数（以前那一位是空的 —— 你报的「已经等了秒」）",
        _p3.get("asking", 0) >= 6, str(_p3)[:80])
    with M.AI_LOCK:
        M.AI["asker"] = None
        M.AI["state"] = {}


    # ---- J-ζ：临时空间（`V-314`：**按插件分**，看 / 清） --------------------------
    _t = api.ai_tmp("info", "", str(_pkgB))
    chk("J ★ 临时空间读得到（路径 + 大小 + 文件数）",
        _t.get("ok") and "path" in (_t.get("tmp") or {}), str(_t.get("tmp")))
    chk("J ★★ 它落在**这个插件的数据目录**里（`state/<包id>/ai/tmp`）",
        "/state/bbb/ai/tmp" in str((_t.get("tmp") or {}).get("path") or "").replace("\\", "/"),
        str((_t.get("tmp") or {}).get("path")))
    _d = MO.ensure_tmp("probe-clean", str(_pkgB))
    _d2 = MO.ensure_tmp("probe-clean-2", str(_pkgA))
    (_d / "x.txt").write_text("x", encoding="utf-8")
    (_d2 / "y.txt").write_text("y", encoding="utf-8")
    api.ai_tmp("clean", "", str(_pkgB))
    chk("J ★★ 清空**只清这个包的**（另一个包的临时文件一条没动）",
        MO.tmp_size(str(_pkgB)).get("files") == 0 and MO.tmp_size(str(_pkgA)).get("files") == 1,
        "B=%s A=%s" % (MO.tmp_size(str(_pkgB)).get("files"),
                       MO.tmp_size(str(_pkgA)).get("files")))
    api.ai_tmp("clean", "", str(_pkgA))

    # ---- J-η：**停止 = 立刻 + 杀子进程**（用户报的"提示我停在下轮，然后依旧卡死"） ----
    _long = tmp / "long_host2.py"
    _long.write_text(
        "# -*- coding: utf-8 -*-\n"
        "import os, subprocess, sys, time\n"
        "kid = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        "open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pids2.txt'), 'w').write(\n"
        "    '%d %d' % (os.getpid(), kid.pid))\n"
        "time.sleep(120)\n", encoding="utf-8")
    _oldh = os.environ.get("MOSS_HOST_CMD")
    os.environ["MOSS_HOST_CMD"] = '"%s" "%s"' % (sys.executable, _long)
    # ★ D 段把模型换成了 `SlowClient`（一直回 list_dir，用来制造"跑着的时候按停止"），
    #   这里要**换回**按剧本走的 FakeClient —— 不换回来，这次跑的就是 200 步 list_dir。
    ai_client.Client = FakeClient
    SCRIPT[:] = [call("run_moss", {"args": ":sleepy", "timeout": 120})]
    _r = api.ai_start("跑个长命令", str(_pkgB))
    chk("J 那条长命令的任务起来了", bool(_r.get("ok")), str(_r)[:60])
    _t0 = time.time()
    while time.time() - _t0 < 6 and not (tmp / "pids2.txt").is_file():
        time.sleep(0.2)
    _mid = api.ai_poll()
    chk("J 这会儿它确实在跑（界面上是「执行中」）", _mid.get("running") is True,
        "步骤=%s 结果=%s" % ([s.get("tool") for s in (_mid.get("steps") or [])][-4:],
                             str((_mid.get("result") or {}).get("reason"))[:90]))
    _st = api.ai_stop()
    chk("J ★★ 按停止**当场就停**（不是「停在下一轮」）", _st.get("done") is True or "停止" in str(_st.get("msg")),
        str(_st.get("msg"))[:60])
    _t1 = time.time()
    while time.time() - _t1 < 20:
        if not api.ai_poll().get("running"):
            break
        time.sleep(0.2)
    chk("J ★★ 一两秒内就收工（老行为是「提示停在下轮」然后卡到超时）",
        time.time() - _t1 < 8, "%.1f 秒" % (time.time() - _t1))
    _pids2 = ((tmp / "pids2.txt").read_text(encoding="utf-8").split()
              if (tmp / "pids2.txt").is_file() else [])
    _alive2 = []
    for _p in _pids2:
        _o = subprocess.run(["tasklist", "/FI", "PID eq %s" % _p, "/NH"],
                            capture_output=True, text=True, errors="replace")
        if _p in (_o.stdout or ""):
            _alive2.append(_p)
    chk("J ★★ 它起的子进程**连子孙一起被收掉**（几十个 moss/python 的根因）",
        len(_pids2) == 2 and not _alive2, "pid=%s 还活着=%s" % (_pids2, _alive2))
    if _oldh is None:
        os.environ.pop("MOSS_HOST_CMD", None)
    else:
        os.environ["MOSS_HOST_CMD"] = _oldh

    print()
    print("=" * 72)
    print("K：`V-423` 收尾竞态 —— `running=false` 必须和最终 `result` 同一拍")
    print("=" * 72)
    # ★ 这条不能只靠"正常跑一遍"：正常写盘太快，空窗可能只有几十毫秒，探针会假绿。
    #   这里把最终记录写盘**强制拖慢 1.5 秒**，专门让轮询撞进老代码那段空窗。
    #   不变量：`ai_poll()` 只要回 `running=false`，同一份 payload 里就必须已经有
    #   最终 `result`；否则页面会停轮询，结论卡永远不出现（用户报过多次）。
    _script_before = list(SCRIPT)
    _client_before = ai_client.Client
    _save_orig = _runs.save

    def _slow_save(rec, scope=None):
        time.sleep(1.5)
        return _save_orig(rec, scope)

    _runs.save = _slow_save
    try:
        SCRIPT[:] = [call("answer", {"text": "收尾结果在这里"})]
        ai_client.Client = FakeClient
        _k_started = api.ai_start("收尾竞态探针", str(pkgs), 100000000)
        chk("K 探针任务起来了", bool(_k_started.get("ok")), str(_k_started)[:100])
        _empty_finish, _k_done, _k_polls = [], None, 0
        _k_deadline = time.time() + 20
        while time.time() < _k_deadline:
            _kp = api.ai_poll()
            _k_polls += 1
            if not _kp.get("running") and not _kp.get("result"):
                _empty_finish.append({
                    "poll": _k_polls,
                    "steps": len(_kp.get("steps") or []),
                    "idle": bool(_kp.get("idle")),
                })
            if not _kp.get("running") and _kp.get("result"):
                _k_done = _kp
                break
            time.sleep(0.1)
        chk("K ★★ 收尾期间绝不出现 `running=false` 但 `result=null`（出现 ⇒ 页面会停轮询）",
            not _empty_finish,
            "空窗命中=%s，共轮询 %d 次" % (json.dumps(_empty_finish, ensure_ascii=False), _k_polls))
        chk("K ★★ 慢写盘结束后最终结果仍然回到页面（不靠点历史）",
            bool(_k_done) and
            str(((_k_done or {}).get("result") or {}).get("summary") or "") == "收尾结果在这里",
            "轮询=%d，结果=%s" % (_k_polls,
                                 json.dumps((_k_done or {}).get("result") or {},
                                            ensure_ascii=False)[:120]))
    finally:
        _runs.save = _save_orig
        ai_client.Client = _client_before
        SCRIPT[:] = _script_before

    shutil.rmtree(tmp, ignore_errors=True)
    print()
    print("=" * 72)
    badN = [r for r in RES if not r[1]]
    print("结论：%s（%d 条，失败 %d）" % ("✅ 全过" if not badN else "✗ 有不对的", len(RES), len(badN)))
    return 0 if not badN else 1


if __name__ == "__main__":
    sys.exit(main())
