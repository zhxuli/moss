import os
import re
import sys

import core

FORMATS_CLI = ['jpg', 'png', 'webp', 'ico']
DEFAULT_QUALITY = 80

USAGE = """图片工具 · 命令行
用法: moss :img [格式] [质量] [宽度] [文件/通配符...] [选项]
      moss :img                    不带参数就是打开界面

  格式   jpg | png | webp | ico
         **不写 = 保持原格式**（只改质量 / 尺寸，最适合"批量重压一批图"）
  质量   60% 或 60          （≤100 的裸数字，默认 80%）
  宽度   1200 或 1200px     （>100 的裸数字；ico 不用宽度）
  文件   *.png  logo*.jpg  D:\\图\\*.jpg  **/*.webp
         不写 = 当前目录下全部图片
  目录   D:\\图              （给了目录，通配符就相对它解析）
  选项   /                  写回源目录（覆盖原图）
         -o <目录>          输出到指定目录（原图不动）
         **两个都不写 → 弹出菜单让你自己选；菜单里直接回车 = 取消**
         -s 16,32,256       ico 尺寸（默认 16/24/32/48/64/128/256 全要）
         -h                 本帮助
         （-y 仍接受但已无意义：指定了 / 或 -o 就是已经确认过，不会再问）

参数顺序随便，只填你会用到的那几个就行。例子
  moss :img ico a.png -o D:\\out   只把 a.png 转成 ico，放到 D:\\out
  moss :img ico a.png b.png -o D:\\out   只转这两个
  moss :img ico *.png -o D:\\out   只转当前目录的 png
  moss :img ico                  当前所有图 → 多分辨率 ico（然后菜单里选输出到哪）
  moss :img ico /                同上，原地覆盖
  moss :img png                  当前所有图 → png 80%
  moss :img 1200                 当前所有图等比缩到 1200 宽，格式不动
  moss :img 60%                  当前所有图按 60% 质量重压，格式不动
  moss :img webp 60 1200         质量 60、宽 1200
  moss :img ico -s 16,32 *.png   只要 16 和 32 两档的 ico"""

_RE_QUALITY_PCT = re.compile(r'^(\d{1,3})%$')
_RE_WIDTH_PX = re.compile(r'^(\d{1,5})px$')
_RE_NUMBER = re.compile(r'^(\d{1,5})$')

def _tokens(text):
    return text.split()

def parse(tokens, cwd):
    opts = {
        'format': None, 'quality': DEFAULT_QUALITY, 'width': None,
        'source_dir': None, 'patterns': [], 'ext_filter': None,
        'output_dir': None, 'in_place': False, 'assume_yes': False,
        'ico_sizes': None, 'help': False, 'unknown': [],
    }
    i = 0
    while i < len(tokens):
        raw = tokens[i]
        low = raw.lower()
        i += 1

        if low in ('-h', '--help', '-?', '?'):
            opts['help'] = True
            continue
        if low in ('-y', '--yes'):
            opts['assume_yes'] = True
            continue
        if low in ('-o', '--out', '--output'):
            if i >= len(tokens):
                return opts, '-o 后面要跟一个输出目录。'
            opts['output_dir'] = tokens[i]
            i += 1
            continue
        if low in ('-s', '--sizes'):
            if i >= len(tokens):
                return opts, '-s 后面要跟尺寸，例如 -s 16,32,256。'
            opts['ico_sizes'] = core.checked_ico_sizes(re.split(r'[,\s]+', tokens[i]))
            i += 1
            continue
        if raw in ('/', '\\'):
            opts['in_place'] = True
            continue

        if low in FORMATS_CLI:
            opts['format'] = low
            continue

        m = _RE_QUALITY_PCT.match(low)
        if m:
            opts['quality'] = max(1, min(100, int(m.group(1))))
            continue
        m = _RE_WIDTH_PX.match(low)
        if m:
            opts['width'] = int(m.group(1))
            continue
        m = _RE_NUMBER.match(low)
        if m:
            value = int(m.group(1))
            if value <= 100:
                opts['quality'] = max(1, value)
            else:
                opts['width'] = value
            continue

        if core.has_wildcard(raw):
            opts['patterns'].append(raw)
            continue

        full = raw if os.path.isabs(raw) else os.path.join(cwd, raw)
        if os.path.isdir(full):
            opts['source_dir'] = os.path.abspath(full)
            continue
        if os.path.isfile(full):
            opts['patterns'].append(os.path.abspath(full))
            continue

        exts = core.split_ext_filter(raw)
        if exts:
            opts['ext_filter'] = core.normalize_exts(exts)
            continue

        opts['unknown'].append(raw)

    return opts, None

def _pick_files(opts, base_dir, note):
    if opts['patterns']:
        files, missed = core.expand_patterns(opts['patterns'], base_dir)
        for pat in missed:
            note('[警告] 没有匹配到文件: %s' % pat)
        return files, None

    got = core.scan_source(base_dir)
    if not got['ok']:
        return [], '源目录不存在: %s' % base_dir
    picked = opts['ext_filter'] or list(core.SUPPORTED_EXTS)
    files = [os.path.join(base_dir, f) for f in sorted(os.listdir(base_dir))
             if os.path.isfile(os.path.join(base_dir, f))
             and os.path.splitext(f)[1].lower() in picked]
    return files, None

_OUT_MODES = [
    ('source',        '覆盖原图', '直接写回源目录，同名文件会被覆盖'),
    ('source_delete', '删除原图', '转换成功后删除源文件，无法撤销'),
    ('separate',      '新文件夹', '输出到 compressed_output\\，原图不动'),
]

