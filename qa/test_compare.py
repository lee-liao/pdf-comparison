# -*- coding: utf-8 -*-
"""比较引擎回归测试

运行: python -m pytest qa/test_compare.py -v
"""

import json
import sys
from pathlib import Path

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pdfdiff import coverage, extract  # noqa: E402
from pdfdiff.compare import compare_texts, normalize  # noqa: E402
from pdfdiff.extract import extract_text  # noqa: E402

TESTDATA = Path(__file__).parent / "testdata"


def _classify(old: str, new: str) -> str:
    """返回比较结果中第一个非 equal 的类型；全部 equal 则返回 'equal'"""
    result = compare_texts(old, new)
    types = [u["type"] for u in result["units"] if u["type"] != "equal"]
    return types[0] if types else "equal"


class TestRealChangesDetected:
    """真实变更必须被检出（安全性：宁多报不漏报）"""

    def test_torque_value_change(self):
        assert _classify(
            "Torque the bolt to 10 N.m (89 lbf.in). Next step.",
            "Torque the bolt to 16 N.m (89 lbf.in). Next step.",
        ) == "modified"

    def test_single_chinese_char_missing(self):
        assert _classify(
            "如果不遵守此指引，会造成人员受伤。",
            "如果不遵守此指引，会造人员受伤。",
        ) == "modified"

    def test_part_number_change(self):
        assert _classify(
            "Apply sealant PR-1440 to the surface.",
            "Apply sealant PR-1441 to the surface.",
        ) == "modified"

    def test_duration_change(self):
        assert _classify("加热 4 分钟后停止。", "加热 6 分钟后停止。") == "modified"

    def test_removed_words_still_visible(self):
        """相似度不足配对时应表现为删除+新增，绝不能静默丢失"""
        result = compare_texts(
            "Remove the four bolts and washers. Then continue.",
            "Remove the four bolts. Then continue.",
        )
        types = {u["type"] for u in result["units"]}
        assert "modified" in types or ("deleted" in types and "added" in types)


class TestArtifactsIgnored:
    """PDF 提取伪影不应产生差异"""

    def test_spacing_artifacts(self):
        assert _classify(
            "Torque to 10 N.m (89 lbf.in).", "Torque to 10N.m(89lbf.in)."
        ) == "equal"

    def test_fullwidth_tilde_range(self):
        assert _classify(
            "温度范围 80 ～ 260 ℃ 之间。", "温度范围80～260℃之间。"
        ) == "equal"

    def test_range_with_units(self):
        assert _classify(
            "压力 270lbf.in ~ 300lbf.in 范围。", "压力270lbf.in~300lbf.in范围。"
        ) == "equal"

    def test_fullwidth_punctuation(self):
        assert _classify("断开传感管[3]，按需松开。", "断开传感管[3], 按需松开。") == "equal"

    def test_latex_celsius(self):
        assert normalize("80 { - } 260 ^ { \\circ } \\mathrm { C }") == "80-260℃"

    def test_latex_nbsp_tilde(self):
        assert "~" not in normalize("8 . 3 ~ \\mathrm { { ^ \\circ C } } )")

    def test_crossref_duplication(self):
        assert _classify(
            "For the procedure given inTable Table1 Optional parts , doS tep Step B.",
            "For the procedure given in Table 1 Optional parts , do Step B.",
        ) == "equal"

    def test_chinese_linebreak_hyphen(self):
        assert _classify("会造成人员受- 伤和设备损坏。", "会造成人员受伤和设备损坏。") == "equal"

    def test_noise_keyword_prefix(self):
        assert _classify(
            "WARNING: DO NOT TOUCH THE ENGINE.", "警告：DO NOT TOUCH THE ENGINE."
        ) == "equal"


