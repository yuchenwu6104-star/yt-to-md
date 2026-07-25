"""Tests for the HackMD upload audit gate without network access."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / ".claude/skills/humanizer-zh/scripts/upload_hackmd.py"
)
SPEC = importlib.util.spec_from_file_location("upload_hackmd", SCRIPT)
upload = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(upload)


def audit_with_section_6(section_6: str) -> str:
    sections = []
    for number in range(1, 8):
        body = section_6 if number == 6 else f"第 {number} 節已完成並留下具體證據。"
        sections.append(f"## {number}. 證據\n\n{body}")
    return "\n\n".join(sections)


class AuditEvidenceTests(unittest.TestCase):
    ARTICLE = (
        "---\n"
        'video_title: "「frontmatter 不列入」"\n'
        "---\n\n"
        "# 測試文章\n\n"
        "甲說：「第一段足以列入逐引述掃描的中文內容。」\n\n"
        "乙說：「太短」。\n\n"
        "丙說：「第二段也有足夠中文字，必須另外建立一列。」\n"
    )

    VALID_SECTION_6 = (
        "逐引述掃描覆蓋：2/2\n\n"
        "| ID | 引述開頭 | 同段／前置串接 | 引述內重複 | 後置解說 | 處置與獨有資訊 |\n"
        "|---|---|---|---|---|---|\n"
        "| Q01 | 第一段足以列入 | 前段只交代說話人 | 無同義反覆 | 無後置解說 | 保留，提供模型選擇理由 |\n"
        "| Q02 | 第二段也有足夠 | 前段提供時間背景 | 第二句補充限制 | 後段轉入新主題 | 保留，提供限制條件 |\n"
    )

    def test_accepts_complete_quote_by_quote_evidence(self) -> None:
        errors = upload._audit_evidence_errors(
            self.ARTICLE,
            audit_with_section_6(self.VALID_SECTION_6),
        )
        self.assertEqual(errors, [])

    def test_counts_only_meaningful_body_quotes(self) -> None:
        self.assertEqual(
            upload._meaningful_quotes(self.ARTICLE),
            [
                "第一段足以列入逐引述掃描的中文內容。",
                "第二段也有足夠中文字，必須另外建立一列。",
            ],
        )

    def test_rejects_duplicate_or_out_of_order_quote_ids(self) -> None:
        section = self.VALID_SECTION_6.replace("| Q02 |", "| Q01 |")
        errors = upload._audit_evidence_errors(
            self.ARTICLE,
            audit_with_section_6(section),
        )
        self.assertTrue(any("ID" in error for error in errors))

    def test_rejects_incomplete_table_rows(self) -> None:
        section = self.VALID_SECTION_6.replace(
            "| Q02 | 第二段也有足夠 | 前段提供時間背景 | 第二句補充限制 | 後段轉入新主題 | 保留，提供限制條件 |",
            "| Q02 | 第二段也有足夠 |",
        )
        errors = upload._audit_evidence_errors(
            self.ARTICLE,
            audit_with_section_6(section),
        )
        self.assertTrue(any("欄位" in error for error in errors))

    def test_ignores_q_rows_outside_section_6(self) -> None:
        section = "逐引述掃描覆蓋：2/2\n\n沒有逐筆表格。"
        audit = audit_with_section_6(section) + "\n\n" + self.VALID_SECTION_6
        errors = upload._audit_evidence_errors(self.ARTICLE, audit)
        self.assertTrue(any("ID" in error for error in errors))

    def test_rejects_provisional_language_case_insensitively(self) -> None:
        audit = audit_with_section_6(self.VALID_SECTION_6) + "\n\ntodo: 再檢查一次"
        errors = upload._audit_evidence_errors(self.ARTICLE, audit)
        self.assertTrue(any("provisional" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
