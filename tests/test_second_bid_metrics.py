from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from auto_quote_daily.runtime import analyze_0708_api_metrics as metrics  # noqa: E402


class SecondBidMetricsTest(unittest.TestCase):
    def test_route_push_distribution_uses_exact_direction_and_all_order_bases(self) -> None:
        rows = [
            {"orderNo": "1", "routeKey": "甲省|甲市|乙省|乙市", "route": "甲省甲市 -> 乙省乙市", "isAutoOffer": 1},
            {"orderNo": "2", "routeKey": "甲省|甲市|乙省|乙市", "route": "甲省甲市 -> 乙省乙市", "isAutoOffer": 1},
            {"orderNo": "3", "routeKey": "甲省|甲市|乙省|乙市", "route": "甲省甲市 -> 乙省乙市", "isAutoOffer": 0},
            {"orderNo": "4", "routeKey": "乙省|乙市|甲省|甲市", "route": "乙省乙市 -> 甲省甲市", "isAutoOffer": 1},
            {"orderNo": "5", "routeKey": "丙省|丙市|丁省|丁市", "route": "丙省丙市 -> 丁省丁市", "isAutoOffer": 1},
        ]
        result = metrics.route_second_bid_push_metrics(rows, [{"订单号": no} for no in ["1", "1", "4", "OUTSIDE"]])
        routes = {item["routeKey"]: item for item in result["sales_second_bid_push_by_route"]}
        forward = routes["甲省|甲市|乙省|乙市"]
        self.assertEqual(forward["总订单数"], 3)
        self.assertEqual(forward["自动报价订单数"], 2)
        self.assertEqual(forward["二次推送订单数"], 1)
        self.assertEqual(forward["二次推送率"], 0.5)
        self.assertEqual(forward["推送分布占比"], 0.5)
        self.assertEqual(routes["丙省|丙市|丁省|丁市"]["二次推送订单数"], 0)
        self.assertEqual(result["sales_second_bid_push_route_count"], 2)
        self.assertEqual(result["sales_second_bid_push_single_order_route_count"], 2)
        self.assertEqual(result["sales_second_bid_push_top50_order_count"], 2)
        self.assertEqual(sum(item["总订单数"] for item in routes.values()), len(rows))
        self.assertEqual(sum(item["二次推送订单数"] for item in routes.values()), 2)
        for item in routes.values():
            self.assertEqual(item["自动报价订单数"], item["二次推送订单数"] + item["未二次推送订单数"])

    def test_order_distance_uses_order_list_then_valid_detail_fallback(self) -> None:
        orders = [
            {"orderNo": "LIST", "createTime": "2026-07-08 10:00:00", "distance": "500.5"},
            {"orderNo": "DETAIL", "createTime": "2026-07-08 10:01:00", "distance": 0},
            {"orderNo": "MISSING", "createTime": "2026-07-08 10:02:00", "distance": "nan"},
        ]
        rows, _ = metrics.build_rows(orders, [], {"LIST": {"distance": 600}, "DETAIL": {"distance": 1000}}, {})
        self.assertEqual([row["distanceKm"] for row in rows], [500.5, 1000, None])
        self.assertEqual([row["distanceBand"] for row in rows], ["500-<1,000", "1,000-<1,500", "公里数未知"])

    def test_distance_push_distribution_counts_boundaries_and_unknown_without_extra_orders(self) -> None:
        distances = [499.5, 500, 999.9, 1000, 1500, 2000, 3000, None, 0, float("nan"), float("inf")]
        rows = [{"orderNo": str(i), "distanceKm": value, "isAutoOffer": int(i in {0, 1, 3, 4, 5, 6, 7})}
                for i, value in enumerate(distances)]
        pushes = [{"订单号": value} for value in ["0", "0", "1", "7", "OUTSIDE_POOL"]]
        result = metrics.distance_second_bid_push_metrics(rows, pushes)
        bands = {item["公里数区间"]: item for item in result["sales_second_bid_push_by_distance"]}
        self.assertEqual(bands["500-<1,000"]["总订单数"], 2)
        self.assertEqual(bands["500-<1,000"]["自动报价订单数"], 1)
        self.assertEqual(bands["500-<1,000"]["二次推送率"], 1)
        self.assertEqual(bands["1,000-<1,500"]["总订单数"], 1)
        self.assertEqual(bands["1,500-<2,000"]["总订单数"], 1)
        self.assertEqual(bands["2,000-<3,000"]["总订单数"], 1)
        self.assertEqual(bands[">=3,000"]["总订单数"], 1)
        self.assertEqual(bands["公里数未知"]["总订单数"], 4)
        self.assertEqual(bands["公里数未知"]["二次推送订单数"], 1)
        self.assertAlmostEqual(bands["公里数未知"]["推送分布占比"], 1 / 3)
        self.assertEqual(result["order_distance_valid_count"], 7)
        self.assertEqual(result["order_distance_unknown_count"], 4)
        self.assertEqual(sum(item["总订单数"] for item in bands.values()), len(rows))
        self.assertEqual(sum(item["二次推送订单数"] for item in bands.values()), 3)
        for item in bands.values():
            self.assertEqual(item["自动报价订单数"], item["二次推送订单数"] + item["未二次推送订单数"])

    def test_second_bid_metrics_require_auto_trunk_price_and_track_anomalies(self) -> None:
        rows = [
            {
                "orderNo": "VALID_EQUAL",
                "isAutoOffer": 1,
                "autoTrunkAmt": 1200,
                "bidMode": "S",
                "isDeal": 1,
            },
            {
                "orderNo": "VALID_HIGH",
                "isAutoOffer": 1,
                "autoTrunkAmt": 1000,
                "bidMode": "S",
                "isDeal": 1,
            },
            {
                "orderNo": "VALID_LOW",
                "isAutoOffer": 1,
                "autoTrunkAmt": 1600,
                "bidMode": "S",
                "isDeal": 1,
            },
            {
                "orderNo": "S_WITHOUT_AUTO",
                "isAutoOffer": 0,
                "autoTrunkAmt": None,
                "bidMode": "S",
                "isDeal": 1,
            },
            {
                "orderNo": "VALID_NO_BID_TRUNK",
                "isAutoOffer": 1,
                "autoTrunkAmt": 1800,
                "bidMode": "S",
                "isDeal": 1,
            },
            {
                "orderNo": "AUTO_NOT_SECOND",
                "isAutoOffer": 1,
                "autoTrunkAmt": 900,
                "bidMode": "A",
                "isDeal": 1,
            },
        ]
        bid_groups_by_order = {
            "VALID_EQUAL": [{"pkId": "g1", "payableAmt": 1200, "confirmStatus": 1}],
            "VALID_HIGH": [{"pkId": "g2", "payableAmt": 1200, "confirmStatus": 1}],
            "VALID_LOW": [{"pkId": "g3", "payableAmt": 1400, "confirmStatus": 1}],
            "VALID_NO_BID_TRUNK": [{"pkId": "g4", "payableAmt": 1800, "confirmStatus": 1}],
        }
        bid_carriers_by_order = {
            "VALID_EQUAL": {"g1": [{"trunkAmt": 1200}]},
            "VALID_HIGH": {"g2": [{"trunkAmt": 1200}]},
            "VALID_LOW": {"g3": [{"trunkAmt": 1400}]},
            "VALID_NO_BID_TRUNK": {"g4": [{"putAmt": 100}]},
        }

        result = metrics.second_bid_metrics(rows, bid_groups_by_order, bid_carriers_by_order)

        self.assertEqual(result["second_bid_order_count"], 4)
        self.assertEqual(result["second_bid_mark_anomaly_count"], 1)
        self.assertEqual(result["second_bid_comparable_count"], 3)
        self.assertEqual(result["second_bid_uncomparable_count"], 1)
        self.assertEqual(result["second_bid_equal_count"], 1)
        self.assertEqual(result["second_bid_changed_count"], 2)
        self.assertEqual(result["second_bid_higher_count"], 1)
        self.assertEqual(result["second_bid_lower_count"], 1)
        self.assertEqual(result["second_bid_equal_deal_count"], 1)
        self.assertEqual(result["second_bid_changed_deal_count"], 2)
        self.assertEqual(result["second_bid_higher_deal_count"], 1)
        self.assertEqual(result["second_bid_lower_deal_count"], 1)
        self.assertEqual(result["second_bid_equal_rate"], 0.25)
        self.assertEqual(result["second_bid_changed_rate"], 0.5)
        self.assertEqual(result["second_bid_higher_rate"], 0.25)
        self.assertEqual(result["second_bid_lower_rate"], 0.25)

    def test_corrected_deal_contribution_attributes_actual_second_bid_deals(self) -> None:
        result = metrics.corrected_deal_contribution_metrics(
            order_count=100,
            auto_offer_non_second_bid_deal_count=10,
            bid_deal_count=20,
            second_bid_equal_deal_count=2,
            second_bid_changed_deal_count=3,
        )

        self.assertEqual(result["corrected_auto_quote_deal_count"], 12)
        self.assertEqual(result["corrected_manual_bid_deal_count"], 23)
        self.assertEqual(result["corrected_auto_quote_deal_contribution_rate"], 0.12)
        self.assertEqual(result["corrected_manual_bid_deal_contribution_rate"], 0.23)

    def test_second_bid_metrics_uses_closed_carrier_order_cost_when_bid_group_is_gone(self) -> None:
        rows = [
            {
                "orderNo": "CLOSED_S",
                "isAutoOffer": 1,
                "autoTrunkAmt": 1700,
                "orderAmount": 2200,
                "carrierOrderProfitAmt": 500,
                "bidMode": "S",
                "isDeal": 1,
            }
        ]

        result = metrics.second_bid_metrics(rows, {}, {})

        self.assertEqual(result["second_bid_comparable_count"], 1)
        self.assertEqual(result["second_bid_equal_count"], 1)
        self.assertEqual(result["second_bid_equal_deal_count"], 1)
        self.assertEqual(result["second_bid_uncomparable_count"], 0)

    def test_query_no_from_order_logs_uses_the_first_auto_query(self) -> None:
        logs = [
            {
                "createTime": "2026-09-20 09:03:00",
                "operateName": "查价",
                "content": "系统自动查价成功，查价单号：YJCXLATER",
            },
            {
                "createTime": "2026-09-20 09:01:00",
                "operateName": "查价",
                "content": "系统自动查价成功，查价单号：YJCXFIRST",
            },
        ]

        self.assertEqual(metrics.query_no_from_order_logs(logs), "YJCXFIRST")

    def test_corrected_quote_close_rates_attribute_actual_second_bid_deals(self) -> None:
        result = metrics.corrected_quote_close_rate_metrics(
            order_count=100,
            auto_offer_order_count=50,
            auto_offer_non_second_bid_deal_count=10,
            bid_deal_count=8,
            second_bid_equal_count=4,
            second_bid_changed_count=6,
            second_bid_equal_deal_count=2,
            second_bid_changed_deal_count=3,
        )

        self.assertEqual(result["corrected_auto_quote_order_count"], 44)
        self.assertEqual(result["corrected_manual_quote_order_count"], 56)
        self.assertEqual(result["corrected_auto_quote_close_deal_count"], 12)
        self.assertEqual(result["corrected_manual_quote_close_deal_count"], 11)
        self.assertAlmostEqual(result["corrected_auto_quote_close_rate"], 12 / 44)
        self.assertAlmostEqual(result["corrected_manual_quote_close_rate"], 11 / 56)

    def test_sales_second_bid_push_metrics_use_manual_log_events_and_owner(self) -> None:
        rows = [
            {"orderNo": "EQUAL", "custOwnerName": "销售甲", "route": "A -> B", "isAutoOffer": 1, "autoTrunkAmt": 1000},
            {"orderNo": "HIGH", "custOwnerName": "销售甲", "route": "C -> D", "isAutoOffer": 1, "autoTrunkAmt": 1000},
            {"orderNo": "LOW", "custOwnerName": "销售乙", "route": "E -> F", "isAutoOffer": 1, "autoTrunkAmt": 1000},
            {"orderNo": "PENDING", "custOwnerName": "销售乙", "route": "G -> H", "isAutoOffer": 1, "autoTrunkAmt": 1000},
            {"orderNo": "SYSTEM_PUSH", "custOwnerName": "销售丙", "route": "I -> J", "isAutoOffer": 1, "autoTrunkAmt": 1000},
            {"orderNo": "NO_AUTO", "custOwnerName": "销售丙", "route": "K -> L", "isAutoOffer": 0, "autoTrunkAmt": 0},
            {"orderNo": "NOT_PUSHED", "custOwnerName": " 销售甲 ", "isAutoOffer": 1, "autoTrunkAmt": 1000},
            {"orderNo": "AUTO_NO_PRICE", "custOwnerName": "销售甲", "isAutoOffer": 1, "autoTrunkAmt": None},
            {"orderNo": "MANUAL", "custOwnerName": "销售甲", "isAutoOffer": 0},
            {"orderNo": "UNASSIGNED", "custOwnerName": "", "isAutoOffer": 0},
        ]
        logs = {
            "EQUAL": [
                {"operateName": "推送运力竞价", "createUserName": "销售甲", "createTime": "2026-07-08 10:00:00"},
                {"operateName": "推送运力竞价", "createUserName": "销售甲", "createTime": "2026-07-08 10:10:00"},
            ],
            "HIGH": [{"operateName": "推送运力竞价", "createUserName": "销售甲", "createTime": "2026-07-08 11:00:00"}],
            "LOW": [{"operateName": "推送运力竞价", "createUserName": "销售乙", "createTime": "2026-07-08 12:00:00"}],
            "PENDING": [{"operateName": "推送运力竞价", "createUserName": "销售乙", "createTime": "2026-07-08 13:00:00"}],
            "SYSTEM_PUSH": [{"operateName": "推送运力竞价", "createUserName": "系统", "createTime": "2026-07-08 14:00:00"}],
            "NO_AUTO": [{"operateName": "推送运力竞价", "createUserName": "销售丙", "createTime": "2026-07-08 14:00:00"}],
        }
        groups = {
            "EQUAL": [{"pkId": "g1", "payableAmt": 1000, "confirmStatus": 1}],
            "HIGH": [{"pkId": "g2", "payableAmt": 1100, "confirmStatus": 1}],
            "LOW": [{"pkId": "g3", "payableAmt": 900, "confirmStatus": 1}],
        }
        carriers = {
            "EQUAL": {"g1": [{"trunkAmt": 1000}]},
            "HIGH": {"g2": [{"trunkAmt": 1100}]},
            "LOW": {"g3": [{"trunkAmt": 900}]},
        }

        totals, by_owner, details = metrics.sales_second_bid_push_metrics(rows, logs, groups, carriers)

        self.assertEqual(totals["sales_second_bid_push_order_count"], 4)
        self.assertEqual(totals["sales_second_bid_push_equal_count"], 1)
        self.assertEqual(totals["sales_second_bid_push_higher_count"], 1)
        self.assertEqual(totals["sales_second_bid_push_lower_count"], 1)
        self.assertEqual(totals["sales_second_bid_push_uncomparable_count"], 1)
        by_owner_name = {item["销售"]: item for item in by_owner}
        self.assertEqual(by_owner_name["销售甲"]["推送订单数"], 2)
        self.assertEqual(by_owner_name["销售乙"]["暂不可比"], 1)
        self.assertEqual(by_owner_name["销售甲"]["总订单数"], 5)
        self.assertEqual(by_owner_name["销售甲"]["自动报价订单数"], 4)
        self.assertEqual(by_owner_name["销售甲"]["未二次推送订单数"], 2)
        self.assertEqual(by_owner_name["销售甲"]["二次推送率"], 0.5)
        self.assertEqual(by_owner_name["销售丙"]["总订单数"], 2)
        self.assertEqual(by_owner_name["销售丙"]["自动报价订单数"], 1)
        self.assertEqual(by_owner_name["销售丙"]["推送订单数"], 0)
        self.assertEqual(by_owner_name["未分配"]["总订单数"], 1)
        self.assertEqual(by_owner_name["未分配"]["二次推送率"], 0)
        self.assertEqual(sum(item["总订单数"] for item in by_owner), len(rows))
        self.assertEqual(sum(item["自动报价订单数"] for item in by_owner), 7)
        for item in by_owner:
            self.assertEqual(item["自动报价订单数"], item["推送订单数"] + item["未二次推送订单数"])
            self.assertEqual(item["推送订单数"], sum(item[key] for key in ["持平", "价格增高", "价格降低", "暂不可比"]))
        self.assertEqual(len(details), 4)
        self.assertEqual(details[0]["推送时间"], "2026-07-08 10:00:00")

    def test_summarize_adds_close_rates_province_distributions_and_profit(self) -> None:
        rows = [
            {
                "orderNo": "AUTO_DEAL",
                "queryMatched": 1,
                "isAutoOffer": 1,
                "isDeal": 1,
                "bidMode": "A",
                "hasBidGroup": 0,
                "offerType": "direct",
                "sourceRetailName": "APP",
                "routeKey": "广东省|广州市|浙江省|杭州市",
                "orderAmount": 2000,
                "autoOfferAmt": 1500,
                "basePayableAmt": 1400,
                "guaranteeAmt": 100,
            },
            {
                "orderNo": "BID_DIFF_DEAL",
                "queryMatched": 1,
                "isAutoOffer": 1,
                "isDeal": 1,
                "bidMode": "B",
                "hasBidGroup": 1,
                "offerType": "direct",
                "sourceRetailName": "APP",
                "routeKey": "广东省|深圳市|江苏省|南京市",
                "autoTrunkAmt": 1000,
                "orderAmount": 1800,
            },
            {
                "orderNo": "SECOND_DIFF",
                "queryMatched": 1,
                "isAutoOffer": 1,
                "isDeal": 0,
                "bidMode": "S",
                "hasBidGroup": 1,
                "offerType": "direct",
                "sourceRetailName": "小程序",
                "routeKey": "四川省|成都市|广东省|广州市",
                "autoTrunkAmt": 900,
                "orderAmount": 1500,
            },
            {
                "orderNo": "BID_NO_AUTO",
                "queryMatched": 0,
                "isAutoOffer": 0,
                "isDeal": 0,
                "bidMode": "B",
                "hasBidGroup": 1,
                "offerType": "",
                "sourceRetailName": "APP",
                "routeKey": "湖南省|长沙市|湖北省|武汉市",
                "orderAmount": 1000,
            },
            {
                "orderNo": "AUTO_DEAL_WITHOUT_CONFIRMED_BID",
                "queryMatched": 1,
                "isAutoOffer": 1,
                "isDeal": 1,
                "bidMode": "A",
                "hasBidGroup": 0,
                "offerType": "direct",
                "sourceRetailName": "APP",
                "routeKey": "广西|南宁市|云南省|昆明市",
                "orderAmount": 1800,
                "autoOfferAmt": 1200,
            },
        ]
        bid_groups_by_order = {
            "AUTO_DEAL": [{"pkId": "auto-bid-1", "payableAmt": 1500, "confirmStatus": 1, "confirmTime": "2026-07-19 09:00:00"}],
            "BID_DIFF_DEAL": [{"pkId": "bid-1", "payableAmt": 1200, "confirmStatus": 1, "confirmTime": "2026-07-19 10:00:00"}],
            "SECOND_DIFF": [{"pkId": "bid-2", "payableAmt": 800, "confirmStatus": 1, "confirmTime": "2026-07-19 11:00:00"}],
        }
        bid_carriers_by_order = {
            "BID_DIFF_DEAL": {"bid-1": [{"trunkAmt": 1200}]},
            "SECOND_DIFF": {"bid-2": [{"trunkAmt": 800}]},
        }

        result = metrics.summarize(rows, [], set(), bid_groups_by_order, bid_carriers_by_order)

        self.assertEqual(result["corrected_auto_quote_deal_count"], 2)
        self.assertEqual(result["corrected_manual_bid_deal_count"], 1)
        self.assertEqual(result["corrected_auto_quote_deal_count"] + result["corrected_manual_bid_deal_count"], result["deal_order_count"])
        self.assertAlmostEqual(result["auto_quote_close_rate"], 2 / 4)
        self.assertEqual(result["manual_bid_order_count"], 3)
        self.assertEqual(result["manual_bid_deal_count"], 1)
        self.assertAlmostEqual(result["manual_bid_close_rate"], 1 / 3)
        self.assertEqual(
            result["bid_auto_diff_start_province_distribution"],
            [{"province": "广东省", "count": 1, "rate": 0.5}, {"province": "四川省", "count": 1, "rate": 0.5}],
        )
        self.assertEqual(
            result["bid_auto_diff_end_province_distribution"],
            [{"province": "江苏省", "count": 1, "rate": 0.5}, {"province": "广东省", "count": 1, "rate": 0.5}],
        )
        self.assertEqual(
            result["second_bid_start_province_distribution"],
            [{"province": "四川省", "count": 1, "rate": 1.0}],
        )
        self.assertEqual(
            result["auto_without_second_bid_end_province_distribution"],
            [
                {"province": "浙江省", "count": 1, "rate": 1 / 3},
                {"province": "江苏省", "count": 1, "rate": 1 / 3},
                {"province": "云南省", "count": 1, "rate": 1 / 3},
            ],
        )
        self.assertEqual(result["profit_by_quote_mode"]["auto_quote"]["order_count"], 1)
        self.assertEqual(result["profit_by_quote_mode"]["auto_quote"]["total_profit"], 500)
        self.assertEqual(result["profit_by_quote_mode"]["manual_quote"]["order_count"], 1)
        self.assertEqual(result["profit_by_quote_mode"]["manual_quote"]["total_profit"], 600)


if __name__ == "__main__":
    unittest.main()
