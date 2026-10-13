from __future__ import annotations

import html
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from auto_quote_daily.runtime import analyze_0708_api_metrics as metrics
from auto_quote_daily.runtime import build_0708_visual_dashboard as daily
from auto_quote_daily.runtime import build_weekly_visual_dashboard as weekly


class FullAutoQuoteMetricsTest(unittest.TestCase):
    def sample_day(self, modes: list[tuple[int, str, float | None]]) -> dict:
        orders = [{"orderNo": str(i), "createTime": "2026-07-08 10:00:00"} for i in range(len(modes))]
        rows, used = metrics.build_rows(orders, [], {}, {})
        for row, (hit, mode, amount) in zip(rows, modes):
            row.update(isAutoOffer=hit, queryMatched=hit, bidMode=mode, autoTrunkAmt=amount,
                       sourceRetailName="APP")
        return {"date": "2026-07-08", "label": "07-08", "rows": rows,
                "summary": metrics.summarize(rows, [], used), "bid_groups": {}, "bid_group_carriers": {}}

    def test_full_auto_excludes_all_hit_s_orders_regardless_of_price_or_deal(self):
        day = self.sample_day([(1, "A", 1000), (1, "", None), (1, "B", 1000),
                               (1, "S", 1000), (1, "S", None), (1, "S", 0),
                               (0, "S", None), (0, "B", None)])
        summary = day["summary"]
        self.assertEqual(summary["auto_offer_order_count"], 6)
        self.assertEqual(summary["second_bid_order_count"], 1)
        self.assertEqual(summary.get("full_auto_offer_order_count"), 3)
        self.assertEqual(summary.get("full_auto_offer_rate"), 3 / 8)
        self.assertEqual(summary["by_channel"][0].get("全自动报价订单数量"), 3)

    def test_no_orders_returns_zero_count_and_rate(self):
        summary = self.sample_day([])["summary"]
        self.assertEqual(summary.get("full_auto_offer_order_count"), 0)
        self.assertEqual(summary.get("full_auto_offer_rate"), 0)

    def test_period_rebuilds_legacy_snapshots_and_uses_total_order_denominator(self):
        days = [self.sample_day([(1, "A", 1000), (1, "S", None)]),
                self.sample_day([(1, "", None)] + [(0, "B", None)] * 7)]
        for day in days:
            day["summary"].pop("full_auto_offer_order_count", None)
            day["summary"].pop("full_auto_offer_rate", None)
            day["summary"]["by_channel"][0].pop("全自动报价订单数量", None)
        result = weekly.aggregate_week(days)
        self.assertEqual(result.get("full_auto_offer_order_count"), 2)
        self.assertEqual(result.get("full_auto_offer_rate"), 0.2)
        trend = weekly.build_day_metrics(days)
        self.assertEqual([item.get("full_auto_offer_rate") for item in trend], [0.5, 0.125])
        channel = weekly.aggregate_channels(days)[0]
        self.assertEqual(channel.get("全自动报价"), 2)
        self.assertEqual(channel.get("全自动报价率"), 0.2)

    def test_daily_and_period_render_new_metric_from_legacy_rows(self):
        day = self.sample_day([(1, "A", 1000), (1, "S", None), (0, "B", None), (0, "", None)])
        day["summary"].pop("full_auto_offer_order_count", None)
        day["summary"].pop("full_auto_offer_rate", None)
        daily_html = daily.build_html(day["summary"], day["rows"], {}, {})
        self.assertTrue('data-metric="core-full-auto"' in daily_html)
        self.assertIn("全自动报价率", daily_html)
        self.assertTrue('data-focus-id="full-auto-rate"' in daily_html)
        auto_position = daily_html.index('data-focus-id="auto-rate"')
        full_auto_position = daily_html.index('data-focus-id="full-auto-rate"')
        deal_position = daily_html.index('data-focus-id="deal-rate"')
        self.assertLess(auto_position, full_auto_position)
        self.assertLess(full_auto_position, deal_position)
        self.assertIn('>25.0%</strong>', daily_html[full_auto_position:deal_position])
        self.assertIn('分子 1 / 分母 4', daily_html[full_auto_position:deal_position])
        period_html = weekly.build_html([day])
        self.assertIn('data-metric="weekly-core-full-auto"', period_html)
        self.assertIn("全自动报价率 25.0%；分子 1 / 分母 4", period_html)
        trend = weekly.build_day_metrics([day])
        for chart in [daily.render_recent_trend(trend), weekly.render_day_trend(trend)]:
            option = json.loads(html.unescape(re.search(r'data-chart="([^"]+)"', chart).group(1)))
            series = next(s for s in option["series"] if s["name"] == "全自动报价率")
            self.assertEqual(series["data"], [25.0])
            self.assertEqual(series["yAxisIndex"], 1)



if __name__ == "__main__":
    unittest.main()
