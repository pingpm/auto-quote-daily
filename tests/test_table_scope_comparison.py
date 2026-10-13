from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from auto_quote_daily.runtime import build_0708_visual_dashboard as dashboard  # noqa: E402


class TableScopeComparisonTest(unittest.TestCase):
    def test_chosen_bid_group_requires_confirmed_group(self) -> None:
        groups = [
            {
                "pkId": "unconfirmed-3000",
                "payableAmt": 3000,
                "confirmStatus": 0,
                "bidTime": "2026-07-17 09:25:46",
            }
        ]

        self.assertIsNone(dashboard.chosen_bid_group(groups))

    def test_chosen_bid_group_uses_confirmed_group_when_later_quotes_exist(self) -> None:
        groups = [
            {
                "pkId": "unconfirmed-3000",
                "payableAmt": 3000,
                "confirmStatus": 0,
                "bidTime": "2026-07-17 09:25:46",
            },
            {
                "pkId": "unconfirmed-1300",
                "payableAmt": 1300,
                "confirmStatus": 0,
                "bidTime": "2026-07-17 10:26:07",
            },
            {
                "pkId": "confirmed-1200",
                "payableAmt": 1200,
                "confirmStatus": 1,
                "confirmTime": "2026-07-17 10:27:47",
                "bidTime": "2026-07-17 10:26:45",
            },
        ]

        self.assertEqual(dashboard.chosen_bid_group(groups)["pkId"], "confirmed-1200")

    def test_table_scoped_bid_comparison_uses_auto_quote_price_not_table_price(self) -> None:
        rows = [
            {
                "orderNo": "YC_TEST_001",
                "route": "河北省保定市 -> 河北省唐山市",
                "routeKey": "河北省|保定市|河北省|唐山市",
                "isAutoOffer": True,
                "hasBidGroup": True,
                "autoTrunkAmt": 2800,
                "isDeal": True,
            }
        ]
        bid_groups_by_order = {
            "YC_TEST_001": [
                {
                    "pkId": "bid-group-1",
                    "payableAmt": 3000,
                    "confirmStatus": 1,
                    "confirmTime": "2026-07-14 10:00:00",
                }
            ]
        }
        bid_group_carriers_by_order = {
            "YC_TEST_001": {
                "bid-group-1": [
                    {"trunkAmt": 2800},
                ]
            }
        }
        maintained_lines = {
            "河北省|保定市|河北省|唐山市": {
                "tablePrice": 3000,
                "route": "河北省保定市 -> 河北省唐山市",
            }
        }

        comparison = dashboard.build_bid_vs_table_comparison(
            rows,
            bid_groups_by_order,
            bid_group_carriers_by_order,
            maintained_lines,
        )

        self.assertEqual(comparison["overall"], {"total": 1, "高于": 0, "低于": 0, "持平": 1})
        self.assertEqual(comparison["deal"], {"total": 1, "高于": 0, "低于": 0, "持平": 1})
        self.assertEqual(comparison["details"][0]["rightLabel"], "自动报价干线价")
        self.assertEqual(comparison["details"][0]["rightAmt"], 2800)
        self.assertEqual(comparison["details"][0]["diff"], 0)

    def test_operational_report_renders_conclusions_explanations_and_anomalies(self) -> None:
        summary = {
            "order_count": 272,
            "auto_offer_order_count": 123,
            "auto_offer_rate": 0.4522,
            "deal_order_count": 10,
            "deal_rate": 0.0368,
            "route_count": 251,
            "auto_offer_route_count": 112,
            "by_channel": [
                {"渠道": "无忧小程序", "下单数量": 133, "自动报价订单数量": 58, "成单数量": 3},
                {"渠道": "APP", "下单数量": 80, "自动报价订单数量": 40, "成单数量": 6},
            ],
        }
        scoped = {
            "overall": {"total": 30, "高于": 7, "低于": 6, "持平": 17},
            "deal": {"total": 2, "高于": 0, "低于": 1, "持平": 1},
            "details": [
                {
                    "orderNo": "YC_TEST_002",
                    "route": "上海市上海市 -> 广东省深圳市",
                    "leftAmt": 4350,
                    "rightAmt": 1200,
                    "diff": 3150,
                    "result": "高于",
                    "isDeal": False,
                }
            ],
        }
        full = {
            "overall": {"total": 66, "高于": 10, "低于": 18, "持平": 38},
            "deal": {"total": 4, "高于": 0, "低于": 3, "持平": 1},
            "details": scoped["details"],
        }

        html = dashboard.render_operational_report(summary)

        self.assertIn("经营概况", html)
        self.assertIn("下单 272 单", html)
        self.assertIn("自动报价率 45.2%", html)
        self.assertNotIn("44.0%", html)
        self.assertNotIn("结论一", html)
        self.assertNotIn("结论五", html)
        self.assertNotIn("异常线路复核清单", html)
        self.assertNotIn("tab-anomaly-scoped", html)

    def test_anomaly_table_includes_diagnosis_and_evidence_when_available(self) -> None:
        html = dashboard.render_anomaly_table(
            [
                {
                    "orderNo": "YC_TEST_002",
                    "route": "上海市上海市 -> 广东省深圳市",
                    "leftAmt": 4350,
                    "rightAmt": 1200,
                    "diff": 3150,
                    "result": "高于",
                    "isDeal": False,
                }
            ],
            diagnostics_by_order={
                "YC_TEST_002": {
                    "diagnosis": "订单运输方式变化：大板改为小板",
                    "priceFreshness": "命中价格超过30天未更新，需结合线路价格波动频率判断",
                    "laterUpdates": "后续更新：1200 元，2026-07-15 09:00:00，更新人 李四",
                    "evidence": "2026-07-14 10:32:25 编辑订单：运输方式：大板 -> 全程小板",
                }
            },
        )

        self.assertIn("初步归因", html)
        self.assertIn("价格时效", html)
        self.assertIn("后续更新", html)
        self.assertIn("证据", html)
        self.assertIn("大板改为小板", html)
        self.assertIn("超过30天", html)
        self.assertIn("李四", html)
        self.assertIn('class="wrap-text"', html)

    def test_second_bid_change_chart_starts_with_auto_quote_and_second_push_counts(self) -> None:
        html = dashboard.render_second_bid_change_chart(
            {
                "auto_offer_order_count": 115,
                "second_bid_order_count": 62,
                "second_bid_equal_count": 40,
                "second_bid_changed_count": 22,
                "second_bid_higher_count": 6,
                "second_bid_lower_count": 16,
                "second_bid_uncomparable_count": 0,
            }
        )

        self.assertIn("自动报价订单", html)
        self.assertIn("115 单 / 100.0%", html)
        self.assertIn("二次推送订单", html)
        self.assertIn("62 单 / 53.9%", html)
        self.assertLess(html.index("自动报价订单"), html.index("二次推送订单"))
        self.assertLess(html.index("二次推送订单"), html.index("推送后持平"))

    def test_dashboard_removes_bottom_metric_visibility_settings(self) -> None:
        summary = {
            "order_count": 1,
            "auto_offer_order_count": 1,
            "auto_offer_rate": 1,
            "deal_order_count": 0,
            "deal_rate": 0,
            "auto_offer_deal_count": 0,
            "auto_offer_orders_deal_count": 0,
            "second_bid_deal_count": 0,
            "bid_deal_count": 0,
            "route_count": 1,
            "auto_offer_route_count": 1,
            "second_bid_order_count": 0,
            "second_bid_rate": 0,
            "second_bid_mark_anomaly_count": 0,
            "by_channel": [{"渠道": "APP", "下单数量": 1, "自动报价订单数量": 1, "成单数量": 0}],
        }

        html = dashboard.build_html(summary, [], {}, {}, include_operational_report=False)

        self.assertNotIn('id="metric-settings"', html)
        self.assertIn('data-metric="core-auto"', html)
        self.assertNotIn('data-controls=', html)
        self.assertIn('data-metric="second-bid-pushed"', html)
        self.assertNotIn("metricVisibility", html)
        self.assertNotIn('type="checkbox"', html)

    def test_dashboard_renders_new_close_rate_province_and_profit_metrics(self) -> None:
        summary = {
            "order_count": 4,
            "auto_offer_order_count": 3,
            "auto_offer_rate": 0.75,
            "deal_order_count": 2,
            "deal_rate": 0.5,
            "auto_offer_deal_count": 1,
            "auto_offer_orders_deal_count": 2,
            "second_bid_deal_count": 0,
            "bid_deal_count": 1,
            "manual_bid_order_count": 2,
            "manual_bid_deal_count": 1,
            "route_count": 3,
            "auto_offer_route_count": 2,
            "second_bid_order_count": 1,
            "second_bid_rate": 1 / 3,
            "second_bid_mark_anomaly_count": 0,
            "auto_quote_close_rate": 1 / 3,
            "manual_bid_close_rate": 0.5,
            "by_channel": [{"渠道": "APP", "下单数量": 4, "自动报价订单数量": 3, "成单数量": 2}],
            "bid_auto_diff_start_province_distribution": [{"province": "广东省", "count": 2, "rate": 1.0}],
            "bid_auto_diff_end_province_distribution": [
                {"province": "江苏省", "count": 1, "rate": 0.5},
                {"province": "浙江省", "count": 1, "rate": 0.5},
            ],
            "second_bid_start_province_distribution": [{"province": "四川省", "count": 1, "rate": 1.0}],
            "second_bid_end_province_distribution": [{"province": "广东省", "count": 1, "rate": 1.0}],
            "auto_without_second_bid_start_province_distribution": [{"province": "广东省", "count": 2, "rate": 1.0}],
            "auto_without_second_bid_end_province_distribution": [{"province": "浙江省", "count": 2, "rate": 1.0}],
            "profit_by_quote_mode": {
                "auto_quote": {
                    "order_count": 1,
                    "sales_amount": 2000,
                    "carrier_cost": 1500,
                    "total_profit": 500,
                    "avg_profit": 500,
                    "profit_rate": 0.25,
                },
                "manual_quote": {
                    "order_count": 1,
                    "sales_amount": 1800,
                    "carrier_cost": 1200,
                    "total_profit": 600,
                    "avg_profit": 600,
                    "profit_rate": 1 / 3,
                },
            },
        }

        html = dashboard.build_html(summary, [], {}, {}, include_operational_report=False)

        self.assertIn("自动报价成单率（修正）", html)
        self.assertIn("人工报价成单率（修正）", html)
        self.assertIn("省份分布", html)
        self.assertIn("运力竞价与自动报价有差异", html)
        self.assertIn("始发省", html)
        self.assertIn("目的省", html)
        self.assertIn("四川省", html)
        self.assertIn("销售利润分析", html)
        self.assertIn("自动报价利润", html)
        self.assertIn("手动报价利润", html)

    def test_analysis_report_styles_anomaly_long_text_as_wrappable(self) -> None:
        summary = {
            "order_count": 1,
            "auto_offer_order_count": 0,
            "auto_offer_rate": 0,
            "deal_order_count": 0,
            "deal_rate": 0,
            "auto_offer_deal_count": 0,
            "auto_offer_orders_deal_count": 0,
            "second_bid_deal_count": 0,
            "bid_deal_count": 0,
            "route_count": 1,
            "auto_offer_route_count": 0,
            "by_channel": [{"渠道": "APP", "下单数量": 1, "自动报价订单数量": 0, "成单数量": 0}],
        }

        html = dashboard.build_html(summary, [], {}, {}, include_operational_report=True)

        self.assertIn(".anomaly-table .wrap-text", html)
        self.assertIn("overflow-wrap: anywhere", html)

    def test_build_html_can_render_pure_dashboard_or_ai_analysis_report(self) -> None:
        summary = {
            "order_count": 1,
            "auto_offer_order_count": 0,
            "auto_offer_rate": 0,
            "deal_order_count": 0,
            "deal_rate": 0,
            "auto_offer_deal_count": 0,
            "auto_offer_orders_deal_count": 0,
            "second_bid_deal_count": 0,
            "bid_deal_count": 0,
            "route_count": 1,
            "auto_offer_route_count": 0,
            "by_channel": [{"渠道": "APP", "下单数量": 1, "自动报价订单数量": 0, "成单数量": 0}],
        }

        pure_html = dashboard.build_html(summary, [], {}, {}, include_operational_report=False)
        report_html = dashboard.build_html(summary, [], {}, {}, include_operational_report=True)

        self.assertIn('data-report-mode="false"', pure_html)
        self.assertIn('data-report-mode="true"', report_html)
        for page in [pure_html, report_html]:
            self.assertIn("经营摘要", page)
            self.assertIn("经营概况", page)
            self.assertIn("价格与异常", page)


if __name__ == "__main__":
    unittest.main()
