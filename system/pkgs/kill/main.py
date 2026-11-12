import sys
import time

import psutil
import questionary

def kill_processes(processes):
    success, failed = 0, 0
    for p in processes:
        try:
            try:
                children = p.children(recursive=True)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                children = []

            for c in children:
                try:
                    c.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            p.terminate()
            p.wait(timeout=3)

            psutil.wait_procs(children, timeout=3)

            success += 1
        except Exception:
            failed += 1
    return success, failed

def _query():
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
    for arg in sys.argv[1:]:
        if arg in ("-c", "") or arg.endswith("main.py"):
            continue
        return arg.strip()
    return ""

def main():
    query = _query()
    if not query:
        print("请提供搜索参数，例如: moss :kill node 或 moss :kill 8080")
        sys.exit(1)

    is_numeric = query.isdigit()

    matched_processes = []

    if is_numeric:
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
                p.cpu_percent(interval=None)
                matched_processes.append(p)
            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                print(f"无法访问 PID {pid}: {e}")
    else:
        for p in psutil.process_iter(['pid', 'name', 'exe', 'memory_info']):
            try:
                name = p.info['name']
                if not name:
                    continue
                if query.lower() in name.lower():
                    p.cpu_percent(interval=None)
                    matched_processes.append(p)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass

    if not matched_processes:
        print(f"未找到与参数 '{query}' 匹配的任何进程或端口。")
        return

    time.sleep(0.1)

    pid_ports = {}
    try:
        for conn in psutil.net_connections(kind='inet'):
            if conn.pid and conn.status == 'LISTEN':
                pid_ports.setdefault(conn.pid, set()).add(conn.laddr.port)
    except psutil.AccessDenied:
        pass

    grouped_data = {}
    for p in matched_processes:
        try:
            name = p.name()
            exe_path = p.exe() or "(路径读取失败，可能需要管理员权限)"

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

    choices = []
    max_name_len = max([len(data["name"]) for data in grouped_data.values()] + [15])

    for path, data in grouped_data.items():
        name = data["name"]
        count = len(data["procs"])
        cpu = data["cpu_total"]
        mem = data["mem_total"]

        port_str = ", ".join(map(str, data["ports"])) if data["ports"] else "-"

        line1 = f"{name:<{max_name_len}} │ {count:>3} 个进程 │ CPU: {cpu:>5.1f}% │ 内存: {mem:>7.1f} MB │ 端口: {port_str}"
        line2 = f"   └─ 路径: {path}"

        title = f"{line1}\n{line2}"
        choices.append(questionary.Choice(title, value=path))

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
