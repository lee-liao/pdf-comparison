"""提取覆盖率自检：与 PDF 文字图层比对，发现静默丢失的内容

提取引擎可能整段丢内容而不报任何错误（实测 MinerU 3.4.0 会丢掉
"发动机部件会在关车后保持高温…"这类完整句子），报告里只表现为
一处"删除"，无法与真实差异区分。本模块用 PyMuPDF 的文字图层做基准，
按 token 多重集比对，把这种静默失败变成可见的覆盖率数字。

比对是顺序无关的（只看内容有无，不看阅读顺序），因为版面顺序的差异
是正常的，不构成内容丢失。

仅对有文字图层的 PDF 有效；扫描件（文字图层近乎为空）自动跳过。
"""

import re
from collections import Counter

import fitz  # PyMuPDF

from . import content

# 与 compare 的口径无关，这里只做内容有无的粗粒度比对
_TOKEN = re.compile(r"[一-鿿]|[A-Za-z]+|\d+")

# 文字图层 token 少于此值视为扫描件，无法作为基准
MIN_TRUTH_TOKENS = 200

# 低于该覆盖率提示可能丢失内容（实测正常提取在 98% 以上）
DEFAULT_THRESHOLD = 0.95


def _tokens(text: str) -> Counter:
    return Counter(t.lower() for t in _TOKEN.findall(text))


def truth_text(pdf_path, regions: dict = None, page_lines: dict = None) -> str:
    """PDF 文字图层基准文本

    提供 regions 时只取内容体范围内的行，与比较时的口径一致，
    否则内容体过滤裁掉的页眉页脚会被误判为"丢失"。
    未检测到锚点的页面（不在 regions 中）本就不过滤，取整页文本。
    """
    if not regions:
        with fitz.open(pdf_path) as doc:
            return " ".join(page.get_text() for page in doc)

    if page_lines is None:
        page_lines = content.content_page_lines(pdf_path, regions)
    parts = []
    with fitz.open(pdf_path) as doc:
        for page_idx, page in enumerate(doc):
            if page_idx in page_lines:
                parts.append(" ".join(page_lines[page_idx]))
            else:
                parts.append(page.get_text())
    return " ".join(parts)


def coverage(extracted_text: str, pdf_path, regions: dict = None,
             page_lines: dict = None) -> tuple:
    """提取文本对 PDF 文字图层的覆盖率

    返回 (recall, missing, total)；无可用文字图层时 recall 为 None。
    """
    truth = _tokens(truth_text(pdf_path, regions, page_lines))
    total = sum(truth.values())
    if total < MIN_TRUTH_TOKENS:
        return None, 0, total
    missing = sum((truth - _tokens(extracted_text)).values())
    return (total - missing) / total, missing, total
