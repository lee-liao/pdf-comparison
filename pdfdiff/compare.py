"""文本差异比较引擎

流程:
1. 将全文按句号/分号/关键词/步骤编号分割为比较单元
2. 过滤干扰前缀（WARNING:/注：等，MinerU 对其识别不稳定）
3. 归一化（去除 PDF 提取伪影：中文间空格、换行连字符等）后对齐
4. replace 块内做相似度动态规划对齐，配对单元生成字符级高亮
"""

import difflib
import html as html_mod
import re

# 配对为"修改"的最低相似度（低于该值视为一删一增）
PAIR_THRESHOLD = 0.85

# 干扰性前缀：MinerU 对这些标记的提取不稳定（如"警告"与"WARNING"互换），
# 统一删除后再比较，避免误报
NOISE_PATTERNS = [
    r"警告[:：]\s*",
    r"警戒[:：]\s*",
    r"注意[:：]\s*",
    r"注[:：]\s*",
    r"WARNING:\s*",
    r"CAUTION:\s*",
    r"NOTE:\s*",
]

# 分割点：关键词开头 / 步骤编号后 / 句末标点后
_SPLIT_RE = re.compile(
    r"""
    (WARNING:|CAUTION:|NOTE:)\s+(?=[A-Z])|             # 关键词后跟空格
    (?<=\)\d\)|\)[a-z]\))\s+|                          # 步骤编号后跟空格
    ([.。；;！!?？])\s*(?=[A-Z\(]|\d|[一-鿿])   # 标点后跟大写/数字/中文
    """,
    re.VERBOSE,
)


def split_units(text: str) -> list:
    """将文本分割为比较单元（分隔符保留在单元末尾）"""
    text = re.sub(r"\s+", " ", text).strip()
    units = []
    last_end = 0
    for match in _SPLIT_RE.finditer(text):
        end = match.end()
        if end > last_end:
            unit = text[last_end:end].strip()
            if unit:
                units.append(unit)
            last_end = end
    if last_end < len(text):
        remaining = text[last_end:].strip()
        if remaining:
            units.append(remaining)
    return units


