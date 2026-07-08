#!/usr/bin/env python3
"""
使用正确的线条检测逻辑

坐标系统：屏幕坐标（y=0在顶部，y向下增大）

检测逻辑：
- 左边线条: x ≈ 25.56
- 顶部线条: y ≈ 55.80 (距顶部55.80点，在页面顶部附近)
- 右边线条: x ≈ 498.96 (距右边113.04点)
- 底部线条: y ≈ 720.00 (距顶部720点=距底部72点，在页面底部附近)
"""

import fitz  # PyMuPDF
from pathlib import Path


# 微调系数（基于屏幕坐标系统：y=0在顶部，y向下增大）
# 用于所有页面
MRO_COEFFS = {
    "name": "MRO",
    "left_offset_pt": 0.56,     # 25.56 - 24.50
    "top_offset_pt": 0.20,      # 55.80 - 55.60（第2页）/ 559.80 - 559.60（第1页）
    "right_offset_pt": 0.74,    # 113.04 - 112.30
    "bottom_offset_pt": 2.00,   # 72.00 - 70.00
}

XINYUAN_COEFFS = {
    "name": "Xinyuan",
    "left_offset_pt": 0.0,
    "top_offset_pt": 0.0,
    "right_offset_pt": 0.0,
    "bottom_offset_pt": 0.0,
}


def detect_pdf_type_by_size(page):
    """通过页面尺寸判断PDF类型"""
    width = page.rect.width
    height = page.rect.height
    width_inch = width / 72
    height_inch = height / 72

    if abs(width_inch - 8.5) < 0.1 and abs(height_inch - 11.0) < 0.1:
        return MRO_COEFFS
    elif abs(width_inch - 8.281) < 0.1 and abs(height_inch - 11.427) < 0.1:
        return XINYUAN_COEFFS
    else:
        return MRO_COEFFS


def is_large_image_page(page, min_area_ratio=0.3):
    """
    判断页面是否为嵌入大图片的页面

    参数:
        page: PyMuPDF页面对象
        min_area_ratio: 图片占页面面积的最小比例（默认0.3=30%）

    返回:
        True: 是大图片页
        False: 不是大图片页（文本页或小图标页）
    """
    page_width = page.rect.width
    page_height = page.rect.height
    page_area = page_width * page_height

    # 检查页面上的图片
    image_list = page.get_images()
    if not image_list:
        return False

    # 检查每个图片在页面上的显示区域
    for img in image_list:
        xref = img[0]
        try:
            image_info = page.get_image_info(xref)
            if image_info:
                for info in image_info:
                    bbox = info.get('bbox')
                    if bbox:
                        x0, y0, x1, y1 = bbox
                        img_width = x1 - x0
                        img_height = y1 - y0
                        img_area = img_width * img_height
                        area_ratio = img_area / page_area

                        # 如果图片面积超过页面面积的30%，认为是图片页
                        if area_ratio >= min_area_ratio:
                            return True
        except Exception:
            continue

    # 额外检查：图片的原始尺寸（大图通常像素很多）
    for img in image_list:
        xref = img[0]
        try:
            # 使用parent document提取图片信息
            parent = page.parent
            if parent:
                base_image = parent.extract_image(xref)
                if base_image:
                    # 大图通常宽度或高度超过1500像素
                    if base_image.width > 1500 or base_image.height > 1500:
                        # 进一步检查这个图片在页面上的显示比例
                        image_info = page.get_image_info(xref)
                        if image_info:
                            for info in image_info:
                                bbox = info.get('bbox')
                                if bbox:
                                    x0, y0, x1, y1 = bbox
                                    img_width = x1 - x0
                                    # 如果大图在页面上宽度超过200点，认为是图片页
                                    if img_width > 200:
                                        return True
        except Exception:
            continue

    return False


def find_image_pages(doc, debug=False):
    """
    找到PDF中第一个大图片页的索引

    返回:
        第一个大图片页的页码（1-based），如果没有则返回None
    """
    for page_num, page in enumerate(doc):
        if is_large_image_page(page):
            if debug:
                print(f"发现大图片页: 第{page_num + 1}页")
            return page_num + 1  # 返回1-based页码

    if debug:
        print("未发现大图片页")
    return None