def _enable_vt():
    if os.name != 'nt':
        return True
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        if not k.GetConsoleMode(h, ctypes.byref(mode)):
            return False
        return bool(k.SetConsoleMode(h, mode.value | 0x0004))
    except Exception:
        return False

def _choose_output_mode():
    print('输出到哪？（没有默认值，请自己选）')

    if os.name == 'nt' and _enable_vt():
        import msvcrt

        cur = -1

        def draw(first=False):
            if not first:
                sys.stdout.write('\x1b[%dA' % (len(_OUT_MODES) + 1))
            for i, (_, name, tip) in enumerate(_OUT_MODES):
                mark = '>' if i == cur else ' '
                sys.stdout.write('\x1b[2K   %s %-9s %s\n' % (mark, name, tip))
            sys.stdout.write('\x1b[2K   ↑↓ 选择 · 回车确认 · Esc 取消\n')
            sys.stdout.flush()

        draw(first=True)
        while True:
            ch = msvcrt.getch()
            if ch in (b'\x00', b'\xe0'):
                k = msvcrt.getch()
                if k == b'H':
                    cur = len(_OUT_MODES) - 1 if cur <= 0 else cur - 1
                elif k == b'P':
                    cur = 0 if cur >= len(_OUT_MODES) - 1 else cur + 1
                draw()
            elif ch == b'\x03':
                raise KeyboardInterrupt
            elif ch == b'\x1b':
                sys.stdout.write('\n')
                return None
            elif ch in (b'\r', b'\n'):
                sys.stdout.write('\n')
                return _OUT_MODES[cur][0] if cur >= 0 else None

    for i, (_, name, tip) in enumerate(_OUT_MODES, 1):
        print('   %d) %s —— %s' % (i, name, tip))
    try:
        answer = input('   请输入序号（直接回车 = 取消）: ').strip()
    except (KeyboardInterrupt, EOFError):
        print()
        return None
    if not answer:
        return None
    try:
        n = int(answer)
    except ValueError:
        return None
    return _OUT_MODES[n - 1][0] if 1 <= n <= len(_OUT_MODES) else None

def _resolve_output(opts, source_dir, cwd):
    if opts['output_dir']:
        od = opts['output_dir']
        return (od if os.path.isabs(od) else os.path.abspath(os.path.join(cwd, od))), 'separate', None

    if opts['in_place']:
        return source_dir, 'source', None

    return source_dir, 'source', None

def run(tokens, cwd=None):
    cwd = cwd or os.getcwd()
    if isinstance(tokens, str):
        tokens = _tokens(tokens)
    opts, err = parse(tokens, cwd)
    if err:
        print('[错误] %s' % err)
        print(USAGE)
        return 1

    if opts['help']:
        print(USAGE)
        return 0

    if opts['unknown']:
        print('提示: 已忽略无法识别的参数: %s' % ', '.join(opts['unknown']))

    source_dir = opts['source_dir'] or cwd
    if not os.path.isdir(source_dir):
        print('[错误] 源目录不存在: %s' % source_dir)
        return 1

    def note(text):
        print(text)

    files, err = _pick_files(opts, source_dir, note)
    if err:
        print('[错误] %s' % err)
        return 1
    if not files:
        print('\n提示: 未找到符合条件的图片。')
        return 1

    fmt = opts['format'] or ''
    width = None if fmt == 'ico' else opts['width']
    in_place = opts['in_place']

    output_dir, save_mode, err = _resolve_output(opts, source_dir, cwd)
    if err == 'CANCELLED':
        print('已取消，什么都没做。')
        return 130
    if err:
        print('[错误] %s' % err)
        return 2
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    mode_name = dict((k, n) for k, n, _ in _OUT_MODES).get(save_mode, save_mode)
    print('---')
    print('任务确认:')
    print('  - 目标格式: %s' % (fmt or '保持原格式（各存各的）'))
    print('  - 压缩质量: %d%%' % opts['quality'])
    print('  - 目标宽度: %s' % ('%dpx' % width if width else '保持原始尺寸'))
    if fmt == 'ico':
        print('  - ICO 尺寸: %s' % ', '.join(
            str(s) for s in core.checked_ico_sizes(opts['ico_sizes'])))
    picked_note = ('按你指定的文件 / 通配符挑的' if opts['patterns']
                   else '当前目录下所有支持的图片格式')
    print('  - 待处理文件: %d 个（%s）' % (len(files), picked_note))
    print('  - 输出模式: %s' % mode_name)
    print('  - 输出位置: %s' % output_dir)
    print('---')

    summary = core.run_files(files, fmt, opts['quality'], width, output_dir, save_mode,
                             core.checked_ico_sizes(opts['ico_sizes']), log=lambda s: print(s, end=''))
    if summary['failed']:
        return 1
    return 0

def _arguments():
    import json
    raw = os.environ.get('MOSS_PKG_PARAMS')
    if raw:
        try:
            got = json.loads(raw).get('args')
            if got is not None:
                return str(got).strip()
        except (ValueError, TypeError):
            pass
    return ' '.join(sys.argv[1:]).strip()

def main():
    text = _arguments()
    if not text:
        print('[错误] 命令行模式没有收到参数。想开界面就直接 `moss :img`。')
        return 1
    return run(_tokens(text))

if __name__ == '__main__':
    sys.exit(main())