class TestGoldenData:
    """qa/testdata 金标数据回归：统计量不应劣化

    基线（2026-07-07）: +35 -29 ~17 未变463

    重要：金标 JSON 是 **MinerU 2.7.5 (hybrid)** 的产物，见其 `_version_name` 键。
    MinerU 同版本内确定性，跨版本不确定：同样两份 PDF 在 3.4.0 上是 +49 -47 ~14。
    服务端已升级且 API 无法指定版本（model_version 只接受 pipeline/vlm/MinerU-HTML），
    该基线因此不可能由在线调用复现——这些 JSON 是刻意冻结的固定装置，
    用于回归 compare.py 的算法，不用于衡量 MinerU 当前表现。请勿重新生成。
    """

    @pytest.fixture(scope="class")
    def golden_result(self):
        with open(TESTDATA / "MinerU_C19M7324501-1-1_mro-P2-17.json", encoding="utf-8") as f:
            d1 = json.load(f)
        with open(TESTDATA / "MinerU_C19M7324501-1-1_xinyuan-P2-17.json", encoding="utf-8") as f:
            d2 = json.load(f)
        return compare_texts(extract_text(d1), extract_text(d2))

    def test_extraction_not_empty(self, golden_result):
        assert len(golden_result["units"]) > 400

    def test_unpaired_rows_not_worse_than_baseline(self, golden_result):
        stats = golden_result["stats"]
        assert stats["additions"] + stats["deletions"] <= 70, stats

    def test_total_diff_rows_not_worse_than_baseline(self, golden_result):
        stats = golden_result["stats"]
        diff_rows = stats["additions"] + stats["deletions"] + stats["modifications"]
        assert diff_rows <= 85, stats

    # 原 test_known_real_change_present 已删除（2026-07-21）：
    # 它断言"新文缺失『成』字"是真实差异，实为 MinerU 2.7.5 的提取缺陷——
    # PyMuPDF 读取两份 PDF 的文字图层，双方都是"会造成人员受伤"，完全一致；
    # 3.4.0 已能正确提取该字。单字丢失的检出能力由
    # TestRealChangesDetected::test_single_chinese_char_missing 以合成用例保证，
    # 不依赖对样本文档的未经证实的断言。


class TestCoverage:
    """提取覆盖率自检：引擎静默丢内容时必须能发现"""

    PDF = TESTDATA / "C19M7324501-1-1_mro-noheader_Page2-17.pdf"

    def test_full_text_layer_scores_high(self):
        """用 PDF 自身文字图层做提取结果，覆盖率应接近 100%"""
        truth = coverage.truth_text(self.PDF)
        recall, missing, total = coverage.coverage(truth, self.PDF)
        assert total > coverage.MIN_TRUTH_TOKENS
        assert recall == pytest.approx(1.0), (recall, missing)

    def test_dropped_content_is_detected(self):
        """丢掉后半段内容时，覆盖率必须显著下降并低于告警阈值"""
        truth = coverage.truth_text(self.PDF)
        recall, _, _ = coverage.coverage(truth[: len(truth) // 2], self.PDF)
        assert recall < coverage.DEFAULT_THRESHOLD

    def test_scanned_pdf_is_skipped(self, tmp_path):
        """无文字图层（扫描件）无法做基准，应返回 None 而不是误报丢失"""
        blank = tmp_path / "blank.pdf"
        doc = fitz.open()
        doc.new_page()
        doc.save(blank)
        doc.close()
        recall, _, _ = coverage.coverage("任意文本", blank)
        assert recall is None


class TestSourceInfo:
    """报告溯源：统计量只在同一提取来源下可比"""

    def test_mineru_metadata(self):
        assert extract.source_info(
            {"_backend": "hybrid", "_version_name": "3.4.0"}
        ) == "MinerU 3.4.0 (hybrid)"

    def test_pdfjs_metadata(self):
        assert extract.source_info(
            {"_backend": "pdfjs", "_version_name": "6.1.200"}
        ) == "pdf.js 6.1.200"

    def test_missing_metadata_is_not_fatal(self):
        assert "unknown" in extract.source_info({})
