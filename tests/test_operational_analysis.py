from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from auto_quote_daily.runtime import operational_analysis as analysis


class OperationalAnalysisTest(unittest.TestCase):
    def setUp(self):
        self.context = analysis.build_context(
            {"date": "2026-10-09", "order_count": 10, "auto_offer_order_count": 8,
             "full_auto_offer_order_count": 5, "deal_order_count": 2}, [], {}, {}, {}
        )
        self.report = {
            "date": "2026-10-09", "dataFingerprint": self.context["dataFingerprint"],
            "generatedAt": "2026-10-12T14:00:00+08:00", "overall": "观察自动化覆盖与人工介入。",
            "conclusions": [{"id": "coverage", "title": "覆盖后仍需人工介入",
                             "evidence": ["auto_rate", "full_auto_rate"], "interpretation": "需复核推送原因。"}],
            "actions": [{"priority": "P1", "relatedConclusions": ["coverage"], "target": "运力运营",
                         "action": "复核二次推送订单。", "verification": "跟踪全自动报价率。"}],
            "limitations": ["快照不代表最终成单结果。"],
        }

    def test_evidence_is_rendered_from_current_facts(self):
        rendered = analysis.render_analysis(self.report, self.context)
        self.assertIn("80.0%", rendered)
        self.assertIn("50.0%", rendered)
        self.assertIn("分子 8 / 分母 10", rendered)
        self.assertIn("优先行动", rendered)

    def test_changed_data_rejects_old_conclusions(self):
        context = analysis.build_context(
            {"date": "2026-10-09", "order_count": 11, "auto_offer_order_count": 8,
             "full_auto_offer_order_count": 5, "deal_order_count": 2}, [], {}, {}, {}
        )
        with self.assertRaises(ValueError):
            analysis.validate_analysis(self.report, context)

    def test_snapshot_changes_are_detected_even_if_totals_match(self):
        summary = {"date": "2026-10-09", "order_count": 10, "auto_offer_order_count": 8,
                   "full_auto_offer_order_count": 5, "deal_order_count": 2}
        first = analysis.build_context(summary, [], {}, {}, {}, source_snapshot={"orders": ["ORDER-A"]})
        second = analysis.build_context(summary, [], {}, {}, {}, source_snapshot={"orders": ["ORDER-B"]})
        self.assertNotEqual(first["dataFingerprint"], second["dataFingerprint"])

    def test_unknown_evidence_and_unrelated_actions_are_rejected(self):
        for field, value in [("evidence", ["invented_profit"]), ("relatedConclusions", ["missing"])]:
            report = copy.deepcopy(self.report)
            report["conclusions" if field == "evidence" else "actions"][0][field] = value
            with self.assertRaises(ValueError):
                analysis.validate_analysis(report, self.context)

    def test_no_orders_does_not_claim_a_measurable_rate(self):
        context = analysis.build_context({"date": "2026-10-09", "order_count": 0,
                                          "auto_offer_order_count": 0, "deal_order_count": 0}, [], {}, {}, {})
        self.assertIsNone(context["facts"]["auto_rate"]["value"])

    def test_text_is_escaped(self):
        self.report["overall"] = '<script>alert(1)</script>'
        rendered = analysis.render_analysis(self.report, self.context)
        self.assertNotIn('<script>', rendered)
        self.assertIn('&lt;script&gt;', rendered)


if __name__ == "__main__":
    unittest.main()
