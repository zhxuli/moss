import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

def raw_args():
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
    try:
        from embed import Embedded, embedded_now
        if embedded_now():
            return Embedded().loop()
    except ImportError:
        pass

    text = raw_args()

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
