"""
PDF 文本比对集成工具
简化版本：提取所有文本内容，按标点和关键词分割，忽略格式差异
"""

import json
import re
import os
import argparse

# 微调系数（与auto_crop_correct_logic.py保持一致）
MRO_COEFFS = {
    "left_offset_pt": 0.56,
    "top_offset_pt": 0.20,
    "right_offset_pt": 0.74,
    "bottom_offset_pt": 2.00,
}


def parse_html_table_rows(html_content):
    """
    解析HTML表格，返回每行的文本
    用于过滤表头行
    """
    import re
    rows = []

    # 简单的正则解析表格行
    # 匹配 <tr>...</tr>
    tr_pattern = re.compile(r'<tr[^>]*>(.*?)</tr>', re.DOTALL)
    for tr_match in tr_pattern.finditer(html_content):
        row_html = tr_match.group(1)
        # 提取行内文本
        text_in_row = re.sub(r'<[^>]+>', ' ', row_html)
        text_in_row = re.sub(r'\s+', ' ', text_in_row).strip()
        if text_in_row:
            rows.append(text_in_row)

    return rows


def filter_html_table_by_page_lines(html_content, page_lines, content_top, content_bottom):
    """
    根据PDF页面的文本行位置过滤HTML表格内容

    参数:
        html_content: MinerU提取的表格HTML
        page_lines: 从PyMuPDF获取的页面文本行 [{bbox, text}, ...]
        content_top: 内容体顶部y坐标
        content_bottom: 内容体底部y坐标

    返回:
        过滤后的文本内容
    """
    import re

    # 解析HTML表格行
    rows = []
    tr_pattern = re.compile(r'<tr[^>]*>(.*?)</tr>', re.DOTALL)
    for tr_match in tr_pattern.finditer(html_content):
        row_html = tr_match.group(1)
        row_text = re.sub(r'<[^>]+>', ' ', row_html)
        row_text = re.sub(r'\s+', ' ', row_text).strip()
        if row_text:
            rows.append({'html': row_html, 'text': row_text})

    if not rows:
        return ''

    # 计算在内容体内的页面行
    content_page_lines = []
    for line in page_lines:
        bbox = line.get('bbox', [])
        if bbox and len(bbox) >= 4:
            y_center = (bbox[1] + bbox[3]) / 2
            if content_top <= y_center <= content_bottom:
                content_page_lines.append(line.get('text', ''))

    # 简化：对于这种表格，HTML行和PDF行基本一一对应
    # 找到第一个在内容体内的HTML行
    start_row = 0
    for i, row in enumerate(rows):
        row_text = row['text']
        # 检查这个HTML行的内容是否与内容体内的页面行匹配
        for page_line in content_page_lines:
            if page_line and page_line in row_text:
                start_row = i
                break
        if start_row > 0:
            break

    # 从start_row开始提取内容
    filtered_rows = rows[start_row:]

    # 组合结果
    result_parts = []
    for row in filtered_rows:
        result_parts.append(row['text'])

    return ' '.join(result_parts)


def get_pdf_page_lines(pdf_path: str, content_regions: dict) -> dict:
    """
    从PDF获取内容体内的文本行，用于table HTML过滤

    返回: {page_num: [line_text1, line_text2, ...]}
    """
    import fitz  # PyMuPDF

    doc = fitz.open(pdf_path)
    page_lines_info = {}

    for page_idx, page in enumerate(doc):
        if page_idx not in content_regions:
            continue

        content_top, content_bottom = content_regions[page_idx]
        content_lines = []

        # 获取页面文本行
        text_dict = page.get_text('dict')
        for block in text_dict.get('blocks', []):
            for line in block.get('lines', []):
                bbox = line.get('bbox', [])
                if bbox and len(bbox) >= 4:
                    y_center = (bbox[1] + bbox[3]) / 2
                    if content_top <= y_center <= content_bottom:
                        line_text = ''.join([span.get('text', '') for span in line.get('spans', [])])
                        if line_text.strip():
                            content_lines.append(line_text.strip())

        page_lines_info[page_idx] = content_lines

    doc.close()
    return page_lines_info


def find_table_start_row(html_rows: list, content_lines: list) -> int:
    """
    找到HTML表格中第一个与内容体行匹配的行号

    参数:
        html_rows: HTML表格行文本列表
        content_lines: 内容体内的行文本列表

    返回:
        第一个匹配行的索引
    """
    if not content_lines:
        return 0

    # 清理内容行，合并可能被分割的文本
    # 例如："No Specific/无特殊要" 和 "求" 应该是 "No Specific/无特殊要求"
    cleaned_content_lines = []
    i = 0
    while i < len(content_lines):
        line = content_lines[i].strip()
        # 检查是否以中文字符结尾但可能被截断
        if i + 1 < len(content_lines):
            next_line = content_lines[i + 1].strip()
            # 如果当前行以中文字符结尾，且下一行很短，可能是续行
            if line and any('\u4e00' <= c <= '\u9fff' for c in line[-1]):
                # 尝试合并
                merged = line + next_line
                cleaned_content_lines.append(merged)
                i += 2
                continue
        cleaned_content_lines.append(line)
        i += 1

    # 取第一个非空内容行作为关键匹配词
    key_content = None
    for line in cleaned_content_lines:
        if line and len(line) > 2:
            key_content = line
            break

    if not key_content:
        return 0

    # 提取关键内容的前几个字符作为匹配词
    # 例如："No Specific/无特殊要求" 或 "2 No Specific"
    import re
    # 尝试提取数字或英文开头的关键词
    match = re.match(r'(\d+|[A-Za-z]+)', key_content)
    if match:
        keyword = match.group(1)
    else:
        # 使用前5个字符
        keyword = key_content[:5]

    # 在HTML行中查找匹配
    for i, html_row in enumerate(html_rows):
        if keyword in html_row:
            return i

    return 0


