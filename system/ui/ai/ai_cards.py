import base64
import binascii
import hashlib
import json
import os
import re
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

import ai_edits as E

MAX_BODY = 3000
DEFAULT_ACCENTS = ["#7C3AED", "#0EA5E9", "#F97316", "#EF4444", "#10B981",
                   "#EC4899", "#F59E0B", "#06B6D4", "#8B5CF6", "#84CC16"]
ICON_CHOICES = [
    "sparkles", "lightbulb", "puzzle", "code", "braces", "terminal", "layers",
    "rocket", "gauge", "shield-check", "file-text", "file-code", "book-open",
    "wrench", "settings", "palette", "paint-roller", "folder-tree", "search",
    "check", "circle-check", "circle-alert", "alert-triangle", "message-square",
    "globe", "git-branch", "package", "play", "history", "database", "plug",
    "binary", "hash", "list-ul", "list-tree", "moss-deepseek", "moss-camera",
]

# ===== 自定义图标（只做界面资源，不进模型上下文） =====
SVG_NS = "http://www.w3.org/2000/svg"
ICON_SVG_MAX = 16000                 # SVG 源码上限（字符）
ICON_IMG_MAX = 96 * 1024             # 位图上限（字节）
ICON_IMAGE_EXT = {"image/png": "png", "image/jpeg": "jpg",
                  "image/webp": "webp", "image/gif": "gif"}
ICON_SVG_TAGS = {
    "svg", "g", "path", "circle", "ellipse", "rect", "line", "polyline",
    "polygon", "defs", "lineargradient", "radialgradient", "stop",
    "clippath", "mask",
}
ICON_SVG_ATTRS = {
    "d", "cx", "cy", "r", "rx", "ry", "x", "y", "x1", "y1", "x2", "y2",
    "width", "height", "points", "viewbox", "transform", "fill",
    "fill-opacity", "fill-rule", "stroke", "stroke-width", "stroke-linecap",
    "stroke-linejoin", "stroke-opacity", "stroke-dasharray",
    "stroke-dashoffset", "opacity", "offset", "stop-color", "stop-opacity",
    "gradientunits", "gradienttransform", "clippathunits", "clip-path",
    "clip-rule", "mask", "id", "class", "style",
}

STUDIO_SYSTEM = """你是 moss 的「经验卡编辑」。
用户会把一条经验、避坑、偏好或一次任务的教训交给你，你要把它整理成一张短小、可执行、可复用的经验卡。

必须只输出一个 JSON 对象，不要 Markdown 代码块，不要解释：
{
  "reply": "给用户看的中文回复，说明你改了什么，不超过 120 字",
  "card": {
    "id": "小写字母开头的短 id，可省略；新卡用 title 自动生成",
    "icon": "从给定图标中选一个",
    "icon_svg": "可选：48×48 的自绘 SVG 源码，只有用户明确要你画图标时才给",
    "title": "不超过 18 个汉字，像卡片标题",
    "body": "不超过 600 字。写清：什么时候用、怎么做、别做什么。用短句或分条，必须可执行。",
    "tags": ["最多 5 个短标签"],
    "accent": "#RRGGBB 颜色"
  }
}

规则：
- 不要写空话、不要复述用户原话、不要写长篇背景。
- 不要把密钥、隐私、完整聊天记录写进卡片。
- 卡片的读者是之后执行任务的 AI；写成第二人称或命令式短句。
- 如果用户只是讨论、还想继续改，也要返回完整修改后的 card，方便实时预览。
- icon 只能从这些里选：ICON_CHOICES。
- icon_svg 只在用户要求画图标时给：根元素 `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">`，
  只许基础图形标签，不许 script / style / image / use / text / href / 事件属性 / 外链，总长 ≤2000 字符。
  用户没提图标就把这个字段省掉，不要自己加。
"""
STUDIO_SYSTEM = STUDIO_SYSTEM.replace("ICON_CHOICES", "、".join(ICON_CHOICES))

