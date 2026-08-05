"""Tests for MiniMax retry selection without making network calls."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import unittest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / ".claude/skills/yt/scripts/yt_to_article.py"
)
SPEC = importlib.util.spec_from_file_location("yt_to_article", SCRIPT)
yt = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(yt)

GATE_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / ".claude/skills/humanizer-zh/scripts/final_gate.py"
)
GATE_SPEC = importlib.util.spec_from_file_location("humanizer_final_gate", GATE_SCRIPT)
gate = importlib.util.module_from_spec(GATE_SPEC)
assert GATE_SPEC.loader is not None
GATE_SPEC.loader.exec_module(gate)


def candidate(cjk_units: int, topics: int, numbers: str) -> dict:
    body = ("這是有實質內容的文章段落。" * cjk_units) + numbers
    return {
        "article": body,
        "topics": [f"主題 {i}" for i in range(topics)],
    }


class RetrySelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.transcript = (
            "第一個主題談 2026 年營收 100 億美元。"
            "第二個主題比較 20% 與 35%。"
            "第三個主題說投資人已在 2025 年減碼 3 倍。"
        )

    def test_cleaner_retry_wins_when_content_is_retained(self) -> None:
        old = candidate(80, 4, "2026 年、100 億美元、20%、35%、2025 年、3 倍")
        new = candidate(70, 4, "2026 年、100 億美元、20%、35%、2025 年、3 倍")
        prefer, regressions = yt._prefer_retry_candidate(
            new, [], old, ["複述"], self.transcript
        )
        self.assertTrue(prefer)
        self.assertEqual(regressions, [])

    def test_cleaner_retry_is_rejected_after_material_content_loss(self) -> None:
        old = candidate(80, 5, "2026 年、100 億美元、20%、35%、2025 年、3 倍")
        new = candidate(20, 2, "2026 年")
        prefer, regressions = yt._prefer_retry_candidate(
            new, [], old, ["複述"], self.transcript
        )
        self.assertFalse(prefer)
        self.assertGreaterEqual(len(regressions), 2)

    def test_equal_violation_count_uses_content_tiebreakers(self) -> None:
        old = candidate(60, 3, "2026 年、100 億美元、20%")
        new = candidate(60, 4, "2026 年、100 億美元、20%、35%")
        prefer, regressions = yt._prefer_retry_candidate(
            new, ["語氣打分"], old, ["舞台指示"], self.transcript
        )
        self.assertTrue(prefer)
        self.assertEqual(regressions, [])

    def test_content_integrity_issue_outweighs_two_style_issues(self) -> None:
        old = candidate(70, 4, "2026 年、100 億美元、20%、35%")
        new = candidate(70, 4, "2026 年、100 億美元、20%、35%")
        prefer, regressions = yt._prefer_retry_candidate(
            new,
            ["串接區出現舞台指示", "串接區替講者語氣打分"],
            old,
            ["覆蓋率不足：成稿只有 300 個中文字，字幕 14000 字元"],
            self.transcript,
        )
        self.assertTrue(prefer)
        self.assertEqual(regressions, [])

    def test_one_fluctuating_proxy_does_not_block_a_cleaner_retry(self) -> None:
        old = candidate(80, 5, "2026 年、100 億美元、20%、35%")
        new = candidate(80, 3, "2026 年、100 億美元、20%、35%")
        prefer, regressions = yt._prefer_retry_candidate(
            new, [], old, ["複述"], self.transcript
        )
        self.assertTrue(prefer)
        self.assertEqual(regressions, [])


class RepresentativeQuoteCoverageTests(unittest.TestCase):
    """引述覆蓋率口徑的 yt ↔ humanizer-zh parity。

    2026-08-06 起 /yt 產出中文全文順稿（無「」引號），此項已不再是 /yt 的
    format_violations 閘門條件；helper 保留供下游 humanizer 成文階段使用，
    這裡只驗證兩邊口徑一致。
    """

    LONG_QUOTE = "這是一段能夠完整呈現講者語氣與論證方式的代表性直接引述，不能只留下零碎名詞。"

    def test_requires_substantive_quotes_in_half_of_main_sections(self) -> None:
        article = "\n\n".join(
            [
                "## 導言\n背景說明。",
                "## 主題一\n全部都是第三人稱轉述。",
                "## 主題二\n全部都是第三人稱轉述。",
                f"## 主題三\n講者說：「{self.LONG_QUOTE}」",
                "## 主題四\n全部都是第三人稱轉述。",
                "## 結語\n全文收束。",
            ]
        )
        covered, total = yt._representative_quote_coverage(article)
        self.assertEqual((covered, total), (1, 4))
        self.assertEqual(gate.representative_quote_coverage(article), (1, 4))

    def test_passes_quote_coverage_without_reintroducing_a_word_quota(self) -> None:
        article = "\n\n".join(
            [
                f"## 主題一\n講者說：「{self.LONG_QUOTE}」",
                "## 主題二\n低歧義的流程資訊採轉述。",
                f"## 主題三\n講者說：「{self.LONG_QUOTE}」",
                "## 主題四\n低歧義的背景資訊採轉述。",
            ]
        )
        covered, total = yt._representative_quote_coverage(article)
        self.assertEqual((covered, total), (2, 4))
        self.assertEqual(gate.representative_quote_coverage(article), (2, 4))

    def test_short_multi_speaker_exchange_counts_in_aggregate(self) -> None:
        article = "\n".join(
            [
                "## 快速交鋒",
                "Ian：『這做法根本不可能規模化。』"
                "Tobias：『我不同意，客戶已經在用了。』"
                "Ian：『試用不等於能長期付費。』",
            ]
        ).replace("『", "「").replace("』", "」")
        self.assertEqual(yt._representative_quote_coverage(article), (1, 1))
        self.assertEqual(gate.representative_quote_coverage(article), (1, 1))

    def test_tiny_quoted_terms_cannot_accumulate_into_coverage(self) -> None:
        quoted_terms = "、".join(f"「名詞{i}」" for i in range(16))
        article = f"## 產品清單\n介面列出：{quoted_terms}。"
        self.assertGreaterEqual(
            sum(
                len(re.findall(r"[一-鿿]", quote))
                for quote in re.findall(r"「([^「」]+)」", article)
            ),
            30,
        )
        self.assertEqual(yt._representative_quote_coverage(article), (0, 1))
        self.assertEqual(gate.representative_quote_coverage(article), (0, 1))


class RestatementDetectionTests(unittest.TestCase):
    def test_detects_same_paragraph_narration_that_previews_quote(self) -> None:
        article = (
            "## 模型選擇\n\n"
            "團隊先比較部署成本、工具相容性與維護負擔，也回顧前兩輪測試結果。"
            "這套流程最後選擇 OpenAI Codex 作為核心模型。"
            "講者說：「這套流程最後選擇 OpenAI Codex 作為核心模型，"
            "因為它能處理完整的研究工作。」"
        )
        yt_hits = yt._redundant_narration(article)
        gate_hits = gate.restatement_candidates(article.split("\n\n"))
        self.assertTrue(any(hit.startswith("同段串接：") for hit in yt_hits))
        self.assertTrue(any(hit.startswith("同段串接：") for hit in gate_hits))

    def test_detects_english_heavy_restatement_with_little_cjk_overlap(self) -> None:
        article = (
            "OpenAI Codex workflow architecture 已定案。\n\n"
            "講者說：「OpenAI Codex workflow architecture handles the "
            "entire research pipeline and review process。」"
        )
        yt_hits = yt._redundant_narration(article)
        gate_hits = gate.restatement_candidates(article.split("\n\n"))
        self.assertTrue(any(hit.startswith("引述前：") for hit in yt_hits))
        self.assertTrue(any(hit.startswith("引述前：") for hit in gate_hits))

    def test_detects_english_heavy_repetition_inside_quote(self) -> None:
        article = (
            "講者說：「OpenAI Codex workflow orchestrates research。"
            "OpenAI Codex workflow runs the research process。」"
        )
        yt_hits = yt._redundant_narration(article)
        gate_hits = gate.restatement_candidates([article])
        self.assertTrue(any("引述內自我複述" in hit for hit in yt_hits))
        self.assertTrue(any("引述內自我複述" in hit for hit in gate_hits))


if __name__ == "__main__":
    unittest.main()
