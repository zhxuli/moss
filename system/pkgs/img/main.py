# -*- coding: utf-8 -*-
"""图片工具 —— 入口 / 模式选择。

一个包，两种用法（`CLI-01`）：

    moss :img                              不带参数 → 打开界面
    moss :img webp 60% 1200 *.png          带参数   → 走命令行

界面优先 WebView（和 exec 同一套外观：pywebview + WebView2 + 设计令牌），
WebView2 或 pywebview 起不来时**自动退回** Tkinter 界面，
保证在没装 WebView2 Runtime 的机器上照样能用。

调试用的强制开关：
    moss :img --tk          即使带了参数也开 Tkinter 界面
    moss :img ui            强制开界面（不带参数时的同义词）
    set MOSS_IMG_UI=tk      环境变量，同上

宿主把「包名后面那一整串」放在 `MOSS_PKG_PARAMS` 的 `args` 字段里
（pkg.json 的 params 上标了 rest:true），本文件只判断它空不空。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def raw_args():
    """拿到宿主给的那一串参数（没有就是空串）。"""
    raw = os.environ.get('MOSS_PKG_PARAMS')
    if raw:
        try:
            got = json.loads(raw).get('args')
            if got:
                return str(got).strip()
        except (ValueError, TypeError):
            pass
    return ' '.join(sys.argv[1:]).strip()


def _pick_ui(tokens):
    """返回 'tk' / 'web' / ''(=先试 web 再退 tk)。"""
    low = [t.lower() for t in tokens]
    if '--tk' in low or '--tkinter' in low:
        return 'tk'
    if '--web' in low or '--webview' in low:
        return 'web'
    want = (os.environ.get('MOSS_IMG_UI') or '').strip().lower()
    return want if want in ('tk', 'web') else ''


def open_ui(tokens):
    want = _pick_ui(tokens)
    if want != 'tk':
        try:
            import gui_web
            gui_web.run_gui()
            return 0
        except Exception as e:
            if want == 'web':
                import traceback
                print('[错误] WebView 界面启动失败: %s' % e, file=sys.stderr)
                traceback.print_exc()
                return 1
            print('[提示] WebView 界面起不来（%s），改用 Tkinter 界面。' % e)
    try:
        import gui_tk
    except Exception as e:
        import traceback
        print('[错误] Tkinter 界面也起不来: %s' % e, file=sys.stderr)
        traceback.print_exc()
        return 1
    gui_tk.run_gui()
    return 0


def main():
    text = raw_args()

    # 没参数 → 界面。这就是「一个包两种用法」的分岔点，只此一处。
    if not text:
        return open_ui([])

    tokens = text.split()
    low = [t.lower() for t in tokens]
    if low and low[0] in ('ui', 'gui', '--ui', '--gui'):
        return open_ui(tokens[1:])

    import cli
    return cli.run(tokens)


if __name__ == '__main__':
    sys.exit(main())