ICON_SYSTEM = """你是 moss 经验卡的图标画师。只输出一个 SVG 源码，不要 Markdown 代码块，不要任何解释。

硬性要求：
- 根元素写成 `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">`，画布就是 48×48。
- 只允许这些标签：svg、g、path、circle、ellipse、rect、line、polyline、polygon、defs、linearGradient、radialGradient、stop、clipPath。
- 禁止：script、style、foreignObject、image、use、text、href / xlink:href、http(s) 外链、任何 on* 事件属性。
- 不要写 width / height，缩放交给 viewBox。
- 造型极简、几何化，四周留至少 4px 空白；缩到 20px 还认得出。
- 默认线性风格：`fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"`；
  需要强调时最多再加 1 个具体色值（#RRGGBB）。
- 总长度不超过 2000 字符，不要输出中文说明。"""


def _dir():
    return E.user_data() / "ai" / "cards"


def _icon_dir():
    return _dir() / "icons"


def _est(text):
    return max(1, int(len(str(text or "")) / 3))


def _safe_id(raw):
    s = str(raw or "").strip().lower()
    s = re.sub(r"[^a-z0-9_-]+", "-", s).strip("-_")
    s = re.sub(r"^[^a-z]+", "", s)
    return (s[:40].strip("-") or ("card-" + uuid.uuid4().hex[:8]))


def _accent_for(seed):
    n = int(hashlib.sha1(str(seed or "card").encode("utf-8")).hexdigest()[:8], 16)
    return DEFAULT_ACCENTS[n % len(DEFAULT_ACCENTS)]


def _local(tag):
    return str(tag or "").split("}")[-1].lower()


def sanitize_svg(text):
    """把外部 SVG 洗成只剩基础图形的片段；洗不干净就返回空串。

    图标只是界面资源，永远不进模型上下文，但它是用户/AI 能塞进来的字符串，
    所以这里当不可信输入处理：白名单标签 + 白名单属性 + 去外链 + 体积上限。
    """
    raw = str(text or "").strip()
    if not raw or len(raw) > ICON_SVG_MAX:
        return ""
    a = raw.lower().find("<svg")
    if a > 0:
        raw = raw[a:]
    b = raw.lower().rfind("</svg>")
    if b > 0:
        raw = raw[:b + 6]
    try:
        root = ET.fromstring(raw)
    except (ET.ParseError, ValueError):
        return ""
    if _local(root.tag) != "svg":
        return ""

    def _walk(el):
        for child in list(el):
            if _local(child.tag) not in ICON_SVG_TAGS:
                el.remove(child)
                continue
            _walk(child)

    _walk(root)
    for el in list(root.iter()):
        keep = {}
        for k, v in list(el.attrib.items()):
            name = _local(k)
            val = str(v or "")
            if name.startswith("on") or name.startswith("xmlns"):
                continue
            if name not in ICON_SVG_ATTRS:
                continue
            if re.search(r"(javascript:|expression\s*\(|@import|<\s*script)",
                         val, re.I):
                continue
            if name == "style" and re.search(r"url\s*\(\s*['\"]?\s*[^#\s]", val, re.I):
                continue
            keep[name] = val
        el.attrib = keep
        el.tag = _local(el.tag)
        if el.text and not el.text.strip():
            el.text = None
        if el.tail and not el.tail.strip():
            el.tail = None
    vb = str(root.attrib.pop("viewbox", "") or "").strip()
    root.attrib.pop("width", None)
    root.attrib.pop("height", None)
    if re.match(r"^-?[\d.]+[\s,]+-?[\d.]+[\s,]+[\d.]+[\s,]+[\d.]+$", vb):
        root.set("viewBox", " ".join(vb.replace(",", " ").split()))
    else:
        root.set("viewBox", "0 0 24 24")
    root.set("xmlns", SVG_NS)
    try:
        out = ET.tostring(root, encoding="unicode")
    except (TypeError, ValueError):
        return ""
    if not out or len(out) > ICON_SVG_MAX:
        return ""
    return out


