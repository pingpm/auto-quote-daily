from __future__ import annotations

import csv
import json
import math
import os
import re
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests


ROOT = Path(os.environ.get("AUTO_QUOTE_WORKSPACE", Path.cwd())).expanduser().resolve()

BASE_URL = os.environ.get("DMS_BASE_URL", "https://dms.iyunche.com").rstrip("/")
ORDER_URL = f"{BASE_URL}/dms-boot/order/toRetail/getOrderList"
DETAIL_URL = f"{BASE_URL}/dms-boot/order/toRetail/getOrderDetail"
QUERY_URL = f"{BASE_URL}/dms-boot/autoPrice/getQueryList"
BID_GROUP_URL = f"{BASE_URL}/dms-boot/tBid/getBidGroupList"
BID_GROUP_CARRIER_URL = f"{BASE_URL}/dms-boot/tBid/getBidGroupCarrierList"
ORDER_LOG_URL = f"{BASE_URL}/dms-boot/order/getOrderLog"
CARRIER_ORDER_URL = f"{BASE_URL}/dms-boot/tOrder/getOrderList"

TOKEN = os.environ.get("DMS_ACCESS_TOKEN", "")

ANALYSIS_DATE = datetime.strptime(os.environ.get("ANALYSIS_DATE", "2026-07-08"), "%Y-%m-%d")
DATE_COMPACT = ANALYSIS_DATE.strftime("%Y%m%d")
DATE_SHORT = ANALYSIS_DATE.strftime("%m%d")
OUT_DIR = ROOT / "outputs" / f"{DATE_SHORT}_api_analysis"
PAGE_SIZE = 1000
MATCH_WINDOW_BEFORE_MIN = 5
MATCH_WINDOW_AFTER_MIN = 30
DEAL_STATUSES = {2, 3, 4}
WORKERS = 12
QUERY_NO_PATTERN = re.compile(r"查价单号[：:]\s*([A-Za-z0-9]+)")
DISTANCE_BANDS = (
    ("<500", 500), ("500-<1,000", 1000), ("1,000-<1,500", 1500),
    ("1,500-<2,000", 2000), ("2,000-<3,000", 3000), (">=3,000", None),
)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\u3000", " ").strip()


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value), fmt)
        except ValueError:
            pass
    return None