def is_bbox_in_content_body(bbox, content_top, content_bottom):
    """
    判断bbox是否与内容体重叠

    参数:
        bbox: [x0, y0, x1, y1]
        content_top: 内容体顶部y坐标
        content_bottom: 内容体底部y坐标

    返回:
        True: 与内容体重叠（部分或全部）
        False: 完全在内容体之外
    """
    if not bbox or len(bbox) < 4:
        return True  # 没有bbox信息，保守地保留

    y0, y1 = bbox[1], bbox[3]

    # 完全在内容体之上
    if y1 <= content_top:
        return False
    # 完全在内容体之下
    if y0 >= content_bottom:
        return False

    # 与内容体重叠
    return True


def extract_all_text(json_data: dict, content_regions: dict = None, page_lines_info: dict = None) -> str:
    """
    从 MinerU JSON 中提取所有文本内容

    参数:
        json_data: MinerU JSON数据
        content_regions: 内容体范围字典 {page_num: (y_top, y_bottom), ...}
                        如果为None，则提取所有内容
        page_lines_info: 页面行信息字典 {page_num: [line_text, ...]，内容体内的行}
                        用于过滤table HTML

    按页面内位置顺序提取 para_blocks，根据content_regions过滤
    """
    all_text = []

    pdf_info = json_data.get("pdf_info", [])

    for page_idx, page in enumerate(pdf_info):
        # 获取当前页的内容体范围
        if content_regions and page_idx in content_regions:
            content_top, content_bottom = content_regions[page_idx]
            use_filter = True
        else:
            use_filter = False

        # 收集所有blocks并按位置排序
        all_blocks = []

        # 添加 para_blocks
        for block in page.get("para_blocks", []):
            all_blocks.append(("para", block))

        # 添加 discarded_blocks（通过bbox过滤）
        for block in page.get("discarded_blocks", []):
            all_blocks.append(("discarded", block))

        # 按 bbox 顶部位置排序（从上到下）
        all_blocks.sort(key=lambda x: (x[1].get("bbox", [0, 0, 0, 0])[1] if x[1].get("bbox") else 0,
                                      x[1].get("index", 0)))

        # 按顺序处理每个block
        for source, block in all_blocks:
            block_type = block.get("type")

            # 跳过 image 类型
            if block_type == "image":
                continue

            # 处理 list 类型（包含子blocks）
            if block_type == "list":
                sub_blocks = block.get("blocks", [])
                for sub_block in sub_blocks:
                    sub_lines = sub_block.get("lines", [])
                    for line in sub_lines:
                        # 检查line的bbox是否在内容体内
                        if use_filter and not is_bbox_in_content_body(line.get("bbox"), content_top, content_bottom):
                            continue
                        spans = line.get("spans", [])
                        for span in spans:
                            span_type = span.get("type")
                            if span_type in ["text", "inline_equation"]:
                                content = span.get("content", "").strip()
                                if content:
                                    all_text.append(content)

            # 处理 table 类型（包含子blocks）
            elif block_type == "table":
                sub_blocks = block.get("blocks", [])
                for sub_block in sub_blocks:
                    sub_lines = sub_block.get("lines", [])
                    for line in sub_lines:
                        # 检查line的bbox是否在内容体内
                        if use_filter and not is_bbox_in_content_body(line.get("bbox"), content_top, content_bottom):
                            continue
                        spans = line.get("spans", [])
                        for span in spans:
                            span_type = span.get("type")
                            if span_type in ["text", "inline_equation"]:
                                content = span.get("content", "").strip()
                                if content:
                                    all_text.append(content)
                            elif span_type == "table":
                                # 表格内容在html字段中
                                html_content = span.get("html", "")
                                if html_content:
                                    # 对于表格，由于HTML包含所有行，需要解析过滤
                                    if use_filter and page_lines_info and page_idx in page_lines_info:
                                        # 解析HTML表格行
                                        html_rows = parse_html_table_rows(html_content)
                                        # 找到起始行
                                        content_lines = page_lines_info[page_idx]
                                        start_row = find_table_start_row(html_rows, content_lines)
                                        # 从起始行开始提取
                                        for row_text in html_rows[start_row:]:
                                            if row_text:
                                                all_text.append(row_text)
                                    else:
                                        # 不过滤，提取所有文本
                                        table_text = re.sub(r'<[^>]+>', ' ', html_content)
                                        table_text = re.sub(r'\s+', ' ', table_text).strip()
                                        if table_text:
                                            all_text.append(table_text)

            # 处理其他所有类型（text, title等）
            else:
                lines = block.get("lines", [])
                for line in lines:
                    # 检查line的bbox是否在内容体内
                    if use_filter and not is_bbox_in_content_body(line.get("bbox"), content_top, content_bottom):
                        continue
                    spans = line.get("spans", [])
                    for span in spans:
                        span_type = span.get("type")
                        if span_type in ["text", "inline_equation"]:
                            content = span.get("content", "").strip()
                            if content:
                                all_text.append(content)
                        elif span_type == "table":
                            # 表格内容在html字段中，提取其中的文本
                            html_content = span.get("html", "")
                            if html_content:
                                # 移除HTML标签，保留文本
                                table_text = re.sub(r'<[^>]+>', ' ', html_content)
                                # 清理多余空格和换行
                                table_text = re.sub(r'\s+', ' ', table_text).strip()
                                if table_text:
                                    all_text.append(table_text)

    # 用空格连接所有文本
    return ' '.join(all_text)


# 需要过滤的干扰性字串
# 注意：长的模式要放在前面，避免部分匹配
FILTER_PATTERNS = [
    r'警告[:：]\s*',
    r'警戒[:：]\s*',
    r'注意[:：]\s*',
    r'注[:：]\s*',
    r'WARNING:\s*',
    r'CAUTION:\s*',
    r'NOTE:\s*',
]


def filter_noise(text: str) -> str:
    """
    过滤干扰性字串
    删除"警告："、"注："等字串
    """
    # 标准化空白字符
    text = re.sub(r'\s+', ' ', text).strip()

    # 过滤掉这些字串
    for pattern in FILTER_PATTERNS:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)

    # 清理多余空格
    return re.sub(r'\s+', ' ', text).strip()