def find_line_below_text(page, text, debug=False, page_label=""):
    """
    找到文本正下方决定top和left margin的横线起点

    返回: (x_start, y) 横线起点坐标，或 None
    """
    page_height = page.rect.height

    # 搜索文本
    instances = page.search_for(text)
    if not instances:
        if debug:
            print(f"  {page_label}: 未找到\"{text}\"文本")
        return None

    text_rect = fitz.Rect(instances[0])

    if debug:
        print(f"  {page_label}: \"{text}\"文本位置: y0={text_rect.y0:.2f}, y1={text_rect.y1:.2f}")

    # 获取所有横线
    drawings = page.get_drawings()
    horizontal_lines = []

    for drawing in drawings:
        items = drawing.get("items", [])
        for item in items:
            if item[0] == "l":
                _, p1, p2 = item
                if abs(p1.y - p2.y) < 0.1:
                    length = abs(p1.x - p2.x)
                    horizontal_lines.append({
                        "x1": min(p1.x, p2.x),
                        "x2": max(p1.x, p2.x),
                        "y": p1.y,
                        "length": length
                    })

    # 找文本正下方的横线（y > text_rect.y1）
    candidates = []
    for line in horizontal_lines:
        if line["y"] > text_rect.y1 and line["length"] > 50:
            # 检查横线的x范围是否覆盖文本中心
            text_center_x = (text_rect.x0 + text_rect.x1) / 2
            if line["x1"] <= text_center_x <= line["x2"]:
                distance = line["y"] - text_rect.y1
                candidates.append({
                    "line": line,
                    "distance": distance
                })

    if not candidates:
        if debug:
            print(f"  {page_label}: 未找到\"{text}\"下方的横线")
        return None

    # 选距离最近的
    candidates.sort(key=lambda x: x["distance"])
    selected = candidates[0]["line"]

    if debug:
        print(f"  {page_label}: \"{text}\"下方横线: 起点=({selected['x1']:.2f}, {selected['y']:.2f}), "
              f"距顶部{selected['y']:.2f}点")

    return selected["x1"], selected["y"]


def find_line_right_of_text(page, text, debug=False, page_label=""):
    """
    找到文本右方决定right和bottom margin的竖线

    返回: (x, y_top) 竖线的x坐标和上起点y坐标，或 None
    """
    page_width = page.rect.width

    # 搜索文本
    instances = page.search_for(text)
    if not instances:
        if debug:
            print(f"  {page_label}: 未找到\"{text}\"文本")
        return None

    text_rect = fitz.Rect(instances[0])

    if debug:
        print(f"  {page_label}: \"{text}\"文本位置: x1={text_rect.x1:.2f}")

    # 获取所有竖线
    drawings = page.get_drawings()
    vertical_lines = []

    for drawing in drawings:
        items = drawing.get("items", [])
        for item in items:
            if item[0] == "l":
                _, p1, p2 = item
                if abs(p1.x - p2.x) < 0.1:
                    length = abs(p1.y - p2.y)
                    vertical_lines.append({
                        "y1": min(p1.y, p2.y),
                        "y2": max(p1.y, p2.y),
                        "x": p1.x,
                        "length": length
                    })

    # 找文本右方的竖线（x > text_rect.x1）
    candidates = []
    for line in vertical_lines:
        if line["x"] > text_rect.x1 and line["length"] > 20:
            # 检查竖线的y范围是否覆盖文本中心
            text_center_y = (text_rect.y0 + text_rect.y1) / 2
            if line["y1"] <= text_center_y <= line["y2"]:
                distance = line["x"] - text_rect.x1
                candidates.append({
                    "line": line,
                    "distance": distance
                })

    if not candidates:
        if debug:
            print(f"  {page_label}: 未找到\"{text}\"右方的竖线")
        return None

    # 选距离最近的
    candidates.sort(key=lambda x: x["distance"])
    selected = candidates[0]["line"]

    if debug:
        from_right = page_width - selected["x"]
        print(f"  {page_label}: \"{text}\"右方竖线: x={selected['x']:.2f} (距右边{from_right:.2f}点), "
              f"上起点y={selected['y1']:.2f}")

    return selected["x"], selected["y1"]


def detect_crop_lines_by_text(page, debug=False, page_label=""):
    """
    基于文本位置检测决定裁剪参数的线条

    坐标系统：屏幕坐标（y=0在顶部，y向下增大）

    返回: (left_x, top_y, right_x, bottom_y) 或 None
    """
    # 找"工卡标题"下方的横线（决定left和top margin）
    result = find_line_below_text(page, "工卡标题", debug=debug, page_label=page_label)
    if result is None:
        return None
    left_x, top_y = result

    # 找"飞机适用范围"右方的竖线（决定right和bottom margin）
    result = find_line_right_of_text(page, "飞机适用范围", debug=debug, page_label=page_label)
    if result is None:
        return None
    right_x, bottom_y_top = result

    # bottom margin用竖线的上起点计算
    page_height = page.rect.height
    bottom_y = bottom_y_top  # 竖线的上起点y坐标

    if debug:
        print(f"  {page_label}: 检测结果: left_x={left_x:.2f}, top_y={top_y:.2f}, "
              f"right_x={right_x:.2f}, bottom_y={bottom_y:.2f}")

    return left_x, top_y, right_x, bottom_y


