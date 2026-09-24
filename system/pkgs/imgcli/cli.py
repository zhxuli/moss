import os
import sys
import re
from PIL import Image

def process_single_image(filepath, output_format, quality, width, output_dir):
    """
    处理单个图片的核心逻辑。
    """
    try:
        with Image.open(filepath) as img:
            print(f"\n- 正在处理: {os.path.basename(filepath)} ({img.width}x{img.height})")

            # 调整尺寸
            if width and img.width > width:
                aspect_ratio = img.height / img.width
                new_height = int(width * aspect_ratio)
                print(f"  - 调整尺寸为: {width}x{new_height}")
                img = img.resize((width, new_height), Image.Resampling.LANCZOS)

            # 准备保存路径和选项
            base_name, _ = os.path.splitext(os.path.basename(filepath))
            output_filename = f"{base_name}.{output_format}"
            output_path = os.path.join(output_dir, output_filename)
            
            # 处理透明背景
            if output_format == 'jpg' and img.mode in ('RGBA', 'P'):
                print("  - 转换透明背景为白色")
                background = Image.new('RGB', img.size, (255, 255, 255))
                background.paste(img, (0, 0), img.getchannel('A') if img.mode == 'RGBA' else None)
                img = background
            
            # 设置压缩质量
            save_options = {'quality': quality} if output_format in ('jpg', 'webp') else {'compress_level': int(9 - (quality/100)*9), 'optimize': True}
            print(f"  - 设置 {output_format.upper()} 质量 (基于 {quality}%)")

            # 保存文件
            img.save(output_path, **save_options)
            print(f"[已保存] 至: {output_path}")

    except Exception as e:
        print(f"[错误] 处理文件 {os.path.basename(filepath)} 时出错: {e}")

def run_tasks(output_format, quality, width, source_filter, save_to_current_dir):
    """
    主执行函数：进行预扫描，然后处理文件。
    """
    output_dir = "." if save_to_current_dir else "compressed_output"
    
    if not save_to_current_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"[成功] 已创建输出目录: {output_dir}")

    # 筛选出需要处理的文件列表
    files_to_process = []
    supported_extensions = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff')
    for filename in os.listdir('.'):
        script_name = os.path.basename(sys.argv[0])
        if filename.lower() == script_name.lower() or filename == output_dir:
            continue
        
        _, original_ext = os.path.splitext(filename)
        if original_ext.lower() in supported_extensions:
            if not source_filter or original_ext.lower() in source_filter:
                files_to_process.append(filename)
    
    if not files_to_process:
        print("\n提示: 未找到符合条件的图片文件。")
        return

    # 预扫描和风险评估 (仅当保存在当前目录时)
    if save_to_current_dir:
        files_at_risk = []
        for filename in files_to_process:
            base_name, _ = os.path.splitext(filename)
            output_filename = f"{base_name}.{output_format}"
            if output_filename.lower() == filename.lower():
                files_at_risk.append(filename)
        
        if files_at_risk:
            print("\n!!! 警告 !!! 以下文件将被原地覆盖:")
            for f in files_at_risk:
                print(f"  - {f}")
            try:
                confirm = input("您确定要继续吗? (输入 y 或 yes 继续): ")
                if confirm.lower() not in ['y', 'yes']:
                    print("操作已由用户取消。")
                    return
            except KeyboardInterrupt:
                print("\n操作已由用户取消。")
                return

    # 执行真正的处理任务
    for filename in files_to_process:
        process_single_image(filename, output_format, quality, width, output_dir)
        
    print("\n所有任务已成功完成。")

def parse_and_run(params_list):
    """
    解析参数并启动任务。
    """
    output_format, quality, width, source_filter, save_to_current_dir = None, 80, None, None, False
    unknown_params = []

    for param in params_list:
        p_lower = param.lower()
        if p_lower in ['jpg', 'png', 'webp']: output_format = p_lower
        elif p_lower.endswith('%'):
            try: quality = int(p_lower[:-1]); assert 1 <= quality <= 100
            except: quality = 80; print(f"[警告] 无效的质量值 '{param}'，已使用默认值 80%。")
        elif p_lower.endswith('px'):
            try: width = int(p_lower[:-2])
            except: unknown_params.append(param)
        elif p_lower == '/': save_to_current_dir = True
        elif ';' in p_lower:
            source_filter = [f".{ext.strip()}" for ext in p_lower.split(';') if ext.strip()]
        else:
            unknown_params.append(param)

    if unknown_params: print(f"提示: 已忽略无法识别的参数: {', '.join(unknown_params)}")
    if not output_format: print("\n[错误] 您必须指定一个输出格式 (jpg, png, 或 webp)。"); print_usage(); return

    print("---")
    print("任务确认:")
    print(f"  - 目标格式: {output_format}")
    print(f"  - 压缩质量: {quality}%")
    print(f"  - 目标宽度: {width}px" if width else "  - 目标宽度: 保持原始尺寸")
    if source_filter: print(f"  - 源文件过滤: 只处理 {', '.join(source_filter)} 类型的文件")
    print(f"  - 保存位置: {'当前文件夹' if save_to_current_dir else '`compressed_output` 文件夹'}")
    print("---")
    
    run_tasks(output_format, quality, width, source_filter, save_to_current_dir)

def print_usage():
    print("\n--- 智能图片压缩工具 ---")
    print("使用方法: python compress.py [格式] [选项...]")
    print("\n【参数说明】")
    print("  jpg, png, webp     : 目标格式 (必须)。")
    print("  75%                : 压缩质量 (可选, 默认: 80%)。")
    print("  1200px             : 目标宽度 (可选, 默认保持原始尺寸)。")
    print("  /                  : 保存到当前文件夹 (可选, 可能会覆盖文件)。")
    print("  jpg;png;           : 源文件过滤器，只处理指定类型的文件 (可选)。")
    print("\n【使用示例】")
    print("  python compress.py webp 80% 1080px")
    print("  python compress.py jpg 90% /")
    print("  python compress.py webp png;gif;")


def _arguments():
    """参数来源。

    ★ 迁移说明：旧版直接读 sys.argv（宿主 pa 把参数拼成字符串传进来）。
      新版走 moss 的类型化参数通道：MOSS_PKG_PARAMS 里是 JSON。
      没有它（脚本被单独跑）时退回 sys.argv。
    """
    import json as _json
    raw = os.environ.get("MOSS_PKG_PARAMS")
    if raw:
        try:
            return str(_json.loads(raw).get("args") or "").strip()
        except Exception:
            pass
    return " ".join(sys.argv[1:])


if __name__ == "__main__":
    combined_input = _arguments()
    if not combined_input or '-h' in combined_input or '--help' in combined_input:
        print_usage()
        if not combined_input:
            try:
                user_input = input("\n请输入指令: ")
                combined_input = user_input
            except KeyboardInterrupt:
                print("\n操作已取消。"); sys.exit()
    
    if combined_input:
        params = re.split(r'\s+', combined_input.strip())
        parse_and_run(params)