def filter_units(units: list) -> list:
    """
    过滤单元列表中的干扰字串
    同时删除过滤后为空的单元
    """
    filtered = []
    for u in units:
        cleaned = filter_noise(u)
        # 只保留非空单元
        if cleaned:
            filtered.append(cleaned)
    return filtered


# 分割符模式：用于将文本分割为便于定位的单元
SPLIT_PATTERNS = [
    # WARNING/CAUTION/NOTE 开头
    r'(?=WARNING:|CAUTION:|NOTE:|警告：|注意：|注：)',
    # 步骤编号 (1) (2) (a) (b) 等
    r'(?=\(\d+\)[.\s]|\([a-z]\)[.\s])',
    # 句号、分号、问号、感叹号（中英文）
    r'(?<=[.。；;！!?？])\s+',
]


def split_text_units(text: str) -> list:
    """
    将文本分割为便于定位的单元
    保留分隔符（句号等）在单元末尾，便于定位
    """
    # 先标准化空白字符
    text = re.sub(r'\s+', ' ', text).strip()

    units = []

    # 分割模式：找到所有分割位置和对应的分隔符
    # 使用正则表达式匹配分割点，并保留分隔符
    pattern = r'''
        (WARNING:|CAUTION:|NOTE:)\s+(?=[A-Z])|      # 关键词后跟空格
        (?<=\)\d\)|\)[a-z]\))\s+|                    # 步骤编号后跟空格
        ([.。；;！!?？])\s*(?=[A-Z\(]|\d|[\u4e00-\u9fff])  # 标点后跟大写/数字/中文
    '''

    # 找到所有匹配位置
    split_positions = []
    for match in re.finditer(pattern, text, re.VERBOSE):
        start, end = match.span()
        # 如果匹配的是关键词(WARNING:等)，start是关键词开始，end是空格后
        # 如果匹配的是标点，start是标点，end是标点后
        # 我们要在标点/关键词之后分割，并保留它们
        split_positions.append((start, end, match.group()))

    # 按位置排序
    split_positions.sort(key=lambda x: x[0])

    # 根据分割位置构建单元
    last_end = 0
    for start, end, matched in split_positions:
        if start > last_end:
            unit = text[last_end:end].strip()  # 包含分隔符
            if unit:
                units.append(unit)
            last_end = end

    # 添加剩余部分
    if last_end < len(text):
        remaining = text[last_end:].strip()
        if remaining:
            units.append(remaining)

    # 过滤噪声关键词：去掉前缀而不是过滤整个单元
    noise_keywords = [
        '警告:', '注意:', '注:', 'WARNING:', 'CAUTION:', 'NOTE:',
        '警告：', '注意：', '注：'
    ]
    filtered_units = []
    for unit in units:
        # 检查单元是否以噪声关键词开头
        processed_unit = unit
        for keyword in noise_keywords:
            stripped = unit.lstrip()
            if stripped.startswith(keyword):
                # 去掉关键词前缀，保留后面的内容
                idx = stripped.find(keyword)
                remaining = stripped[idx + len(keyword):].strip()
                if remaining:  # 如果后面还有内容，保留
                    processed_unit = remaining
                else:
                    # 如果没有其他内容，跳过这个单元
                    processed_unit = None
                break
        if processed_unit:
            filtered_units.append(processed_unit)

    return filtered_units


