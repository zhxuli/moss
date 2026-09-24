#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图标小尺寸优化：把 ≤N 像素的那几帧压成单色剪影。

为什么需要
----------
Windows 图标是**多尺寸打包**的，系统会按场景挑：任务栏 32×32、资源管理器
16/48、Alt+Tab 32。你生成的那张苔藓 M 在 32 及以上很清楚，但在 **16×16**
上，两个绿色互相交叠形成的斑块会变成噪点，边缘的扇贝形也糊成毛边。

这是所有图标集的通用做法：**小尺寸不照搬大尺寸的细节，而是简化**。
（macOS / Windows / Material 的图标集都这么干。）

做法
----
    ≤ THRESHOLD 的帧：先在大尺寸上把"苔藓绿"统一成一个亮绿（去斑块），再缩小
    >  THRESHOLD 的帧：原样缩小，保留渐变细节

用法
----
    python tools\\图标优化.py <源.ico 或 .png> [输出.ico] [阈值]

    python tools\\图标优化.py icon.png icon-优化.ico
    python tools\\图标优化.py icon.png icon-优化.ico 24

不带参数时：源 icon.png，输出 icon-优化.ico，阈值 32。
"""
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("[错误] 需要 Pillow。用自带运行时跑：")
    print(r"  system\runtimes\python\3.12\python.exe tools\图标优化.py")
    sys.exit(2)

SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
THRESHOLD_DEFAULT = 32

# 小尺寸统一用的亮苔绿（在深炭底上对比度最好）
FLAT_GREEN = (127, 191, 106)      # #7FBF6A


def is_moss(px):
    """判断一个像素是不是"苔藓绿"（区别于深炭底色和其他任何东西）。"""
    r, g, b, a = px
    return a > 128 and g > r + 15 and g > b + 15 and g > 50


def mark_bbox(im):
    """苔藓部分的包围盒 —— 用来看 mark 占了多少地方（padding 够不够）。"""
    px = im.load()
    x0, y0, x1, y1 = im.width, im.height, -1, -1
    for y in range(im.height):
        for x in range(im.width):
            if is_moss(px[x, y]):
                x0, y0 = min(x0, x), min(y0, y)
                x1, y1 = max(x1, x), max(y1, y)
    if x1 < 0:
        return None
    return (x0, y0, x1, y1)


def flatten_moss(im, color=FLAT_GREEN):
    """把苔藓绿统一成一个颜色，去掉内部斑块。"""
    im = im.convert("RGBA").copy()
    px = im.load()
    for y in range(im.height):
        for x in range(im.width):
            if is_moss(px[x, y]):
                px[x, y] = (color[0], color[1], color[2], 255)
    return im


def to_base(im):
    """把源图变成 1024 的 RGBA 底图。.ico 取最大帧。"""
    if im.format == "ICO" or (hasattr(im, "n_frames") and getattr(im, "n_frames", 1) > 1):
        im.size = max(im.info.get("sizes", [(256, 256)]))
    im = im.convert("RGBA")
    return im.resize((1024, 1024), Image.LANCZOS) if im.size != (1024, 1024) else im


def build(src_path, out_path, threshold):
    src = Image.open(src_path)
    base = to_base(src)

    bb = mark_bbox(base)
    if bb:
        x0, y0, x1, y1 = bb
        pad_l, pad_t = x0 / base.width, y0 / base.height
        pad_r, pad_b = 1 - x1 / base.width, 1 - y1 / base.height
        print("苔藓占比 : %.0f%% x %.0f%%" % ((x1 - x0) / base.width * 100,
                                              (y1 - y0) / base.height * 100))
        print("四周留白 : 左%.1f%% 上%.1f%% 右%.1f%% 下%.1f%%"
              % (pad_l * 100, pad_t * 100, pad_r * 100, pad_b * 100))
        if min(pad_l, pad_t, pad_r, pad_b) < 0.08:
            print("  ⚠ 最小留白不足 8% —— 小尺寸下圆角方块会被吃掉，建议 mark 再缩一点")

    flat = flatten_moss(base)
    frames = []
    for w, h in SIZES:
        use = flat if w <= threshold else base
        frames.append(use.resize((w, h), Image.LANCZOS))

    frames[-1].save(out_path, format="ICO",
                    sizes=[(f.width, f.height) for f in frames], append_images=frames[:-1])
    print("已生成   : %s" % out_path)
    print("阈值     : ≤%d 的帧用单色剪影" % threshold)


def make_preview(ico_path, out_path, sizes=(16, 24, 32, 48), scale=7, pad=16):
    """把 ico 里的各尺寸按【真实像素】放大渲染成一张对比图，用眼睛验收。

    缩小后好不好认，光看 256 那帧是看不出来的 —— 必须按真实像素看。
    """
    panels = []
    for s in sizes:
        im = Image.open(ico_path)
        im.size = (s, s)
        panels.append(im.convert("RGBA").resize((s * scale, s * scale), Image.NEAREST))
    w = sum(p.width for p in panels) + pad * (len(panels) + 1)
    h = max(p.height for p in panels) + pad * 2
    row = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    x = pad
    for p in panels:
        row.paste(p, (x, pad), p)
        x += p.width + pad
    row.save(out_path)
    return out_path


def main():
    args = sys.argv[1:]
    src = Path(args[0]) if len(args) > 0 else Path("icon.png")
    out = Path(args[1]) if len(args) > 1 else Path("icon-优化.ico")
    threshold = int(args[2]) if len(args) > 2 else THRESHOLD_DEFAULT

    if not src.is_file():
        print("[错误] 找不到源文件：%s" % src)
        return 1
    print("源       : %s" % src)
    build(str(src), str(out), threshold)

    preview = str(out) + ".preview.png"
    make_preview(str(out), preview)
    print("自检预览 : %s" % preview)
    print("           （左到右 16/24/32/48，按真实像素放大 7 倍 —— 用眼睛过一遍）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