def strip_noise(text: str) -> str:
    """删除干扰性字串并压缩空白"""
    text = re.sub(r"\s+", " ", text).strip()
    for pattern in NOISE_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def normalize(text: str) -> str:
    """归一化用于比较：去除 PDF 提取伪影

    - 中文换行连字符、中文字符间空格
    - 中文标点前后空格、中英文之间空格
    - 英文字母/数字之间的多余空格（PDF 断词伪影）
    - LaTeX 公式符号与 Unicode 符号统一（℃/~/- 等）
    - 全角/半角标点统一
    - MinerU 交叉引用链接文字的重复提取
    注意: 不删除英文单词内部有意义的连字符
    """
    # LaTeX 公式伪影：MinerU 有时把 ℃/~/- 提取为行内公式 LaTeX 代码
    # （变体繁多，如 \mathrm{^\circ C}、\mathsf{C}、^ circ C 等）
    text = text.replace("\\sim", "~").replace("\\cdot", "·").replace("\\circ", "°")
    text = re.sub(r"\\math\w+", "", text)
    text = re.sub(r"\bcirc\b", "°", text)
    text = re.sub(r"[{}]", "", text)
    text = re.sub(r"\^?\s*°\s*C(?![a-z])", "℃", text)
    text = re.sub(r"\^?\s*°\s*F(?![a-z])", "℉", text)
    # 中文换行连字符
    text = re.sub(r"([一-鿿])-\s*", r"\1", text)
    # 中文字符之间的空格
    text = re.sub(r"([一-鿿])\s+([一-鿿])", r"\1\2", text)
    # 中文标点前后的空格
    text = re.sub(r"([，。；：！？、）】])\s+", r"\1", text)
    text = re.sub(r"\s+([，。；：！？、【（])", r"\1", text)
    # 中文与英文/数字/括号之间的空格
    text = re.sub(r"([一-鿿])\s+([A-Za-z0-9\(\)\[\]])", r"\1\2", text)
    text = re.sub(r"([A-Za-z0-9\(\)\[\]])\s+([一-鿿])", r"\1\2", text)
    # 标点/括号与字母数字之间的空格
    text = re.sub(r"([,\.\'])\s+([A-Za-z0-9])", r"\1\2", text)
    text = re.sub(r"([A-Za-z0-9])\s+([\(\)\[\]])", r"\1\2", text)
    text = re.sub(r"([\(\)\[\]])\s+([A-Za-z0-9])", r"\1\2", text)
    # 数字与温度符号之间的空格
    text = re.sub(r"(\d)\s+(℃)", r"\1\2", text)
    # 弯引号后的空格
    text = re.sub(r"([’ʼ])\s+([A-Za-z0-9])", r"\1\2", text)
    # 空括号内的空格
    text = re.sub(r"\(\s+\)", "()", text)
    text = re.sub(r"\[\s+\]", "[]", text)
    # 全角/半角标点统一（，vs , 等宽度差异是排版伪影）
    text = text.translate(str.maketrans("～，；：！？、（）【】。", "~,;:!?,()[]."))
    # 重复的波浪号（\sim 与 ~ 并存的伪影）
    text = re.sub(r"~(\s*~)+", "~", text)
    # LaTeX 中 ~ 是不换行空格：字母/右括号前的孤立波浪号视为空格；
    # 数字前的保留（是数值区间，如 "80 ~ 260℃"）
    text = re.sub(r"\s+~\s*(?=[A-Za-z℃℉°])", " ", text)
    text = re.sub(r"\s*~\s*(?=[)\]])", "", text)
    text = re.sub(r"\s+~\s*$", "", text)
    # 收紧区间波浪号周围的空格
    text = re.sub(r"\s*~\s*", "~", text)
    # 英文字母/数字之间的所有空格（循环处理直到无变化）
    while True:
        new_text = re.sub(r"([A-Za-z0-9])\s+([A-Za-z0-9])", r"\1\2", text)
        if new_text == text:
            break
        text = new_text
    # 连字符后的空格；数字区间中连字符前后的空格
    text = re.sub(r"-\s+", "-", text)
    text = re.sub(r"(\d)\s*-\s*(\d)", r"\1-\2", text)
    # MinerU 对交叉引用链接文字会重复提取，空格清理后表现为
    # "TableTable1"、"StepStepB" 等；仅收敛这些引用关键词，
    # 避免误伤如 "RefertoReferto"（Refer to Refer to）等合法重复
    text = re.sub(r"(Table|Step|Figure|Fig|Task|Section|Para|Chapter)\1+", r"\1", text)
    # 交叉引用短语重复："Refer to Figure Refer to Fig." -> "Refer to Fig."
    text = re.sub(r"Referto(?:Figure|Fig|Table|Step|Task)?(?=Referto)", "", text)
    return re.sub(r"\s+", " ", text).strip()


