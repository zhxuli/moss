# ai —— AI 对话

```bash
moss :ai 帮我写个正则      # 问一次，答完退出
moss :ai                   # 多轮对话模式（exit / quit 退出）
```

## 配置（含密钥）

`user_data/state/ai/config.json`：

```json
{ "API_KEY": "", "BASE_URL": "https://api.apifast.tech/v1", "MODEL": "gemini-2.0-flash" }
```

首次运行会自动生成这份模板并提示你去填。**Key 只存在你自己的数据目录里，不在包里。**

> ⚠️ 现在这份 config.json 是**明文**的（照抄旧项目的行为，没改）。
> 账本 `D-07`（密钥放 `user_data/secrets/` + DPAPI 加密）还没定 ——
> 定了之后这里要跟着改，见 `D-07` / `X-11`。

## 参数

一个 `rest: true` 的参数 `prompt`：宿主把包名后面的词全交给它，由包自己拼成一句话
（和旧行为一致）。

## 来历

原样搬自 `QuickTools\bin\cli\ai\main.py`（旧宿主 `pa :ai`），只改了参数来源。
依赖 `openai` 库（自带运行时里已有）。`ai.expose = false`：它会出网、且用你的 key，
不适合让 AI 自己触发。