def fmt_dt(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else ""


def safe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def first_present_float(*values: Any) -> float | None:
    for value in values:
        if value is None or value == "":
            continue
        return safe_float(value)
    return None


def normalized_distance_km(*values: Any) -> float | None:
    for value in values:
        if isinstance(value, bool):
            continue
        distance = first_present_float(value)
        if distance is not None and math.isfinite(distance) and distance > 0:
            return distance
    return None


def distance_band(value: Any) -> str:
    distance = normalized_distance_km(value)
    if distance is None:
        return "公里数未知"
    return next(label for label, upper in DISTANCE_BANDS if upper is None or distance < upper)


def has_positive_auto_trunk(row: dict[str, Any]) -> bool:
    auto_trunk = first_present_float(row.get("autoTrunkAmt"))
    return bool(row.get("isAutoOffer")) and auto_trunk is not None and auto_trunk > 0


def full_auto_quote_metrics(rows: list[dict[str, Any]]) -> dict[str, int | float]:
    count = sum(1 for row in rows if row.get("isAutoOffer") and clean_text(row.get("bidMode")) != "S")
    return {
        "full_auto_offer_order_count": count,
        "full_auto_offer_rate": count / len(rows) if rows else 0,
    }


def chosen_confirmed_bid_group(groups: list[dict[str, Any]]) -> dict[str, Any] | None:
    confirmed = [
        group
        for group in groups
        if safe_float(group.get("payableAmt")) > 0 and safe_int(group.get("confirmStatus")) == 1
    ]
    if not confirmed:
        return None
    return sorted(
        confirmed,
        key=lambda group: clean_text(group.get("confirmTime") or group.get("modifyTime") or group.get("bidTime")),
    )[0]


def bid_trunk_amt(order_no: str, bid_group: dict[str, Any], carriers_by_order: dict[str, Any]) -> float | None:
    bid_id = clean_text(bid_group.get("pkId"))
    carrier_rows = (carriers_by_order.get(order_no) or {}).get(bid_id) or []
    trunk_values = [
        value
        for value in (first_present_float(item.get("trunkAmt")) for item in carrier_rows)
        if value is not None
    ]
    if not trunk_values:
        return None
    return round(sum(trunk_values), 2)


def carrier_order_confirmed_cost(row: dict[str, Any]) -> float | None:
    """Derive confirmed carrier cost for a closed S order from tOrder data."""
    order_amount = first_present_float(row.get("orderAmount"))
    profit_amt = first_present_float(row.get("carrierOrderProfitAmt"))
    if order_amount is None or profit_amt is None:
        return None
    return round(order_amount - profit_amt, 2)


def route_provinces(row: dict[str, Any]) -> tuple[str, str]:
    parts = (clean_text(row.get("routeKey")).split("|") + ["", "", "", ""])[:4]
    return parts[0], parts[2]


def province_distribution(rows: list[dict[str, Any]], province_index: int) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for row in rows:
        province = route_provinces(row)[province_index]
        if province:
            counter[province] += 1
    total = sum(counter.values())
    return [
        {"province": province, "count": count, "rate": count / total if total else 0}
        for province, count in counter.most_common()
    ]


def bid_cost_total(order_no: str, bid_group: dict[str, Any], carriers_by_order: dict[str, Any]) -> float | None:
    payable = first_present_float(bid_group.get("payableAmt"))
    if payable is not None and payable > 0:
        return payable
    bid_id = clean_text(bid_group.get("pkId"))
    carrier_rows = (carriers_by_order.get(order_no) or {}).get(bid_id) or []
    values = []
    for item in carrier_rows:
        values.append(
            sum(
                safe_float(item.get(field))
                for field in ["trunkAmt", "putAmt", "sendAmt", "otherAmt"]
            )
        )
    positive_values = [value for value in values if value > 0]
    if not positive_values:
        return None
    return round(sum(positive_values), 2)


def quote_mode_profit_metrics(
    rows: list[dict[str, Any]],
    bid_groups_by_order: dict[str, list[dict[str, Any]]],
    bid_group_carriers_by_order: dict[str, dict[str, list[dict[str, Any]]]],
) -> dict[str, dict[str, float | int]]:
    buckets = {
        "auto_quote": {"order_count": 0, "sales_amount": 0.0, "carrier_cost": 0.0, "total_profit": 0.0},
        "manual_quote": {"order_count": 0, "sales_amount": 0.0, "carrier_cost": 0.0, "total_profit": 0.0},
    }
    for row in rows:
        if not row.get("isDeal"):
            continue
        bid_mode = clean_text(row.get("bidMode"))
        if bid_mode == "A":
            bucket_name = "auto_quote"
        elif bid_mode in {"B", "S"}:
            bucket_name = "manual_quote"
        else:
            continue

        order_no = clean_text(row.get("orderNo"))
        sales_amount = safe_float(row.get("orderAmount"))
        bid_group = chosen_confirmed_bid_group(bid_groups_by_order.get(order_no, []))
        carrier_cost = bid_cost_total(order_no, bid_group, bid_group_carriers_by_order) if bid_group else None
        if carrier_cost is None:
            continue

        bucket = buckets[bucket_name]
        bucket["order_count"] += 1
        bucket["sales_amount"] += sales_amount
        bucket["carrier_cost"] += carrier_cost
        bucket["total_profit"] += sales_amount - carrier_cost

    for bucket in buckets.values():
        order_count = int(bucket["order_count"])
        sales_amount = float(bucket["sales_amount"])
        total_profit = float(bucket["total_profit"])
        bucket["sales_amount"] = round(sales_amount, 2)
        bucket["carrier_cost"] = round(float(bucket["carrier_cost"]), 2)
        bucket["total_profit"] = round(total_profit, 2)
        bucket["avg_profit"] = round(total_profit / order_count, 2) if order_count else 0.0
        bucket["profit_rate"] = total_profit / sales_amount if sales_amount else 0.0
    return buckets


def bid_auto_diff_rows(
    rows: list[dict[str, Any]],
    bid_groups_by_order: dict[str, list[dict[str, Any]]],
    bid_group_carriers_by_order: dict[str, dict[str, list[dict[str, Any]]]],
) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        auto_amt = first_present_float(row.get("autoTrunkAmt"))
        if not row.get("isAutoOffer") or not row.get("hasBidGroup") or auto_amt is None:
            continue
        order_no = clean_text(row.get("orderNo"))
        bid_group = chosen_confirmed_bid_group(bid_groups_by_order.get(order_no, []))
        bid_amt = bid_trunk_amt(order_no, bid_group, bid_group_carriers_by_order) if bid_group else None
        if bid_amt is None or abs(round(bid_amt - auto_amt, 2)) < 0.01:
            continue
        result.append(row)
    return result


def second_bid_metrics(
    rows: list[dict[str, Any]],
    bid_groups_by_order: dict[str, list[dict[str, Any]]],
    bid_group_carriers_by_order: dict[str, dict[str, list[dict[str, Any]]]],
) -> dict[str, Any]:
    second_bid_rows = [row for row in rows if clean_text(row.get("bidMode")) == "S"]
    valid_rows = [row for row in second_bid_rows if has_positive_auto_trunk(row)]
    anomaly_rows = [row for row in second_bid_rows if not has_positive_auto_trunk(row)]
    denominator = len(valid_rows)
    equal_count = 0
    higher_count = 0
    lower_count = 0
    equal_deal_count = 0
    higher_deal_count = 0
    lower_deal_count = 0
    uncomparable_count = 0

    for row in valid_rows:
        order_no = clean_text(row.get("orderNo"))
        auto_amt = first_present_float(row.get("autoTrunkAmt"))
        bid_group = chosen_confirmed_bid_group(bid_groups_by_order.get(order_no, []))
        bid_amt = bid_trunk_amt(order_no, bid_group, bid_group_carriers_by_order) if bid_group else None
        if bid_amt is None and row.get("isDeal"):
            bid_amt = carrier_order_confirmed_cost(row)
        if auto_amt is None or bid_amt is None:
            uncomparable_count += 1
            continue
        diff = round(bid_amt - auto_amt, 2)
        if abs(diff) < 0.01:
            equal_count += 1
            equal_deal_count += int(bool(row.get("isDeal")))
        elif diff > 0:
            higher_count += 1
            higher_deal_count += int(bool(row.get("isDeal")))
        else:
            lower_count += 1
            lower_deal_count += int(bool(row.get("isDeal")))

    changed_count = higher_count + lower_count
    changed_deal_count = higher_deal_count + lower_deal_count

    def rate(count: int) -> float:
        return count / denominator if denominator else 0

    return {
        "second_bid_order_count": denominator,
        "second_bid_mark_anomaly_count": len(anomaly_rows),
        "second_bid_comparable_count": equal_count + changed_count,
        "second_bid_uncomparable_count": uncomparable_count,
        "second_bid_equal_count": equal_count,
        "second_bid_changed_count": changed_count,
        "second_bid_higher_count": higher_count,
        "second_bid_lower_count": lower_count,
        "second_bid_equal_deal_count": equal_deal_count,
        "second_bid_changed_deal_count": changed_deal_count,
        "second_bid_higher_deal_count": higher_deal_count,
        "second_bid_lower_deal_count": lower_deal_count,
        "second_bid_equal_rate": rate(equal_count),
        "second_bid_changed_rate": rate(changed_count),
        "second_bid_higher_rate": rate(higher_count),
        "second_bid_lower_rate": rate(lower_count),
        "second_bid_uncomparable_rate": rate(uncomparable_count),
    }


def sales_second_bid_push_metrics(
    rows: list[dict[str, Any]],
    order_logs_by_order: dict[str, list[dict[str, Any]]],
    bid_groups_by_order: dict[str, list[dict[str, Any]]],
    bid_group_carriers_by_order: dict[str, dict[str, list[dict[str, Any]]]],
) -> tuple[dict[str, int], list[dict[str, Any]], list[dict[str, Any]]]:
    """Summarize manual sales pushes using the order-log event, not bidMode."""
    by_owner: dict[str, dict[str, int]] = defaultdict(
        lambda: {"总订单数": 0, "自动报价订单数": 0, "推送订单数": 0,
                 "持平": 0, "价格增高": 0, "价格降低": 0, "暂不可比": 0}
    )
    details: list[dict[str, Any]] = []
    for row in rows:
        owner = clean_text(row.get("custOwnerName")) or "未分配"
        bucket = by_owner[owner]
        bucket["总订单数"] += 1
        bucket["自动报价订单数"] += int(bool(row.get("isAutoOffer")))
        if not has_positive_auto_trunk(row):
            continue
        order_no = clean_text(row.get("orderNo"))
        manual_pushes = [
            log
            for log in order_logs_by_order.get(order_no, [])
            if clean_text(log.get("operateName")) == "推送运力竞价"
            and clean_text(log.get("createUserName")) not in {"", "系统"}
            and (log_time := parse_dt(log.get("createTime"))) is not None
            and log_time.date() == ANALYSIS_DATE.date()
        ]
        if not manual_pushes:
            continue
        push_log = min(manual_pushes, key=lambda item: clean_text(item.get("createTime")))
        bucket["推送订单数"] += 1

        auto_amt = first_present_float(row.get("autoTrunkAmt"))
        bid_group = chosen_confirmed_bid_group(bid_groups_by_order.get(order_no, []))
        bid_amt = bid_trunk_amt(order_no, bid_group, bid_group_carriers_by_order) if bid_group else None
        if auto_amt is None or bid_amt is None:
            status = "暂不可比"
            diff = None
        else:
            diff = round(bid_amt - auto_amt, 2)
            if abs(diff) < 0.01:
                status = "持平"
            elif diff > 0:
                status = "价格增高"
            else:
                status = "价格降低"
        bucket[status] += 1
        details.append(
            {
                "订单归属销售": owner,
                "实际推送操作人": clean_text(push_log.get("createUserName")),
                "推送时间": clean_text(push_log.get("createTime")),
                "订单号": order_no,
                "线路": clean_text(row.get("route")),
                "订单公里数": normalized_distance_km(row.get("distanceKm")),
                "公里数区间": distance_band(row.get("distanceKm")),
                "自动报价干线价": auto_amt,
                "确认竞价干线价": bid_amt,
                "差价": diff,
                "价格状态": status,
            }
        )

    by_owner_rows = []
    for owner, bucket in by_owner.items():
        total = bucket["推送订单数"]
        comparable = total - bucket["暂不可比"]
        by_owner_rows.append(
            {
                "销售": owner,
                **bucket,
                "未二次推送订单数": bucket["自动报价订单数"] - total,
                "二次推送率": total / bucket["自动报价订单数"] if bucket["自动报价订单数"] else 0,
                "可比订单数": comparable,
                "持平占比": bucket["持平"] / total if total else 0,
                "增高占比": bucket["价格增高"] / total if total else 0,
                "降低占比": bucket["价格降低"] / total if total else 0,
            }
        )
    by_owner_rows.sort(key=lambda item: (-int(item["推送订单数"]), -int(item["总订单数"]), str(item["销售"])))

    totals = {
        "sales_second_bid_push_order_count": len(details),
        "sales_second_bid_push_equal_count": sum(item["持平"] for item in by_owner.values()),
        "sales_second_bid_push_higher_count": sum(item["价格增高"] for item in by_owner.values()),
        "sales_second_bid_push_lower_count": sum(item["价格降低"] for item in by_owner.values()),
        "sales_second_bid_push_uncomparable_count": sum(item["暂不可比"] for item in by_owner.values()),
    }
    return totals, by_owner_rows, sorted(details, key=lambda item: (item["推送时间"], item["订单号"]))


def distance_second_bid_push_metrics(
    rows: list[dict[str, Any]], sales_push_details: list[dict[str, Any]],
) -> dict[str, Any]:
    pushed_order_nos = {clean_text(item.get("订单号")) for item in sales_push_details}
    buckets = {
        label: {"公里数区间": label, "总订单数": 0, "自动报价订单数": 0, "二次推送订单数": 0}
        for label in [*[label for label, _ in DISTANCE_BANDS], "公里数未知"]
    }
    for row in rows:
        bucket = buckets[distance_band(row.get("distanceKm"))]
        bucket["总订单数"] += 1
        if row.get("isAutoOffer"):
            bucket["自动报价订单数"] += 1
            bucket["二次推送订单数"] += int(clean_text(row.get("orderNo")) in pushed_order_nos)
    total_pushed = sum(item["二次推送订单数"] for item in buckets.values())
    for bucket in buckets.values():
        auto_count = bucket["自动报价订单数"]
        pushed = bucket["二次推送订单数"]
        bucket["未二次推送订单数"] = auto_count - pushed
        bucket["二次推送率"] = pushed / auto_count if auto_count else 0
        bucket["推送分布占比"] = pushed / total_pushed if total_pushed else 0
    unknown_count = buckets["公里数未知"]["总订单数"]
    return {
        "sales_second_bid_push_by_distance": list(buckets.values()),
        "order_distance_valid_count": len(rows) - unknown_count,
        "order_distance_unknown_count": unknown_count,
    }


def route_second_bid_push_metrics(
    rows: list[dict[str, Any]], sales_push_details: list[dict[str, Any]],
) -> dict[str, Any]:
    pushed_order_nos = {clean_text(item.get("订单号")) for item in sales_push_details}
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = clean_text(row.get("routeKey")) or clean_text(row.get("route")) or "线路未知"
        bucket = buckets.setdefault(key, {
            "routeKey": key, "线路": clean_text(row.get("route")) or "线路未知",
            "总订单数": 0, "自动报价订单数": 0, "二次推送订单数": 0,
        })
        bucket["总订单数"] += 1
        if row.get("isAutoOffer"):
            bucket["自动报价订单数"] += 1
            bucket["二次推送订单数"] += int(clean_text(row.get("orderNo")) in pushed_order_nos)
    total_pushed = sum(item["二次推送订单数"] for item in buckets.values())
    for bucket in buckets.values():
        auto_count = bucket["自动报价订单数"]
        pushed = bucket["二次推送订单数"]
        bucket["未二次推送订单数"] = auto_count - pushed
        bucket["二次推送率"] = pushed / auto_count if auto_count else 0
        bucket["推送分布占比"] = pushed / total_pushed if total_pushed else 0
    ranked = sorted(buckets.values(), key=lambda item: (
        -item["二次推送订单数"], -item["自动报价订单数"], item["线路"], item["routeKey"],
    ))
    pushed_routes = [item for item in ranked if item["二次推送订单数"]]
    return {
        "sales_second_bid_push_by_route": ranked,
        "sales_second_bid_push_route_count": len(pushed_routes),
        "sales_second_bid_push_single_order_route_count": sum(item["二次推送订单数"] == 1 for item in pushed_routes),
        "sales_second_bid_push_top10_order_count": sum(item["二次推送订单数"] for item in pushed_routes[:10]),
        "sales_second_bid_push_top50_order_count": sum(item["二次推送订单数"] for item in pushed_routes[:50]),
    }


def corrected_deal_contribution_metrics(
    order_count: int,
    auto_offer_non_second_bid_deal_count: int,
    bid_deal_count: int,
    second_bid_equal_deal_count: int,
    second_bid_changed_deal_count: int,
) -> dict[str, float]:
    """Attribute closed orders from each order's actual S-mode price status."""
    corrected_auto_deals = auto_offer_non_second_bid_deal_count + second_bid_equal_deal_count
    corrected_manual_deals = bid_deal_count + second_bid_changed_deal_count

    return {
        "corrected_auto_quote_deal_count": corrected_auto_deals,
        "corrected_manual_bid_deal_count": corrected_manual_deals,
        "corrected_auto_quote_deal_contribution_rate": corrected_auto_deals / order_count if order_count else 0.0,
        "corrected_manual_bid_deal_contribution_rate": corrected_manual_deals / order_count if order_count else 0.0,
    }


def corrected_quote_close_rate_metrics(
    order_count: int,
    auto_offer_order_count: int,
    auto_offer_non_second_bid_deal_count: int,
    bid_deal_count: int,
    second_bid_equal_count: int,
    second_bid_changed_count: int,
    second_bid_equal_deal_count: int,
    second_bid_changed_deal_count: int,
) -> dict[str, float]:
    """Calculate close rates from actual equal/changed S-mode orders.

    Unlike corrected contribution, this does not allocate S-mode orders by a
    price-mix ratio. Each comparable S order is assigned directly according
    to its own final price status and deal status.
    """
    corrected_auto_deals = auto_offer_non_second_bid_deal_count + second_bid_equal_deal_count
    corrected_manual_deals = bid_deal_count + second_bid_changed_deal_count
    corrected_auto_orders = max(0, auto_offer_order_count - second_bid_changed_count)
    corrected_manual_orders = max(0, order_count - auto_offer_order_count) + second_bid_changed_count

    return {
        "corrected_auto_quote_order_count": corrected_auto_orders,
        "corrected_manual_quote_order_count": corrected_manual_orders,
        "corrected_auto_quote_close_deal_count": corrected_auto_deals,
        "corrected_manual_quote_close_deal_count": corrected_manual_deals,
        "corrected_auto_quote_close_rate": (
            corrected_auto_deals / corrected_auto_orders
            if corrected_auto_orders
            else 0.0
        ),
        "corrected_manual_quote_close_rate": (
            corrected_manual_deals / corrected_manual_orders
            if corrected_manual_orders
            else 0.0
        ),
    }


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def route_key(row: dict[str, Any]) -> str:
    fields = ["startProvName", "startCityName", "endProvName", "endCityName"]
    return "|".join(clean_text(row.get(field)) for field in fields)


def route_label(key: str) -> str:
    start_prov, start_city, end_prov, end_city = (key.split("|") + ["", "", "", ""])[:4]
    return f"{start_prov}{start_city} -> {end_prov}{end_city}"


def query_time(row: dict[str, Any]) -> datetime | None:
    return parse_dt(row.get("offerTime")) or parse_dt(row.get("createTime"))


def is_deal_order(order: dict[str, Any]) -> bool:
    if parse_dt(order.get("acceptTime")) is not None:
        return True
    status = safe_int(order.get("status"))
    return status in DEAL_STATUSES if status is not None else False


def request_json(
    session: requests.Session,
    url: str,
    payload: dict[str, Any],
    retries: int = 3,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = session.post(url, json=payload, timeout=15)
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    return data
                raise RuntimeError(f"API success=false: {data}")
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < retries - 1:
                time.sleep(1.2 * (attempt + 1))
    raise RuntimeError(f"request failed for {url}: {last_error}")


def request_get_json(
    session: requests.Session,
    url: str,
    params: dict[str, Any],
    retries: int = 3,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = session.get(url, params=params, timeout=15)
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    return data
                raise RuntimeError(f"API success=false: {data}")
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < retries - 1:
                time.sleep(1.2 * (attempt + 1))
    raise RuntimeError(f"request failed for {url}: {last_error}")


def make_session() -> requests.Session:
    if not TOKEN:
        raise RuntimeError("DMS_ACCESS_TOKEN is required; configure an authorized token locally.")
    session = requests.Session()
    session.headers.update({"x-access-token": TOKEN, "Content-Type": "application/json"})
    return session


def fetch_paginated(
    session: requests.Session,
    url: str,
    base_payload: dict[str, Any],
    page_size: int = PAGE_SIZE,
) -> list[dict[str, Any]]:
    page = 1
    pages = 1
    records: list[dict[str, Any]] = []
    while page <= pages:
        payload = {**base_payload, "page": page, "pageSize": page_size}
        data = request_json(session, url, payload)
        result = data.get("result") or {}
        records.extend(result.get("records") or [])
        pages = int(result.get("pages") or 1)
        page += 1
    return records


def fetch_orders(session: requests.Session) -> list[dict[str, Any]]:
    day = ANALYSIS_DATE.strftime("%Y-%m-%d")
    return fetch_paginated(
        session,
        ORDER_URL,
        {
            "orderType": 5,
            "startDate": f"{day} 00:00:00",
            "endDate": f"{day} 23:59:59",
            "dateType": 1,
            "tabType": 7,
        },
    )


def fetch_queries(session: requests.Session) -> list[dict[str, Any]]:
    day = ANALYSIS_DATE.strftime("%Y-%m-%d")
    return fetch_paginated(
        session,
        QUERY_URL,
        {
            "queryNo": None,
            "startCreateTime": day,
            "endCreateTime": day,
        },
    )


def fetch_detail(session: requests.Session, order_no: str) -> dict[str, Any]:
    data = request_json(session, DETAIL_URL, {"orderNo": order_no})
    return data.get("result") or {}


def fetch_bid_groups(session: requests.Session, order_no: str) -> list[dict[str, Any]]:
    return fetch_paginated(
        session,
        BID_GROUP_URL,
        {"orderNo": order_no},
        page_size=100,
    )


def fetch_bid_group_carriers(session: requests.Session, bid_id: str) -> list[dict[str, Any]]:
    data = request_json(session, BID_GROUP_CARRIER_URL, {"bidId": bid_id})
    result = data.get("result") or []
    if isinstance(result, dict):
        return result.get("records") or []
    return result


def fetch_order_logs(session: requests.Session, order_id: str) -> list[dict[str, Any]]:
    data = request_get_json(session, ORDER_LOG_URL, {"orderId": order_id, "page": 1, "pageSize": 100})
    return ((data.get("result") or {}).get("records") or [])


def fetch_carrier_order(session: requests.Session, order_no: str) -> dict[str, Any]:
    data = request_json(
        session,
        CARRIER_ORDER_URL,
        {"page": 1, "pageSize": 10, "tabId": "", "orderNos": order_no, "carVins": ""},
    )
    records = ((data.get("result") or {}).get("records") or [])
    return next(
        (record for record in records if clean_text(record.get("orderNo")) == order_no),
        {},
    )


def enrich_order(
    order: dict[str, Any],
) -> tuple[
    str,
    dict[str, Any],
    list[dict[str, Any]],
    dict[str, list[dict[str, Any]]],
    list[dict[str, Any]],
    dict[str, Any],
    str,
]:
    order_no = clean_text(order.get("orderNo") or order.get("ycOrderNo"))
    order_id = clean_text(order.get("pkId"))
    session = make_session()
    detail: dict[str, Any] = {}
    bid_groups: list[dict[str, Any]] = []
    bid_group_carriers: dict[str, list[dict[str, Any]]] = {}
    order_logs: list[dict[str, Any]] = []
    carrier_order: dict[str, Any] = {}
    errors: list[str] = []
    try:
        detail = fetch_detail(session, order_no)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"detail: {exc}")
    try:
        bid_groups = fetch_bid_groups(session, order_no)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"bid_groups: {exc}")
    for group in bid_groups:
        bid_id = clean_text(group.get("pkId"))
        if not bid_id:
            continue
        try:
            bid_group_carriers[bid_id] = fetch_bid_group_carriers(session, bid_id)
        except Exception as exc:  # noqa: BLE001
            bid_group_carriers[bid_id] = []
            errors.append(f"bid_group_carriers[{bid_id}]: {exc}")
    if order_id:
        try:
            order_logs = fetch_order_logs(session, order_id)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"order_logs: {exc}")
    else:
        errors.append("order_logs: missing order pkId")
    bid_mode = clean_text(detail.get("bidMode")) or clean_text(order.get("bidMode"))
    if is_deal_order(order) and bid_mode == "S":
        try:
            carrier_order = fetch_carrier_order(session, order_no)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"carrier_order: {exc}")
    return order_no, detail, bid_groups, bid_group_carriers, order_logs, carrier_order, "; ".join(errors)


