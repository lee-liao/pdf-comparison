# -*- coding: utf-8 -*-
"""比较引擎回归测试

运行: python -m pytest qa/test_compare.py -v
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
    参考旧版报告: +53 -59 ~54（配对质量更低）
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

    def test_known_real_change_present(self, golden_result):
        """已知真实差异：新文缺失"成"字，必须出现在修改单元中"""
        modified = [u for u in golden_result["units"] if u["type"] == "modified"]
        assert any(
            "会造成人员受伤" in normalize(u["old"] or "")
            and "会造人员受伤" in normalize(u["new"] or "")
            for u in modified
        )
