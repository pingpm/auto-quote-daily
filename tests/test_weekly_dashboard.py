from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from auto_quote_daily.runtime import build_weekly_visual_dashboard as weekly  # noqa: E402


class WeeklyDashboardTest(unittest.TestCase):
    def test_iter_report_days_supports_custom_end_date(self) -> None:
        days = weekly.iter_report_days(weekly.parse_report_date("2026-07-01"), weekly.parse_report_date("2026-07-29"))

        self.assertEqual(len(days), 29)
        self.assertEqual(days[0].strftime("%Y-%m-%d"), "2026-07-01")
        self.assertEqual(days[-1].strftime("%Y-%m-%d"), "2026-07-29")

    def test_report_label_uses_range_wording_for_non_week_period(self) -> None:
        self.assertEqual(
            weekly.report_period_label(weekly.parse_report_date("2026-07-01"), weekly.parse_report_date("2026-07-29")),
            "区间",
        )
        self.assertEqual(
            weekly.report_period_label(weekly.parse_report_date("2026-07-20"), weekly.parse_report_date("2026-07-26")),
            "周",
        )

    def sample_day(self, date: str, label: str, summary: dict[str, int | float]) -> dict[str, object]:
        return {
            "date": date,
            "label": label,
            "summary": {
                "order_count": 10,
                "auto_offer_order_count": 4,
                "deal_order_count": 1,
                "auto_offer_deal_count": 1,
                "auto_offer_direct_deal_count": 1,
                "bid_deal_count": 0,
                "second_bid_deal_count": 0,
                "auto_offer_orders_deal_count": 1,
                "bid_order_count": 5,
                "query_record_count": 10,
                "second_bid_order_count": 2,
                "second_bid_mark_anomaly_count": 0,
                "second_bid_comparable_count": 2,
                "second_bid_uncomparable_count": 0,
                "second_bid_equal_count": 1,
                "second_bid_changed_count": 1,
                "second_bid_higher_count": 0,
                "second_bid_lower_count": 1,
                "by_channel": [{"渠道": "APP", "下单数量": 10, "自动报价订单数量": 4, "成单数量": 1}],
                **summary,
            },
            "rows": [{"routeKey": f"{label}|B|C|D", "isAutoOffer": 1}],
            "bid_groups": {},
            "bid_group_carriers": {},
        }

    def test_aggregate_week_sums_second_bid_metrics(self) -> None:
        days = [
            {
                "summary": {
                    "order_count": 10,
                    "auto_offer_order_count": 4,
                    "deal_order_count": 1,
                    "auto_offer_deal_count": 1,
                    "auto_offer_direct_deal_count": 1,
                    "bid_deal_count": 0,
                    "second_bid_deal_count": 0,
                    "auto_offer_orders_deal_count": 1,
                    "bid_order_count": 5,
                    "query_record_count": 10,
                    "second_bid_order_count": 2,
                    "second_bid_mark_anomaly_count": 1,
                    "second_bid_comparable_count": 2,
                    "second_bid_uncomparable_count": 0,
                    "second_bid_equal_count": 1,
                    "second_bid_changed_count": 1,
                    "second_bid_higher_count": 1,
                    "second_bid_lower_count": 0,
                },
                "rows": [
                    {"routeKey": "A|B|C|D", "isAutoOffer": 1},
                    {"routeKey": "A|B|E|F", "isAutoOffer": 0},
                ],
            },
            {
                "summary": {
                    "order_count": 10,
                    "auto_offer_order_count": 6,
                    "deal_order_count": 1,
                    "auto_offer_deal_count": 0,
                    "auto_offer_direct_deal_count": 0,
                    "bid_deal_count": 1,
                    "second_bid_deal_count": 0,
                    "auto_offer_orders_deal_count": 1,
                    "bid_order_count": 4,
                    "query_record_count": 10,
                    "second_bid_order_count": 3,
                    "second_bid_mark_anomaly_count": 0,
                    "second_bid_comparable_count": 2,
                    "second_bid_uncomparable_count": 1,
                    "second_bid_equal_count": 0,
                    "second_bid_changed_count": 2,
                    "second_bid_higher_count": 0,
                    "second_bid_lower_count": 2,
                },
                "rows": [
                    {"routeKey": "A|B|C|D", "isAutoOffer": 1},
                    {"routeKey": "G|H|I|J", "isAutoOffer": 1},
                ],
            },
        ]

        result = weekly.aggregate_week(days)

        self.assertEqual(result["second_bid_order_count"], 5)
        self.assertEqual(result["second_bid_rate"], 0.5)
        self.assertEqual(result["second_bid_mark_anomaly_count"], 1)
        self.assertEqual(result["second_bid_equal_count"], 1)
        self.assertEqual(result["second_bid_changed_count"], 3)
        self.assertEqual(result["second_bid_higher_count"], 1)
        self.assertEqual(result["second_bid_lower_count"], 2)
        self.assertEqual(result["second_bid_uncomparable_count"], 1)
        self.assertEqual(result["direct_manual_bid_order_count"], 0)

    def test_aggregate_week_sums_new_close_rate_distribution_and_profit_metrics(self) -> None:
        days = [
            {
                "summary": {
                    "order_count": 10,
                    "auto_offer_order_count": 4,
                    "deal_order_count": 2,
                    "auto_offer_deal_count": 1,
                    "auto_offer_direct_deal_count": 1,
                    "auto_offer_non_second_bid_deal_count": 1,
                    "bid_deal_count": 1,
                    "second_bid_deal_count": 0,
                    "auto_offer_orders_deal_count": 1,
                    "bid_order_count": 4,
                    "manual_bid_order_count": 3,
                    "manual_bid_deal_count": 1,
                    "query_record_count": 10,
                    "second_bid_order_count": 1,
                    "second_bid_mark_anomaly_count": 0,
                    "second_bid_comparable_count": 1,
                    "second_bid_uncomparable_count": 0,
                    "second_bid_equal_count": 0,
                    "second_bid_changed_count": 1,
                    "second_bid_higher_count": 1,
                    "second_bid_lower_count": 0,
                    "second_bid_equal_deal_count": 0,
                    "second_bid_changed_deal_count": 0,
                    "bid_auto_diff_start_province_distribution": [{"province": "广东省", "count": 2, "rate": 1.0}],
                    "bid_auto_diff_end_province_distribution": [{"province": "江苏省", "count": 2, "rate": 1.0}],
                    "second_bid_start_province_distribution": [{"province": "四川省", "count": 1, "rate": 1.0}],
                    "second_bid_end_province_distribution": [{"province": "广东省", "count": 1, "rate": 1.0}],
                    "auto_without_second_bid_start_province_distribution": [{"province": "广东省", "count": 3, "rate": 1.0}],
                    "auto_without_second_bid_end_province_distribution": [{"province": "浙江省", "count": 3, "rate": 1.0}],
                    "profit_by_quote_mode": {
                        "auto_quote": {"order_count": 1, "sales_amount": 2000, "carrier_cost": 1500, "total_profit": 500, "avg_profit": 500, "profit_rate": 0.25},
                        "manual_quote": {"order_count": 1, "sales_amount": 1800, "carrier_cost": 1200, "total_profit": 600, "avg_profit": 600, "profit_rate": 1 / 3},
                    },
                },
                "rows": [{"routeKey": "A|B|C|D", "isAutoOffer": 1}],
            },
            {
                "summary": {
                    "order_count": 10,
                    "auto_offer_order_count": 6,
                    "deal_order_count": 2,
                    "auto_offer_deal_count": 2,
                    "auto_offer_direct_deal_count": 2,
                    "auto_offer_non_second_bid_deal_count": 2,
                    "bid_deal_count": 0,
                    "second_bid_deal_count": 1,
                    "auto_offer_orders_deal_count": 2,
                    "bid_order_count": 5,
                    "manual_bid_order_count": 4,
                    "manual_bid_deal_count": 1,
                    "query_record_count": 10,
                    "second_bid_order_count": 2,
                    "second_bid_mark_anomaly_count": 0,
                    "second_bid_comparable_count": 2,
                    "second_bid_uncomparable_count": 0,
                    "second_bid_equal_count": 1,
                    "second_bid_changed_count": 1,
                    "second_bid_higher_count": 0,
                    "second_bid_lower_count": 1,
                    "second_bid_equal_deal_count": 1,
                    "second_bid_changed_deal_count": 0,
                    "bid_auto_diff_start_province_distribution": [{"province": "广东省", "count": 1, "rate": 0.5}, {"province": "四川省", "count": 1, "rate": 0.5}],
                    "bid_auto_diff_end_province_distribution": [{"province": "江苏省", "count": 1, "rate": 0.5}, {"province": "广东省", "count": 1, "rate": 0.5}],
                    "second_bid_start_province_distribution": [{"province": "四川省", "count": 2, "rate": 1.0}],
                    "second_bid_end_province_distribution": [{"province": "广东省", "count": 2, "rate": 1.0}],
                    "auto_without_second_bid_start_province_distribution": [{"province": "广东省", "count": 4, "rate": 1.0}],
                    "auto_without_second_bid_end_province_distribution": [{"province": "浙江省", "count": 4, "rate": 1.0}],
                    "profit_by_quote_mode": {
                        "auto_quote": {"order_count": 2, "sales_amount": 4000, "carrier_cost": 2600, "total_profit": 1400, "avg_profit": 700, "profit_rate": 0.35},
                        "manual_quote": {"order_count": 1, "sales_amount": 2200, "carrier_cost": 1700, "total_profit": 500, "avg_profit": 500, "profit_rate": 0.2273},
                    },
                },
                "rows": [{"routeKey": "E|F|G|H", "isAutoOffer": 1}],
            },
        ]

        result = weekly.aggregate_week(days)

        self.assertEqual(result["manual_bid_order_count"], 7)
        self.assertEqual(result["manual_bid_deal_count"], 2)
        self.assertEqual(result["auto_quote_close_rate"], 0.3)
        self.assertAlmostEqual(result["manual_bid_close_rate"], 2 / 7)
        self.assertAlmostEqual(result["corrected_auto_quote_deal_contribution_rate"], 4 / 20)
        self.assertAlmostEqual(result["corrected_manual_bid_deal_contribution_rate"], 1 / 20)
        self.assertEqual(result["corrected_auto_quote_order_count"], 8)
        self.assertEqual(result["corrected_manual_quote_order_count"], 12)
        self.assertAlmostEqual(result["corrected_auto_quote_close_rate"], 4 / 8)
        self.assertAlmostEqual(result["corrected_manual_quote_close_rate"], 1 / 12)
        self.assertEqual(result["bid_auto_diff_start_province_distribution"][0], {"province": "广东省", "count": 3, "rate": 0.75})
        self.assertEqual(result["second_bid_start_province_distribution"], [{"province": "四川省", "count": 3, "rate": 1.0}])
        self.assertEqual(result["profit_by_quote_mode"]["auto_quote"]["order_count"], 3)
        self.assertEqual(result["profit_by_quote_mode"]["auto_quote"]["total_profit"], 1900)
        self.assertEqual(result["profit_by_quote_mode"]["auto_quote"]["avg_profit"], 633.33)

    def test_weekly_html_includes_second_bid_without_metric_settings(self) -> None:
        days = [
            {
                **self.sample_day("2026-07-13", "07-13", {}),
                "rows": [
                    {
                        "orderNo": "YC-S001",
                        "routeKey": "A|B|C|D",
                        "isAutoOffer": 1,
                        "bidMode": "S",
                        "autoTrunkAmt": 1000,
                    }
                ],
                "bid_groups": {
                    "YC-S001": [{"pkId": "BID-S001", "confirmStatus": 1, "payableAmt": 1200, "confirmTime": "2026-07-13 10:00:00"}]
                },
                "bid_group_carriers": {"YC-S001": {"BID-S001": [{"trunkAmt": 1200}]}},
            },
            {
                **self.sample_day("2026-07-14", "07-14", {}),
                "rows": [
                    {
                        "orderNo": "YC-S002",
                        "routeKey": "A|B|C|D",
                        "isAutoOffer": 1,
                        "bidMode": "S",
                        "autoTrunkAmt": 1100,
                    }
                ],
                "bid_groups": {
                    "YC-S002": [{"pkId": "BID-S002", "confirmStatus": 1, "payableAmt": 900, "confirmTime": "2026-07-14 10:00:00"}]
                },
                "bid_group_carriers": {"YC-S002": {"BID-S002": [{"trunkAmt": 900}]}},
            },
            self.sample_day("2026-07-15", "07-15", {}),
            self.sample_day("2026-07-16", "07-16", {}),
            self.sample_day("2026-07-17", "07-17", {}),
            self.sample_day("2026-07-18", "07-18", {}),
            self.sample_day("2026-07-19", "07-19", {}),
        ]

        html = weekly.build_html(days)

        self.assertIn("二次竞价跟进", html)
        self.assertIn("按周统计", html)
        self.assertIn("自动报价订单", html)
        self.assertIn("二次竞价推送订单", html)
        self.assertIn("每日订单自动报价后推送运力二次竞价趋势", html)
        self.assertIn("推送二次竞价订单", html)
        self.assertIn("推送率", html)
        self.assertIn('data-metric="weekly-second-bid-push-trend"', html)
        self.assertIn('data-metric="weekly-second-bid-pushed"', html)
        self.assertNotIn('id="metric-settings"', html)
        self.assertNotIn('data-controls=', html)
        self.assertNotIn('metricVisibility:', html)
        self.assertNotIn("二次竞价后价格趋势", html)
        self.assertNotIn("自动报价均价", html)
        self.assertNotIn("运力竞价均价", html)
        self.assertNotIn('weekly-second-bid-price-trend', html)
        self.assertNotIn("周二次竞价", html)
        self.assertNotIn("周二次推送", html)

        self.assertIn('class="metric-help"', html)
        self.assertIn('aria-label="查看指标计算口径"', html)
        self.assertIn("公式：自动报价方式成单贡献率（修正）", html)
        self.assertIn("S 订单逐笔按实际持平或变化", html)
        self.assertIn("自动报价成单率（修正）", html)
        self.assertIn('data-metric="weekly-core-corrected-auto-quote-close-rate"', html)
        self.assertIn("分子 28 / 分母 70", html)

        section_order = [
            "周核心指标",
            "每日经营趋势",
            "渠道与利润",
            "二次竞价跟进",
            "价格对比",
            "省份分布",
        ]
        positions = [html.index(title) for title in section_order]
        self.assertEqual(positions, sorted(positions))

    def test_weekly_html_includes_route_price_trend_for_diff_routes(self) -> None:
        route = "广东广州 -> 浙江杭州"
        route_key = "广东省|广州市|浙江省|杭州市"
        days = [
            {
                **self.sample_day("2026-07-13", "07-13", {}),
                "rows": [
                    {
                        "orderNo": "YC001",
                        "route": route,
                        "routeKey": route_key,
                        "isAutoOffer": 1,
                        "hasBidGroup": 1,
                        "autoTrunkAmt": 1000,
                        "isDeal": True,
                    }
                ],
                "bid_groups": {
                    "YC001": [
                        {
                            "pkId": "BID001",
                            "confirmStatus": 1,
                            "payableAmt": 1200,
                            "bidTime": "2026-07-13 10:00:00",
                            "confirmTime": "2026-07-13 10:05:00",
                            "bidderName": "运力A",
                        }
                    ]
                },
                "bid_group_carriers": {
                    "YC001": {
                        "BID001": [
                            {
                                "carrierId": "C001",
                                "carrierName": "承运商甲",
                                "trunkAmt": 1200,
                                "createTime": "2026-07-13 10:01:00",
                            }
                        ]
                    }
                },
            },
            {
                **self.sample_day("2026-07-14", "07-14", {}),
                "rows": [
                    {
                        "orderNo": "YC002",
                        "route": route,
                        "routeKey": route_key,
                        "isAutoOffer": 1,
                        "hasBidGroup": 1,
                        "autoTrunkAmt": 1100,
                        "isDeal": False,
                    }
                ],
                "bid_groups": {
                    "YC002": [
                        {
                            "pkId": "BID002",
                            "confirmStatus": 1,
                            "payableAmt": 900,
                            "bidTime": "2026-07-14 11:00:00",
                            "confirmTime": "2026-07-14 11:05:00",
                            "bidderName": "运力B",
                        }
                    ]
                },
                "bid_group_carriers": {
                    "YC002": {
                        "BID002": [
                            {
                                "carrierId": "C002",
                                "carrierName": "承运商乙",
                                "trunkAmt": 900,
                                "createTime": "2026-07-14 11:01:00",
                            }
                        ]
                    }
                },
            },
        ]

        html = weekly.build_html(days)

        self.assertIn("差异线路价格趋势", html)
        self.assertIn("广东广州", html)
        self.assertIn("浙江杭州", html)
        self.assertIn("自动报价趋势", html)
        self.assertIn("运力竞价趋势", html)
        self.assertIn("差价趋势", html)
        self.assertIn("承运商 2 个", html)
        self.assertIn("承运商甲", html)
        self.assertIn("承运商乙", html)
        self.assertIn("运力A", html)
        self.assertIn("运力B", html)
        self.assertIn('data-route-trend="广东广州 -&gt; 浙江杭州"', html)


if __name__ == "__main__":
    unittest.main()