@dataclass(frozen=True)
class QueryCandidate:
    index: int
    query: dict[str, Any]
    query_time: datetime
    route: str
    car_num: int | None


def build_query_groups(queries: list[dict[str, Any]]) -> dict[str, list[QueryCandidate]]:
    groups: dict[str, list[QueryCandidate]] = defaultdict(list)
    for index, query in enumerate(queries):
        qt = query_time(query)
        if qt is None:
            continue
        key = route_key(query)
        groups[key].append(
            QueryCandidate(
                index=index,
                query=query,
                query_time=qt,
                route=key,
                car_num=safe_int(query.get("carNum")),
            )
        )
    for candidates in groups.values():
        candidates.sort(key=lambda item: item.query_time)
    return groups


def match_orders_to_queries(
    orders: list[dict[str, Any]],
    queries: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], set[int]]:
    query_groups = build_query_groups(queries)
    used_query_indexes: set[int] = set()
    matches: dict[str, dict[str, Any]] = {}

    for order in sorted(orders, key=lambda item: clean_text(item.get("createTime"))):
        order_no = clean_text(order.get("orderNo") or order.get("ycOrderNo"))
        order_time = parse_dt(order.get("createTime"))
        key = route_key(order)
        car_num = safe_int(order.get("carNum"))
        matched: QueryCandidate | None = None
        match_diff_min: float | None = None

        if order_time is not None:
            candidates = query_groups.get(key, [])
            if car_num is not None:
                same_car = [item for item in candidates if item.car_num == car_num]
                if same_car:
                    candidates = same_car

            in_window: list[tuple[float, QueryCandidate]] = []
            for candidate in candidates:
                diff = (candidate.query_time - order_time).total_seconds() / 60
                if -MATCH_WINDOW_BEFORE_MIN <= diff <= MATCH_WINDOW_AFTER_MIN:
                    in_window.append((diff, candidate))

            unused = [(diff, item) for diff, item in in_window if item.index not in used_query_indexes]
            pool = unused if unused else in_window
            if pool:
                match_diff_min, matched = min(pool, key=lambda pair: abs(pair[0]))
                used_query_indexes.add(matched.index)

        query = matched.query if matched else {}
        matches[order_no] = {
            "matched": matched is not None,
            "matchDiffMin": None if match_diff_min is None else round(match_diff_min, 4),
            "query": query,
            "queryIndex": matched.index if matched else None,
        }
    return matches, used_query_indexes


