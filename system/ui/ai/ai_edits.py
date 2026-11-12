import base64
import json
import mimetypes
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

def _home():
    env = (os.environ.get("MOSS_HOME") or "").strip()
    if env:
        return Path(env)
    return HERE.parents[2]

HOME = _home()

def user_data():
    env = (os.environ.get("MOSS_USER_DATA_DIR") or "").strip()
    return Path(env) if env else (HOME / "user_data")

def write_root():
    return user_data() / "pkgs"

def tool_root():
    return user_data() / "state" / "skill"

def write_roots():
    return [write_root(), tool_root()]

def inside(path, root):
    try:
        p = os.path.realpath(str(path))
        r = os.path.realpath(str(root))
    except OSError:
        return False
    return p == r or p.startswith(r + os.sep)

def check_writable(path, scope=None):
    import ai_mode as M
    return M.can_write(path, scope=scope)

def read_roots(scope=None):
    import ai_mode as M
    return [write_root(),
            tool_root(),
            M.tmp_root(),
            HOME / "system" / "spec",
            HOME / "system" / "pkgs"] + M.readable_extra(scope)

def check_readable(path, scope=None):
    import ai_mode as M
    if inside(path, HOME / "system" / "spec"):
        return ("[拒绝] 契约不要用 read_file 整篇读 —— 用 `spec` 工具按小节取："
                "`spec(\"\")` 看目录、`spec(\"拖放\")` / `spec(\"pkg.json\")` / `spec(\"避坑\")` 取某一节。"
                "（整篇读会把上下文撑爆、把轮次烧光。）")
    if M.readable_builtin(path):
        return None
    if scope:
        sc = Path(scope)
        root = write_root()
        if inside(path, root) and not inside(path, sc):
            return ("[拒绝] 这次干活的地方是 `%s` —— **只在这个包下面看**。"
                    "`%s` 是**别的包**，不归这次任务管（样板请看 `system/pkgs/skill`，那是留给你抄的）。"
                    % (sc, path))
    return M.can_read(path, scope=scope)

IMAGE_MIMES = {
    "image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp",
}
IMAGE_DATA_CAP = 12 * 1024 * 1024

def image_mime(path):
    p = Path(path)
    try:
        with p.open("rb") as fh:
            head = fh.read(64)
    except OSError:
        return ""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if head.startswith(b"BM"):
        return "image/bmp"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    guess = (mimetypes.guess_type(p.name)[0] or "").lower()
    return guess if guess in IMAGE_MIMES else ""

def image_data_url(path, cap=IMAGE_DATA_CAP):
    p = Path(path)
    mime = image_mime(p)
    if not mime:
        return None, "不是模型能直接看的图片（支持 png/jpg/gif/webp/bmp）：%s" % p
    try:
        size = p.stat().st_size
        if size > int(cap or IMAGE_DATA_CAP):
            return None, "图片太大（%d 字节，上限 %d）：%s" % (size, int(cap or IMAGE_DATA_CAP), p)
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    except OSError as e:
        return None, "图片读不了：%s（%s）" % (p, e)
    return "data:%s;base64,%s" % (mime, b64), None

def read_text(path, offset=1, limit=400, scope=None):
    p = Path(path)
    if not p.is_file():
        return None, "没有这个文件：%s" % p
    bad = check_readable(p, scope)
    if bad:
        return None, bad
    try:
        raw = p.read_bytes()
    except OSError as e:
        return None, "读不了：%s" % e
    mime = image_mime(p)
    if mime:
        return None, ("[拒绝] `%s` 是图片（%s），不是文本文件。要看图请用 `read_image` "
                      "（它会直接把图片作为视觉输入交给模型；不要找 OCR、也不要再用 read_file）。"
                      % (p, mime))
    if b"\x00" in raw[:8192]:
        return None, ("[拒绝] `%s` 看起来是二进制文件（检测到 NUL 字节），不能当文本读。"
                      "如果它是图片，请用 `read_image`；其它二进制请用对应的工具。" % p)
    text = raw.decode("utf-8", "replace").replace("\r\n", "\n")
    lines = text.split("\n")
    start = max(1, int(offset or 1))
    stop = min(len(lines), start - 1 + max(1, int(limit or 400)))
    out = ["%5d| %s" % (i + 1, lines[i]) for i in range(start - 1, stop)]
    head = "（共 %d 行，这是 %d-%d 行）" % (len(lines), start, stop) if lines else "（空文件）"
    return "\n".join([head] + out), None

def _split_lines(text):
    return text.split("\n")

