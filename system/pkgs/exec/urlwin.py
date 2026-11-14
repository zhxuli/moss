"""把网址用 pywebview 自己的窗口打开。

由 core._open_url_in_window() 拉成一个独立进程跑 —— pywebview 的 GUI 循环必须占住
主线程，放在插件进程里会和已经起来的界面抢线程。
"""
import sys


def main():
    url = sys.argv[1].strip() if len(sys.argv) > 1 else ''
    if not url:
        print('没有给网址。')
        return 2

    import webview

    title = url.split('://', 1)[-1]
    webview.create_window(title, url=url, width=1200, height=840, min_size=(480, 360))
    webview.start()
    return 0


if __name__ == '__main__':
    sys.exit(main())