def query_no_from_order_logs(logs: list[dict[str, Any]]) -> str:
    candidates: list[tuple[datetime, str]] = []
    for log in logs:
        if clean_text(log.get("operateName")) != "查价":
            continue
        match = QUERY_NO_PATTERN.search(clean_text(log.get("content")))
        timestamp = parse_dt(log.get("createTime"))
        if match and timestamp:
            candidates.append((timestamp, match.group(1)))
    return min(candidates, default=(None, ""), key=lambda item: item[0] or datetime.max)[1]


def bid_time_summary(groups: list[dict[str, Any]]) -> dict[str, str]:
    bid_times = [parse_dt(item.get("bidTime")) for item in groups]
    bid_times = [item for item in bid_times if item is not None]
    confirm_times = [
        parse_dt(item.get("modifyTime")) or parse_dt(item.get("confirmTime"))
        for item in groups
    ]
    confirm_times = [item for item in confirm_times if item is not None]
    return {
        "firstBidTime": fmt_dt(min(bid_times) if bid_times else None),
        "firstBidConfirmTime": fmt_dt(min(confirm_times) if confirm_times else None),
    }


def build_rows(
    orders: list[dict[str, Any]],
    queries: list[dict[str, Any]],
    details_by_order: dict[str, dict[str, Any]],
    bid_groups_by_order: dict[str, list[dict[str, Any]]],
    order_logs_by_order: dict[str, list[dict[str, Any]]] | None = None,
    carrier_orders_by_order: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], set[int]]:
    matches, used_query_indexes = match_orders_to_queries(orders, queries)
    query_by_no = {
        clean_text(query.get("queryNo")): (index, query)
        for index, query in enumerate(queries)
        if clean_text(query.get("queryNo"))
    }
    rows: list[dict[str, Any]] = []

    for order in sorted(orders, key=lambda item: clean_text(item.get("createTime"))):
        order_no = clean_text(order.get("orderNo") or order.get("ycOrderNo"))
        detail = details_by_order.get(order_no) or {}
        bid_groups = bid_groups_by_order.get(order_no) or []
        match = matches.get(order_no) or {}
        query = match.get("query") or {}
        matched = bool(match.get("matched"))
        logged_query_no = query_no_from_order_logs((order_logs_by_order or {}).get(order_no) or [])
        if logged_query_no in query_by_no:
            query_index, query = query_by_no[logged_query_no]
            matched = True
            used_query_indexes.add(query_index)
        is_offer = safe_int(query.get("isOffer")) == 1 if matched else False
        deal = is_deal_order(order)
        detail_bid_mode = clean_text(detail.get("bidMode"))
        order_bid_mode = clean_text(order.get("bidMode"))
        bid_mode = detail_bid_mode or order_bid_mode
        bid_times = bid_time_summary(bid_groups)
        order_time = parse_dt(order.get("createTime"))
        distance_km = normalized_distance_km(order.get("distance"), detail.get("distance"))

        rows.append(
            {
                "date": order_time.strftime("%Y-%m-%d") if order_time else "",
                "orderNo": order_no,
                "createTime": clean_text(order.get("createTime")),
                "acceptTime": clean_text(order.get("acceptTime")),
                "status": safe_int(order.get("status")),
                "statusText": clean_text(order.get("statusText")),
                "isDeal": 1 if deal else 0,
                "bidMode": bid_mode,
                "bidModeName": {"A": "自动报价", "B": "运力竞价", "S": "运力二次竞价"}.get(bid_mode, ""),
                "sourceRetailName": clean_text(order.get("sourceRetailName")),
                "custOwnerName": clean_text(order.get("custOwnerName")),
                "route": route_label(route_key(order)),
                "routeKey": route_key(order),
                "carNum": safe_int(order.get("carNum")),
                "distanceKm": distance_km,
                "distanceBand": distance_band(distance_km),
                "queryMatched": 1 if matched else 0,
                "matchDiffMin": match.get("matchDiffMin"),
                "queryNo": clean_text(query.get("queryNo")),
                "queryMatchSource": "order_log" if logged_query_no in query_by_no else "route_time",
                "autoOfferTime": clean_text(query.get("offerTime") or query.get("createTime")),
                "isAutoOffer": 1 if is_offer else 0,
                "offerType": clean_text(query.get("offerType")).lower(),
                "autoOfferAmt": safe_float(query.get("totalRoundAmt")),
                "autoTrunkAmt": first_present_float(query.get("freightAmt"), query.get("trunkAmt")),
                "hasBidGroup": 1 if bid_groups else 0,
                "bidGroupCount": len(bid_groups),
                "firstBidTime": bid_times["firstBidTime"],
                "firstBidConfirmTime": bid_times["firstBidConfirmTime"],
                "orderAmount": safe_float(order.get("orderAmount")),
                "basePayableAmt": safe_float(order.get("basePayableAmt")),
                "guaranteeAmt": safe_float(order.get("guaranteeAmt")),
                "carrierOrderProfitAmt": first_present_float(
                    (carrier_orders_by_order or {}).get(order_no, {}).get("profitAmt")
                ),
            }
        )
    return rows, used_query_indexes


