import webview
import psutil
import time
import os
import sys
import json
import subprocess # 【新增】用于打开系统文件管理器

application_path = os.path.dirname(sys.executable) if 'python' not in os.path.basename(sys.executable).lower() else os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.path.abspath(sys.path[0])
html_file = os.path.join(application_path, 'index.html')

class Api:
    def __init__(self):
        self.blacklist = set()

    def kill_process(self, pid):
        try:
            p = psutil.Process(int(pid))
            p.kill()
            return {'status': 'success', 'message': f'已击杀进程 PID: {pid}'}
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            return {'status': 'error', 'message': f'无法结束 {pid}: 权限不足或已退出'}
        except Exception as e:
            return {'status': 'error', 'message': f'未知错误: {str(e)}'}

    # --- 【新增】打开文件位置 ---
    def open_file_location(self, path):
        if not path or not os.path.exists(path):
            return {'status': 'error', 'message': '路径不存在或无法访问'}
        try:
            if sys.platform == 'win32':
                # Windows: 打开资源管理器并选中该文件
                subprocess.run(['explorer', '/select,', os.path.normpath(path)])
            elif sys.platform == 'darwin':
                # macOS: 在 Finder 中显示
                subprocess.run(['open', '-R', path])
            else:
                # Linux: 打开所在文件夹
                subprocess.run(['xdg-open', os.path.dirname(path)])
            return {'status': 'success'}
        except Exception as e:
            return {'status': 'error', 'message': f'打开路径失败: {str(e)}'}

    def get_blacklist(self):
        return list(self.blacklist)

    def add_blacklist(self, name):
        self.blacklist.add(name.lower().strip())
        return {'status': 'success'}

    def remove_blacklist(self, name):
        name_lower = name.lower().strip()
        if name_lower in self.blacklist:
            self.blacklist.remove(name_lower)
        return {'status': 'success'}


def get_system_data(window, api):
    for p in psutil.process_iter():
        try:
            p.cpu_percent()
        except:
            pass

    while True:
        try:
            procs = []
            current_blacklist = api.blacklist.copy()

            for p in psutil.process_iter(['pid', 'name', 'username', 'status', 'memory_percent', 'exe']):
                try:
                    p_name = p.info['name']
                    
                    if p_name and p_name.lower() in current_blacklist:
                        p.kill()
                        print(f"🗡️ 黑名单触发：已自动击杀 {p_name} (PID: {p.info['pid']})")
                        continue 

                    cpu_percent = p.cpu_percent()
                    
                    if cpu_percent > 0.01 or len(procs) < 100:
                        procs.append({
                            'pid': p.info['pid'],
                            'name': p_name,
                            'exe': p.info.get('exe') or '', 
                            'user': p.info.get('username') or 'N/A',
                            'status': p.info['status'],
                            'cpu': f"{cpu_percent:.1f}",
                            'mem': f"{p.info.get('memory_percent', 0):.1f}"
                        })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            perf_data = {
                'cpu': psutil.cpu_percent(),
                'mem': psutil.virtual_memory().percent
            }

            net_data = []
            try:
                pid_map = {p.pid: p.info['name'] for p in psutil.process_iter(['pid', 'name'])}
                for conn in psutil.net_connections():
                    if conn.pid and conn.status == 'ESTABLISHED':
                        net_data.append({
                            'pid': conn.pid,
                            'name': pid_map.get(conn.pid, 'N/A'),
                            'laddr': f"{conn.laddr.ip}:{conn.laddr.port}" if conn.laddr else "",
                            'raddr': f"{conn.raddr.ip}:{conn.raddr.port}" if conn.raddr else "",
                            'status': conn.status
                        })
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                 net_data = "权限不足，请尝试以管理员身份运行以查看完整网络连接。"

            if window:
                window.evaluate_js(f"updateProcessTable({json.dumps(procs)})")
                window.evaluate_js(f"updatePerformanceCharts({json.dumps(perf_data)})")
                window.evaluate_js(f"updateNetworkTable({json.dumps(net_data)})")

        except Exception as e:
            pass

        time.sleep(2)

if __name__ == '__main__':
    api = Api()
    window = webview.create_window(
        'Advanced Task Manager Pro',
        html_file,
        js_api=api,
        width=1200,
        height=800,
        resizable=True
    )
    webview.start(get_system_data, (window, api))