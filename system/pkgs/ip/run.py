# -*- coding: utf-8 -*-
"""IP 查询 —— 查询 IP 归属信息

★ 从旧项目的 exec 命令迁移而来：
    QuickTools/user_data/exec/cmds/ip.json

  迁移时只改了【参数的取法】，业务逻辑一行没动（照抄原则 E-20）。
  末尾追加了一段结构化返回（纯增量）。
"""

import os, sys, urllib.request, json

# 参数：moss 通过 MOSS_PKG_PARAMS 传 JSON（类型化参数通道）。
# 旧版（exec 命令）读的是 sys.argv[1] —— 那套在新系统里已经不存在了。
try:
    _params = json.loads(os.environ.get("MOSS_PKG_PARAMS") or "{}")
except Exception:
    _params = {}
target_ip = str(_params.get("target") or "").strip()

try:
    if target_ip:
        print(f'正在查询指定IP: {target_ip} ...')
        req = urllib.request.urlopen(f'http://ip-api.com/json/{target_ip}?lang=zh-CN')
    else:
        print('正在查询本机当前网络IP...')
        req = urllib.request.urlopen('http://ip-api.com/json/?lang=zh-CN')
    
    data = json.loads(req.read())
    if data.get('status') == 'success':
        print(f"IP地址: {data.get('query')}")
        print(f"位置: {data.get('country')} {data.get('regionName')} {data.get('city')}")
        print(f"运营商: {data.get('isp')}")
    else:
        print('查询失败。')
except Exception as e:
    print(f'请求出错: {e}')

def _result():
    """结构化返回（新增）。

    ⚠️ 必须用 globals() —— 函数体内的 locals() 只有这个函数自己的局部变量，
       拿不到模块级的 data，会永远返回空。
       data 在异常路径上可能不存在，所以用 globals().get 兜一下。
    """
    d = globals().get("data") or {}
    if not isinstance(d, dict) or d.get("status") != "success":
        return {"ok": False, "raw": str(d)[:200]}
    return {
        "ok": True,
        "ip": d.get("query"),
        "country": d.get("country"),
        "region": d.get("regionName"),
        "city": d.get("city"),
        "isp": d.get("isp"),
    }


# ---------------------------------------------------------------- 结构化返回
# 这一段是迁移时【新增】的（上面的逻辑一行没动）。
# 作用：把结果写进宿主给的 MOSS_RESULT_FILE，宿主读回来当 data ——
# 这样界面和 AI 拿到的是结构化数据，不用去解析人类可读的 print 文本。
_rf = os.environ.get("MOSS_RESULT_FILE")
if _rf:
    try:
        with open(_rf, "w", encoding="utf-8") as _f:
            json.dump(_result(), _f, ensure_ascii=False)
    except Exception:
        pass