def summarize(
    rows: list[dict[str, Any]],
    queries: list[dict[str, Any]],
    used_query_indexes: set[int],
    bid_groups_by_order: dict[str, list[dict[str, Any]]] | None = None,
    bid_group_carriers_by_order: dict[str, dict[str, list[dict[str, Any]]]] | None = None,
    order_logs_by_order: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    order_count = len(rows)
    matched_count = sum(row["queryMatched"] for row in rows)
    auto_offer_count = sum(row["isAutoOffer"] for row in rows)
    deal_count = sum(row["isDeal"] for row in rows)
    auto_offer_deal_count = sum(1 for row in rows if row["isDeal"] and row["bidMode"] == "A")
    auto_offer_direct_deal_count = sum(
        1 for row in rows if row["isAutoOffer"] and row["isDeal"] and row["bidMode"] == "A"
    )
    bid_deal_count = sum(1 for row in rows if row["isDeal"] and row["bidMode"] == "B")
    second_bid_deal_count = sum(1 for row in rows if row["isDeal"] and row["bidMode"] == "S")
    auto_offer_orders_deal_count = sum(1 for row in rows if row["isAutoOffer"] and row["isDeal"])
    bid_order_count = sum(1 for row in rows if row["hasBidGroup"])
    direct_offer_count = sum(1 for row in rows if row["isAutoOffer"] and row["offerType"] == "direct")
    pass_offer_count = sum(1 for row in rows if row["isAutoOffer"] and row["offerType"] == "pass")

    by_channel = []
    channels = sorted({row["sourceRetailName"] or "未知" for row in rows})
    for channel in channels:
        channel_rows = [row for row in rows if (row["sourceRetailName"] or "未知") == channel]
        total = len(channel_rows)
        by_channel.append(
            {
                "渠道": channel,
                "下单数量": total,
                "自动报价订单数量": sum(row["isAutoOffer"] for row in channel_rows),
                "全自动报价订单数量": full_auto_quote_metrics(channel_rows)["full_auto_offer_order_count"],
                "成单数量": sum(row["isDeal"] for row in channel_rows),
                "运力竞价订单数量": sum(row["hasBidGroup"] for row in channel_rows),
            }
        )

    bid_mode_counts = Counter(row["bidMode"] or "空" for row in rows if row["isDeal"])
    route_count = len({row["routeKey"] for row in rows})
    auto_offer_route_count = len({row["routeKey"] for row in rows if row["isAutoOffer"]})
    query_extra_count = max(0, len(queries) - len(used_query_indexes))
    second_bid = second_bid_metrics(
        rows,
        bid_groups_by_order or {},
        bid_group_carriers_by_order or {},
    )
    corrected_contribution = corrected_deal_contribution_metrics(
        order_count,
        sum(1 for row in rows if row["isAutoOffer"] and row["isDeal"] and row["bidMode"] == "A"),
        bid_deal_count,
        second_bid["second_bid_equal_deal_count"],
        second_bid["second_bid_changed_deal_count"],
    )
    manual_bid_order_count = sum(1 for row in rows if row["bidMode"] in {"B", "S"})
    direct_manual_bid_order_count = sum(1 for row in rows if row["bidMode"] == "B")
    auto_offer_non_second_bid_deal_count = sum(
        1 for row in rows if row["isAutoOffer"] and row["isDeal"] and row["bidMode"] == "A"
    )
    corrected_close_rates = corrected_quote_close_rate_metrics(
        order_count,
        auto_offer_count,
        auto_offer_non_second_bid_deal_count,
        bid_deal_count,
        second_bid["second_bid_equal_count"],
        second_bid["second_bid_changed_count"],
        second_bid["second_bid_equal_deal_count"],
        second_bid["second_bid_changed_deal_count"],
    )
    manual_bid_deal_count = bid_deal_count + second_bid_deal_count
    diff_rows = bid_auto_diff_rows(
        rows,
        bid_groups_by_order or {},
        bid_group_carriers_by_order or {},
    )
    second_bid_rows = [row for row in rows if row["bidMode"] == "S"]
    auto_without_second_bid_rows = [row for row in rows if row["isAutoOffer"] and row["bidMode"] != "S"]
    profit_by_quote_mode = quote_mode_profit_metrics(
        rows,
        bid_groups_by_order or {},
        bid_group_carriers_by_order or {},
    )
    sales_push_totals, sales_push_by_owner, sales_push_details = sales_second_bid_push_metrics(
        rows,
        order_logs_by_order or {},
        bid_groups_by_order or {},
        bid_group_carriers_by_order or {},
    )

    return {
        "date": ANALYSIS_DATE.strftime("%Y-%m-%d"),
        "order_count": order_count,
        "query_record_count": len(queries),
        "matched_query_order_count": matched_count,
        "unmatched_order_count": order_count - matched_count,
        "query_extra_record_count": query_extra_count,
        "auto_offer_order_count": auto_offer_count,
        **full_auto_quote_metrics(rows),
        "direct_auto_offer_order_count": direct_offer_count,
        "pass_auto_offer_order_count": pass_offer_count,
        "deal_order_count": deal_count,
        "auto_offer_deal_count": auto_offer_deal_count,
        "bid_deal_count": bid_deal_count,
        "second_bid_deal_count": second_bid_deal_count,
        "manual_bid_order_count": manual_bid_order_count,
        "direct_manual_bid_order_count": direct_manual_bid_order_count,
        "auto_offer_non_second_bid_deal_count": auto_offer_non_second_bid_deal_count,
        "manual_bid_deal_count": manual_bid_deal_count,
        "auto_offer_orders_deal_count": auto_offer_orders_deal_count,
        "bid_order_count": bid_order_count,
        "auto_offer_rate": auto_offer_count / order_count if order_count else 0,
        "deal_rate": deal_count / order_count if order_count else 0,
        # The A-mode count is retained for the deal-method breakdown. The
        # customer-facing conversion only includes orders that both received
        # an automatic quote and closed directly with bidMode=A.
        "auto_offer_deal_rate": auto_offer_direct_deal_count / auto_offer_count if auto_offer_count else 0,
        "auto_offer_direct_deal_count": auto_offer_direct_deal_count,
        "auto_offer_final_deal_rate": auto_offer_orders_deal_count / auto_offer_count if auto_offer_count else 0,
        "auto_quote_close_rate": auto_offer_direct_deal_count / auto_offer_count if auto_offer_count else 0,
        "manual_bid_close_rate": manual_bid_deal_count / manual_bid_order_count if manual_bid_order_count else 0,
        "auto_quote_deal_contribution_rate": auto_offer_deal_count / order_count if order_count else 0,
        "manual_bid_deal_contribution_rate": manual_bid_deal_count / order_count if order_count else 0,
        "second_bid_rate": second_bid["second_bid_order_count"] / auto_offer_count if auto_offer_count else 0,
        "query_match_rate": matched_count / order_count if order_count else 0,
        "auto_offer_orders_final_deal_rate": auto_offer_orders_deal_count / auto_offer_count if auto_offer_count else 0,
        "route_count": route_count,
        "auto_offer_route_count": auto_offer_route_count,
        "bid_mode_counts_for_deals": dict(bid_mode_counts),
        "by_channel": by_channel,
        "bid_auto_diff_start_province_distribution": province_distribution(diff_rows, 0),
        "bid_auto_diff_end_province_distribution": province_distribution(diff_rows, 1),
        "second_bid_start_province_distribution": province_distribution(second_bid_rows, 0),
        "second_bid_end_province_distribution": province_distribution(second_bid_rows, 1),
        "auto_without_second_bid_start_province_distribution": province_distribution(auto_without_second_bid_rows, 0),
        "auto_without_second_bid_end_province_distribution": province_distribution(auto_without_second_bid_rows, 1),
        "profit_by_quote_mode": profit_by_quote_mode,
        "sales_second_bid_push_by_owner": sales_push_by_owner,
        **distance_second_bid_push_metrics(rows, sales_push_details),
        **route_second_bid_push_metrics(rows, sales_push_details),
        **second_bid,
        **corrected_contribution,
        **corrected_close_rates,
        **sales_push_totals,
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_report(summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    unmatched = [row for row in rows if not row["queryMatched"]]
    bid_orders = [row for row in rows if row["hasBidGroup"]]
    first_create = min((row["createTime"] for row in rows if row["createTime"]), default="")
    last_create = max((row["createTime"] for row in rows if row["createTime"]), default="")
    first_offer = min((row["autoOfferTime"] for row in rows if row["isAutoOffer"] and row["autoOfferTime"]), default="")
    last_offer = max((row["autoOfferTime"] for row in rows if row["isAutoOffer"] and row["autoOfferTime"]), default="")
    first_bid = min((row["firstBidTime"] for row in bid_orders if row["firstBidTime"]), default="")
    last_bid = max((row["firstBidTime"] for row in bid_orders if row["firstBidTime"]), default="")

    metric_rows = [
        ("下单数量", summary["order_count"], "订单列表 createTime 在当天"),
        ("自动报价订单数量", summary["auto_offer_order_count"], f"自动报价率 {pct(summary['auto_offer_rate'])}"),
        ("全自动报价订单数量", summary["full_auto_offer_order_count"], f"全自动报价率 {pct(summary['full_auto_offer_rate'])}；命中自动报价且 bidMode!=S，不要求成单"),
        ("成单数量", summary["deal_order_count"], f"成单率 {pct(summary['deal_rate'])}"),
        ("自动报价方式成单数量", summary["auto_offer_deal_count"], "已成单且 bidMode=A"),
        ("自动报价直接成单数量", summary["auto_offer_direct_deal_count"], "命中自动报价、直接以 bidMode=A 成单"),
        ("运力二次竞价订单数", summary["second_bid_order_count"], "bidMode=S 且自动报价干线价不为空"),
        (
            "销售手动推送二次竞价订单数",
            summary.get("sales_second_bid_push_order_count", 0),
            "自动报价命中且日志为推送运力竞价、操作人非系统；同订单当天多次推送只计 1 单",
        ),
        ("二次竞价占比", pct(summary["second_bid_rate"]), "运力二次竞价订单数 / 自动报价订单数量"),
        ("二次竞价标记异常订单数", summary["second_bid_mark_anomaly_count"], "bidMode=S 但自动报价干线价为空或未命中"),
        ("运力竞价订单数量", summary["bid_order_count"], "有竞价组记录的订单数"),
        ("自动报价方式成单贡献率", pct(summary["auto_quote_deal_contribution_rate"]), "bidMode=A 成单数 / 全部订单数"),
        ("人工竞价方式成单贡献率", pct(summary["manual_bid_deal_contribution_rate"]), "bidMode=B/S 成单数 / 全部订单数"),
        (
            "自动报价方式成单贡献率（修正）",
            pct(summary["corrected_auto_quote_deal_contribution_rate"]),
            "自动报价命中且非 S 成单 + S 持平成单，再除以全部订单数",
        ),
        (
            "人工竞价方式成单贡献率（修正）",
            pct(summary["corrected_manual_bid_deal_contribution_rate"]),
            "B 成单 + S 价格变化成单，再除以全部订单数",
        ),
        (
            "自动报价成单率（修正）",
            pct(summary["corrected_auto_quote_close_rate"]),
            "自动报价修正成单数 /（自动报价订单数 - S 价格变化订单数）",
        ),
        (
            "人工报价成单率（修正）",
            pct(summary["corrected_manual_quote_close_rate"]),
            "人工报价修正成单数 /（未命中自动报价订单数 + S 价格变化订单数）",
        ),
    ]

    def distribution_lines(title: str, items: list[dict[str, Any]]) -> list[str]:
        output = ["", f"### {title}", "", "| 省份 | 订单数 | 占比 |", "| --- | ---: | ---: |"]
        if not items:
            output.append("| 无 | 0 | 0.00% |")
            return output
        for item in items[:10]:
            output.append(f"| {item['province']} | {item['count']} | {pct(item['rate'])} |")
        return output

    def profit_lines() -> list[str]:
        profit = summary.get("profit_by_quote_mode") or {}
        labels = [("自动报价利润", profit.get("auto_quote") or {}), ("手动报价利润", profit.get("manual_quote") or {})]
        output = [
            "",
            "## 销售利润分析",
            "",
            "利润=销售价格-确认运力竞价成本；仅统计有确认竞价组的成单订单。",
            "",
            "| 类型 | 订单数 | 销售额 | 运力成本 | 总利润 | 单均利润 | 利润率 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for label, item in labels:
            output.append(
                f"| {label} | {int(item.get('order_count', 0))} | {float(item.get('sales_amount', 0)):.0f} | "
                f"{float(item.get('carrier_cost', 0)):.0f} | {float(item.get('total_profit', 0)):.0f} | "
                f"{float(item.get('avg_profit', 0)):.0f} | {pct(float(item.get('profit_rate', 0)))} |"
            )
        return output

    lines = [
        f"# {ANALYSIS_DATE:%Y-%m-%d} 汽车托运订单自动报价分析",
        "",
        "## 核心指标",
        "",
        "| 指标 | 数值 | 说明 |",
        "| --- | ---: | --- |",
    ]
    for name, value, desc in metric_rows:
        lines.append(f"| {name} | {value} | {desc} |")

    lines.extend(
        [
            "",
            "## 时间范围",
            "",
            f"- 下单时间：{first_create} ~ {last_create}",
            f"- 自动报价时间：{first_offer or '无'} ~ {last_offer or '无'}",
            f"- 运力竞价时间：{first_bid or '无'} ~ {last_bid or '无'}",
            "",
            "## 成单方式",
            "",
            "| 成单方式 | 数量 |",
            "| --- | ---: |",
            f"| 自动报价成单 A | {summary['auto_offer_deal_count']} |",
            f"| 运力竞价成单 B | {summary['bid_deal_count']} |",
            f"| 运力二次竞价成单 S | {summary['second_bid_deal_count']} |",
            "",
            "## 运力二次竞价价格变化",
            "",
            "| 指标 | 订单数 | 占运力二次竞价订单数 |",
            "| --- | ---: | ---: |",
            f"| 推送后持平 | {summary['second_bid_equal_count']} | {pct(summary['second_bid_equal_rate'])} |",
            f"| 推送后变化 | {summary['second_bid_changed_count']} | {pct(summary['second_bid_changed_rate'])} |",
            f"| 推送后价格变高 | {summary['second_bid_higher_count']} | {pct(summary['second_bid_higher_rate'])} |",
            f"| 推送后价格变低 | {summary['second_bid_lower_count']} | {pct(summary['second_bid_lower_rate'])} |",
            f"| 暂不可比 | {summary['second_bid_uncomparable_count']} | {pct(summary['second_bid_uncomparable_rate'])} |",
            "",
            "## 销售手动推送二次竞价",
            "",
            "仅统计自动报价命中订单中，当天由非系统操作人执行“推送运力竞价”的订单；按订单归属销售汇总。同一订单当天多次推送仅计 1 单。",
            "总订单数为当天归属该销售的全部订单；二次推送率 = 二次推送订单数 / 自动报价订单数。未二次推送订单数仅统计自动报价订单。",
            "",
            "| 销售 | 总订单数 | 自动报价订单数 | 二次推送订单数 | 二次推送率 | 未二次推送订单数 | 持平 | 价格增高 | 价格降低 | 暂不可比 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    sales_push_rows = summary.get("sales_second_bid_push_by_owner") or []
    if sales_push_rows:
        for item in sales_push_rows:
            lines.append(
                f"| {item['销售']} | {item['总订单数']} | {item['自动报价订单数']} | {item['推送订单数']} | "
                f"{pct(item['二次推送率']) if item['自动报价订单数'] else '-'} | {item['未二次推送订单数']} | "
                f"{item['持平']} | {item['价格增高']} | "
                f"{item['价格降低']} | {item['暂不可比']} |"
            )
    else:
        lines.append("| 无 | 0 | 0 | 0 | - | 0 | 0 | 0 | 0 | 0 |")
    lines.extend([
        "", "## 订单公里数与二次推送", "",
        "公里数取订单列表 distance，缺失或无效时取订单详情 distance，单位为公里；空值、非正数或非有限数归为公里数未知。以本次订单快照为准，不代表推送时刻的历史距离。",
        "二次推送沿用销售手动推送口径。推送率 = 区间内二次推送订单数 / 区间内自动报价订单数；推送分布占比 = 区间内二次推送订单数 / 全部销售手动二次推送订单数。",
        "", "| 公里数区间 | 总订单 | 自动报价订单 | 二次推送订单 | 未二次推送订单 | 二次推送率 | 推送分布占比 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for item in summary.get("sales_second_bid_push_by_distance", []):
        lines.append(
            f"| {item['公里数区间']} | {item['总订单数']} | {item['自动报价订单数']} | "
            f"{item['二次推送订单数']} | {item['未二次推送订单数']} | "
            f"{pct(item['二次推送率']) if item['自动报价订单数'] else '-'} | "
            f"{pct(item['推送分布占比']) if summary.get('sales_second_bid_push_order_count') else '-'} |"
        )
    lines.extend([
        "", "## 二次推送线路分布 Top50", "",
        "按四个省市字段完全匹配、区分方向；按二次推送订单数降序，同单量按自动报价订单数降序。",
        "推送率 = 该线路二次推送订单 / 该线路自动报价订单；分布占比以当天全部手动二次推送订单为分母。自动报价样本不足5单的线路仅作线索观察。",
        "", "| 线路 | 总订单 | 自动报价订单 | 二次推送订单 | 未二次推送订单 | 推送率 | 推送分布占比 | 样本 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ])
    for item in [row for row in summary.get("sales_second_bid_push_by_route", []) if row["二次推送订单数"]][:50]:
        lines.append(
            f"| {item['线路']} | {item['总订单数']} | {item['自动报价订单数']} | "
            f"{item['二次推送订单数']} | {item['未二次推送订单数']} | {pct(item['二次推送率'])} | "
            f"{pct(item['推送分布占比'])} | {'样本较少' if item['自动报价订单数'] < 5 else '-'} |"
        )
    lines.extend(["", f"全部线路明细：`sales_second_bid_push_routes_{DATE_COMPACT}.csv`。", "", "## 省份分布"])
    lines.extend(distribution_lines("运力竞价与自动报价有差异：始发省", summary["bid_auto_diff_start_province_distribution"]))
    lines.extend(distribution_lines("运力竞价与自动报价有差异：目的省", summary["bid_auto_diff_end_province_distribution"]))
    lines.extend(distribution_lines("运力二次竞价：始发省", summary["second_bid_start_province_distribution"]))
    lines.extend(distribution_lines("运力二次竞价：目的省", summary["second_bid_end_province_distribution"]))
    lines.extend(distribution_lines("自动报价未二次竞价：始发省", summary["auto_without_second_bid_start_province_distribution"]))
    lines.extend(distribution_lines("自动报价未二次竞价：目的省", summary["auto_without_second_bid_end_province_distribution"]))
    lines.extend(profit_lines())

    lines.extend(
        [
            "",
            "## 渠道汇总",
            "",
            "| 渠道 | 下单数量 | 自动报价订单数量 | 全自动报价订单数量 | 全自动报价率 | 成单数量 | 运力竞价订单数量 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for item in summary["by_channel"]:
        lines.append(
            f"| {item['渠道']} | {item['下单数量']} | {item['自动报价订单数量']} | "
            f"{item['全自动报价订单数量']} | {pct(item['全自动报价订单数量'] / item['下单数量'] if item['下单数量'] else 0)} | "
            f"{item['成单数量']} | {item['运力竞价订单数量']} |"
        )

    lines.extend(
        [
            "",
            "## 明细文件",
            "",
            f"- `matched_orders_{DATE_COMPACT}.csv`：订单级匹配、成单方式、自动报价时间、竞价时间明细。",
            f"- `sales_second_bid_push_{DATE_COMPACT}.csv`：销售手动推送订单及价格比较明细。",
            f"- `summary_{DATE_COMPACT}.json`：汇总指标机器可读版本。",
        ]
    )

    if unmatched:
        lines.extend(["", "## 未匹配订单", "", "| 订单号 | 下单时间 | 线路 | 车辆数 |", "| --- | --- | --- | ---: |"])
        for row in unmatched[:20]:
            lines.append(f"| {row['orderNo']} | {row['createTime']} | {row['route']} | {row['carNum']} |")
        if len(unmatched) > 20:
            lines.append(f"| ... | ... | 另有 {len(unmatched) - 20} 单见 CSV | ... |")

    (OUT_DIR / f"{DATE_SHORT}_汽车托运订单自动报价分析.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = make_session()

    orders = fetch_orders(session)
    queries = fetch_queries(session)
    print(f"fetched orders={len(orders)}, query_records={len(queries)}", flush=True)

    details_by_order: dict[str, dict[str, Any]] = {}
    bid_groups_by_order: dict[str, list[dict[str, Any]]] = {}
    bid_group_carriers_by_order: dict[str, dict[str, list[dict[str, Any]]]] = {}
    order_logs_by_order: dict[str, list[dict[str, Any]]] = {}
    carrier_orders_by_order: dict[str, dict[str, Any]] = {}
    enrich_errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        future_map = {executor.submit(enrich_order, order): order for order in orders}
        for index, future in enumerate(as_completed(future_map), start=1):
            order_no, detail, bid_groups, bid_group_carriers, order_logs, carrier_order, error = future.result()
            details_by_order[order_no] = detail
            bid_groups_by_order[order_no] = bid_groups
            bid_group_carriers_by_order[order_no] = bid_group_carriers
            order_logs_by_order[order_no] = order_logs
            if carrier_order:
                carrier_orders_by_order[order_no] = carrier_order
            if error:
                enrich_errors[order_no] = error
            if index % 50 == 0 or index == len(orders):
                print(f"enriched {index}/{len(orders)} orders", flush=True)

    rows, used_query_indexes = build_rows(
        orders,
        queries,
        details_by_order,
        bid_groups_by_order,
        order_logs_by_order,
        carrier_orders_by_order,
    )
    summary = summarize(
        rows,
        queries,
        used_query_indexes,
        bid_groups_by_order,
        bid_group_carriers_by_order,
        order_logs_by_order,
    )
    _, _, sales_push_details = sales_second_bid_push_metrics(
        rows,
        order_logs_by_order,
        bid_groups_by_order,
        bid_group_carriers_by_order,
    )
    unmatched_rows = [row for row in rows if not row["queryMatched"]]

    (OUT_DIR / f"raw_orders_{DATE_COMPACT}.json").write_text(json.dumps(orders, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / f"raw_query_records_{DATE_COMPACT}.json").write_text(json.dumps(queries, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / f"raw_order_details_{DATE_COMPACT}.json").write_text(json.dumps(details_by_order, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / f"raw_bid_groups_{DATE_COMPACT}.json").write_text(json.dumps(bid_groups_by_order, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / f"raw_bid_group_carriers_{DATE_COMPACT}.json").write_text(json.dumps(bid_group_carriers_by_order, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / f"raw_order_logs_{DATE_COMPACT}.json").write_text(json.dumps(order_logs_by_order, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / f"raw_carrier_orders_{DATE_COMPACT}.json").write_text(json.dumps(carrier_orders_by_order, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / f"enrich_errors_{DATE_COMPACT}.json").write_text(json.dumps(enrich_errors, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / f"matched_orders_{DATE_COMPACT}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / f"summary_{DATE_COMPACT}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(OUT_DIR / f"matched_orders_{DATE_COMPACT}.csv", rows)
    write_csv(OUT_DIR / f"unmatched_orders_{DATE_COMPACT}.csv", unmatched_rows)
    write_csv(OUT_DIR / f"sales_second_bid_push_{DATE_COMPACT}.csv", sales_push_details)
    write_csv(OUT_DIR / f"sales_second_bid_push_routes_{DATE_COMPACT}.csv", summary["sales_second_bid_push_by_route"])
    write_report(summary, rows)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"outputs: {OUT_DIR}")


if __name__ == "__main__":
    main()