def _sniff_image(blob):
    if not blob:
        return ""
    if blob.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if blob.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if blob.startswith(b"GIF87a") or blob.startswith(b"GIF89a"):
        return "image/gif"
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return "image/webp"
    return ""


def parse_image_source(src):
    """data URL（或裸 base64）→ (bytes, mime)；不合规返回 (b"", "")。"""
    s = str(src or "").strip()
    if not s:
        return b"", ""
    m = re.match(r"^data:([a-z0-9.+/-]+);base64,(.*)$", s, re.I | re.S)
    if m:
        blob = re.sub(r"\s+", "", m.group(2))
    else:
        blob = re.sub(r"\s+", "", s)
    try:
        raw = base64.b64decode(blob, validate=True)
    except (binascii.Error, ValueError):
        return b"", ""
    if not raw or len(raw) > ICON_IMG_MAX:
        return b"", ""
    mime = _sniff_image(raw)
    if not mime:
        return b"", ""
    return raw, mime


def parse_icon_svg(text):
    """从模型的回答里抠出一段 SVG 并清洗。返回 (svg, 错误说明)。"""
    raw = str(text or "").strip()
    if not raw:
        return "", "AI 什么都没返回"
    m = re.search(r"<svg\b.*?</svg\s*>", raw, re.S | re.I)
    if not m:
        return "", "AI 没给出 <svg> 片段"
    svg = sanitize_svg(m.group(0))
    if not svg:
        return "", "这段 SVG 没通过安全检查（标签 / 属性 / 体积）"
    return svg, ""


def _icon_drop(cid):
    d = _icon_dir()
    cid = _safe_id(cid)
    if not cid or not d.is_dir():
        return
    for f in d.glob(cid + ".*"):
        try:
            f.unlink()
        except OSError:
            pass


def _icon_write(cid, kind, payload):
    _icon_drop(cid)
    d = _icon_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
        if kind == "svg":
            p = d / (cid + ".svg")
            tmp = p.with_name(p.name + ".tmp")
            tmp.write_text(str(payload), encoding="utf-8", newline="\n")
            os.replace(str(tmp), str(p))
            return "svg"
        blob, mime = payload
        ext = ICON_IMAGE_EXT.get(mime) or "png"
        p = d / (cid + "." + ext)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_bytes(blob)
        os.replace(str(tmp), str(p))
        return "img"
    except OSError:
        return ""


def _decorate(card):
    """把磁盘上的自定义图标读出来挂到卡上（只给界面看）。"""
    kind = str(card.get("icon_kind") or "builtin")
    cid = str(card.get("id") or "")
    if not cid:
        return card
    if kind == "svg":
        try:
            txt = (_icon_dir() / (cid + ".svg")).read_text(encoding="utf-8",
                                                           errors="replace")
        except OSError:
            txt = ""
        svg = sanitize_svg(txt)
        if svg:
            card["icon_svg"] = svg
        else:
            card["icon_kind"] = "builtin"
    elif kind == "img":
        url = ""
        d = _icon_dir()
        if d.is_dir():
            for f in sorted(d.glob(cid + ".*")):
                if f.suffix.lower() == ".svg":
                    continue
                try:
                    blob = f.read_bytes()
                except OSError:
                    continue
                mime = _sniff_image(blob)
                if not mime or len(blob) > ICON_IMG_MAX:
                    continue
                url = "data:%s;base64,%s" % (
                    mime, base64.b64encode(blob).decode("ascii"))
                break
        if url:
            card["icon_img"] = url
        else:
            card["icon_kind"] = "builtin"
    return card