def normalize_for_compare(text: str) -> str:
    """
    标准化文本用于比较
    - 统一空白字符为单个空格
    - 去除首尾空白
    - 删除中文字符之间的连字符（PDF换行伪影）
    - 删除中文相关空格（PDF提取伪影）
    注意：不删除英文之间的连字符，因为它们可能有意义
    """
    # 删除中文字符后面的连字符（这是PDF换行伪影）
    text = re.sub(r'([\u4e00-\u9fff])-\s*', r'\1', text)
    # 删除中文字符之间的连字符
    text = re.sub(r'([\u4e00-\u9fff])-\s*([\u4e00-\u9fff])', r'\1\2', text)
    # 删除中文与英文之间的连字符（PDF换行伪影）
    text = re.sub(r'([\u4e00-\u9fff])-\s*([A-Za-z])', r'\1\2', text)
    # 删除中文字符之间的空格
    text = re.sub(r'([\u4e00-\u9fff])\s+([\u4e00-\u9fff])', r'\1\2', text)
    # 删除中文标点后的空格
    text = re.sub(r'([，。；：！？、）】])\s+', r'\1', text)
    # 删除中文标点前的空格
    text = re.sub(r'\s+([，。；：！？、【（])', r'\1', text)
    # 删除中文与英文/数字/括号之间的空格
    text = re.sub(r'([\u4e00-\u9fff])\s+([A-Za-z0-9\(\)\[\]])', r'\1\2', text)
    text = re.sub(r'([A-Za-z0-9\(\)\[\]])\s+([\u4e00-\u9fff])', r'\1\2', text)
    # 删除标点符号与字母/数字之间的空格
    text = re.sub(r'([,\.\'])\s+([A-Za-z0-9])', r'\1\2', text)
    text = re.sub(r'([A-Za-z0-9])\s+([\(\)\[\]])', r'\1\2', text)
    text = re.sub(r'([\(\)\[\]])\s+([A-Za-z0-9])', r'\1\2', text)
    # 删除数字与温度符号之间的空格
    text = re.sub(r'(\d)\s+(℃)', r'\1\2', text)
    # 删除smart single quote (') 后面的空格 - 用Unicode范围
    text = re.sub(r'([\u2019\u02BC])\s+([A-Za-z0-9])', r'\1\2', text)
    # 删除括号之间的纯空格
    text = re.sub(r'\(\s+\)', '()', text)
    text = re.sub(r'\[\s+\]', '[]', text)
    # 删除英文字母/数字之间的所有空格（循环处理直到无变化）
    while True:
        new_text = re.sub(r'([A-Za-z0-9])\s+([A-Za-z0-9])', r'\1\2', text)
        if new_text == text:
            break
        text = new_text
    # 删除破折号/连字符后的空格（PDF提取伪影）
    text = re.sub(r'-\s+', '-', text)
    # 统一空白字符为单个空格
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def compare_texts(old_text: str, new_text: str) -> dict:
    """
    比较两个文本，返回差异结果
    使用基于位置和内容相似度的匹配算法，保持原始顺序
    """
    import difflib

    old_units = split_text_units(old_text)
    new_units = split_text_units(new_text)

    # 先过滤干扰字串
    old_units = filter_units(old_units)
    new_units = filter_units(new_units)

    result = {
        'stats': {
            'additions': 0,
            'deletions': 0,
            'modifications': 0,
            'unchanged': 0,
        },
        'units': [],
    }

    # 使用 SequenceMatcher 进行基于位置的匹配
    # 这样可以保持原始顺序
    matcher = difflib.SequenceMatcher(None, old_units, new_units, autojunk=False)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        old_chunk = old_units[i1:i2]
        new_chunk = new_units[j1:j2]

        if tag == 'equal':
            # 内容相同（按位置对应）
            for old_unit, new_unit in zip(old_chunk, new_chunk):
                result['stats']['unchanged'] += 1
                result['units'].append({
                    'type': 'equal',
                    'old': old_unit,
                    'new': new_unit,
                })

        elif tag == 'replace':
            # 内容替换：使用 SequenceMatcher 在块内进行匹配，保持顺序
            sub_matcher = difflib.SequenceMatcher(None, old_chunk, new_chunk, autojunk=False)

            for sub_tag, sub_i1, sub_i2, sub_j1, sub_j2 in sub_matcher.get_opcodes():
                sub_old_chunk = old_chunk[sub_i1:sub_i2]
                sub_new_chunk = new_chunk[sub_j1:sub_j2]

                if sub_tag == 'equal':
                    # 内容相同
                    for old_unit, new_unit in zip(sub_old_chunk, sub_new_chunk):
                        old_normalized = normalize_for_compare(old_unit)
                        new_normalized = normalize_for_compare(new_unit)
                        ratio = difflib.SequenceMatcher(None, old_normalized, new_normalized).ratio()

                        if ratio >= 0.98:
                            result['stats']['unchanged'] += 1
                            result['units'].append({
                                'type': 'equal',
                                'old': old_unit,
                                'new': new_unit,
                            })
                        else:
                            old_diff, new_diff = compute_char_diff(old_unit, new_unit)
                            has_highlights = ('added-word' in old_diff or 'added-word' in new_diff or
                                              'deleted-word' in old_diff or 'deleted-word' in new_diff)
                            if not has_highlights:
                                result['stats']['unchanged'] += 1
                                result['units'].append({
                                    'type': 'equal',
                                    'old': old_unit,
                                    'new': new_unit,
                                })
                            else:
                                result['stats']['modifications'] += 1
                                result['units'].append({
                                    'type': 'modified',
                                    'old': old_unit,
                                    'new': new_unit,
                                    'old_diff': old_diff,
                                    'new_diff': new_diff,
                                })

                elif sub_tag == 'delete':
                    # 原文有，新文没有
                    for old_unit in sub_old_chunk:
                        result['stats']['deletions'] += 1
                        result['units'].append({
                            'type': 'deleted',
                            'old': old_unit,
                            'new': None,
                        })

                elif sub_tag == 'insert':
                    # 新文有，原文没有
                    for new_unit in sub_new_chunk:
                        result['stats']['additions'] += 1
                        result['units'].append({
                            'type': 'added',
                            'old': None,
                            'new': new_unit,
                        })

                elif sub_tag == 'replace':
                    # 子块替换：保持原文和新文的相对顺序
                    # 使用归一化后的单元进行匹配
                    sub_old_norm = [normalize_for_compare(u) for u in sub_old_chunk]
                    sub_new_norm = [normalize_for_compare(u) for u in sub_new_chunk]

                    # 使用 SequenceMatcher 在归一化后的单元间匹配
                    sub_sub_matcher = difflib.SequenceMatcher(None, sub_old_norm, sub_new_norm, autojunk=False)

                    for sub_sub_tag, sub_sub_i1, sub_sub_i2, sub_sub_j1, sub_sub_j2 in sub_sub_matcher.get_opcodes():
                        sub_sub_old_chunk = sub_old_chunk[sub_sub_i1:sub_sub_i2]
                        sub_sub_new_chunk = sub_new_chunk[sub_sub_j1:sub_sub_j2]

                        if sub_sub_tag == 'equal':
                            # 一对一匹配
                            for old_u, new_u in zip(sub_sub_old_chunk, sub_sub_new_chunk):
                                m = difflib.SequenceMatcher(None, normalize_for_compare(old_u), normalize_for_compare(new_u))
                                if m.ratio() >= 0.98:
                                    result['stats']['unchanged'] += 1
                                    result['units'].append({'type': 'equal', 'old': old_u, 'new': new_u})
                                else:
                                    old_diff, new_diff = compute_char_diff(old_u, new_u)
                                    has_highlights = ('added-word' in old_diff or 'added-word' in new_diff or
                                                      'deleted-word' in old_diff or 'deleted-word' in new_diff)
                                    if not has_highlights:
                                        result['stats']['unchanged'] += 1
                                        result['units'].append({'type': 'equal', 'old': old_u, 'new': new_u})
                                    else:
                                        result['stats']['modifications'] += 1
                                        result['units'].append({
                                            'type': 'modified', 'old': old_u, 'new': new_u,
                                            'old_diff': old_diff, 'new_diff': new_diff,
                                        })

                        elif sub_sub_tag == 'delete':
                            for old_u in sub_sub_old_chunk:
                                result['stats']['deletions'] += 1
                                result['units'].append({'type': 'deleted', 'old': old_u, 'new': None})

                        elif sub_sub_tag == 'insert':
                            for new_u in sub_sub_new_chunk:
                                result['stats']['additions'] += 1
                                result['units'].append({'type': 'added', 'old': None, 'new': new_u})

                        elif sub_sub_tag == 'replace':
                            # 在更小的块中，尝试找到最佳匹配，同时保持顺序
                            # 限制匹配范围：只允许在相邻位置匹配
                            max_len = max(len(sub_sub_old_chunk), len(sub_sub_new_chunk))
                            for k in range(max_len):
                                old_u = sub_sub_old_chunk[k] if k < len(sub_sub_old_chunk) else None
                                new_u = sub_sub_new_chunk[k] if k < len(sub_sub_new_chunk) else None

                                if old_u and new_u:
                                    # 尝试匹配
                                    ratio = difflib.SequenceMatcher(None, normalize_for_compare(old_u), normalize_for_compare(new_u)).ratio()
                                    if ratio >= 0.85:
                                        old_diff, new_diff = compute_char_diff(old_u, new_u)
                                        has_highlights = ('added-word' in old_diff or 'added-word' in new_diff or
                                                          'deleted-word' in old_diff or 'deleted-word' in new_diff)
                                        if not has_highlights:
                                            result['stats']['unchanged'] += 1
                                            result['units'].append({'type': 'equal', 'old': old_u, 'new': new_u})
                                        else:
                                            result['stats']['modifications'] += 1
                                            result['units'].append({
                                                'type': 'modified', 'old': old_u, 'new': new_u,
                                                'old_diff': old_diff, 'new_diff': new_diff,
                                            })
                                    else:
                                        # 不匹配，分别处理
                                        result['stats']['deletions'] += 1
                                        result['units'].append({'type': 'deleted', 'old': old_u, 'new': None})
                                        result['stats']['additions'] += 1
                                        result['units'].append({'type': 'added', 'old': None, 'new': new_u})
                                elif old_u:
                                    result['stats']['deletions'] += 1
                                    result['units'].append({'type': 'deleted', 'old': old_u, 'new': None})
                                elif new_u:
                                    result['stats']['additions'] += 1
                                    result['units'].append({'type': 'added', 'old': None, 'new': new_u})

        elif tag == 'delete':
            # 原文中有，新文中没有
            for old_unit in old_chunk:
                result['stats']['deletions'] += 1
                result['units'].append({
                    'type': 'deleted',
                    'old': old_unit,
                    'new': None,
                })

        elif tag == 'insert':
            # 新文中有，原文中没有
            for new_unit in new_chunk:
                result['stats']['additions'] += 1
                result['units'].append({
                    'type': 'added',
                    'old': None,
                    'new': new_unit,
                })

    return result


