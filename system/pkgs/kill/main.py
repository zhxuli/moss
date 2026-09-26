#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""杀进程 —— 按进程名（模糊匹配）或端口号结束进程。

    moss :kill node       按名字杀：进程名里**包含** node 的都算命中（不分大小写）
    moss :kill 8080       按端口杀：找正在**监听** 8080 的那个进程

命中之后不是直接杀，而是先列出来让你选：
    同一个可执行文件的进程会被合并成一组，菜单里显示
    「名字 │ 几个进程 │ CPU │ 内存 │ 占用端口」+ 它的路径，
    上下键选一组回车 = 杀这一组；也可以选「清理以上全部进程」。
    terminate() 之后等最多 3 秒；进程赖着不退就算失败（不升级成 kill -9）。

移植说明（2026-09-27，`D-14`）
----------------------------
原样搬自旧项目 `pa_soft\\bin\\cli\\kill\\main.py`（旧宿主里是 `pa :kill`）。
**判定与杀进程的逻辑一字未改** —— 缓存、分组、菜单、超时全部照抄。
只动了三处「宿主差异」，不是功能改动：
  ① 参数来源：宿主 moss 把参数放在 `MOSS_PKG_PARAMS` / `MOSS_ARGS` 里
     （老 pa 是把参数拼成字符串塞进 argv）。读不到这两个环境变量时
     仍按 `sys.argv` 取，方便直接 `python main.py node` 调试。
  ② 用法提示里的命令名：`python main.py x` → `moss :kill x`。
  ③ 返回值：照抄原来的 `sys.exit(1)`（没给参数时），宿主只记退出码、不当报错打。

