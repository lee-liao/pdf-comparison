#!/usr/bin/env python3
"""PDF 差异比较工具 - 命令行入口

子命令:
  run      全流程: 两个 PDF -> 提取 -> 比较 -> HTML 报告（推荐）
  extract  仅提取: PDF -> layout.json
  compare  仅比较: 两个 layout.json -> HTML 报告

提取引擎（--engine）: mineru（在线 API，默认）/ pdfjs（本地 Node，无需额度）

示例:
  python pdf_compare.py run old.pdf new.pdf -o diff.html
  python pdf_compare.py run old.pdf new.pdf --engine pdfjs
  python pdf_compare.py run old.pdf new.pdf --pages 2-17
  python pdf_compare.py extract file.pdf -o output/file
  python pdf_compare.py compare old.json new.json --pdf1 old.pdf --pdf2 new.pdf
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

from pdfdiff import compare, content, coverage, extract, report
from pdfdiff.mineru import MinerUClient
from pdfdiff.pdfjs import PdfJsClient

DEFAULT_OUTPUT = "diff_result.html"

# 提取引擎：两者均产出同构的 layout.json，下游流程完全一致
ENGINES = {"mineru": MinerUClient, "pdfjs": PdfJsClient}


def _setup_console():
    """Windows 控制台默认编码可能是 cp1252/GBK，统一为 UTF-8"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _content_context(pdf_path, enabled: bool):
    """计算内容体范围与页面行信息；锚点检测不到时返回 (None, None) 不过滤"""
    if not enabled or not pdf_path or not Path(pdf_path).exists():
        return None, None
    regions = content.content_regions(pdf_path)
    if not regions:
        print(f"  提示: {Path(pdf_path).name} 未检测到内容体锚点，跳过 header/footer 过滤")
        return None, None
    print(f"  内容体过滤: {Path(pdf_path).name} 检测到 {len(regions)} 页范围")
    page_lines = content.content_page_lines(pdf_path, regions)
    return regions, page_lines


def _report_coverage(text, pdf_path, regions, page_lines) -> None:
    """打印提取覆盖率；偏低时提示可能有内容被引擎静默丢弃"""
    if not pdf_path or not Path(pdf_path).exists():
        return
    recall, missing, total = coverage.coverage(text, pdf_path, regions, page_lines)
    if recall is None:
        print(f"  提取覆盖率: {Path(pdf_path).name} 无文字图层（扫描件），跳过检查")
        return
    line = f"  提取覆盖率: {Path(pdf_path).name} {recall:.1%}（缺失 {missing}/{total} token）"
    if recall < coverage.DEFAULT_THRESHOLD:
        line += "  ⚠ 可能有内容丢失"
    print(line)


def compare_json_files(json1, json2, output, theme="dark",
                       pdf1=None, pdf2=None, use_filter=True,
                       title=None) -> dict:
    """比较两个 layout.json，生成 HTML 报告，返回统计信息"""
    print("提取文本内容...")
    regions1, lines1 = _content_context(pdf1, use_filter)
    regions2, lines2 = _content_context(pdf2, use_filter)
    data1, data2 = _load_json(json1), _load_json(json2)
    text1 = extract.extract_text(data1, regions1, lines1)
    text2 = extract.extract_text(data2, regions2, lines2)
    print(f"  原文 {len(text1)} 字符 / 新文 {len(text2)} 字符")
    _report_coverage(text1, pdf1, regions1, lines1)
    _report_coverage(text2, pdf2, regions2, lines2)

    print("比较差异...")
    result = compare.compare_texts(text1, text2)

    old_name = Path(pdf1 or json1).name
    new_name = Path(pdf2 or json2).name
    # 差异统计只在同一提取来源下可比，故写入报告
    src1, src2 = extract.source_info(data1), extract.source_info(data2)
    provenance = f"提取来源: {src1}" if src1 == src2 else f"提取来源: 原文 {src1} / 新文 {src2}"
    report.generate_html(result, output,
                         title=title or f"{old_name} vs {new_name} - 差异比较",
                         old_name=old_name, new_name=new_name, theme=theme,
                         provenance=provenance)

    stats = result["stats"]
    print(f"✓ 差异报告: {output}")
    print(f"  新增 +{stats['additions']}  删除 -{stats['deletions']}  "
          f"修改 ~{stats['modifications']}  未变 {stats['unchanged']}")
    return stats


def _extract_one(client, pdf_path, output_dir, model, pages=None):
    """提取单个 PDF（可选先截取页码范围）

    返回 (layout.json 路径, 实际送入提取的 PDF 路径)。
    返回后者是因为内容体过滤必须基于同一份 PDF，否则页码错位。
    """
    pdf_path = Path(pdf_path)
    if pages:
        sliced = Path(tempfile.mkdtemp(prefix="pdfdiff_")) / f"{pdf_path.stem}_p{pages}.pdf"
        content.slice_pages(pdf_path, pages, sliced)
        print(f"截取页码 {pages}: {sliced.name}")
        pdf_path = sliced
    return client.extract(pdf_path, output_dir, model), pdf_path