def _crlf(raw):
    return b"\r\n" in raw

def _pkg_id_guard(path, old_text, new_text):
    try:
        if Path(path).name.lower() != "pkg.json":
            return ""
        old = json.loads(str(old_text or ""))
        new = json.loads(str(new_text or ""))
        if not isinstance(old, dict) or not isinstance(new, dict):
            return ""
        oid = str(old.get("id") or "").strip()
        nid = str(new.get("id") or "").strip()
        if oid and nid and oid != nid:
            return ("不许直接改 `pkg.json` 的 `id`（%s → %s）—— 手改不会搬包目录，"
                    "也不会搬 `state/<旧id>/` 里的数据，AI 会话会看起来消失。"
                    "改名请用 run_moss(`--rename %s %s`)；只改显示名就改 `name` / `aliases`，不要动 `id`。"
                    % (oid, nid, oid, nid))
    except Exception:
        return ""
    return ""

def apply_edit(path, find, replace, replace_all=False, scope=None):
    p = Path(path)
    bad = check_writable(p, scope)
    if bad:
        return {"ok": False, "error": bad}
    if not p.is_file():
        return {"ok": False, "error": "没有这个文件：%s（新建文件用 write_file）" % p}
    raw = p.read_bytes()
    text = raw.decode("utf-8", "replace").replace("\r\n", "\n")
    find = str(find or "").replace("\r\n", "\n")
    replace = str(replace or "").replace("\r\n", "\n")
    if not find:
        return {"ok": False, "error": "find 不能是空的（要替换整段就用 write_file）"}
    n = text.count(find)
    if n == 0:
        return {"ok": False, "replaced": 0,
                "error": "没找到那段。**一个字都不能差**（缩进、空行都算）。",
                "hint": _miss_hint(text, find)}
    if n > 1 and not replace_all:
        lines = [i + 1 for i, ln in enumerate(_split_lines(text)) if find.split("\n")[0] and ln.find(find.split("\n")[0]) >= 0]
        return {"ok": False, "replaced": 0,
                "error": "这一段出现了 %d 次，不肯猜你要改哪一个：要么把 find 写长一点"
                         "（带上前后文到唯一），要么显式给 replace_all=true。" % n,
                "hint": "候选行号：%s" % (lines[:12] or "（按首行没定位到，建议多带几行上下文）")}
    new = text.replace(find, replace) if replace_all else text.replace(find, replace, 1)
    bad = _pkg_id_guard(p, text, new)
    if bad:
        return {"ok": False, "replaced": 0, "error": bad}
    try:
        if _crlf(raw):
            p.write_bytes(new.replace("\n", "\r\n").encode("utf-8"))
        else:
            p.write_bytes(new.encode("utf-8"))
    except OSError as e:
        return {"ok": False, "error": "写不进去：%s" % e}
    return {"ok": True, "replaced": (n if replace_all else 1)}

def write_new(path, content, overwrite=False, scope=None):
    p = Path(path)
    bad = check_writable(p, scope)
    if bad:
        return {"ok": False, "error": bad}
    if p.exists() and not overwrite:
        return {"ok": False, "error":
                "文件已经在了：%s\n"
                "· 改几行 ⇒ 用 `edit_file`（精确替换，最稳）；\n"
                "· 要**整篇重写** ⇒ 再调一次 `write_file`，并显式带上 `overwrite=true`。" % p}
    if p.name.lower() == "pkg.json" and p.exists():
        try:
            old_text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            old_text = ""
        bad = _pkg_id_guard(p, old_text, str(content or ""))
        if bad:
            return {"ok": False, "error": bad}
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(str(content or "").encode("utf-8"))
    except OSError as e:
        return {"ok": False, "error": "写不进去：%s" % e}
    return {"ok": True, "bytes": len(str(content or "").encode("utf-8")),
            "overwrote": bool(overwrite and p.exists())}

def _miss_hint(text, find):
    import difflib
    lines = _split_lines(text)
    first = (find.split("\n")[0] or "").strip()
    hit = [i + 1 for i, ln in enumerate(lines) if first and first in ln]
    close = difflib.get_close_matches(first, [ln.strip() for ln in lines], n=3, cutoff=0.55)
    bits = []
    if hit:
        bits.append("你给的第一行出现在第 %s 行" % hit[:8])
    if close:
        bits.append("最像的行：%s" % " / ".join(repr(c) for c in close))
    bits.append("常见原因：缩进对不上（空格/制表符）、文件是 CRLF、这段是**改过之后**的样子")
    return "；".join(bits)
