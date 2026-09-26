# dsh —— DSH 桥（本机桥守护进程）

> ⚠️ **先看这段：这个包不是「下载就能用」的单体。** 它是「DeepSeek Harness 远程访问」
> **两半系统里的本机半边**，另一半（服务器）不在这个包里。别人要用它，必须先满足：
>
> | 前置 | 说明 | 没有会怎样 |
> |---|---|---|
> | **① 装了 DSH 本体** | `node` + `@deepseek-ai/dsh`（npm 全局或 npx 缓存都行，桥会自己找） | 3080 拉不起来，日志里是「启动 DSH 失败」 |
> | **② 有「服务器那一半」** | 隧道对面那套 uvicorn 服务（作者那边在 `ZeEn/main.py`）。设置向导里只有两个选项：`本地测试 ws://localhost:8633`（自己在本机跑服务端）或 `线上使用 wss://zeen.xin`（作者的线上服务，**别人的账号连不上**） | 桥连得上 DSH，但手机/外网进不来 |
> | **③ 自己的 token / 密码** | token 是**服务器那一半所属账号**的登录 token；密码是你在设置页自己设的本机密码 | 设置页会一直停在第 2 步 |
>
> 这三样都是**外部依赖**，不是这个包的 bug —— 本包只能负责「本机这半边」。
> 相关环境变量（都不设也能跑，只是不够明确）：
> `DSH_BRIDGE_CWD`（DSH 的工作目录＝DSH 里的工作区）、
> `DSH_PYTHON` / `DSH_PYTHONW`（换解释器，默认用 moss 自带运行时）。


## 这是什么

`main.py` 是**本机桥守护进程**，是「DeepSeek Harness 远程访问」的本机那一半：

- 从本机**主动连出**一条 WebSocket 长连到 zeen.xin（或本地调试服务器），
  靠主动连出做 **NAT 穿透**，让手机/外网能访问这台机器上的 DSH。
- 提供**本机密码门**：密码用 scrypt 加盐哈希只存本机；没带本机会话票据的请求
  被劫持成设置页（`unlock.html`），验过密码才由本机签发 `dsh_session` 票据。
- 把隧道请求转发到 `127.0.0.1:3080`（DSH 本体），响应分块流式回传。
- 顺带两件与本机文件有关的事：`/file.fetch` 直传本机文件、`/file.view` 渲染
  `file_viewer.html` 显示页（前端资源在 `viewer/`）。
- 还有一个「3080 监护」：发现 DSH 本体没在跑就自动拉起。

## 怎么起

```
moss :dsh                 前台运行（日志直接打在控制台，Ctrl+C 停止）
moss :dsh --status        看配置摘要（不连网）
moss :dsh --daemon        转后台守护运行
moss :dsh --no-browser    启动时不自动打开设置页
moss :dsh --set-token     更换 zeen token
moss :dsh --set-password  更换本机二级密码
```

首次使用：`moss :dsh` → 自动打开本地设置向导 <http://127.0.0.1:8788/>，
依次做「1 选服务器 → 2 登录（验证码 + 账号）→ 3 设本机密码 → 4 连接」。
配置齐全后每次启动会自动连。

★ `pkg.json` 里写的是 `ai.expose: false` / `risk: high`：它是**长驻联网服务**，
不要让 AI 自动把它拉起来。

## 它连哪儿

| 方向 | 地址 |
|---|---|
| 桥 → 服务器 | `wss://zeen.xin`（线上）或 `ws://localhost:8633`（本地测试） |
| 注册路径 | `/dsh/bridge/ws`（配置里只写主机，路径由程序拼） |
| 桥 → DSH 本体 | `http://127.0.0.1:3080`，WebSocket 中继 `ws://127.0.0.1:3080<path>` |
| 对外监听 | `127.0.0.1:8788`（仅本机，设置向导） |

## 数据放哪

全部在宿主注入的 **`MOSS_PLUGIN_DATA_DIR`**（= `user_data/state/dsh/`）：

| 文件 | 是什么 |
|---|---|
| `dsh_bridge.json` | 配置：服务器、zeen token、本机密码（scrypt 哈希）、票据有效期等 |
| `dsh.pid` | 上次运行的 PID，用于启动时接管旧实例 |
| `dsh.log` | `--daemon` 模式下的日志 |
| `dsh3080.log` | DSH 本体的输出（桥也从这里捡 DSH 的启动令牌交换 cookie） |

没有东西写在自己的包目录里。老 pa 的 `PA_PLUGIN_DATA_DIR` 仍作兜底。

## 危险点

- **会开端口、会联网**：8788 本机监听 + 主动长连外网，等于给这台机器开了一条
  进来的通道（正是它的用途，但要清楚你在开什么）。
- **会读写本机文件**：`/file.fetch` 与 `/file.view` 默认**不做目录白名单**，
  只要过了桥的两道鉴权（zeen 登录 token + 二级密码票据），就能取本机任意可读
  文件。想限定范围得自己往 `dsh_bridge.json` 里加 `file_roots`。
- **会结束别的进程**：启动时按 `dsh.pid` 和 8788 端口占用者做「单实例接管」
  （`taskkill /F`），还会在 3080 不在时用 npx/node 把 DSH 本体拉起来。
- **凭据在配置里是明文**：`dsh_bridge.json` 里的 zeen token 不是加密存储，
  那份文件泄漏等于账号被顶。
- **密码尝试有锁定**：5 次 / 30 秒窗口 → 锁 300 秒，别拿它做压测。

## 来历

从旧项目 `QuickTools/pa_soft/bin/soft/dsh/` **机械移植**而来（见 `pkg.json` 的
`origin`）。除"宿主管道"外代码一字未改，具体改动（对着旧文件看）：

1. 数据目录优先读 `MOSS_PLUGIN_DATA_DIR`，`PA_PLUGIN_DATA_DIR` 保留兜底。
2. 依赖自举里那条写死的旧路径兜底，改成"以脚本自身所在目录为准"。
3. 依赖自举的 venv 重执行：`MOSS_PLUGIN_DATA_DIR` 存在（= 跑在 moss 里）时
   直接跳过，老宿主逻辑原样保留。
4. 包参数改成优先读 `MOSS_PKG_PARAMS` / `MOSS_ARGS`，读不到才退回 `sys.argv`。
5. 文案里的 `pa :dsh` 改成 `moss :dsh`。

## 已知事项（移植遗留，待拍板）

`file_viewer.html` 里对 `viewer/` 资源的引用写的是**旧项目的绝对路径**
（`D:\python\two\QuickTools\pa_soft\bin\soft\dsh\viewer\...`）。移植时按"不动
前端"的要求原样拷贝，因此显示页目前仍从旧目录取那 8 个资源文件；哪天旧目录
没了就会掉样式/脚本。要修的话，把这 8 条 URL 的 path 参数改成运行时本包目录即可。
