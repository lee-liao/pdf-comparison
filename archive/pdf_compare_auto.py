#!/usr/bin/env python3
"""
PDF差异比较自动化工具

将三步法合并为一个命令：
1. 使用mineru_extract.py提取PDF内容
2. 使用compare_integration.py比较差异
3. 生成HTML报告

中间文件会自动保存到临时目录，并在完成后可选清理。
"""

import sys
import argparse
import subprocess
import tempfile
import shutil
from pathlib import Path

# 默认输出目录
DEFAULT_OUTPUT_DIR = "output"


def run_mineru_extract(pdf_path, output_dir):
    """运行MinerU提取"""
    print(f"提取PDF内容: {Path(pdf_path).name}")

    json_path = output_dir / f"{Path(pdf_path).stem}_mineru.json"

    cmd = [sys.executable, "mineru_extract.py", str(pdf_path), str(json_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise Exception(f"MinerU提取失败: {result.stderr}")

    return json_path


def run_compare_integration(json1_path, json2_path, output_path, theme='dark', pdf1_path=None, pdf2_path=None):
    """运行差异比较"""
    print(f"比较差异...")

    cmd = [
        sys.executable, "compare_integration.py",
        "--json", str(json1_path), str(json2_path),
        "-o", str(output_path),
        "-t", theme
    ]

    # 添加PDF路径参数用于计算内容体范围
    if pdf1_path:
        cmd.extend(["--pdf1", str(pdf1_path)])
    if pdf2_path:
        cmd.extend(["--pdf2", str(pdf2_path)])

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise Exception(f"差异比较失败: {result.stderr}")

    return output_path


def compare_pdfs_auto(pdf1_path, pdf2_path, output_path, theme='dark', keep_intermediate=False, debug=False, use_content_filter=True):
    """自动比较两个PDF文件"""
    pdf1_path = Path(pdf1_path)
    pdf2_path = Path(pdf2_path)
    output_path = Path(output_path)

    if not pdf1_path.exists():
        raise FileNotFoundError(f"文件不存在: {pdf1_path}")
    if not pdf2_path.exists():
        raise FileNotFoundError(f"文件不存在: {pdf2_path}")

    # 创建临时目录存放中间文件
    if keep_intermediate:
        temp_dir = Path(DEFAULT_OUTPUT_DIR) / "intermediate"
        temp_dir.mkdir(parents=True, exist_ok=True)
        cleanup = False
    else:
        temp_dir = Path(tempfile.mkdtemp(prefix="pdf_diff_"))
        cleanup = True

    try:
        print(f"比较PDF文件:")
        print(f"  文件1: {pdf1_path.name}")
        print(f"  文件2: {pdf2_path.name}")
        print(f"  输出: {output_path}")
        if use_content_filter:
            print(f"  内容体过滤: 启用")
        print()

        # 步骤1: 提取PDF1
        json1_path = run_mineru_extract(pdf1_path, temp_dir)
        print(f"  ✓ 保存到: {json1_path}")

        # 步骤2: 提取PDF2
        json2_path = run_mineru_extract(pdf2_path, temp_dir)
        print(f"  ✓ 保存到: {json2_path}")

        # 步骤3: 比较差异
        if use_content_filter:
            run_compare_integration(json1_path, json2_path, output_path, theme, pdf1_path, pdf2_path)
        else:
            run_compare_integration(json1_path, json2_path, output_path, theme)
        print(f"  ✓ 差异报告已保存到: {output_path}")

        return 0

    finally:
        # 清理临时文件
        if cleanup and temp_dir.exists():
            try:
                shutil.rmtree(temp_dir)
                print(f"\n临时文件已清理: {temp_dir}")
            except Exception as e:
                print(f"\n警告: 无法清理临时文件: {e}")
        elif not cleanup:
            print(f"\n中间文件保留在: {temp_dir}")


def main():
    parser = argparse.ArgumentParser(
        description='PDF差异比较自动化工具 - 合并三步法为一个命令',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  %(prog)s file1.pdf file2.pdf
  %(prog)s file1.pdf file2.pdf -o result.html
  %(prog)s file1.pdf file2.pdf --keep-intermediate
  %(prog)s file1.pdf file2.pdf --no-content-filter
        '''
    )

    parser.add_argument('pdf_files', nargs=2, metavar=('FILE1', 'FILE2'),
                        help='要比较的两个PDF文件')
    parser.add_argument('-o', '--output', default='diff_result.html',
                        help='输出HTML文件路径 (默认: diff_result.html)')
    parser.add_argument('-t', '--theme', choices=['light', 'dark'],
                        default='dark', help='颜色主题 (默认: dark)')
    parser.add_argument('--keep-intermediate', action='store_true',
                        help='保留中间文件（JSON）到output/intermediate目录')
    parser.add_argument('--no-content-filter', action='store_true',
                        help='禁用内容体过滤（不过滤header/footer）')
    parser.add_argument('--debug', action='store_true', help='显示调试信息')

    args = parser.parse_args()

    try:
        return compare_pdfs_auto(
            args.pdf_files[0],
            args.pdf_files[1],
            args.output,
            args.theme,
            args.keep_intermediate,
            args.debug,
            use_content_filter=not args.no_content_filter
        )
    except Exception as e:
        print(f"错误: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
