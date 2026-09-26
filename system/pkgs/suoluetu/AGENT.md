# suoluetu —— 图标修复

```bash
moss :suoluetu
```

## 它到底会做什么

1. `taskkill /f /im explorer.exe` —— **把资源管理器关掉**（桌面和任务栏会消失一下）
2. 删 `%LOCALAPPDATA%\IconCache.db`
3. `start explorer.exe` 把它拉回来
4. 末尾 `pause`：**要按一下键才结束**（照抄旧脚本，没改）

所以：桌面上有没保存的东西、正在开的资源管理器窗口，都会被打断 —— 这是这个脚本本来的行为，
不是新加的。它不需要管理员权限。

## 参数

无。`runner` 是 `shell`，入口就是这个 `.bat`（**一个字节没改**，照抄旧项目）。

## 来历

原样搬自 `QuickTools\bin\cli\suoluetu\main.bat`（旧宿主 `pa :suoluetu`）。
`ai.expose = false`：它会重启资源管理器，不适合让 AI 自动触发。
