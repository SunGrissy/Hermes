# -*- coding: utf-8 -*-
import unittest

from review_webhook_format import humanize_review_for_webhook, strip_markdown_tables


class ReviewWebhookFormatTests(unittest.TestCase):
    def test_strip_markdown_tables_removes_pipe_rows(self):
        raw = (
            "## 变更摘要\n"
            "| 行 | 变更类型 | 内容 |\n"
            "|---|---|---|\n"
            "| 172 | 修改 | align-items |\n"
            "正文一行说明。\n"
        )
        out = strip_markdown_tables(raw)
        self.assertNotIn("| 172 |", out)
        self.assertIn("正文一行说明", out)

    def test_humanize_prefers_issue_section_not_table(self):
        report = (
            "## 代码审查报告\n"
            "| 行 | 类型 |\n"
            "| 1 | 改 |\n"
            "## 问题清单\n"
            "- 中等：删除后 _fillVersionSelect 可能误导\n"
            "## 下一步\n"
            "合并前再看一眼。\n"
        )
        h = humanize_review_for_webhook(report)
        self.assertNotIn("| 行 |", h)
        self.assertIn("删除后", h)
        self.assertIn("Multica", h)


if __name__ == "__main__":
    unittest.main()