def detect_crop_lines(page, debug=False, page_label=""):

    # 获取所有线条
    drawings = page.get_drawings()

    horizontal_lines = []
    vertical_lines = []

    for drawing in drawings:
        items = drawing.get("items", [])
        for item in items:
            if item[0] == "l":
                _, p1, p2 = item
                if abs(p1.y - p2.y) < 0.1:
                    length = abs(p1.x - p2.x)
                    horizontal_lines.append({
                        "x1": min(p1.x, p2.x),
                        "x2": max(p1.x, p2.x),
                        "y": p1.y,
                        "length": length
                    })
                elif abs(p1.x - p2.x) < 0.1:
                    length = abs(p1.y - p2.y)
                    vertical_lines.append({
                        "y1": min(p1.y, p2.y),
                        "y2": max(p1.y, p2.y),
                        "x": p1.x,
                        "length": length
                    })

    # 找左边线条（x ≈ 25.56）
    left_candidates = [l for l in vertical_lines if abs(l["x"] - target_x_left) < 10]
    left_x = None
    if left_candidates:
        left_candidates.sort(key=lambda l: abs(l["x"] - target_x_left))
        left_x = left_candidates[0]["x"]
        if debug:
            print(f"    ✓ 左边线条: x={left_x:.2f} (距左边{left_x:.2f}点)")

    # 找顶部线条（y ≈ 55.80，在页面顶部附近搜索）
    top_candidates = [l for l in horizontal_lines if abs(l["y"] - target_y_top) < 200]
    top_y = None
    if top_candidates:
        # 优先找跨越整个页面的长横线（>500点）
        very_long_lines = [l for l in top_candidates if l["length"] > 500]
        if very_long_lines:
            very_long_lines.sort(key=lambda l: abs(l["y"] - target_y_top))
            top_y = very_long_lines[0]["y"]
        else:
            # 如果没有超长线，找长度>100点的线
            long_lines = [l for l in top_candidates if l["length"] > 100]
            if long_lines:
                long_lines.sort(key=lambda l: abs(l["y"] - target_y_top))
                top_y = long_lines[0]["y"]
        if debug and top_y is not None:
            print(f"    ✓ 顶部线条: y={top_y:.2f} (距顶部{top_y:.2f}点)")

    # 找右边线条（x ≈ 498.96）
    right_candidates = [l for l in vertical_lines if abs(l["x"] - target_x_right) < 10]
    right_x = None
    if right_candidates:
        right_candidates.sort(key=lambda l: abs(l["x"] - target_x_right))
        right_x = right_candidates[0]["x"]
        if debug:
            from_right = page_width - right_x
            print(f"    ✓ 右边线条: x={right_x:.2f} (距右边{from_right:.2f}点)")

    # 找底部线条（y ≈ 720.00，在页面底部附近搜索）
    bottom_candidates = [l for l in horizontal_lines if abs(l["y"] - target_y_bottom) < 50]
    bottom_y = None
    if bottom_candidates:
        # 找最接近目标y值，且长度较长的线条（>100点）
        long_lines = [l for l in bottom_candidates if l["length"] > 100]
        if long_lines:
            long_lines.sort(key=lambda l: abs(l["y"] - target_y_bottom))
            bottom_y = long_lines[0]["y"]
            if debug:
                from_bottom = page_height - bottom_y
                print(f"    ✓ 底部线条: y={bottom_y:.2f} (距顶部{bottom_y:.2f}点=距底部{from_bottom:.2f}点)")

    # 默认值
    if left_x is None:
        left_x = target_x_left
    if top_y is None:
        top_y = target_y_top
    if right_x is None:
        right_x = target_x_right
    if bottom_y is None:
        bottom_y = target_y_bottom

    return left_x, top_y, right_x, bottom_y


