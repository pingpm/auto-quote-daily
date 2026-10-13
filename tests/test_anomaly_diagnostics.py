from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from auto_quote_daily.runtime import anomaly_diagnostics as diagnostics  # noqa: E402


class AnomalyDiagnosticsTest(unittest.TestCase):
    def test_transport_mode_change_has_highest_priority(self) -> None:
        result = diagnostics.diagnose_anomaly(
            {
                "orderNo": "YC_TEST_001",
                "diff": 3150,
                "leftAmt": 4350,
                "rightAmt": 1200,
            },
            order_logs=[
                {
                    "operateName": "编辑订单",
                    "createTime": "2026-07-14 10:32:25",
                    "createUserName": "赵晓宁",
                    "content": "编辑基础信息：运输方式：大板 -> 全程小板；\n提车方式：代驾 -> 小板；",
                }
            ],
            query_detail={},
            line_prices=[],
        )

        self.assertEqual(result["causeCode"], "transport_mode_changed")
        self.assertIn("大板改为小板", result["diagnosis"])
        self.assertIn("2026-07-14 10:32:25", result["evidence"])
        self.assertEqual(result["currentLinePriceStatus"], "运输方式口径不一致")
        self.assertIn("不直接对比", result["currentLinePriceSuggestion"])

    def test_line_price_reverted_after_hit_price_spike(self) -> None:
        result = diagnostics.diagnose_anomaly(
            {
                "orderNo": "YC_TEST_002",
                "diff": -2500,
                "leftAmt": 900,
                "rightAmt": 3400,
            },
            order_logs=[],
            query_detail={
                "queryBidList": [
                    {
                        "linePriceNo": "TEST-LINE-00111",
                        "unitPrice": 3400,
                    }
                ]
            },
            line_prices=[
                {"linePriceNo": "TEST-LINE-00112", "unitPrice": 900, "dataTime": "2026-07-14 23:00:00"},
                {"linePriceNo": "TEST-LINE-00111", "unitPrice": 3400, "dataTime": "2026-07-14 22:40:00"},
                {"linePriceNo": "TEST-LINE-00110", "unitPrice": 900, "dataTime": "2026-07-14 22:10:00"},
            ],
        )

        self.assertEqual(result["causeCode"], "line_price_spike_reverted")
        self.assertIn("疑似线路价格误操作后修正", result["diagnosis"])
        self.assertIn("00111", result["evidence"])

    def test_marks_hit_price_as_stale_and_lists_later_updates(self) -> None:
        result = diagnostics.diagnose_anomaly(
            {
                "orderNo": "YC_TEST_003",
                "diff": -500,
                "leftAmt": 1000,
                "rightAmt": 1500,
                "autoOfferTime": "2026-07-14 12:00:00",
            },
            order_logs=[],
            query_detail={
                "queryInfo": {"offerTime": "2026-07-14 12:00:00"},
                "queryBidList": [
                    {
                        "linePriceNo": "TEST-LINE-00111",
                        "unitPrice": 1500,
                    }
                ],
            },
            line_prices=[
                {
                    "linePriceNo": "TEST-LINE-00112",
                    "unitPrice": 1200,
                    "modifyTime": "2026-07-15 09:00:00",
                    "modifyUserName": "李四",
                },
                {
                    "linePriceNo": "TEST-LINE-00111",
                    "unitPrice": 1500,
                    "modifyTime": "2026-06-01 09:00:00",
                    "modifyUserName": "王平",
                },
            ],
        )

        self.assertIn("超过30天", result["priceFreshness"])
        self.assertIn("1200", result["laterUpdates"])
        self.assertIn("李四", result["laterUpdates"])
        self.assertIn("更新时间 2026-06-01 09:00:00", result["evidence"])
        self.assertIn("更新人 王平", result["evidence"])

    def test_compares_analysis_time_latest_line_price_with_bid_price(self) -> None:
        result = diagnostics.diagnose_anomaly(
            {
                "orderNo": "YC_TEST_004",
                "diff": -2500,
                "leftAmt": 900,
                "rightAmt": 3400,
            },
            order_logs=[],
            query_detail={
                "queryBidList": [
                    {
                        "linePriceNo": "TEST-LINE-00111",
                        "unitPrice": 3400,
                    }
                ],
            },
            line_prices=[
                {
                    "linePriceNo": "TEST-LINE-00112",
                    "unitPrice": 900,
                    "modifyTime": "2026-07-15 09:00:00",
                    "modifyUserName": "李四",
                },
                {
                    "linePriceNo": "TEST-LINE-00111",
                    "unitPrice": 3400,
                    "modifyTime": "2026-07-14 22:40:00",
                    "modifyUserName": "王平",
                },
            ],
        )

        self.assertEqual(result["currentLinePriceStatus"], "已调整且与竞价一致")
        self.assertIn("分析时最新价 900 元", result["currentLinePriceEvidence"])
        self.assertIn("更新时间 2026-07-15 09:00:00", result["currentLinePriceEvidence"])
        self.assertIn("更新人 李四", result["currentLinePriceEvidence"])
        self.assertIn("观察后续同线路命中情况", result["currentLinePriceSuggestion"])


if __name__ == "__main__":
    unittest.main()