def cmd_run(args):
    for p in (args.pdf1, args.pdf2):
        if not Path(p).exists():
            print(f"错误: 文件不存在: {p}")
            return 1

    json_dir = Path(args.keep_json) if args.keep_json else Path(tempfile.mkdtemp(prefix="pdfdiff_"))
    client = ENGINES[args.engine]()
    # 内容体过滤基于送入提取引擎的同一份 PDF（截取后为临时文件），避免页码错位
    json1, pdf1 = _extract_one(client, args.pdf1, json_dir / Path(args.pdf1).stem, args.model, args.pages)
    json2, pdf2 = _extract_one(client, args.pdf2, json_dir / Path(args.pdf2).stem, args.model, args.pages)
    if args.keep_json:
        print(f"中间 JSON 保留在: {json_dir}")

    compare_json_files(json1, json2, args.output, args.theme,
                       pdf1=pdf1, pdf2=pdf2,
                       use_filter=not args.no_content_filter,
                       title=f"{Path(args.pdf1).name} vs {Path(args.pdf2).name} - 差异比较")
    return 0


def cmd_extract(args):
    if not Path(args.pdf).exists():
        print(f"错误: 文件不存在: {args.pdf}")
        return 1
    output_dir = args.output or f"output/{Path(args.pdf).stem}"
    client = ENGINES[args.engine]()
    layout, _ = _extract_one(client, args.pdf, output_dir, args.model, args.pages)
    print(f"\n提取完成: {layout}")
    return 0


def cmd_compare(args):
    for p in (args.json1, args.json2):
        if not Path(p).exists():
            print(f"错误: 文件不存在: {p}")
            return 1
    compare_json_files(args.json1, args.json2, args.output, args.theme,
                       pdf1=args.pdf1, pdf2=args.pdf2,
                       use_filter=not args.no_content_filter)
    return 0


def main():
    _setup_console()
    parser = argparse.ArgumentParser(
        description="PDF 差异比较工具（MinerU/pdf.js 提取 + 单元级差异 + HTML 报告）")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p):
        p.add_argument("-o", "--output", default=DEFAULT_OUTPUT,
                       help=f"输出 HTML 路径 (默认: {DEFAULT_OUTPUT})")
        p.add_argument("-t", "--theme", choices=["light", "dark"], default="dark",
                       help="颜色主题 (默认: dark)")
        p.add_argument("--no-content-filter", action="store_true",
                       help="禁用内容体过滤（不过滤 header/footer）")

    def add_engine(p):
        p.add_argument("-e", "--engine", choices=sorted(ENGINES), default="mineru",
                       help="提取引擎: mineru（在线 API，默认）/ pdfjs（本地 Node，无需额度）")
        p.add_argument("--model", choices=["pipeline", "vlm"], default="vlm",
                       help="MinerU 模型 (默认: vlm，对应 hybrid 后端；pdfjs 引擎忽略)")

    p_run = sub.add_parser("run", help="全流程: 提取两个 PDF 并比较（推荐）")
    p_run.add_argument("pdf1", help="原文 PDF")
    p_run.add_argument("pdf2", help="新文 PDF")
    p_run.add_argument("--pages", help="仅处理页码范围（1-based，如 2-17）")
    p_run.add_argument("--keep-json", metavar="DIR",
                       help="保留中间 layout.json 到指定目录")
    add_engine(p_run)
    add_common(p_run)
    p_run.set_defaults(func=cmd_run)

    p_ext = sub.add_parser("extract", help="仅提取: PDF -> layout.json")
    p_ext.add_argument("pdf", help="输入 PDF")
    p_ext.add_argument("-o", "--output", help="输出目录 (默认: output/<文件名>)")
    p_ext.add_argument("--pages", help="仅提取页码范围（1-based，如 2-17）")
    add_engine(p_ext)
    p_ext.set_defaults(func=cmd_extract)

    p_cmp = sub.add_parser("compare", help="仅比较: 两个 layout.json -> HTML")
    p_cmp.add_argument("json1", help="原文 layout.json")
    p_cmp.add_argument("json2", help="新文 layout.json")
    p_cmp.add_argument("--pdf1", help="原文 PDF（用于内容体过滤）")
    p_cmp.add_argument("--pdf2", help="新文 PDF（用于内容体过滤）")
    add_common(p_cmp)
    p_cmp.set_defaults(func=cmd_compare)

    args = parser.parse_args()
    try:
        return args.func(args)
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