def calculate_margins_from_detection(detection, page_width, page_height, coeffs, debug=False):
    """
    根据检测值和微调系数计算裁剪参数

    坐标系统：屏幕坐标（y=0在顶部，y向下增大）
    """
    left_x, top_y, right_x, bottom_y = detection

    # 计算裁剪参数（屏幕坐标系统）
    left_pt = left_x + coeffs["left_offset_pt"]
    top_pt = top_y + coeffs["top_offset_pt"]  # 直接使用top_y，不需要转换
    right_pt = (page_width - right_x) + coeffs["right_offset_pt"]
    bottom_pt = (page_height - bottom_y) + coeffs["bottom_offset_pt"]  # bottom_y是距顶部的距离

    margins_pt = {
        "left": left_pt,
        "top": top_pt,
        "right": right_pt,
        "bottom": bottom_pt,
    }

    margins_inch = {k: v / 72 for k, v in margins_pt.items()}

    if debug:
        print(f"    检测值: left_x={left_x:.2f}, top_y={top_y:.2f}, right_x={right_x:.2f}, bottom_y={bottom_y:.2f}")
        print(f"    微调后: left={margins_pt['left']:.2f}, top={margins_pt['top']:.2f}, "
              f"right={margins_pt['right']:.2f}, bottom={margins_pt['bottom']:.2f}")
        print(f"    英寸: left={margins_inch['left']:.3f}, top={margins_inch['top']:.3f}, "
              f"right={margins_inch['right']:.3f}, bottom={margins_inch['bottom']:.3f}")

    return margins_pt


def auto_crop_correct_logic(input_path, output_path, debug=False):
    """使用正确的检测逻辑裁剪PDF"""
    print(f"分析文件: {Path(input_path).name}\n")

    doc = fitz.open(input_path)

    if len(doc) < 2:
        print("错误: PDF少于2页")
        doc.close()
        return None

    # 检测并删除图片页
    print("检测大图片页...")
    first_image_page = find_image_pages(doc, debug=debug)

    if first_image_page is not None:
        print(f"从第{first_image_page}页开始是图片页，将删除该页及后续所有页")
        # PyMuPDF的select方法用于选择要保留的页面
        # 保留第1页到第(first_image_page - 1)页
        doc.select(range(first_image_page - 1))
        print(f"保留第1页到第{first_image_page - 1}页，共{first_image_page - 1}页\n")
    else:
        print("未发现大图片页，保留所有页面\n")

    # 检测PDF类型
    coeffs = detect_pdf_type_by_size(doc[1])
    print(f"使用{coeffs['name']}微调系数\n")

    # 检测第2页（使用文本定位逻辑）
    print("检测第2页（基于\"工卡标题\"和\"飞机适用范围\"位置）:")
    detection_page2 = detect_crop_lines_by_text(doc[1], debug=debug, page_label="第2页")
    if detection_page2 is None:
        print("错误: 无法通过文本定位检测第2页线条")
        doc.close()
        return None
    margins_page2 = calculate_margins_from_detection(
        detection_page2, doc[1].rect.width, doc[1].rect.height, coeffs, debug=debug
    )

    # 检测第1页（使用与第2页相同的微调系数）
    print("\n检测第1页:")
    detection_page1 = detect_crop_lines_by_text(doc[0], debug=debug, page_label="第1页")
    if detection_page1 is None:
        print("警告: 无法通过文本定位检测第1页线条，使用第2页参数")
        margins_page1 = margins_page2
    else:
        margins_page1 = calculate_margins_from_detection(
            detection_page1, doc[0].rect.width, doc[0].rect.height, coeffs, debug=debug
        )

    # 执行裁剪
    print("\n开始裁剪...")
    for page_num, page in enumerate(doc, 1):
        if page_num == 1:
            margins_pt = margins_page1
        else:
            margins_pt = margins_page2

        rect = page.rect
        new_rect = fitz.Rect(
            rect.x0 + margins_pt["left"],
            rect.y0 + margins_pt["top"],
            rect.x1 - margins_pt["right"],
            rect.y1 - margins_pt["bottom"]
        )

        page.set_cropbox(new_rect)

        if page_num % 10 == 0:
            print(f"  处理进度: {page_num}/{len(doc)}", end="\r")

    print()

    doc.save(output_path)
    doc.close()

    print(f"\n✓ 已保存到: {output_path}")

    return margins_page2


def main():
    import argparse

    parser = argparse.ArgumentParser(description="使用正确的检测逻辑裁剪PDF（屏幕坐标系统）")
    parser.add_argument("input", help="输入PDF文件")
    parser.add_argument("-o", "--output", help="输出PDF文件")
    parser.add_argument("--debug", action="store_true", help="显示调试信息")

    args = parser.parse_args()

    if not args.input:
        parser.print_help()
        return 1

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"错误: 文件不存在: {input_path}")
        return 1

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path.parent / f"correct_{input_path.name}"

    auto_crop_correct_logic(str(input_path), str(output_path), debug=args.debug)

    return 0


if __name__ == "__main__":
    exit(main())
