import hashlib
import json
import os
import re
import time
import uuid
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

STUDIO_SYSTEM = """你是 moss 的「经验卡编辑」。
用户会把一条经验、避坑、偏好或一次任务的教训交给你，你要把它整理成一张短小、可执行、可复用的经验卡。

必须只输出一个 JSON 对象，不要 Markdown 代码块，不要解释：
{
  "reply": "给用户看的中文回复，说明你改了什么，不超过 120 字",
  "card": {
    "id": "小写字母开头的短 id，可省略；新卡用 title 自动生成",
    "icon": "从给定图标中选一个",
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
"""
STUDIO_SYSTEM = STUDIO_SYSTEM.replace("ICON_CHOICES", "、".join(ICON_CHOICES))


def _dir():
    return E.user_data() / "ai" / "cards"


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
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    return {"id": cid, "title": title, "body": body, "tags": tags,
            "icon": icon, "accent": accent,
            "created": str(old.get("created") or raw.get("created") or now),
            "updated": now}


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
        card = _clean_card(raw)
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
        return _clean_card(json.loads(p.read_text(encoding="utf-8")))
    except Exception:
        return None


def save_card(raw):
    old = {}
    cid_hint = ""
    if isinstance(raw, dict):
        cid_hint = str(raw.get("id") or "").strip()
    if cid_hint:
        old = get_card(cid_hint) or {}
    card = _clean_card(raw, old)
    if not card.get("title") or not card.get("body"):
        return {"ok": False, "msg": "标题和正文都要有"}
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
        p = d / (card["id"] + ".json")
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(card, ensure_ascii=False, indent=1) + "\n",
                       encoding="utf-8")
        os.replace(str(tmp), str(p))
    except OSError as e:
        return {"ok": False, "msg": "存不下来：%s" % e}
    card["chars"] = len(card.get("body") or "")
    card["tokens"] = _est(card.get("body") or "")
    return {"ok": True, "card": card}


def delete_card(cid):
    cid = _safe_id(cid)
    p = _dir() / (cid + ".json")
    try:
        p.unlink()
        return {"ok": True}
    except FileNotFoundError:
        return {"ok": False, "msg": "没有这张卡"}
    except OSError as e:
        return {"ok": False, "msg": "删不掉：%s" % e}


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
        cur = "\n\n当前卡片（请在此基础上修改，不要丢掉仍适用的内容）：\n" + json.dumps(
            card, ensure_ascii=False)
    msgs.append({"role": "user", "content": str(text or "").strip() + cur})
    return msgs


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