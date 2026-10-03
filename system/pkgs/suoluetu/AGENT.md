# suoluetu —— 图标修复

```bash
moss :suoluetu
```

## 它到底会做什么

1. `taskkill /f /im explorer.exe` —— **把资源管理器关掉**（桌面和任务栏会消失一下）
2. 删 `%LOCALAPPDATA%\IconCache.db`（还有 `iconcache*` / `thumbcache*`）
3. 等 2 秒（`timeout /t 2`；**在 moss 下这句其实没等** —— 见下面「已知坑」）
4. 没在跑就 `start explorer.exe` 把它拉回来（`tasklist | find` 判一下，别起两个）

所以：桌面上有没保存的东西、正在开的资源管理器窗口，都会被打断 —— 这是这个脚本本来的行为，
不是新加的。它不需要管理员权限。

## 已知坑（`V-220`，真踩过）

- **`start "" explorer.exe` 会让 moss 以为这个包还在跑**：宿主给包的进程注入了
  `MOSS_PKG_ID=suoluetu`，它**会被 explorer.exe 继承**，而 explorer 又占着桌面/任务栏那些窗口
  ⇒ 宿主"按进程认"的那条判据命中：**界面上的「停止」永远亮着（重启 moss 也照样）**，
  而且点下去会把 **explorer 一起杀掉**（桌面和任务栏当场消失）。
  宿主那边已经改成"有窗口的进程，**可执行文件必须真在包目录里**才算"（`V-220`），
  explorer.exe 不再被算进来；但**包自己**也该守规矩：**别 `start` 长驻的外部程序**
  （细节见契约 §8 第 16 条）。
- **`.bat` 里的 `timeout /t N` 在 moss 下不等**：宿主给的 stdin 是管子，
  `timeout` 遇到 stdin 重定向会立刻报错退出。要真等就用 `ping -n <N+1> 127.0.0.1 >nul`。

## 参数

无。`runner` 是 `shell`，入口就是这个 `.bat`（**一个字节没改**，照抄旧项目）。

## 来历

原样搬自 `QuickTools\bin\cli\suoluetu\main.bat`（旧宿主 `pa :suoluetu`），
**后来改过两处**（`V-220` 那轮）：① 去掉末尾的 `pause`（原来要按一下键才结束），
② `start explorer.exe` 前面加了 `tasklist | find` 判断，别起两个资源管理器。
`ai.expose = false`：它会重启资源管理器，不适合让 AI 自动触发。