def _clean_card(raw, old=None):
    raw = raw if isinstance(raw, dict) else {}
    old = old if isinstance(old, dict) else {}
    title = str(raw.get("title") or old.get("title") or "未命名经验卡").strip()[:80]
    cid = _safe_id(raw.get("id") or old.get("id") or title)
    body = str(raw.get("body") or old.get("body") or "").strip()[:MAX_BODY]
    tags = raw.get("tags", old.get("tags", []))
    if isinstance(tags, str):
        tags = [x.strip() for x in re.split(r"[,，、|]+", tags) if x.strip()]
    if not isinstance(tags, list):
        tags = []
    tags = [str(x).strip()[:24] for x in tags if str(x).strip()][:8]
    icon = str(raw.get("icon") or old.get("icon") or "sparkles").strip()
    if icon not in ICON_CHOICES:
        icon = "sparkles"
    accent = str(raw.get("accent") or old.get("accent") or _accent_for(cid)).strip()
    if not re.match(r"^#[0-9a-fA-F]{6}$", accent):
        accent = _accent_for(cid)
    kind = str(raw.get("icon_kind") or old.get("icon_kind") or "builtin").strip().lower()
    if kind not in ("builtin", "svg", "img"):
        kind = "builtin"
    if raw.get("icon_reset"):
        kind = "builtin"
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    card = {"id": cid, "title": title, "body": body, "tags": tags,
            "icon": icon, "icon_kind": kind, "accent": accent,
            "created": str(old.get("created") or raw.get("created") or now),
            "updated": now}
    if str(raw.get("icon_svg") or "").strip():
        svg = sanitize_svg(raw.get("icon_svg"))
        if svg:
            card["icon_svg"] = svg
            card["icon_kind"] = "svg"
    if str(raw.get("icon_img") or raw.get("icon_data") or "").strip() \
            and card["icon_kind"] != "svg":
        blob, mime = parse_image_source(raw.get("icon_img") or raw.get("icon_data"))
        if blob:
            card["icon_img"] = "data:%s;base64,%s" % (
                mime, base64.b64encode(blob).decode("ascii"))
            card["icon_kind"] = "img"
    return card


def list_cards():
    out = []
    d = _dir()
    if not d.is_dir():
        return out
    for f in sorted(d.glob("*.json")):
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        card = _decorate(_clean_card(raw))
        card["chars"] = len(card.get("body") or "")
        card["tokens"] = _est(card.get("body") or "")
        out.append(card)
    out.sort(key=lambda x: str(x.get("updated") or ""), reverse=True)
    return out


def get_card(cid):
    cid = _safe_id(cid)
    if not cid:
        return None
    p = _dir() / (cid + ".json")
    try:
        return _decorate(_clean_card(json.loads(p.read_text(encoding="utf-8"))))
    except Exception:
        return None


def save_card(raw):
    raw = raw if isinstance(raw, dict) else {}
    old = {}
    cid_hint = str(raw.get("id") or "").strip()
    if cid_hint:
        old = get_card(cid_hint) or {}
    card = _clean_card(raw, old)
    if not card.get("title") or not card.get("body"):
        return {"ok": False, "msg": "标题和正文都要有"}
    if str(raw.get("icon_svg") or "").strip() and card.get("icon_kind") != "svg":
        return {"ok": False, "msg": "这个 SVG 没通过安全检查"
                                    "（只允许基础图形，不许 script / 外链 / 事件属性，≤16000 字符）"}
    if str(raw.get("icon_img") or raw.get("icon_data") or "").strip() \
            and card.get("icon_kind") != "img":
        return {"ok": False, "msg": "图标图片读不出来"
                                    "（只支持 PNG / JPEG / WebP / GIF，≤96KB）"}
    svg_payload = str(card.pop("icon_svg", "") or "")
    img_payload = str(card.pop("icon_img", "") or "")
    want = str(card.get("icon_kind") or "builtin")
    d = _dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
        if not old:
            base = card["id"]
            for n in range(2, 1000):
                if not (d / (card["id"] + ".json")).exists():
                    break
                suffix = "-%d" % n
                card["id"] = (base[:36 - len(suffix)].rstrip("-_") + suffix).strip("-_")
        cid = card["id"]
        if want == "svg" and svg_payload:
            card["icon_kind"] = _icon_write(cid, "svg", svg_payload) or "builtin"
            if card["icon_kind"] == "builtin":
                _icon_drop(cid)
        elif want == "img" and img_payload:
            blob, mime = parse_image_source(img_payload)
            card["icon_kind"] = (_icon_write(cid, "img", (blob, mime))
                                 if blob else "builtin")
            if card["icon_kind"] == "builtin":
                _icon_drop(cid)
        elif want == "builtin":
            _icon_drop(cid)
            card["icon_kind"] = "builtin"
        p = d / (cid + ".json")
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(card, ensure_ascii=False, indent=1) + "\n",
                       encoding="utf-8")
        os.replace(str(tmp), str(p))
    except OSError as e:
        return {"ok": False, "msg": "存不下来：%s" % e}
    card = _decorate(card)
    card["chars"] = len(card.get("body") or "")
    card["tokens"] = _est(card.get("body") or "")
    return {"ok": True, "card": card}


