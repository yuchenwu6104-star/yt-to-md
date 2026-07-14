"""Tests for MiniMax retry selection without making network calls."""

from __future__ import annotations

import importlib.util
from pathlib import Path
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
            ["只有 0/4 個主要章節含實質直接引述"],
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
        self.assertTrue(
            any("實質直接引述" in issue for issue in yt.format_violations(article))
        )

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
        self.assertFalse(
            any("實質直接引述" in issue for issue in yt.format_violations(article))
        )


if __name__ == "__main__":
    unittest.main()