依赖：`psutil`、`questionary` —— **都在自带运行时里**（`system/runtimes/python/3.12`），
用户不需要自己装。
"""
import sys
import time

import psutil
import questionary


def kill_processes(processes):
    """terminate + 最多等 3 秒。返回 (成功数, 失败数)。**照抄旧实现。**"""
    success, failed = 0, 0
    for p in processes:
        try:
            p.terminate()
            p.wait(timeout=3)
            success += 1
        except Exception:
            failed += 1
    return success, failed


def _query():
    """取出「要搜什么」这一个参数。

    宿主 moss 把包参数放在 `MOSS_PKG_PARAMS`（JSON）里的 query 字段 ——
    优先用它；没有就退回 `MOSS_ARGS`（原样字符串）；再没有才按 sys.argv 取，
    这样 `python main.py node` 这种直接调试也照旧能用（见文件头的 ①）。
    """
    import json as _json
    import os as _os

    raw = _os.environ.get("MOSS_PKG_PARAMS")
    if raw:
        try:
            q = (_json.loads(raw) or {}).get("query")
            if q not in (None, ""):
                return str(q).strip()
        except Exception:
            pass
    raw = _os.environ.get("MOSS_ARGS")
    if raw:
        return raw.strip()
    # 直接调试时的兜底：跳过脚本自己和那些解释器参数，取第一个真参数
    for arg in sys.argv[1:]:
        if arg in ("-c", "") or arg.endswith("main.py"):
            continue
        return arg.strip()
    return ""


def main():
    query = _query()
    if not query:
        # 照抄旧提示，只把命令名换成新的
        print("请提供搜索参数，例如: moss :kill node 或 moss :kill 8080")
        sys.exit(1)

    is_numeric = query.isdigit()

    matched_processes = []

    if is_numeric:
        # 按端口查询：查找监听该端口的进程
        port = int(query)
        pids = set()
        try:
            for conn in psutil.net_connections(kind='inet'):
                if conn.status == 'LISTEN' and conn.laddr.port == port and conn.pid:
                    pids.add(conn.pid)
        except psutil.AccessDenied:
            print("警告：权限不足，可能无法读取所有网络连接。请尝试以管理员身份运行。")
        except Exception as e:
            print(f"查询网络连接时出错: {e}")

        if not pids:
            print(f"未找到监听端口 {port} 的进程。")
            return

        for pid in pids:
            try:
                p = psutil.Process(pid)
                # 初始化 CPU 占用率计算
                p.cpu_percent(interval=None)
                matched_processes.append(p)
            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                print(f"无法访问 PID {pid}: {e}")
    else:
        # 按进程名查询
        for p in psutil.process_iter(['pid', 'name', 'exe', 'memory_info']):
            try:
                name = p.info['name']
                if not name:
                    continue
                if query.lower() in name.lower():
                    # 调用一次 cpu_percent 初始化时间戳，值为 0.0
                    p.cpu_percent(interval=None)
                    matched_processes.append(p)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass

    if not matched_processes:
        print(f"未找到与参数 '{query}' 匹配的任何进程或端口。")
        return

    # 微小的延迟，为了让第二次读取 CPU 占用率时有真实数据
    time.sleep(0.1)

    # 获取全局网络端口映射 (PID -> Ports)，用于显示
    pid_ports = {}
    try:
        for conn in psutil.net_connections(kind='inet'):
            if conn.pid and conn.status == 'LISTEN':
                pid_ports.setdefault(conn.pid, set()).add(conn.laddr.port)
    except psutil.AccessDenied:
        pass  # 非管理员可能无法读取所有网络连接

    # 按“绝对路径”进行分组聚合
    grouped_data = {}
    for p in matched_processes:
        try:
            name = p.name()
            # 如果权限不足无法获取路径，则显示提示
            exe_path = p.exe() or "(路径读取失败，可能需要管理员权限)"

            # 获取实时指标
            cpu = p.cpu_percent(interval=None)
            mem_mb = p.memory_info().rss / (1024 * 1024) if p.memory_info() else 0
            ports = pid_ports.get(p.pid, set())

            if exe_path not in grouped_data:
                grouped_data[exe_path] = {
                    "name": name,
                    "procs": [],
                    "cpu_total": 0.0,
                    "mem_total": 0.0,
                    "ports": set()
                }

            grouped_data[exe_path]["procs"].append(p)
            grouped_data[exe_path]["cpu_total"] += cpu
            grouped_data[exe_path]["mem_total"] += mem_mb
            grouped_data[exe_path]["ports"].update(ports)

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    # 构建排版对齐的多行菜单
    choices = []
    # 动态计算名称列的最大宽度以保证对齐
    max_name_len = max([len(data["name"]) for data in grouped_data.values()] + [15])

    for path, data in grouped_data.items():
        name = data["name"]
        count = len(data["procs"])
        cpu = data["cpu_total"]
        mem = data["mem_total"]

        # 格式化端口展示
        port_str = ", ".join(map(str, data["ports"])) if data["ports"] else "-"

        # 核心格式化：第一行显示对齐的数据，第二行显示缩进的路径
        line1 = f"{name:<{max_name_len}} │ {count:>3} 个进程 │ CPU: {cpu:>5.1f}% │ 内存: {mem:>7.1f} MB │ 端口: {port_str}"
        line2 = f"   └─ 路径: {path}"

        title = f"{line1}\n{line2}"
        choices.append(questionary.Choice(title, value=path))

    # 添加底部操作选项
    separator_len = max_name_len + 60
    choices.extend([
        questionary.Separator("─" * separator_len),
        questionary.Choice("清理以上全部进程", value="ALL"),
        questionary.Choice("取消并退出", value="CANCEL")
    ])

    choice = questionary.select(
        f"找到以下与 '{query}' 相关的进程 (按路径合并)：",
        choices=choices,
        instruction="(↑/↓ 选择, Enter 确认)"
    ).ask()

    # 执行清理
    if not choice or choice == "CANCEL":
        print("已取消。")
        return

    if choice == "ALL":
        all_processes = [p for data in grouped_data.values() for p in data["procs"]]
        success, failed = kill_processes(all_processes)
        print(f"\n执行结果: 成功清理全部匹配项，共终止 {success} 个进程，失败 {failed} 个。")
    else:
        target_processes = grouped_data[choice]["procs"]
        success, failed = kill_processes(target_processes)
        print(f"\n执行结果: 成功终止 {success} 个进程，失败 {failed} 个。")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已取消。")
