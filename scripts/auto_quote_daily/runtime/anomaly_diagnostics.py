from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from . import build_0708_visual_dashboard as dashboard
from .analyze_0708_api_metrics import TOKEN


ROOT = Path(os.environ.get("AUTO_QUOTE_WORKSPACE", Path.cwd())).expanduser().resolve()
BASE_URL = os.environ.get("DMS_BASE_URL", "https://dms.iyunche.com").rstrip("/")
ORDER_LOG_URL = f"{BASE_URL}/dms-boot/order/getOrderLog"
QUERY_DETAIL_URL = f"{BASE_URL}/dms-boot/autoPrice/getQueryDetail"
LINE_LIST_URL = f"{BASE_URL}/dms-boot/autoBidLine/getLineList"
LINE_PRICE_LIST_URL = f"{BASE_URL}/dms-boot/autoBidLine/getLinePriceList"

ANALYSIS_DATE = datetime.strptime(os.environ.get("ANALYSIS_DATE", "2026-07-14"), "%Y-%m-%d")
DATE_COMPACT = ANALYSIS_DATE.strftime("%Y%m%d")
DATE_SHORT = ANALYSIS_DATE.strftime("%m%d")
OUT_DIR = ROOT / "outputs" / f"{DATE_SHORT}_api_analysis"
TOP_N = int(os.environ.get("ANOMALY_TOP_N", "10"))


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\u3000", " ").strip()


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def make_session() -> requests.Session:
    if not TOKEN:
        raise RuntimeError("DMS_ACCESS_TOKEN is required; configure an authorized token locally.")
    session = requests.Session()
    session.headers.update({"x-access-token": TOKEN, "Content-Type": "application/json"})
    return session


