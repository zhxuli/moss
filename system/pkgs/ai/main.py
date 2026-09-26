#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""AI 对话 —— 读数据目录里的 config.json，调 OpenAI 兼容接口。

    moss :ai 帮我写个正则          一次性提问，答完就退出
    moss :ai                       不给问题 → 进多轮对话模式（exit/quit 退出）

配置与密钥
----------
放在**插件自己的数据目录**里的 `config.json`（= `user_data/state/ai/config.json`）：

    {
      "API_KEY":  "填你的 key",
      "BASE_URL": "https://api.apifast.tech/v1",
      "MODEL":    "gemini-2.0-flash"
    }

文件不存在时会**自动落一份模板**（`API_KEY` 是空的），然后提示你去填 ——
所以密钥从来不在包里，只在你自己的数据目录里（旧项目就是这么设计的，没改）。

移植说明（2026-09-27）：原样搬自旧项目 `pa_soft\bin\cli\ai\main.py`，
**对话、流式输出、多轮模式、配置格式全部一字未改**。只改一处宿主差异：
参数来源（老 pa 拼进 argv；新宿主 moss 放 `MOSS_PKG_PARAMS` / `MOSS_ARGS`）。
"""
# main.py
import sys
import os
import json
from openai import OpenAI

# --- 路径: 插件目录 / 插件专属数据目录 ---
# 兼容通过 exec() 或者 python -c 启动时没有 __file__ 变量的情况
if '__file__' in globals():
    PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
else:
    PLUGIN_DIR = sys.path[0] if sys.path else os.getcwd()

# 宿主 pa 注入的插件专属数据目录 (user_data/<插件目录名>)；独立运行时退回插件目录
DATA_DIR = (os.environ.get('MOSS_PLUGIN_DATA_DIR')
            or os.environ.get('PA_PLUGIN_DATA_DIR')   # 老 pa，保留兜底
            or PLUGIN_DIR)
CONFIG_FILE = os.path.join(DATA_DIR, 'config.json')

# --- AI核心配置 ---
# 系统提示词, 强制AI精简回复
SYSTEM_PROMPT = "You are a helpful assistant. Keep your answers concise and to the point."

DEFAULT_CONFIG = {
    "API_KEY": "",
    "BASE_URL": "https://api.apifast.tech/v1",
    "MODEL": "gemini-2.0-flash",
}


def load_config():
    """从插件数据目录读取配置；首次运行只落一份模板，不再把密钥打进包里。"""
    cfg = dict(DEFAULT_CONFIG)
    config_path = CONFIG_FILE

    if os.path.isfile(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                cfg.update(loaded)
        except Exception as e:
            print(f"[配置] 读取配置失败: {e}. 将使用默认设置。")
    else:
        # 懒加载：只有真正写入配置时才创建数据目录
        print("[配置] 未找到配置文件，将为您自动创建一个。")
        try:
            if not os.path.isdir(DATA_DIR):
                os.makedirs(DATA_DIR, exist_ok=True)
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
            print(f"[配置] 成功创建配置文件: {config_path}")
        except Exception as e:
            print(f"[配置错误] 无法创建配置文件: {e}")
            print("[配置] 将在本次运行中使用默认设置。")

    # 兼容旧的同目录 config.py：数据目录里还没填 key 时沿用它的值
    if not cfg.get("API_KEY"):
        try:
            import config as _legacy
            cfg["API_KEY"] = getattr(_legacy, "API_KEY", "") or cfg["API_KEY"]
            cfg["BASE_URL"] = getattr(_legacy, "BASE_URL", "") or cfg["BASE_URL"]
            cfg["MODEL"] = getattr(_legacy, "MODEL", "") or cfg["MODEL"]
        except ImportError:
            pass

    return cfg


CFG = load_config()

if not CFG.get("API_KEY"):
    print(f"错误：未配置 API_KEY，请在以下文件中填写后重试：")
    print(f"  {CONFIG_FILE}")
    sys.exit(1)

# 初始化客户端
try:
    client = OpenAI(
        api_key=CFG["API_KEY"],
        base_url=CFG["BASE_URL"],
    )
except Exception as e:
    print(f"错误：AI 客户端初始化失败: {e}")
    sys.exit(1)


def _split_args(s):
    r"""按空白拆参数，但**不碰反斜杠**（shlex 会吃掉 Windows 路径里的 `\`，见 `E-06`）。"""
    out, cur, quote = [], "", None
    for ch in s:
        if quote:
            if ch == quote:
                quote = None
            else:
                cur += ch
        elif ch in "\"'":
            quote = ch
        elif ch.isspace():
            if cur:
                out.append(cur)
                cur = ""
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out


def _moss_args():
    """从宿主拿参数；拿不到返回 None（调用方退回 sys.argv）。

    新宿主 moss 把参数放在 `MOSS_PKG_PARAMS`（JSON，键是 pkg.json 里声明的参数名）
    和 `MOSS_ARGS`（原始字符串）两个环境变量里，**不会**往 argv 塞用户参数 ——
    而老 pa 是把参数拼进 argv 的。这就是移植时必须改的那一处。
    """
    import json as _json
    import os as _os

    raw = _os.environ.get("MOSS_PKG_PARAMS")
    if raw:
        try:
            p = _json.loads(raw) or {}
            if p.get("args"):
                return _split_args(str(p["args"]))
        except Exception:
            pass
    raw = _os.environ.get("MOSS_ARGS")
    if raw:
        return _split_args(raw)
    return None


def _moss_prompt():
    r"""取出「这一次要问什么」—— 是一整串（本包声明了 rest，剩下的词全归它）。

    新宿主放在 `MOSS_PKG_PARAMS` / `MOSS_ARGS` 里；读不到才退回 `sys.argv[1:]`。
    末尾那个 `.replace('" "', "")` 是**照抄旧代码**的（老宿主把参数拼成字符串时
    会留下这种引号痕迹），不是新加的清理逻辑。
    """
    import os as _os

    raw = _os.environ.get("MOSS_PKG_PARAMS")
    if raw:
        try:
            p = json.loads(raw) or {}
            if p.get("prompt"):
                return str(p["prompt"]).replace('" "', "")
        except Exception:
            pass
    raw = _os.environ.get("MOSS_ARGS")
    if raw:
        return raw.strip().replace('" "', "")
    if len(sys.argv) > 1:
        return " ".join(sys.argv[1:]).replace('" "', "")
    return ""


def get_ai_response(messages_history):
    """请求AI并流式打印回复，返回完整的AI回复内容"""
    full_response_content = ""
    try:
        stream = client.chat.completions.create(
            model=CFG["MODEL"],
            messages=messages_history,
            stream=True
        )
        for chunk in stream:
            if chunk.choices and len(chunk.choices) > 0:
                if content := chunk.choices[0].delta.content:
                    print(content, end="", flush=True)
                    full_response_content += content
        print()
        return full_response_content
    except Exception as e:
        print(f"\nAPI调用出错: {e}")
        return ""


def main():
    user_prompt = _moss_prompt()
    if user_prompt:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ]
        get_ai_response(messages)
    else:
        print("已进入多轮对话模式。输入 'exit' 或 'quit' 退出。")
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        while True:
            try:
                user_input = input("You: ")
                if user_input.lower() in ["exit", "quit"]:
                    break

                messages.append({"role": "user", "content": user_input})

                print("AI: ", end="")
                ai_reply = get_ai_response(messages)

                if ai_reply:
                    messages.append({"role": "assistant", "content": ai_reply})

            except (KeyboardInterrupt, EOFError):
                break
        print("\n再见!")


if __name__ == "__main__":
    main()
