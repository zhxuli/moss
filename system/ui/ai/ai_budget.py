# -*- coding: utf-8 -*-
"""AI 工作台的**预算与上下文策略**（`V-238`~`V-244`）。

两块东西存在一起 `user_data/ai/budget.json`（和提示词同一层：不进包、不进 exe，改完立刻生效）：

  ① **这次任务最多烧多少 token**（你定的：默认 1 亿；DeepSeek 闲时 + 缓存命中 99% 时 1 亿才几块钱）
  ② **上下文压缩策略** —— 照 **DSH 那份参数**（`dsh-compaction-basic`）：
     · `thresholdRatio = 0.8`：上下文用到**窗口的 80%** 才开始压
     · `retainRatio   = 0.16`：最新的 **16% 逐字保留**，一个字不动
     · 压缩**触发后先修剪**（本地、不发模型调用）；修剪完已经低于阈值 ⇒ **就到此为止**
     · 它那边"修剪不够就发一次模型摘要"（`maxTokens 8192`）——**我们不做摘要**（那要多花一次
       模型调用）；这条差别写在下面，也写在界面提示里。

★ 为什么"折太勤"是坏事（真机踩过两次）：折掉的内容模型就看不见了，它只会**重读**
  （实测：同一个文件 grep 十几遍）—— 省下的 token 又从重读里花回去。
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent                   # system/ui/ai
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import ai_edits as E                                     # noqa: E402

#: 一百万（界面上"上限"那一格的单位）
M = 1000000
#: 出厂默认：**1 亿 token**
MAX_TOKENS_DEFAULT = 100 * M
#: 到上限的百分之多少就劝它收尾
WARN_PCT = 0.8
#: 兜底的步数上限（不给界面调）
STEPS_BACKSTOP = 200
#: 允许的范围（token）：0.5 百万 ~ 200 亿
MIN_TOKENS = int(0.5 * M)
MAX_TOKENS = 20000 * M

# ---- 上下文压缩策略（`V-244`：照 DSH 的参数）----------------------------------
#: 上下文窗口默认值（没配、也猜不出来时用这个）
CONTEXT_DEFAULT = 128000
#: 用到窗口的多少就开始压（DSH: thresholdRatio 0.8）
THRESHOLD_RATIO = 0.8
#: 最新多少比例**逐字保留**（DSH: retainRatio 0.16）
RETAIN_RATIO = 0.16
#: 常见模型的窗口（猜的；用户可以在 budget.json 里用 `context` 覆盖）
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
    """读当前配置（没有 / 读坏了 ⇒ 用默认）。"""
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
    except Exception:                                                 # noqa: BLE001
        pass
    return cur


def warn_at(max_tokens=None):
    """提醒线（烧到多少 token 就劝一次收尾）。"""
    mt = int(max_tokens or load().get("max_tokens") or MAX_TOKENS_DEFAULT)
    return int(mt * WARN_PCT)


def context_window(model="", override=0):
    """这个模型的上下文窗口多大。

    顺序：显式给的 override → budget.json 里的 `context` → 按模型名猜 → 默认 128k。
    （DSH 那边是从"已路由模型"的元数据拿的；我们没有那张表，所以能猜就猜、能配就配，
      并在界面上把用到的数字显示出来 —— 猜错了你看得见，随时能改。）
    """
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
    """压到多少 token 就开始压缩（DSH：`floor(窗口 × 0.8)`）。"""
    win = context_window(model, context)
    return int(win * THRESHOLD_RATIO)


def retain_tokens(model="", context=0):
    """最新多少 token 逐字保留（DSH：`窗口 × 0.16`）。"""
    win = context_window(model, context)
    return int(win * RETAIN_RATIO)


# ---- 数值校验 / 存取 ---------------------------------------------------------
def check(max_tokens, context=0):
    """校验：回一句人话（None = 通过）。"""
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
        # `V-367`：不拿别的项目（DSH）当依据解释，也不报内部参数名
        return "这个上下文窗口太小：留给收尾的余量反而比触发点还大 —— 把窗口填大一点。"
    return None


def save(max_tokens, context=0):
    """存下来。回 `{ok, max_tokens, context, ...}` 或 `{ok: False, msg}`。"""
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
    """给人看的数字：`32.6k` / `1.5M` / `100M` / `1.2B`。"""
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
    """粗略估一段文本多少 token（**估算**，给"保留多少"用）。

    ★ 为什么是估算：真正的 tokenizer 要引依赖（我们只用标准库），而**触发用的是
      API 回来那个真实的 `prompt_tokens`** —— 触发准、保留量是估的（±30% 量级），
      这个取舍写在界面上，不装作精确。
      折算按"中英混排"取 len/3：纯英文约 4 字符/token、中文约 1.5 字符/token。
    """
    return max(1, int(len(str(text or "")) / 3))
