import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import ai_edits as E

M = 1000000
MAX_TOKENS_DEFAULT = 100 * M
WARN_PCT = 0.8
MIN_TOKENS = int(0.5 * M)
MAX_TOKENS = 20000 * M

CONTEXT_DEFAULT = 128000
THRESHOLD_RATIO = 0.8
RETAIN_RATIO = 0.16
MODEL_CONTEXT = (
    ("deepseek", 128000),
    ("gpt-4", 128000), ("gpt-4o", 128000), ("o1", 200000), ("o3", 200000),
    ("gemini", 1000000),
    ("kimi", 256000), ("moonshot", 256000),
    ("qwen", 131072), ("glm", 128000), ("yi", 16384),
    ("claude", 200000),
    ("llama", 131072), ("qwen2", 131072), ("mistral", 32768),
)

def path():
    return E.user_data() / "ai" / "budget.json"

def load():
    cur = {"max_tokens": MAX_TOKENS_DEFAULT, "context": 0}
    try:
        p = path()
        if p.is_file():
            got = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(got, dict):
                if got.get("max_tokens"):
                    cur["max_tokens"] = int(got["max_tokens"])
                if got.get("context"):
                    cur["context"] = int(got["context"])
    except Exception:
        pass
    return cur

def warn_at(max_tokens=None):
    mt = int(max_tokens or load().get("max_tokens") or MAX_TOKENS_DEFAULT)
    return int(mt * WARN_PCT)

def context_window(model="", override=0):
    for v in (override, load().get("context")):
        try:
            if v and int(v) > 0:
                return int(v)
        except (TypeError, ValueError):
            pass
    low = str(model or "").lower()
    for key, size in MODEL_CONTEXT:
        if key in low:
            return size
    return CONTEXT_DEFAULT

def compact_at(model="", context=0):
    win = context_window(model, context)
    return int(win * THRESHOLD_RATIO)

def retain_tokens(model="", context=0):
    win = context_window(model, context)
    return int(win * RETAIN_RATIO)

def check(max_tokens, context=0):
    try:
        mt = int(max_tokens)
    except (TypeError, ValueError):
        return "要填一个数（单位：百万 token）。"
    if mt < MIN_TOKENS:
        return ("太小了：最少 %.1f 百万 —— 一次正经任务就要几万到几十万 token，"
                "上限设太小只会让活干到一半被掐。" % (MIN_TOKENS / float(M)))
    if mt > MAX_TOKENS:
        return "太大了（上限 %d 百万）—— 想「基本不限」就填 %d。" % (MAX_TOKENS // M, MAX_TOKENS // M)
    try:
        ctx = int(context or 0)
    except (TypeError, ValueError):
        return "上下文窗口要填整数（token 数）。"
    if ctx and not (2000 <= ctx <= 10000000):
        return "上下文窗口不合理（2000 ~ 1000 万之间；留空就按模型名猜）。"
    if ctx and retain_tokens(context=ctx) >= compact_at(context=ctx):
        return "这个上下文窗口太小：留给收尾的余量反而比触发点还大 —— 把窗口填大一点。"
    return None

def save(max_tokens, context=0):
    bad = check(max_tokens, context)
    if bad:
        return {"ok": False, "msg": bad}
    cur = {"max_tokens": int(max_tokens), "context": int(context or 0)}
    try:
        p = path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cur, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as e:
        return {"ok": False, "msg": "存不下来：%s" % e}
    return dict(cur, ok=True, warn=warn_at(cur["max_tokens"]),
                compact_at=compact_at(context=cur["context"]),
                retain=retain_tokens(context=cur["context"]), path=str(p))

def human(n):
    try:
        v = float(n or 0)
    except (TypeError, ValueError):
        return "0"
    for unit, div in (("B", 1000000000.0), ("M", 1000000.0), ("k", 1000.0)):
        if v >= div:
            s = "%.2f" % (v / div) if unit == "k" else "%.1f" % (v / div)
            if s.endswith(".0"):
                s = s[:-2]
            return s + unit
    return "%.0f" % v

def est_tokens(text):
    return max(1, int(len(str(text or "")) / 3))