def compute_char_diff(old_text: str, new_text: str) -> tuple:
    """
    计算字符级差异
    """
    import difflib
    import html

    old_text = normalize_for_compare(old_text)
    new_text = normalize_for_compare(new_text)

    if not old_text and not new_text:
        return '', ''
    if not old_text:
        return '', f'<span class="added-word">{html.escape(new_text)}</span>'
    if not new_text:
        return f'<span class="deleted-word">{html.escape(old_text)}</span>', ''

    matcher = difflib.SequenceMatcher(None, old_text, new_text)

    old_html = []
    new_html = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        old_chunk = old_text[i1:i2]
        new_chunk = new_text[j1:j2]

        if tag == 'equal':
            old_html.append(html.escape(old_chunk))
            new_html.append(html.escape(new_chunk))
        elif tag == 'delete':
            old_html.append(f'<span class="deleted-word">{html.escape(old_chunk)}</span>')
        elif tag == 'insert':
            new_html.append(f'<span class="added-word">{html.escape(new_chunk)}</span>')
        elif tag == 'replace':
            old_html.append(f'<span class="deleted-word">{html.escape(old_chunk)}</span>')
            new_html.append(f'<span class="added-word">{html.escape(new_chunk)}</span>')

    return ''.join(old_html), ''.join(new_html)


