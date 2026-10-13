from __future__ import annotations

import sys
import html as html_lib
import json
import re
import unittest
from pathlib import Path

from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from auto_quote_daily.runtime import build_0708_visual_dashboard as daily  # noqa: E402


class DailyDashboardTest(unittest.TestCase):
    def test_price_detail_keeps_exact_signed_difference_for_filtering(self) -> None:
        details = [
            {"orderNo": "HIGH", "route": "广东省深圳市 -> 上海市上海市", "result": "高于",
             "leftAmt": 2000.5, "rightAmt": 1000, "diff": 1000.5, "isDeal": False,
             "leftLabel": "竞价", "rightLabel": "自动报价"},
            {"orderNo": "LOW", "route": "广东省深圳市 -> 上海市上海市", "result": "低于",
             "leftAmt": 1000, "rightAmt": 2000.5, "diff": -1000.5, "isDeal": True,
             "leftLabel": "竞价", "rightLabel": "自动报价"},
        ]
        for result, expected in [("高于", 1000.5), ("低于", -1000.5)]:
            soup = BeautifulSoup(daily.render_price_detail_table(details, result), "html.parser")
            row = soup.select_one('tbody tr')
            self.assertEqual(float(row['data-price-diff']), expected)

    def test_price_difference_list_keeps_every_non_equal_order(self) -> None:
        details = [
            {"orderNo": f"LOW-{i}", "route": "河南省焦作市 -> 广西南宁市",
             "result": "低于", "leftAmt": 1600 + i, "rightAmt": 2800,
             "diff": -1200 + i}
            for i in range(8)
        ]
        details.extend([
            {"orderNo": "HIGH", "route": "广东省深圳市 -> 上海市上海市",
             "result": "高于", "leftAmt": 3200, "rightAmt": 2800, "diff": 400},
            {"orderNo": "EQUAL", "route": "广东省深圳市 -> 上海市上海市",
             "result": "持平", "leftAmt": 2800, "rightAmt": 2800, "diff": 0},
        ])
        rendered = daily.render_actionable_route_recommendations({"details": details})
        rows = re.findall(r"<tr>\s*(.*?)\s*</tr>", rendered, re.S)[1:]
        self.assertEqual(len(rows), 9)
        for item in details[:-1]:
            row = next(row for row in rows if item["orderNo"] in row)
            self.assertIn(daily.money(item["leftAmt"]), row)
            self.assertIn(daily.money(item["rightAmt"]), row)
            self.assertIn(daily.signed_money(item["diff"]), row)
        self.assertNotIn("EQUAL", rendered)

    def test_price_difference_list_shows_high_only_orders(self) -> None:
        rendered = daily.render_actionable_route_recommendations({"details": [
            {"orderNo": "HIGH-ONLY", "route": "广东省深圳市 -> 上海市上海市",
             "result": "高于", "leftAmt": 3200, "rightAmt": 2800, "diff": 400},
        ]})
        self.assertIn("HIGH-ONLY", rendered)

    def test_route_push_section_defaults_to_top50_but_keeps_all_routes(self) -> None:
        routes = [{"routeKey": str(i), "线路": f"线路{i}", "总订单数": 4, "自动报价订单数": 3,
                   "二次推送订单数": 1, "未二次推送订单数": 2, "二次推送率": 1 / 3,
                   "推送分布占比": 1 / 60} for i in range(60)]
        rendered = daily.render_route_second_bid_push_section({
            "sales_second_bid_push_by_route": routes, "sales_second_bid_push_route_count": 60,
            "sales_second_bid_push_order_count": 60,
        })
        self.assertEqual(len(re.findall(r'<tr data-route-key=', rendered)), 50)
        self.assertIn('value="50" selected', rendered)
        self.assertIn('value="100"', rendered)
        self.assertIn('value="all"', rendered)
        self.assertIn('data-route-sort', rendered)
        self.assertIn('data-route-min-sample', rendered)
        self.assertIn('data-route-scope', rendered)
        self.assertIn('data-route-search', rendered)
        payload = json.loads(html_lib.unescape(re.search(r'data-route-rows="([^"]+)"', rendered).group(1)))
        self.assertEqual(len(payload), 60)
        self.assertIn("二次推送率", rendered)
        self.assertIn("样本较少", rendered)

    def test_distance_section_shows_counts_and_rate_with_correct_denominator(self) -> None:
        summary = {"order_count": 10, "order_distance_valid_count": 10, "order_distance_unknown_count": 0,
                   "sales_second_bid_push_by_distance": [
            {"公里数区间": "500-<1,000", "总订单数": 10, "自动报价订单数": 8,
             "二次推送订单数": 2, "未二次推送订单数": 6, "二次推送率": 0.25, "推送分布占比": 1},
        ]}
        rendered = daily.render_distance_second_bid_push_section(summary)
        for label in ["总订单", "自动报价订单", "二次推送订单", "二次推送率", "25.0%", "推送分布占比"]:
            self.assertIn(label, rendered)
        option = json.loads(html_lib.unescape(re.search(r'data-chart="([^"]+)"', rendered).group(1)))
        series = {item["name"]: item for item in option["series"]}
        self.assertEqual(series["二次推送订单"]["data"], [2])
        self.assertEqual(series["未二次推送订单"]["data"], [6])
        self.assertEqual(series["二次推送率"]["data"], [25])
        self.assertEqual(series["二次推送率"]["yAxisIndex"], 1)

    def test_sales_push_section_compares_order_base_with_secondary_pushes(self) -> None:
        summary = {"sales_second_bid_push_by_owner": [
            {"销售": "销售甲", "总订单数": 10, "自动报价订单数": 8, "未二次推送订单数": 6,
             "推送订单数": 2, "二次推送率": 0.25, "持平": 1, "价格增高": 1, "持平占比": 0.5},
            {"销售": "销售乙", "总订单数": 3, "自动报价订单数": 0, "未二次推送订单数": 0,
             "推送订单数": 0, "二次推送率": 0, "持平占比": 0},
        ]}
        rendered = daily.render_sales_second_bid_push_section(summary)
        for label in ["总订单", "自动报价订单", "二次推送订单", "二次推送率", "销售乙", "25.0%"]:
            self.assertIn(label, rendered)
        option = json.loads(html_lib.unescape(re.search(r'data-chart="([^"]+)"', rendered).group(1)))
        series = {item["name"]: item for item in option["series"]}
        self.assertEqual(series["总订单"]["data"], [10, 3])
        self.assertEqual(series["自动报价订单"]["data"], [8, 0])
        self.assertEqual(series["持平"]["data"], [1, 0])

    def test_legacy_sales_push_summary_does_not_invent_order_base(self) -> None:
        rendered = daily.render_sales_second_bid_push_section({"sales_second_bid_push_by_owner": [
            {"销售": "销售甲", "推送订单数": 2, "持平": 2, "持平占比": 1},
        ]})
        self.assertIn("<td>-</td>", rendered)
        self.assertNotIn("<td>0.0%</td>", rendered)

    def test_daily_dashboard_groups_business_tabs_and_removes_metric_settings(self) -> None:
        summary = {
            "order_count": 10,
            "auto_offer_order_count": 5,
            "deal_order_count": 2,
            "auto_offer_deal_count": 1,
            "auto_offer_orders_deal_count": 1,
            "bid_deal_count": 1,
            "second_bid_deal_count": 0,
            "second_bid_order_count": 1,
            "second_bid_mark_anomaly_count": 0,
            "second_bid_equal_count": 1,
            "second_bid_changed_count": 0,
            "second_bid_higher_count": 0,
            "second_bid_lower_count": 0,
            "second_bid_uncomparable_count": 0,
            "auto_offer_rate": 0.5,
            "deal_rate": 0.2,
            "second_bid_rate": 0.2,
            "auto_quote_deal_contribution_rate": 0.1,
            "manual_bid_deal_contribution_rate": 0.1,
            "corrected_auto_quote_deal_contribution_rate": 0.1,
            "corrected_manual_bid_deal_contribution_rate": 0.1,
            "corrected_auto_quote_deal_count": 1,
            "corrected_manual_bid_deal_count": 1,
            "corrected_auto_quote_close_deal_count": 1,
            "corrected_manual_quote_close_deal_count": 1,
            "corrected_auto_quote_order_count": 4,
            "corrected_manual_quote_order_count": 2,
            "corrected_auto_quote_close_rate": 0.3,
            "corrected_manual_quote_close_rate": 0.4,
            "route_count": 4,
            "auto_offer_route_count": 2,
            "by_channel": [{"渠道": "APP", "下单数量": 10, "自动报价订单数量": 5, "成单数量": 2}],
            "profit_by_quote_mode": {
                "auto_quote": {"order_count": 1, "sales_amount": 2000, "carrier_cost": 1500, "total_profit": 500, "avg_profit": 500, "profit_rate": 0.25},
                "manual_quote": {"order_count": 1, "sales_amount": 1800, "carrier_cost": 1400, "total_profit": 400, "avg_profit": 400, "profit_rate": 2 / 9},
            },
            "bid_auto_diff_start_province_distribution": [{"province": "广东省", "count": 1, "rate": 1.0}],
            "bid_auto_diff_end_province_distribution": [{"province": "浙江省", "count": 1, "rate": 1.0}],
            "second_bid_start_province_distribution": [{"province": "四川省", "count": 1, "rate": 1.0}],
            "second_bid_end_province_distribution": [{"province": "广东省", "count": 1, "rate": 1.0}],
            "auto_without_second_bid_start_province_distribution": [{"province": "江苏省", "count": 4, "rate": 1.0}],
            "auto_without_second_bid_end_province_distribution": [{"province": "上海市", "count": 4, "rate": 1.0}],
            "sales_second_bid_push_by_owner": [
                {"销售": "销售甲", "推送订单数": 2, "持平": 1, "价格增高": 1, "价格降低": 0, "暂不可比": 0, "持平占比": 0.5},
            ],
        }

        trend_metrics = [
            {"date": "2026-09-02", "label": "09-02", "order_count": 8, "auto_offer_order_count": 4, "deal_order_count": 1, "auto_offer_rate": 0.5, "deal_rate": 0.125, "corrected_auto_quote_close_rate": 0.2, "corrected_manual_quote_close_rate": 0.1},
            {"date": "2026-09-16", "label": "09-16", "order_count": 10, "auto_offer_order_count": 5, "deal_order_count": 2, "auto_offer_rate": 0.5, "deal_rate": 0.2, "corrected_auto_quote_close_rate": 0.3, "corrected_manual_quote_close_rate": 0.4},
        ]
        html = daily.build_html(summary, [], {}, {}, trend_metrics=trend_metrics)

        soup = BeautifulSoup(html, "html.parser")
        tabs = soup.select('[role="tab"]')
        self.assertEqual([t.get_text(strip=True) for t in tabs], ["经营总览", "自动报价", "二次竞价", "成单与利润", "价格与异常"])
        panels = {p["data-business-panel"]: p for p in soup.select('[data-business-panel]')}
        self.assertEqual(len(panels), 5)
        self.assertNotIn("hidden", panels["overview"].attrs)
        self.assertTrue(all("hidden" in p.attrs for key, p in panels.items() if key != "overview"))
        self.assertEqual(len(soup.select('.business-summary [data-metric]')), 4)
        self.assertIsNotNone(panels["auto"].select_one('[data-metric="core-auto-line-update"]'))
        self.assertIsNotNone(panels["second"].select_one('[data-metric="sales-second-bid-push"]'))
        self.assertIsNotNone(panels["deals"].select_one('[data-metric="profit-summary"]'))
        self.assertIsNotNone(panels["deals"].select_one('[data-metric="core-corrected-auto-quote-close-rate"]'))
        self.assertIsNone(panels["overview"].select_one('[data-metric="core-corrected-auto-quote-close-rate"]'))
        self.assertIsNotNone(panels["auto"].select_one('[data-metric="province-auto-without-second-start"]'))
        self.assertIsNotNone(panels["second"].select_one('[data-metric="province-second-bid-start"]'))
        self.assertIsNotNone(panels["prices"].select_one('[data-metric="province-bid-auto-diff-start"]'))
        self.assertIsNotNone(soup.select_one('[data-full-report]'))
        self.assertIsNotNone(soup.select_one('[data-print-report]'))
        self.assertIsNone(soup.select_one('[data-controls]'))
        self.assertIsNone(soup.select_one('#metric-settings'))
        self.assertNotIn('metricVisibility:', html)
        self.assertEqual(len(soup.select('[id]')), len({e['id'] for e in soup.select('[id]')}))
        self.assertIn("渠道下单构成", html)
        self.assertIn("二次竞价价格状态", html)
        self.assertIn("销售手动推送分布", html)
        self.assertIn("订单归属销售", html)
        self.assertIn("销售额", html)
        self.assertIn('class="echart pie-chart"', html)
        self.assertIn("echarts@5", html)
        self.assertNotIn("每日经营趋势", html)
        self.assertIn('data-metric="method-chart"', html)
        self.assertIn('&quot;name&quot;: &quot;成单方式&quot;', html)
        self.assertIn("修正后成单归因", html)
        self.assertIn('data-metric="corrected-method-chart"', html)
        self.assertIn("自动报价线路更新", html)
        self.assertIn('data-metric="core-auto-line-update"', html)
        self.assertIn("自动报价线路更新数", html)
        self.assertIn('data-metric="line-update-summary"', html)
        self.assertIn("自动报价成单率（修正）", html)
        self.assertIn("人工报价成单率（修正）", html)
        self.assertIn('data-metric="core-corrected-auto-quote-close-rate"', html)
        self.assertIn('data-metric="core-corrected-manual-quote-close-rate"', html)
        self.assertIn("S 订单逐笔按实际持平或变化", html)
        self.assertIn("分子 1 / 分母 4", html)
        self.assertIn("分子 5 / 分母 10", html)
        self.assertIn('data-metric="recent-trend"', html)
        self.assertIn("已加载 2/15 天", html)
        self.assertIn('&quot;name&quot;: &quot;自动报价率&quot;', html)
        self.assertIn('data-metric="quote-close-rate-trend"', html)
        self.assertIn("总成单率", html)
        self.assertIn('&quot;name&quot;: &quot;人工报价成单率（修正）&quot;', html)
        self.assertIn('data-metric="second-bid-push-trend"', html)
        self.assertIn('data-metric="price-compare-trend"', html)
        self.assertIn("最近15天二次竞价推送趋势", html)
        self.assertIn("最近15天价格对比趋势", html)
        self.assertNotIn("表格线路内", html)

        funnel = str(panels["deals"].select_one('.funnel-stack'))
        self.assertIn('data-metric="funnel-order"', funnel)
        self.assertIn('data-metric="funnel-deal"', funnel)
        self.assertIn('class="funnel-stack"', funnel)
        self.assertIn('class="funnel-shape"', funnel)
        self.assertNotIn('data-metric="funnel-auto"', funnel)
        self.assertNotIn('data-metric="funnel-auto-deal"', funnel)

        report = BeautifulSoup(daily.build_html(summary, [], {}, {}, include_operational_report=True), "html.parser")
        self.assertTrue(all('hidden' not in panel.attrs for panel in report.select('[data-business-panel]')))
        self.assertIsNone(report.select_one('[data-controls]'))


if __name__ == "__main__":
    unittest.main()