def delete_card(cid):
    cid = _safe_id(cid)
    p = _dir() / (cid + ".json")
    try:
        p.unlink()
    except FileNotFoundError:
        return {"ok": False, "msg": "没有这张卡"}
    except OSError as e:
        return {"ok": False, "msg": "删不掉：%s" % e}
    _icon_drop(cid)
    return {"ok": True}


def mount_block(ids):
    cards = []
    seen = set()
    for cid in (ids or []):
        cid = str(cid or "").strip()
        if not cid or cid in seen:
            continue
        seen.add(cid)
        card = get_card(cid)
        if card and card.get("body"):
            cards.append(card)
    if not cards:
        return "", []
    rows = ["【本次挂载的经验卡】下面是用户挑给你的经验 / 避坑，优先当行为约束；"
            "和硬规矩冲突时以硬规矩为准。"]
    for i, c in enumerate(cards, 1):
        rows.append("\n[%d] %s（%s）\n%s" % (i, c.get("title"), c.get("id"),
                                             c.get("body")))
    rows.append("\n这些是经验，不是用户的新任务；不要因为挂载了卡片就扩大任务范围。")
    return "\n".join(rows), cards


def studio_messages(history, text, card=None):
    msgs = [{"role": "system", "content": STUDIO_SYSTEM}]
    hist = history if isinstance(history, list) else []
    for m in hist[-12:]:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or "")
        content = str(m.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            msgs.append({"role": role, "content": content[:4000]})
    cur = ""
    if isinstance(card, dict) and (card.get("title") or card.get("body")):
        slim = {k: card.get(k) for k in ("id", "title", "body", "tags", "icon",
                                         "accent") if card.get(k)}
        cur = "\n\n当前卡片（请在此基础上修改，不要丢掉仍适用的内容）：\n" + json.dumps(
            slim, ensure_ascii=False)
    msgs.append({"role": "user", "content": str(text or "").strip() + cur})
    return msgs


def icon_messages(card, hint=""):
    card = card if isinstance(card, dict) else {}
    bits = ["卡片标题：" + (str(card.get("title") or "").strip() or "（还没写）")]
    tags = card.get("tags") or []
    if isinstance(tags, list) and tags:
        bits.append("标签：" + "、".join(str(t) for t in tags[:6]))
    accent = str(card.get("accent") or "").strip()
    if re.match(r"^#[0-9a-fA-F]{6}$", accent):
        bits.append("这张卡的强调色：" + accent)
    body = str(card.get("body") or "").strip()
    if body:
        bits.append("正文（只用它判断主题，不要把文字画进图标）：\n" + body[:500])
    extra = str(hint or "").strip()
    if extra:
        bits.append("用户对图形的要求：" + extra[:200])
    bits.append("现在直接给 SVG。")
    return [{"role": "system", "content": ICON_SYSTEM},
            {"role": "user", "content": "\n\n".join(bits)}]


def parse_studio(raw):
    text = str(raw or "").strip()
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, dict):
                reply = str(data.get("reply") or "").strip()
                card = data.get("card")
                if isinstance(card, dict):
                    return {"ok": True, "reply": reply, "card": _clean_card(card),
                            "raw": text[:2000]}
                return {"ok": True, "reply": reply, "card": None, "raw": text[:2000]}
        except Exception:
            pass
    return {"ok": False, "msg": "AI 没按卡片格式返回", "raw": text[:2000]}
