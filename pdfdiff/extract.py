"""从 MinerU layout.json 提取文本

块结构:
- 普通块 (text/title/...): block.lines[].spans[]
- 复合块 (list/table): block.blocks[].lines[].spans[]
- span 类型: text / inline_equation 取 content；table 取 html（整表 HTML）
- image 块跳过

内容体过滤: 提供 regions 时，按 line 的 bbox 过滤 header/footer；
整表 HTML 无逐行 bbox，用页面文本行匹配定位起始行。
"""

import re


def source_info(json_data: dict) -> str:
    """读取提取引擎与版本，用于报告溯源

    同一份 PDF 在不同引擎/不同 MinerU 服务端版本下的提取结果差异显著
    （实测 MinerU 2.7.5 与 3.4.0 的差异统计相差近一倍），
    因此报告必须记录本次结果由谁产出。
    """
    backend = json_data.get("_backend") or "unknown"
    version = json_data.get("_version_name") or "unknown"
    if backend == "pdfjs":
        return f"pdf.js {version}"
    return f"MinerU {version} ({backend})"


def _strip_tags(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


def table_html_rows(html: str) -> list:
    """解析表格 HTML，返回每行(<tr>)的纯文本列表"""
    rows = []
    for match in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL):
        text = _strip_tags(match.group(1))
        if text:
            rows.append(text)
    return rows


def _table_start_row(html_rows: list, content_lines: list) -> int:
    """找表格 HTML 中第一个属于内容体的行号

    以内容体第一行的开头（数字/英文单词或前 5 个字符）作为关键词，
    在 HTML 行中定位；找不到则从第 0 行开始（不过滤）。
    """
    key = next((ln for ln in content_lines if len(ln.strip()) > 2), None)
    if not key:
        return 0
    match = re.match(r"(\d+|[A-Za-z]+)", key)
    keyword = match.group(1) if match else key[:5]
    for i, row in enumerate(html_rows):
        if keyword in row:
            return i
    return 0


def _bbox_overlaps_region(bbox, top: float, bottom: float) -> bool:
    """判断 bbox 与内容体 y 范围是否重叠；无 bbox 信息时保守保留"""
    if not bbox or len(bbox) < 4:
        return True
    y0, y1 = bbox[1], bbox[3]
    return y1 > top and y0 < bottom


def _iter_lines(block):
    """遍历块中的所有 line（list/table 的嵌套子块拍平）"""
    if block.get("type") in ("list", "table"):
        for sub in block.get("blocks", []):
            yield from sub.get("lines", [])
    else:
        yield from block.get("lines", [])


def extract_text(json_data: dict, regions: dict = None, page_lines: dict = None) -> str:
    """从 MinerU JSON 提取全部文本，返回空格连接的单一字符串

    regions: {page_idx: (y_top, y_bottom)}，提供时过滤内容体之外的行
    page_lines: {page_idx: [line_text, ...]}，用于表格 HTML 的起始行定位
    """
    pieces = []

    for page in json_data.get("pdf_info", []):
        page_idx = page.get("page_idx", 0)
        region = regions.get(page_idx) if regions else None

        # 正文块与被 MinerU 丢弃的块（如误判为 header 的正文）一并收集，按版面位置排序
        blocks = list(page.get("para_blocks", [])) + list(page.get("discarded_blocks", []))
        blocks.sort(key=lambda b: ((b.get("bbox") or [0, 0, 0, 0])[1], b.get("index", 0)))

        for block in blocks:
            if block.get("type") == "image":
                continue
            for line in _iter_lines(block):
                if region and not _bbox_overlaps_region(line.get("bbox"), *region):
                    continue
                for span in line.get("spans", []):
                    span_type = span.get("type")
                    if span_type in ("text", "inline_equation"):
                        content = (span.get("content") or "").strip()
                        if content:
                            pieces.append(content)
                    elif span_type == "table":
                        html = span.get("html") or ""
                        if not html:
                            continue
                        rows = table_html_rows(html)
                        if region and page_lines and page_idx in page_lines:
                            rows = rows[_table_start_row(rows, page_lines[page_idx]):]
                        pieces.extend(rows)

    return " ".join(pieces)