def generate_html(diff_result: dict, output_file: str, title: str, theme: str = 'dark'):
    """生成HTML差异报告 - 左右对照布局"""

    THEMES = {
        'light': {
            'bg': '#ffffff',
            'text': '#1f2328',
            'line_number_bg': '#f6f8fa',
            'line_number_text': '#656d76',
            'add_bg': '#dafbe1',
            'add_border': '#2da44e',
            'add_text': '#1a7f37',
            'del_bg': '#ffebe9',
            'del_border': '#cf222e',
            'del_text': '#cf222e',
            'header_bg': '#f6f8fa',
            'header_border': '#d0d7de',
            'changed_bg': '#fff8c5',
            'changed_border': '#d4a72c',
            'changed_text': '#9a6700',
            'add_word_bg': '#1a7f37',
            'add_word_text': '#ffffff',
            'del_word_bg': '#cf222e',
            'del_word_text': '#ffffff',
        },
        'dark': {
            'bg': '#0d1117',
            'text': '#c9d1d9',
            'line_number_bg': '#161b22',
            'line_number_text': '#484f58',
            'add_bg': '#1c3a29',
            'add_border': '#2ea44f',
            'add_text': '#3fb950',
            'del_bg': '#3d1c1c',
            'del_border': '#f85149',
            'del_text': '#ff7b72',
            'header_bg': '#161b22',
            'header_border': '#30363d',
            'changed_bg': '#3d3a00',
            'changed_border': '#d4a72c',
            'changed_text': '#e3b341',
            'add_word_bg': '#238636',
            'add_word_text': '#ffffff',
            'del_word_bg': '#da3633',
            'del_word_text': '#ffffff',
        },
    }

    t = THEMES.get(theme, THEMES['dark'])
    stats = diff_result['stats']
    units = diff_result['units']
    total_units = len(units)

    # 生成左右对照的行
    left_rows = []
    right_rows = []

    for unit in units:
        unit_type = unit['type']

        if unit_type == 'equal':
            left_rows.append(('equal', unit['old']))
            right_rows.append(('equal', unit['new']))

        elif unit_type == 'deleted':
            left_rows.append(('deleted', unit['old']))
            right_rows.append(('empty', ''))

        elif unit_type == 'added':
            left_rows.append(('empty', ''))
            right_rows.append(('added', unit['new']))

        elif unit_type == 'modified':
            left_rows.append(('modified', unit['old_diff'] if 'old_diff' in unit else unit['old']))
            right_rows.append(('modified', unit['new_diff'] if 'new_diff' in unit else unit['new']))

    def esc(s):
        import html
        return html.escape(str(s)) if s else ''

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{esc(title)}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background-color: {t['bg']};
            color: {t['text']};
            line-height: 1.5;
        }}
        .container {{ max-width: 1600px; margin: 0 auto; padding: 16px; }}

        /* 头部 */
        .header {{
            background-color: {t['header_bg']};
            border: 1px solid {t['header_border']};
            border-radius: 8px;
            padding: 16px 20px;
            margin-bottom: 16px;
        }}
        .header h1 {{ font-size: 18px; font-weight: 600; margin-bottom: 12px; }}

        /* 统计 */
        .stats {{ display: flex; flex-wrap: wrap; gap: 16px; margin-bottom: 12px; }}
        .stat-item {{ display: flex; align-items: center; gap: 8px; font-size: 13px; }}
        .badge {{
            display: inline-flex; align-items: center; padding: 2px 8px;
            border-radius: 12px; font-size: 12px; font-weight: 600;
        }}
        .badge.added {{ background: {t['add_bg']}; color: {t['add_text']}; border: 1px solid {t['add_border']}; }}
        .badge.deleted {{ background: {t['del_bg']}; color: {t['del_text']}; border: 1px solid {t['del_border']}; }}
        .badge.changed {{ background: {t['changed_bg']}; color: {t['changed_text']}; border: 1px solid {t['changed_border']}; }}

        /* 图例 */
        .legend {{ display: flex; gap: 16px; font-size: 12px; color: {t['line_number_text']}; }}
        .legend-item {{ display: flex; align-items: center; gap: 4px; }}
        .legend-box {{ width: 14px; height: 14px; border-radius: 3px; border: 1px solid; }}

        /* 差异容器 */
        .diff-wrapper {{ border: 1px solid {t['header_border']}; border-radius: 8px; overflow: hidden; }}
        .diff-container {{ display: flex; font-size: 13px; line-height: 20px; }}

        /* 左右面板 */
        .diff-panel {{ flex: 1; display: flex; flex-direction: column; }}
        .diff-panel:first-child {{ border-right: 1px solid {t['header_border']}; }}

        .panel-header {{
            background-color: {t['header_bg']};
            padding: 8px 16px;
            font-size: 12px;
            font-weight: 600;
            border-bottom: 1px solid {t['header_border']};
        }}

        .diff-content {{ font-family: "SFMono-Regular", Consolas, monospace; }}

        /* 行样式 */
        .diff-row {{ display: flex; min-height: 20px; }}
        .diff-row:not(:last-child) {{ border-bottom: 1px solid {t['header_border']}; }}

        .line-number {{
            width: 50px; min-width: 50px;
            padding: 0 8px;
            text-align: right;
            color: {t['line_number_text']};
            font-size: 12px;
            user-select: none;
            border-right: 1px solid {t['header_border']};
            background-color: {t['line_number_bg']};
        }}

        .line-content {{ flex: 1; padding: 0 12px; white-space: pre-wrap; word-break: break-word; }}

        /* 差异行背景 */
        .row-added {{ background-color: {t['add_bg']}; }}
        .row-deleted {{ background-color: {t['del_bg']}; }}
        .row-modified {{ background-color: {t['changed_bg']}; }}
        .row-empty {{ background-color: {t['line_number_bg']}; }}

        /* 字符高亮 */
        .added-word {{ background: {t['add_word_bg']}; color: {t['add_word_text']}; padding: 1px 3px; border-radius: 3px; font-weight: 600; }}
        .deleted-word {{ background: {t['del_word_bg']}; color: {t['del_word_text']}; text-decoration: line-through; padding: 1px 3px; border-radius: 3px; font-weight: 600; }}

        /* 搜索 */
        .search-input {{
            width: 100%; max-width: 300px; padding: 6px 12px;
            border: 1px solid {t['header_border']}; border-radius: 6px;
            background: {t['bg']}; color: {t['text']}; font-size: 13px;
        }}
        .search-highlight {{ background: #fffb8c; border: 1px solid #eac54f; border-radius: 2px; }}

        /* 悬浮按钮 */
        .fab {{
            position: fixed; bottom: 30px; right: 30px; width: 44px; height: 44px;
            border-radius: 50%; background: {t['add_border']}; color: white;
            border: none; font-size: 20px; cursor: pointer;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        }}
        .fab:hover {{ transform: scale(1.1); }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{esc(title)}</h1>
            <div class="stats">
                <div class="stat-item"><span class="badge added">+{stats['additions']}</span><span>新增</span></div>
                <div class="stat-item"><span class="badge deleted">-{stats['deletions']}</span><span>删除</span></div>
                <div class="stat-item"><span class="badge changed">~{stats['modifications']}</span><span>修改</span></div>
                <div class="stat-item"><span>共 {total_units} 个单元</span></div>
            </div>
            <div class="legend">
                <div class="legend-item"><div class="legend-box" style="background: {t['add_bg']}; border-color: {t['add_border']};"></div><span>新增</span></div>
                <div class="legend-item"><div class="legend-box" style="background: {t['del_bg']}; border-color: {t['del_border']};"></div><span>删除</span></div>
                <div class="legend-item"><div class="legend-box" style="background: {t['changed_bg']}; border-color: {t['changed_border']};"></div><span>修改</span></div>
            </div>
            <input type="text" class="search-input" id="searchInput" placeholder="搜索内容..." style="margin-top: 12px;">
        </div>

        <div class="diff-wrapper">
            <div class="diff-container">
                <div class="diff-panel">
                    <div class="panel-header">原文</div>
                    <div class="diff-content" id="leftPanel">
'''

    # 生成左侧内容（带行号）
    line_num = 1
    for row_type, content in left_rows:
        row_class = {
            'equal': 'row-empty',
            'deleted': 'row-deleted',
            'modified': 'row-modified',
            'empty': 'row-empty',
        }.get(row_type, 'row-empty')

        # 只在非空行显示行号
        num_display = str(line_num) if row_type != 'empty' else ''
        if row_type != 'empty':
            line_num += 1

        html += f'''                        <div class="diff-row {row_class}">
                            <div class="line-number">{num_display}</div>
                            <div class="line-content">{content if content else '&nbsp;'}</div>
                        </div>
'''

    html += '''                    </div>
                </div>
                <div class="diff-panel">
                    <div class="panel-header">新文</div>
                    <div class="diff-content" id="rightPanel">
'''

    # 生成右侧内容（带行号）
    line_num = 1
    for row_type, content in right_rows:
        row_class = {
            'equal': 'row-empty',
            'added': 'row-added',
            'modified': 'row-modified',
            'empty': 'row-empty',
        }.get(row_type, 'row-empty')

        # 只在非空行显示行号
        num_display = str(line_num) if row_type != 'empty' else ''
        if row_type != 'empty':
            line_num += 1

        html += f'''                        <div class="diff-row {row_class}">
                            <div class="line-number">{num_display}</div>
                            <div class="line-content">{content if content else '&nbsp;'}</div>
                        </div>
'''

    html += '''                    </div>
                </div>
            </div>
        </div>
    </div>

    <button class="fab" onclick="scrollToFirstDiff()" title="跳转到第一个差异">↓</button>

    <script>
        // 同步滚动
        const leftPanel = document.getElementById('leftPanel');
        const rightPanel = document.getElementById('rightPanel');
        let isScrollingLeft = false;
        let isScrollingRight = false;

        leftPanel.addEventListener('scroll', function() {
            if (!isScrollingRight) {{
                isScrollingLeft = true;
                rightPanel.scrollTop = this.scrollTop;
            }}
            setTimeout(() => {{ isScrollingLeft = false; }}, 50);
        });

        rightPanel.addEventListener('scroll', function() {
            if (!isScrollingLeft) {{
                isScrollingRight = true;
                leftPanel.scrollTop = this.scrollTop;
            }}
            setTimeout(() => {{ isScrollingRight = false; }}, 50);
        });

        // 搜索功能
        const searchInput = document.getElementById('searchInput');
        searchInput.addEventListener('input', function() {
            clearHighlights();
            const query = this.value.trim().toLowerCase();
            if (query.length < 2) return;
            highlightText(query);
        });

        function clearHighlights() {
            document.querySelectorAll('.search-highlight').forEach(el => {
                const parent = el.parentNode;
                parent.replaceChild(document.createTextNode(el.textContent), el);
                parent.normalize();
            });
        }

        function highlightText(query) {
            [leftPanel, rightPanel].forEach(panel => {
                const walker = document.createTreeWalker(panel, NodeFilter.SHOW_TEXT, null);
                const textNodes = [];
                let node;
                while (node = walker.nextNode()) {
                    if (node.textContent.toLowerCase().includes(query)) {
                        textNodes.push(node);
                    }
                }
                textNodes.forEach(textNode => {
                    const regex = new RegExp(`(${escapeRegex(query)})`, 'gi');
                    const span = document.createElement('span');
                    span.innerHTML = textNode.textContent.replace(regex, '<mark class="search-highlight">$1</mark>');
                    textNode.parentNode.replaceChild(span, textNode);
                });
            });
        }

        function escapeRegex(string) {
            return string.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&');
        }

        function scrollToFirstDiff() {
            const firstDiff = document.querySelector('.row-added, .row-deleted, .row-modified');
            if (firstDiff) {
                firstDiff.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        }

        document.addEventListener('keydown', function(e) {
            if (e.ctrlKey && e.key === 'f') {
                e.preventDefault();
                searchInput.focus();
                searchInput.select();
            }
        });
    </script>
</body>
</html>'''

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html)


def calculate_content_regions_from_pdf(pdf_path: str) -> dict:
    """
    从PDF文件计算内容体范围

    返回: {page_num: (y_top, y_bottom), ...}
    """
    import fitz  # PyMuPDF

    doc = fitz.open(pdf_path)
    content_regions = {}

    for page_idx, page in enumerate(doc):
        # 检测"工卡标题"文本位置
        text_instances = page.search_for("工卡标题")
        if not text_instances:
            # 如果找不到，使用默认值
            page_height = page.rect.height
            content_regions[page_idx] = (100, page_height - 50)
            continue

        text_rect = fitz.Rect(text_instances[0])

        # 获取所有横线，找文本正下方的横线
        drawings = page.get_drawings()
        horizontal_lines = []
        for drawing in drawings:
            items = drawing.get("items", [])
            for item in items:
                if item[0] == "l":
                    _, p1, p2 = item
                    if abs(p1.y - p2.y) < 0.1:
                        length = abs(p1.x - p2.x)
                        if length > 50:
                            horizontal_lines.append({
                                "x1": min(p1.x, p2.x),
                                "x2": max(p1.x, p2.x),
                                "y": p1.y,
                            })

        # 找文本正下方的横线
        candidates = []
        for line in horizontal_lines:
            if line["y"] > text_rect.y1:
                text_center_x = (text_rect.x0 + text_rect.x1) / 2
                if line["x1"] <= text_center_x <= line["x2"]:
                    distance = line["y"] - text_rect.y1
                    candidates.append((line["y"], distance))

        if candidates:
            candidates.sort(key=lambda x: x[1])
            content_top = candidates[0][0] + MRO_COEFFS["top_offset_pt"]
        else:
            content_top = text_rect.y1 + 10

        # 检测"飞机适用范围"文本位置
        text_instances = page.search_for("飞机适用范围")
        if text_instances:
            text_rect = fitz.Rect(text_instances[0])

            # 获取所有竖线
            vertical_lines = []
            for drawing in drawings:
                items = drawing.get("items", [])
                for item in items:
                    if item[0] == "l":
                        _, p1, p2 = item
                        if abs(p1.x - p2.x) < 0.1:
                            length = abs(p1.y - p2.y)
                            if length > 20:
                                vertical_lines.append({
                                    "y1": min(p1.y, p2.y),
                                    "y2": max(p1.y, p2.y),
                                    "x": p1.x,
                                })

            # 找文本右方的竖线
            candidates = []
            for line in vertical_lines:
                if line["x"] > text_rect.x1:
                    text_center_y = (text_rect.y0 + text_rect.y1) / 2
                    if line["y1"] <= text_center_y <= line["y2"]:
                        distance = line["x"] - text_rect.x1
                        candidates.append((line["y1"], distance))

            if candidates:
                candidates.sort(key=lambda x: x[1])
                content_bottom = candidates[0][0]
            else:
                content_bottom = page.rect.height - 50
        else:
            content_bottom = page.rect.height - 50

        content_regions[page_idx] = (content_top, content_bottom)

    doc.close()
    return content_regions


def compare_pdf_json_files(file1_path: str, file2_path: str,
                          output_file: str = 'pdf_diff_result.html',
                          theme: str = 'dark',
                          content_regions: dict = None,
                          pdf1_for_crop: str = None,
                          pdf2_for_crop: str = None) -> str:
    """
    比较两个 MinerU JSON 文件

    参数:
        file1_path: 原文JSON文件路径
        file2_path: 新文JSON文件路径
        output_file: 输出HTML文件路径
        theme: 颜色主题
        content_regions: 内容体范围 {page_num: (y_top, y_bottom), ...}
                        如果为None且提供了pdf1_for_crop，则自动计算
        pdf1_for_crop: 用于计算内容体范围的原文PDF路径
        pdf2_for_crop: 用于计算内容体范围的新文PDF路径
    """
    if not os.path.exists(file1_path):
        raise FileNotFoundError(f"文件不存在: {file1_path}")
    if not os.path.exists(file2_path):
        raise FileNotFoundError(f"文件不存在: {file2_path}")

    print(f"正在读取文件: {file1_path}")
    with open(file1_path, 'r', encoding='utf-8') as f:
        data1 = json.load(f)

    print(f"正在读取文件: {file2_path}")
    with open(file2_path, 'r', encoding='utf-8') as f:
        data2 = json.load(f)

    # 计算内容体范围
    pdf_for_crop = None
    if content_regions is None:
        if pdf1_for_crop and os.path.exists(pdf1_for_crop):
            pdf_for_crop = pdf1_for_crop
        elif pdf2_for_crop and os.path.exists(pdf2_for_crop):
            pdf_for_crop = pdf2_for_crop

        if pdf_for_crop:
            print("正在计算内容体范围...")
            content_regions = calculate_content_regions_from_pdf(pdf_for_crop)
            print(f"  内容体范围: 第0页 y={content_regions[0][0]:.1f} 到 {content_regions[0][1]:.1f}")
            # 获取页面行信息用于table过滤
            page_lines_info = get_pdf_page_lines(pdf_for_crop, content_regions)
        else:
            page_lines_info = None
    else:
        if pdf1_for_crop and os.path.exists(pdf1_for_crop):
            pdf_for_crop = pdf1_for_crop
        elif pdf2_for_crop and os.path.exists(pdf2_for_crop):
            pdf_for_crop = pdf2_for_crop

        if pdf_for_crop:
            page_lines_info = get_pdf_page_lines(pdf_for_crop, content_regions)
        else:
            page_lines_info = None

    print("正在提取文本内容...")
    text1 = extract_all_text(data1, content_regions, page_lines_info)
    text2 = extract_all_text(data2, content_regions, page_lines_info)

    print(f"文件1提取到 {len(text1)} 个字符")
    print(f"文件2提取到 {len(text2)} 个字符")

    print("正在比较差异...")
    diff_result = compare_texts(text1, text2)

    file1_name = os.path.basename(file1_path)
    file2_name = os.path.basename(file2_path)
    title = f"{file1_name} vs {file2_name} - 差异比较"

    generate_html(diff_result, output_file, title, theme)

    stats = diff_result['stats']
    print(f"✓ 差异报告已生成: {output_file}")
    print(f"  新增单元: +{stats['additions']}")
    print(f"  删除单元: -{stats['deletions']}")
    print(f"  修改单元: ~{stats['modifications']}")
    print(f"  未变单元: {stats['unchanged']}")

    return output_file


def main():
    parser = argparse.ArgumentParser(
        description='PDF 文本比对工具 - 简化版本',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  %(prog)s --json file1.json file2.json
  %(prog)s --json file1.json file2.json -o result.html -t light
  %(prog)s --json file1.json file2.json --pdf1 file1.pdf
  %(prog)s --json file1.json file2.json --pdf1 file1.pdf --pdf2 file2.pdf
        '''
    )

    parser.add_argument('--json', nargs=2, metavar=('FILE1', 'FILE2'),
                        help='比较两个 MinerU JSON 文件')
    parser.add_argument('-o', '--output', default='diff_result.html',
                        help='输出HTML文件路径 (默认: diff_result.html)')
    parser.add_argument('-t', '--theme', choices=['light', 'dark'],
                        default='dark', help='颜色主题 (默认: dark)')
    parser.add_argument('--pdf1', metavar='PDF_FILE',
                        help='原文PDF文件路径（用于计算内容体范围，过滤header/footer）')
    parser.add_argument('--pdf2', metavar='PDF_FILE',
                        help='新文PDF文件路径（用于计算内容体范围，过滤header/footer）')

    args = parser.parse_args()

    if not args.json:
        parser.print_help()
        return 1

    try:
        compare_pdf_json_files(
            args.json[0],
            args.json[1],
            args.output,
            args.theme,
            content_regions=None,
            pdf1_for_crop=args.pdf1,
            pdf2_for_crop=args.pdf2
        )
        return 0
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    exit(main())
