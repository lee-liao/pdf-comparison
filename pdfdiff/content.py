"""基于 PDF 版面的内容体范围检测（PyMuPDF）

工卡 PDF 每页由表格线框出内容体：
- 顶部边界 = "工卡标题" 文本正下方的横线
- 底部边界 = "飞机适用范围" 文本右侧竖线的上端点

坐标系统：屏幕坐标（y=0 在顶部，y 向下增大）。
锚点文本检测不到的页面不做过滤（返回 None），避免误裁。
"""

from pathlib import Path

import fitz  # PyMuPDF

TOP_ANCHOR = "工卡标题"
BOTTOM_ANCHOR = "飞机适用范围"


def _page_line_segments(page) -> tuple:
    """提取页面中的横线和竖线段

    返回: (horizontal, vertical)
      horizontal: [{x1, x2, y, length}, ...]
      vertical:   [{y1, y2, x, length}, ...]
    """
    horizontal, vertical = [], []
    for drawing in page.get_drawings():
        for item in drawing.get("items", []):
            if item[0] != "l":
                continue
            _, p1, p2 = item
            if abs(p1.y - p2.y) < 0.1:
                horizontal.append({
                    "x1": min(p1.x, p2.x), "x2": max(p1.x, p2.x),
                    "y": p1.y, "length": abs(p1.x - p2.x),
                })
            elif abs(p1.x - p2.x) < 0.1:
                vertical.append({
                    "y1": min(p1.y, p2.y), "y2": max(p1.y, p2.y),
                    "x": p1.x, "length": abs(p1.y - p2.y),
                })
    return horizontal, vertical


def _line_below_text(page, text: str, min_length: float = 50) -> float:
    """找文本正下方最近的横线，返回其 y 坐标；找不到返回 None"""
    hits = page.search_for(text)
    if not hits:
        return None
    rect = fitz.Rect(hits[0])
    center_x = (rect.x0 + rect.x1) / 2
    horizontal, _ = _page_line_segments(page)
    candidates = [
        ln for ln in horizontal
        if ln["y"] > rect.y1 and ln["length"] > min_length
        and ln["x1"] <= center_x <= ln["x2"]
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda ln: ln["y"] - rect.y1)["y"]


def _vline_top_right_of_text(page, text: str, min_length: float = 20) -> float:
    """找文本右侧最近的竖线，返回其上端点 y 坐标；找不到返回 None"""
    hits = page.search_for(text)
    if not hits:
        return None
    rect = fitz.Rect(hits[0])
    center_y = (rect.y0 + rect.y1) / 2
    _, vertical = _page_line_segments(page)
    candidates = [
        ln for ln in vertical
        if ln["x"] > rect.x1 and ln["length"] > min_length
        and ln["y1"] <= center_y <= ln["y2"]
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda ln: ln["x"] - rect.x1)["y1"]


def content_regions(pdf_path) -> dict:
    """计算每页内容体范围

    返回: {page_idx: (y_top, y_bottom)}，仅包含两个锚点均检测成功的页面。
    锚点缺失的页面不在字典中（该页不做过滤）。
    """
    regions = {}
    with fitz.open(pdf_path) as doc:
        for page_idx, page in enumerate(doc):
            top = _line_below_text(page, TOP_ANCHOR)
            bottom = _vline_top_right_of_text(page, BOTTOM_ANCHOR)
            if top is not None and bottom is not None and top < bottom:
                regions[page_idx] = (top, bottom)
    return regions


def content_page_lines(pdf_path, regions: dict) -> dict:
    """提取各页内容体范围内的文本行（用于表格 HTML 起始行匹配）

    返回: {page_idx: [line_text, ...]}
    """
    page_lines = {}
    with fitz.open(pdf_path) as doc:
        for page_idx, page in enumerate(doc):
            if page_idx not in regions:
                continue
            top, bottom = regions[page_idx]
            lines = []
            for block in page.get_text("dict").get("blocks", []):
                for line in block.get("lines", []):
                    bbox = line.get("bbox")
                    if not bbox or len(bbox) < 4:
                        continue
                    y_center = (bbox[1] + bbox[3]) / 2
                    if top <= y_center <= bottom:
                        text = "".join(sp.get("text", "") for sp in line.get("spans", [])).strip()
                        if text:
                            lines.append(text)
            page_lines[page_idx] = lines
    return page_lines


def slice_pages(pdf_path, page_range: str, output_path) -> Path:
    """按页码范围截取 PDF（1-based，如 "2-17" 或 "3"），保存到 output_path"""
    if "-" in page_range:
        start_s, _, end_s = page_range.partition("-")
        start, end = int(start_s), int(end_s)
    else:
        start = end = int(page_range)

    output_path = Path(output_path)
    with fitz.open(pdf_path) as doc:
        if not (1 <= start <= end <= len(doc)):
            raise ValueError(f"页码范围 {page_range} 超出文档页数 (1-{len(doc)})")
        doc.select(range(start - 1, end))
        doc.save(output_path)
    return output_path
