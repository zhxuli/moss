# -*- coding: utf-8 -*-
"""图片工具 —— 命令行模式。

宿主把包名后面的东西**整串**放进 `MOSS_PKG_PARAMS.args`（一个字段），
本文件自己解析 —— 写法尽量短，顺序随便：

    moss :img webp                     当前目录所有图 → webp 80%
    moss :img webp 60% 1200            质量 60、宽 1200
    moss :img webp 1200 60             顺序随便
    moss :img png *.jpg                通配符：只挑当前目录的 jpg
    moss :img webp D:\\图 "*.png"       给了目录，通配符就相对它解析
    moss :img webp /                   原地覆盖（会问一次）
    moss :img ico *.png                生成多分辨率 ico

不带任何参数 = 打开界面（见 main.py）。

处理逻辑全在 `core.py`，这里只做「解析命令行 + 打印」。
"""
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
  选项   /                  输出到源目录（原地覆盖，会问一次）
         -o <目录>          指定输出目录
         -s 16,32,256       ico 尺寸（默认 16/24/32/48/64/128/256 全要）
         -y                 覆盖时不再询问
         -h                 本帮助

参数顺序随便，只填你会用到的那几个就行。例子
  moss :img ico                  当前所有图 → 多分辨率 ico（只要这两个词）
  moss :img png                  当前所有图 → png 80%
  moss :img 1200                 当前所有图等比缩到 1200 宽，格式不动
  moss :img 60%                  当前所有图按 60% 质量重压，格式不动
  moss :img webp 60 1200         质量 60、宽 1200
  moss :img png *.jpg            只挑当前目录的 jpg
  moss :img ico -s 16,32 *.png   只要 16 和 32 两档的 ico
  moss :img webp -o D:\\out       换输出目录
  moss :img jpg 90% / -y         原地覆盖，不问"""

_RE_QUALITY_PCT = re.compile(r'^(\d{1,3})%$')
_RE_WIDTH_PX = re.compile(r'^(\d{1,5})px$')
_RE_NUMBER = re.compile(r'^(\d{1,5})$')


def _tokens(text):
    """宿主给的是一个整串，这里自己切词（就是按空白切，没有别的花样）。"""
    return text.split()


def parse(tokens, cwd):
    """把词解析成一份选项。返回 (opts, error)。"""
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
            # 裸数字：小的是质量、大的是宽度（100 及以下当质量）
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
    """定出要处理哪些文件：给了通配符就展开，否则扫目录。"""
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


def _confirm_overwrite(files, output_dir, output_format, assume_yes):
    """原地覆盖时先列出来问一句（照抄旧版命令行版的做法）。

    目标文件名要按**每张图各自解析出来的格式**算 —— 不写格式时是"各存各的"，
    固定用同一个扩展名会算错（把不会覆盖的当成会覆盖，或者反过来）。
    """
    at_risk = []
    for path in files:
        base, _ = os.path.splitext(os.path.basename(path))
        fmt = core.resolve_format(path, output_format)
        target = os.path.join(output_dir, base + '.' + fmt)
        if os.path.abspath(target).lower() == os.path.abspath(path).lower():
            at_risk.append(os.path.basename(path))
    if not at_risk:
        return True
    print('\n!!! 警告 !!! 以下文件将被原地覆盖:')
    for name in at_risk:
        print('  - %s' % name)
    if assume_yes:
        print('（-y 已指定，直接继续）')
        return True
    try:
        answer = input('您确定要继续吗? (输入 y 或 yes 继续): ')
    except (KeyboardInterrupt, EOFError):
        print('\n操作已由用户取消。')
        return False
    if answer.strip().lower() not in ('y', 'yes'):
        print('操作已由用户取消。')
        return False
    return True


def run(tokens, cwd=None):
    """命令行模式的入口。返回退出码。"""
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

    # 不写格式 = 保持原格式（由 core.resolve_format 逐张判定）
    fmt = opts['format'] or ''
    width = None if fmt == 'ico' else opts['width']
    in_place = opts['in_place']
    if opts['output_dir']:
        od = opts['output_dir']
        output_dir = od if os.path.isabs(od) else os.path.abspath(os.path.join(cwd, od))
    elif in_place:
        output_dir = source_dir
    else:
        output_dir = os.path.join(source_dir, 'compressed_output')
    save_mode = 'source' if in_place else 'separate'

    if not os.path.isdir(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    print('---')
    print('任务确认:')
    print('  - 目标格式: %s' % (fmt or '保持原格式（各存各的）'))
    print('  - 压缩质量: %d%%' % opts['quality'])
    print('  - 目标宽度: %s' % ('%dpx' % width if width else '保持原始尺寸'))
    if fmt == 'ico':
        print('  - ICO 尺寸: %s' % ', '.join(
            str(s) for s in core.checked_ico_sizes(opts['ico_sizes'])))
    print('  - 待处理文件: %d 个（当前目录下所有支持的图片格式）' % len(files))
    print('  - 输出位置: %s' % output_dir)
    print('---')

    if save_mode == 'source' and not _confirm_overwrite(
            files, output_dir, fmt, opts['assume_yes']):
        return 130

    summary = core.run_files(files, fmt, opts['quality'], width, output_dir, save_mode,
                             core.checked_ico_sizes(opts['ico_sizes']), log=lambda s: print(s, end=''))
    if summary['failed']:
        return 1
    return 0


def _arguments():
    """参数来源：宿主放进来的那一个字段。

    ★ 迁移说明：旧版直接读 sys.argv（宿主 pa 把参数拼成字符串传进来）。
      新版走 moss 的参数通道：`MOSS_PKG_PARAMS` 里是 JSON，`args` 就是
      「包名后面那一整串」。没有它（脚本被单独跑）时退回 sys.argv。
    """
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