def char_diff_html(old_text: str, new_text: str) -> tuple:
    """字符级差异高亮，返回 (old_html, new_html)"""
    esc = html_mod.escape
    old_parts, new_parts = [], []
    matcher = difflib.SequenceMatcher(None, old_text, new_text, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        old_chunk, new_chunk = old_text[i1:i2], new_text[j1:j2]
        if tag == "equal" or (not old_chunk.strip() and not new_chunk.strip()):
            # 两侧均为空白的差异是提取伪影，不高亮
            old_parts.append(esc(old_chunk))
            new_parts.append(esc(new_chunk))
        else:
            if old_chunk:
                old_parts.append(f'<span class="deleted-word">{esc(old_chunk)}</span>')
            if new_chunk:
                new_parts.append(f'<span class="added-word">{esc(new_chunk)}</span>')
    return "".join(old_parts), "".join(new_parts)


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def _align_by_similarity(old_norm: list, new_norm: list, threshold: float) -> list:
    """块内相似度动态规划对齐（保持顺序）

    返回操作列表: ('pair', i, j) / ('del', i, None) / ('add', None, j)
    仅当相似度 ≥ threshold 时配对，最大化配对相似度总和。
    """
    n, m = len(old_norm), len(new_norm)
    # score[i][j]: 对齐 old[:i] 与 new[:j] 的最大配对相似度总和
    score = [[0.0] * (m + 1) for _ in range(n + 1)]
    move = [[None] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        for j in range(m + 1):
            if i == 0 and j == 0:
                continue
            best, best_move = -1.0, None
            if i > 0 and j > 0:
                sim = _similarity(old_norm[i - 1], new_norm[j - 1])
                if sim >= threshold:
                    cand = score[i - 1][j - 1] + sim
                    if cand > best:
                        best, best_move = cand, "pair"
            if i > 0 and score[i - 1][j] > best:
                best, best_move = score[i - 1][j], "del"
            if j > 0 and score[i][j - 1] >= best:
                best, best_move = score[i][j - 1], "add"
            score[i][j], move[i][j] = best, best_move

    ops = []
    i, j = n, m
    while i > 0 or j > 0:
        mv = move[i][j]
        if mv == "pair":
            i, j = i - 1, j - 1
            ops.append(("pair", i, j))
        elif mv == "del":
            i -= 1
            ops.append(("del", i, None))
        else:
            j -= 1
            ops.append(("add", None, j))
    ops.reverse()
    return ops


def compare_texts(old_text: str, new_text: str) -> dict:
    """比较两个文本，返回 {'stats': {...}, 'units': [...]}

    units 条目: {'type': equal|modified|deleted|added,
                 'old': str|None, 'new': str|None,
                 'old_html': ..., 'new_html': ...}  # 仅 modified 有 *_html
    """
    old_units = [u for u in (strip_noise(u) for u in split_units(old_text)) if u]
    new_units = [u for u in (strip_noise(u) for u in split_units(new_text)) if u]
    old_norm = [normalize(u) for u in old_units]
    new_norm = [normalize(u) for u in new_units]

    stats = {"additions": 0, "deletions": 0, "modifications": 0, "unchanged": 0}
    units = []

    def emit_equal(i, j):
        stats["unchanged"] += 1
        units.append({"type": "equal", "old": old_units[i], "new": new_units[j]})

    def emit_pair(i, j):
        """配对单元：归一化后相同为未变，否则为修改（带字符级高亮）

        归一化已消除所有语义相关的空格差异，残留的空格差异
        （如连字符前的空格）均为提取伪影，比较时忽略。
        """
        if old_norm[i].replace(" ", "") == new_norm[j].replace(" ", ""):
            emit_equal(i, j)
            return
        old_html, new_html = char_diff_html(old_norm[i], new_norm[j])
        stats["modifications"] += 1
        units.append({"type": "modified", "old": old_units[i], "new": new_units[j],
                      "old_html": old_html, "new_html": new_html})

    def emit_deleted(i):
        stats["deletions"] += 1
        units.append({"type": "deleted", "old": old_units[i], "new": None})

    def emit_added(j):
        stats["additions"] += 1
        units.append({"type": "added", "old": None, "new": new_units[j]})

    matcher = difflib.SequenceMatcher(None, old_norm, new_norm, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for i, j in zip(range(i1, i2), range(j1, j2)):
                emit_equal(i, j)
        elif tag == "delete":
            for i in range(i1, i2):
                emit_deleted(i)
        elif tag == "insert":
            for j in range(j1, j2):
                emit_added(j)
        else:  # replace: 块内相似度对齐
            ops = _align_by_similarity(old_norm[i1:i2], new_norm[j1:j2], PAIR_THRESHOLD)
            for op, oi, nj in ops:
                if op == "pair":
                    emit_pair(i1 + oi, j1 + nj)
                elif op == "del":
                    emit_deleted(i1 + oi)
                else:
                    emit_added(j1 + nj)

    return {"stats": stats, "units": units}