def request_post_json(session: requests.Session, url: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = session.post(url, json=payload, timeout=20)
    response.raise_for_status()
    data = response.json()
    if not data.get("success"):
        raise RuntimeError(f"API success=false: {data}")
    return data


def request_get_json(session: requests.Session, url: str, params: dict[str, Any]) -> dict[str, Any]:
    response = session.get(url, params=params, timeout=20)
    response.raise_for_status()
    data = response.json()
    if not data.get("success"):
        raise RuntimeError(f"API success=false: {data}")
    return data


def fetch_order_logs(session: requests.Session, order_id: str) -> list[dict[str, Any]]:
    data = request_get_json(session, ORDER_LOG_URL, {"orderId": order_id, "page": 1, "pageSize": 100})
    return ((data.get("result") or {}).get("records") or [])


def fetch_query_detail(session: requests.Session, query_pkid: str) -> dict[str, Any]:
    data = request_post_json(session, QUERY_DETAIL_URL, {"pkId": query_pkid})
    return data.get("result") or {}


def fetch_line_list(session: requests.Session, line_no: str) -> list[dict[str, Any]]:
    data = request_post_json(
        session,
        LINE_LIST_URL,
        {"lineNo": line_no, "page": 1, "pageSize": 10, "linePriceNo": None},
    )
    return ((data.get("result") or {}).get("records") or [])


def fetch_line_price_list(session: requests.Session, line_id: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    page = 1
    pages = 1
    while page <= pages:
        data = request_post_json(
            session,
            LINE_PRICE_LIST_URL,
            {
                "lineId": line_id,
                "page": page,
                "pageSize": 100,
                "sortRules": "3",
                "linePriceNo": "",
            },
        )
        result = data.get("result") or {}
        records.extend(result.get("records") or [])
        pages = int(result.get("pages") or 1)
        page += 1
    return records


def select_top_anomalies(comparison: dict[str, Any], limit: int = TOP_N) -> list[dict[str, Any]]:
    return sorted(
        [item for item in comparison.get("details", []) if abs(float(item.get("diff") or 0)) >= 100],
        key=lambda item: abs(float(item.get("diff") or 0)),
        reverse=True,
    )[:limit]


def relevant_edit_logs(order_logs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        log
        for log in order_logs
        if clean_text(log.get("operateName")) == "编辑订单"
        and any(keyword in clean_text(log.get("content")) for keyword in ["运输方式", "起始", "目的", "提车方式", "送车方式"])
    ]


def find_transport_mode_change(order_logs: list[dict[str, Any]]) -> dict[str, Any] | None:
    for log in sorted(relevant_edit_logs(order_logs), key=lambda item: clean_text(item.get("createTime"))):
        content = clean_text(log.get("content"))
        if "运输方式" in content and "大板" in content and "小板" in content:
            return log
    return None


def find_route_change(order_logs: list[dict[str, Any]]) -> dict[str, Any] | None:
    route_keywords = ["起始地", "始发", "目的地", "到达", "发车城市", "到达城市"]
    for log in sorted(relevant_edit_logs(order_logs), key=lambda item: clean_text(item.get("createTime"))):
        content = clean_text(log.get("content"))
        if any(keyword in content for keyword in route_keywords):
            return log
    return None


def compact_log_evidence(log: dict[str, Any]) -> str:
    content = re.sub(r"\s+", " ", clean_text(log.get("content")))
    if len(content) > 140:
        content = content[:137] + "..."
    return f"{clean_text(log.get('createTime'))} {clean_text(log.get('createUserName'))} {clean_text(log.get('operateName'))}：{content}"


def query_bid_lines(query_detail: dict[str, Any]) -> list[dict[str, Any]]:
    return query_detail.get("queryBidList") or []


def hit_line_price_no(query_detail: dict[str, Any]) -> str:
    lines = query_bid_lines(query_detail)
    return clean_text(lines[0].get("linePriceNo")) if lines else ""


def hit_line_no(query_detail: dict[str, Any]) -> str:
    lines = query_bid_lines(query_detail)
    return clean_text(lines[0].get("lineNo")) if lines else ""


def hit_line_unit_price(query_detail: dict[str, Any]) -> float | None:
    lines = query_bid_lines(query_detail)
    return safe_float(lines[0].get("unitPrice")) if lines else None


def line_price_time(row: dict[str, Any]) -> datetime:
    return parse_dt(row.get("dataTime")) or parse_dt(row.get("modifyTime")) or parse_dt(row.get("createTime")) or datetime.min


def line_price_time_text(row: dict[str, Any]) -> str:
    return clean_text(row.get("modifyTime") or row.get("dataTime") or row.get("createTime"))


def line_price_user(row: dict[str, Any]) -> str:
    return clean_text(row.get("modifyUserName") or row.get("createUserName") or "-")


def sorted_line_prices(line_prices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(line_prices, key=line_price_time, reverse=True)


def find_hit_neighbor_prices(line_prices: list[dict[str, Any]], line_price_no: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    ordered = sorted_line_prices(line_prices)
    for index, item in enumerate(ordered):
        if clean_text(item.get("linePriceNo")) == line_price_no:
            newer = ordered[index - 1] if index > 0 else None
            older = ordered[index + 1] if index + 1 < len(ordered) else None
            return item, newer, older
    return None, None, None


def quote_time(anomaly: dict[str, Any], query_detail: dict[str, Any]) -> datetime | None:
    query_info = query_detail.get("queryInfo") or {}
    return (
        parse_dt(anomaly.get("autoOfferTime"))
        or parse_dt(query_info.get("offerTime"))
        or parse_dt(query_info.get("createTime"))
    )


def price_freshness(anomaly: dict[str, Any], query_detail: dict[str, Any], hit: dict[str, Any] | None) -> str:
    if not hit:
        return "未取得命中子线路更新时间"
    qt = quote_time(anomaly, query_detail)
    ht = line_price_time(hit)
    if not qt or ht == datetime.min:
        return "命中价格更新时间或自动报价时间缺失"
    age_days = (qt - ht).days
    if age_days > 30:
        return f"命中价格距自动报价 {age_days} 天未更新，超过30天，需结合线路价格波动频率判断"
    if age_days >= 0:
        return f"命中价格距自动报价 {age_days} 天，未超过30天"
    return "命中价格时间晚于自动报价时间，需复核数据时间"


def later_updates_text(line_prices: list[dict[str, Any]], hit: dict[str, Any] | None, limit: int = 3) -> str:
    if not hit:
        return "未取得命中子线路，无法判断后续更新"
    hit_time = line_price_time(hit)
    if hit_time == datetime.min:
        return "命中子线路更新时间缺失，无法判断后续更新"
    later = [item for item in sorted_line_prices(line_prices) if line_price_time(item) > hit_time]
    if not later:
        return "后续无更新记录"
    parts = []
    for item in later[:limit]:
        price = safe_float(item.get("unitPrice"))
        price_text = f"{price:g} 元" if price is not None else "价格未知"
        parts.append(f"{price_text}，{line_price_time_text(item) or '时间未知'}，更新人 {line_price_user(item)}")
    if len(later) > limit:
        parts.append(f"另有 {len(later) - limit} 条")
    return "；".join(parts)


def price_text(value: float | None) -> str:
    return f"{value:g} 元" if value is not None else "价格未知"


def current_line_price_context(anomaly: dict[str, Any], line_prices: list[dict[str, Any]], hit: dict[str, Any] | None) -> dict[str, str]:
    bid_price = safe_float(anomaly.get("leftAmt"))
    latest = sorted_line_prices(line_prices)[0] if line_prices else None
    latest_price = safe_float((latest or {}).get("unitPrice"))
    hit_price = safe_float((hit or {}).get("unitPrice"))

    if not latest:
        return {
            "currentLinePriceStatus": "无法判断",
            "currentLinePriceEvidence": "分析时未取得线路库价格列表，无法判断当前最新报价与订单竞价是否一致。",
            "currentLinePriceSuggestion": "建议人工查询线路库最新价格后再判断是否需要更新。",
        }
    if bid_price is None or latest_price is None:
        return {
            "currentLinePriceStatus": "无法判断",
            "currentLinePriceEvidence": "订单竞价或分析时线路库最新价缺失，无法判断当前最新报价与订单竞价是否一致。",
            "currentLinePriceSuggestion": "建议补齐订单竞价和线路库价格后复核。",
        }

    evidence_parts = [
        f"分析时最新价 {price_text(latest_price)}",
        f"更新时间 {line_price_time_text(latest) or '未知'}",
        f"更新人 {line_price_user(latest)}",
        f"订单竞价 {price_text(bid_price)}",
    ]
    if hit_price is not None:
        evidence_parts.append(f"自动报价命中价 {price_text(hit_price)}")
    evidence = "；".join(evidence_parts)

    if abs(latest_price - bid_price) < 0.01:
        return {
            "currentLinePriceStatus": "已调整且与竞价一致",
            "currentLinePriceEvidence": evidence,
            "currentLinePriceSuggestion": "线路库已修正，建议观察后续同线路命中情况。",
        }
    if hit_price is not None and abs(latest_price - hit_price) < 0.01:
        return {
            "currentLinePriceStatus": "当前仍未修正",
            "currentLinePriceEvidence": evidence,
            "currentLinePriceSuggestion": "建议优先更新该线路库价格。",
        }
    return {
        "currentLinePriceStatus": "已调整但仍有差异",
        "currentLinePriceEvidence": evidence,
        "currentLinePriceSuggestion": "建议复核分析时最新线路价是否符合当前运力成本。",
    }


def with_incomparable_line_price_context(price_context: dict[str, str], status: str, suggestion: str) -> dict[str, str]:
    return {
        **price_context,
        "currentLinePriceStatus": status,
        "currentLinePriceSuggestion": suggestion,
    }


def diagnose_line_price_change(query_detail: dict[str, Any], line_prices: list[dict[str, Any]]) -> dict[str, str] | None:
    line_price_no = hit_line_price_no(query_detail)
    if not line_price_no:
        return None
    hit, newer, older = find_hit_neighbor_prices(line_prices, line_price_no)
    if not hit:
        return {
            "causeCode": "line_price_evidence_missing",
            "diagnosis": "未在线路价格列表中找到命中的子线路",
            "evidence": f"命中子线路 {line_price_no}，但线路价格列表未返回该记录。",
        }

    hit_price = safe_float(hit.get("unitPrice"))
    newer_price = safe_float((newer or {}).get("unitPrice"))
    older_price = safe_float((older or {}).get("unitPrice"))
    parts = [
        f"命中子线路 {line_price_no} 价格 {hit_price:g}" if hit_price is not None else f"命中子线路 {line_price_no}",
        f"更新时间 {line_price_time_text(hit) or '未知'}",
        f"更新人 {line_price_user(hit)}",
    ]
    if older:
        parts.append(f"前一条较旧价格 {older_price:g}" if older_price is not None else "前一条较旧价格未知")
    if newer:
        parts.append(f"后一条较新价格 {newer_price:g}" if newer_price is not None else "后一条较新价格未知")
    evidence = "；".join(parts)
    extra = {
        "priceFreshness": price_freshness({}, query_detail, hit),
        "laterUpdates": later_updates_text(line_prices, hit),
    }

    if (
        hit_price is not None
        and newer_price is not None
        and older_price is not None
        and abs(newer_price - older_price) < 0.01
        and abs(hit_price - newer_price) >= 100
    ):
        return {
            "causeCode": "line_price_spike_reverted",
            "diagnosis": "疑似线路价格误操作后修正",
            "evidence": evidence,
            **extra,
        }

    if newer and hit_price is not None and newer_price is not None and abs(hit_price - newer_price) >= 100:
        return {
            "causeCode": "line_price_adjusted_after_quote",
            "diagnosis": "自动报价后线路价格已有调整",
            "evidence": evidence,
            **extra,
        }

    return {
        "causeCode": "line_price_stable_or_unclear",
        "diagnosis": "线路价格变化证据不明显",
        "evidence": evidence,
        **extra,
    }


def diagnose_anomaly(
    anomaly: dict[str, Any],
    order_logs: list[dict[str, Any]],
    query_detail: dict[str, Any],
    line_prices: list[dict[str, Any]],
) -> dict[str, Any]:
    line_price_no = hit_line_price_no(query_detail)
    hit, _, _ = find_hit_neighbor_prices(line_prices, line_price_no) if line_price_no else (None, None, None)
    price_context = {
        "priceFreshness": price_freshness(anomaly, query_detail, hit),
        "laterUpdates": later_updates_text(line_prices, hit),
        **current_line_price_context(anomaly, line_prices, hit),
    }

    transport_log = find_transport_mode_change(order_logs)
    if transport_log:
        transport_context = with_incomparable_line_price_context(
            price_context,
            "运输方式口径不一致",
            "订单已由大板改小板，大板线路库最新价与小板竞价不直接对比；建议按订单修改后的运输方式重新查价或人工复核。",
        )
        return {
            "orderNo": anomaly.get("orderNo"),
            "causeCode": "transport_mode_changed",
            "diagnosis": "订单运输方式变化：大板改为小板，自动报价与竞价口径不一致",
            "evidence": compact_log_evidence(transport_log),
            **transport_context,
        }

    route_log = find_route_change(order_logs)
    if route_log:
        route_context = with_incomparable_line_price_context(
            price_context,
            "线路口径不一致",
            "订单起始地或目的地已变化，命中线路库最新价与竞价线路可能不一致；建议按修改后的线路重新查价或人工复核。",
        )
        return {
            "orderNo": anomaly.get("orderNo"),
            "causeCode": "route_changed",
            "diagnosis": "订单起始地或目的地发生变化，自动报价与竞价线路可能不一致",
            "evidence": compact_log_evidence(route_log),
            **route_context,
        }

    line_result = diagnose_line_price_change(query_detail, line_prices)
    if line_result:
        line_result.update(price_context)
        return {"orderNo": anomaly.get("orderNo"), **line_result}

    return {
        "orderNo": anomaly.get("orderNo"),
        "causeCode": "evidence_insufficient",
        "diagnosis": "证据不足，需人工复核",
        "evidence": "未发现影响干线价的订单编辑日志，且未取得有效线路价格变化证据。",
        **price_context,
    }


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def build_anomalies_for_date() -> list[dict[str, Any]]:
    rows = load_json(OUT_DIR / f"matched_orders_{DATE_COMPACT}.json")
    bid_groups = load_json(OUT_DIR / f"raw_bid_groups_{DATE_COMPACT}.json")
    bid_group_carriers = load_json(OUT_DIR / f"raw_bid_group_carriers_{DATE_COMPACT}.json")
    full_comparison = dashboard.build_price_comparison(rows, bid_groups, bid_group_carriers)
    anomalies_by_order: dict[str, dict[str, Any]] = {}
    for anomaly in select_top_anomalies(full_comparison, TOP_N):
        anomalies_by_order[clean_text(anomaly.get("orderNo"))] = anomaly
    return sorted(
        anomalies_by_order.values(),
        key=lambda item: abs(float(item.get("diff") or 0)),
        reverse=True,
    )


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    anomalies = build_anomalies_for_date()
    details_by_order = load_json(OUT_DIR / f"raw_order_details_{DATE_COMPACT}.json")
    query_records = load_json(OUT_DIR / f"raw_query_records_{DATE_COMPACT}.json")
    query_pkid_by_no = {clean_text(item.get("queryNo")): clean_text(item.get("pkId")) for item in query_records}
    matched_rows = load_json(OUT_DIR / f"matched_orders_{DATE_COMPACT}.json")
    query_no_by_order = {clean_text(item.get("orderNo")): clean_text(item.get("queryNo")) for item in matched_rows}

    session = make_session()
    logs_path = OUT_DIR / f"raw_order_logs_{DATE_COMPACT}.json"
    raw_order_logs: dict[str, list[dict[str, Any]]] = load_json(logs_path) if logs_path.exists() else {}
    raw_query_details: dict[str, dict[str, Any]] = {}
    raw_line_lists: dict[str, list[dict[str, Any]]] = {}
    raw_line_price_lists: dict[str, list[dict[str, Any]]] = {}
    diagnostics: list[dict[str, Any]] = []

    for index, anomaly in enumerate(anomalies, start=1):
        order_no = clean_text(anomaly.get("orderNo"))
        print(f"diagnosing {index}/{len(anomalies)} {order_no}", flush=True)
        detail = details_by_order.get(order_no) or {}
        order_id = clean_text(detail.get("pkId") or detail.get("ycOrderId"))
        logs: list[dict[str, Any]] = []
        query_detail: dict[str, Any] = {}
        line_prices: list[dict[str, Any]] = []
        errors: list[str] = []

        if order_id:
            try:
                logs = fetch_order_logs(session, order_id)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"order_logs: {exc}")
        else:
            errors.append("order_logs: missing order id")
        if logs or order_no not in raw_order_logs:
            raw_order_logs[order_no] = logs

        query_no = query_no_by_order.get(order_no, "")
        query_pkid = query_pkid_by_no.get(query_no, "")
        if query_pkid:
            try:
                query_detail = fetch_query_detail(session, query_pkid)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"query_detail: {exc}")
        else:
            errors.append("query_detail: missing query pkId")
        raw_query_details[order_no] = query_detail

        line_no = hit_line_no(query_detail)
        if line_no:
            try:
                line_list = fetch_line_list(session, line_no)
                raw_line_lists[line_no] = line_list
                line_id = clean_text((line_list[0] if line_list else {}).get("pkId"))
                if line_id:
                    line_prices = fetch_line_price_list(session, line_id)
                    raw_line_price_lists[line_no] = line_prices
                else:
                    errors.append("line_price_list: missing line pkId")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"line_price_list: {exc}")
        else:
            errors.append("line_price_list: missing lineNo")

        diagnosis = diagnose_anomaly(anomaly, logs, query_detail, line_prices)
        diagnostics.append(
            {
                **anomaly,
                "diagnosedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "queryNo": query_no,
                "lineNo": line_no,
                "linePriceNo": hit_line_price_no(query_detail),
                "lineUnitPrice": hit_line_unit_price(query_detail),
                **diagnosis,
                "errors": errors,
            }
        )

    write_json(logs_path, raw_order_logs)
    write_json(OUT_DIR / f"raw_query_details_{DATE_COMPACT}.json", raw_query_details)
    write_json(OUT_DIR / f"raw_line_lists_{DATE_COMPACT}.json", raw_line_lists)
    write_json(OUT_DIR / f"raw_line_price_lists_{DATE_COMPACT}.json", raw_line_price_lists)
    write_json(OUT_DIR / f"anomaly_diagnostics_{DATE_COMPACT}.json", diagnostics)
    print(f"wrote {OUT_DIR / f'anomaly_diagnostics_{DATE_COMPACT}.json'}")


if __name__ == "__main__":
    main()
