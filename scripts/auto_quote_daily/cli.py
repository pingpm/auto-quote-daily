"""Portable, credential-free DMS auto-quotation daily analysis CLI."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import requests


DEFAULT_BASE_URL = "https://dms.iyunche.com"
MATCH_WINDOW_BEFORE = timedelta(minutes=5)
MATCH_WINDOW_AFTER = timedelta(minutes=30)
DEAL_STATUSES = {2, 3, 4}
PAGE_SIZE = 1000
PROJECT_ROOT = Path(os.environ.get("AUTO_QUOTE_WORKSPACE", Path.cwd())).expanduser().resolve()


def clean(value: Any) -> str:
    return "" if value is None else str(value).replace("\u3000", " ").strip()


def as_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def as_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def parse_time(value: Any) -> datetime | None:
    value = clean(value)
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, pattern)
        except ValueError:
            continue
    return None


def percent(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def percent_text(value: float) -> str:
    return f"{value * 100:.1f}%"


def load_local_env() -> dict[str, str]:
    """Read only the per-user config file; never read a checkout .env file."""
    config_root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    path = config_root / "auto-quote-daily" / ".env"
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def settings() -> tuple[str, str]:
    local = load_local_env()
    token = clean(os.environ.get("DMS_ACCESS_TOKEN") or local.get("DMS_ACCESS_TOKEN"))
    base_url = clean(os.environ.get("DMS_BASE_URL") or local.get("DMS_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    if not token:
        raise RuntimeError(
            "DMS_ACCESS_TOKEN is not configured. Ask the authorized user to copy x-access-token "
            "from Chrome DevTools > Network > a DMS request > Headers, then set it locally."
        )
    return token, base_url


class DmsClient:
    def __init__(self) -> None:
        token, base_url = settings()
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({"x-access-token": token, "Content-Type": "application/json"})

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self.session.post(f"{self.base_url}{path}", json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            raise RuntimeError(f"DMS request failed for {path}: {exc}") from exc
        except ValueError as exc:
            raise RuntimeError(f"DMS returned a non-JSON response for {path}") from exc
        if not data.get("success"):
            message = clean(data.get("message")) or f"code {data.get('code', 'unknown')}"
            raise RuntimeError(f"DMS rejected {path}: {message}")
        return data

    def paged(self, path: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        page = 1
        # Use returned row counts instead of the unreliable `pages` field seen in some DMS responses.
        while True:
            response = self.post(path, {**payload, "page": page, "pageSize": PAGE_SIZE})
            result = response.get("result") or {}
            batch = result.get("records") or []
            if not isinstance(batch, list):
                raise RuntimeError(f"Unexpected records shape from {path}")
            records.extend(item for item in batch if isinstance(item, dict))
            if len(batch) < PAGE_SIZE:
                return records
            page += 1
            if page > 1000:
                raise RuntimeError(f"Pagination safety limit reached for {path}")

    def orders(self, analysis_date: date) -> list[dict[str, Any]]:
        day = analysis_date.isoformat()
        return self.paged(
            "/dms-boot/order/toRetail/getOrderList",
            {
                "orderType": 5,
                "startDate": f"{day} 00:00:00",
                "endDate": f"{day} 23:59:59",
                "dateType": 1,
                "tabType": 7,
            },
        )

    def queries(self, analysis_date: date) -> list[dict[str, Any]]:
        day = analysis_date.isoformat()
        return self.paged(
            "/dms-boot/autoPrice/getQueryList",
            {"queryNo": None, "startCreateTime": day, "endCreateTime": day},
        )


def route_key(row: dict[str, Any]) -> str:
    return "|".join(clean(row.get(key)) for key in ("startProvName", "startCityName", "endProvName", "endCityName"))


def route_label(key: str) -> str:
    start_prov, start_city, end_prov, end_city = (key.split("|") + ["", "", "", ""])[:4]
    return f"{start_prov}{start_city} -> {end_prov}{end_city}"


def is_deal(order: dict[str, Any]) -> bool:
    return parse_time(order.get("acceptTime")) is not None or as_int(order.get("status")) in DEAL_STATUSES


def normalize_orders(orders: list[dict[str, Any]], queries: list[dict[str, Any]], analysis_date: date) -> tuple[list[dict[str, Any]], set[int]]:
    query_index: dict[tuple[str, int | None], list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for index, query in enumerate(queries):
        query_index[(route_key(query), as_int(query.get("carNum")))].append((index, query))

    used_queries: set[int] = set()
    normalized: list[dict[str, Any]] = []
    for order in orders:
        order_time = parse_time(order.get("createTime"))
        candidates: list[tuple[timedelta, int, dict[str, Any]]] = []
        for index, query in query_index[(route_key(order), as_int(order.get("carNum")))]:
            if index in used_queries or order_time is None:
                continue
            candidate_time = parse_time(query.get("offerTime")) or parse_time(query.get("createTime"))
            if candidate_time is None or not order_time - MATCH_WINDOW_BEFORE <= candidate_time <= order_time + MATCH_WINDOW_AFTER:
                continue
            candidates.append((abs(candidate_time - order_time), index, query))
        matched_query: dict[str, Any] | None = None
        matched_diff: float | None = None
        if candidates:
            delta, query_id, matched_query = min(candidates, key=lambda item: item[0])
            used_queries.add(query_id)
            matched_diff = round(delta.total_seconds() / 60, 2)

        key = route_key(order)
        auto_offer = bool(matched_query and as_int(matched_query.get("isOffer")) == 1)
        mode = clean(order.get("bidMode"))
        normalized.append(
            {
                "date": analysis_date.isoformat(),
                "orderNo": clean(order.get("orderNo") or order.get("ycOrderNo")),
                "createTime": clean(order.get("createTime")),
                "acceptTime": clean(order.get("acceptTime")),
                "status": as_int(order.get("status")),
                "statusText": clean(order.get("statusText")),
                "isDeal": is_deal(order),
                "bidMode": mode,
                "sourceRetailName": clean(order.get("sourceRetailName")) or "未标注渠道",
                "route": route_label(key),
                "routeKey": key,
                "carNum": as_int(order.get("carNum")),
                "queryMatched": matched_query is not None,
                "matchDiffMin": matched_diff,
                "queryNo": clean(matched_query.get("queryNo")) if matched_query else "",
                "autoOfferTime": clean(matched_query.get("offerTime") or matched_query.get("createTime")) if matched_query else "",
                "isAutoOffer": auto_offer,
                "offerType": clean(matched_query.get("offerType")) if matched_query else "",
                "autoOfferAmt": as_float(matched_query.get("totalRoundAmt")) if auto_offer else 0.0,
                "autoTrunkAmt": as_float(matched_query.get("freightAmt") or matched_query.get("trunkAmt")) if auto_offer else 0.0,
            }
        )
    return normalized, used_queries


def channel_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, int]] = defaultdict(lambda: {"order_count": 0, "query_matched_count": 0, "auto_offer_count": 0, "deal_count": 0})
    for row in rows:
        bucket = buckets[row["sourceRetailName"]]
        bucket["order_count"] += 1
        bucket["query_matched_count"] += int(bool(row["queryMatched"]))
        bucket["auto_offer_count"] += int(bool(row["isAutoOffer"]))
        bucket["deal_count"] += int(bool(row["isDeal"]))
    result = []
    for channel, bucket in buckets.items():
        total = bucket["order_count"]
        result.append({"channel": channel, **bucket, "query_coverage_rate": percent(bucket["query_matched_count"], total), "auto_offer_rate": percent(bucket["auto_offer_count"], total), "deal_rate": percent(bucket["deal_count"], total)})
    return sorted(result, key=lambda item: (-item["order_count"], item["channel"]))


def route_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, int]] = defaultdict(lambda: {"order_count": 0, "auto_offer_count": 0, "auto_offer_miss_count": 0})
    for row in rows:
        bucket = buckets[row["route"]]
        bucket["order_count"] += 1
        bucket["auto_offer_count"] += int(bool(row["isAutoOffer"]))
        bucket["auto_offer_miss_count"] += int(bool(row["queryMatched"]) and not bool(row["isAutoOffer"]))
    return sorted(({"route": route, **bucket, "auto_offer_rate": percent(bucket["auto_offer_count"], bucket["order_count"])} for route, bucket in buckets.items()), key=lambda item: (-item["order_count"], item["route"]))


def summarize(rows: list[dict[str, Any]], query_count: int, used_queries: set[int], analysis_date: date) -> dict[str, Any]:
    order_count = len(rows)
    query_matched_count = sum(bool(row["queryMatched"]) for row in rows)
    auto_offer_count = sum(bool(row["isAutoOffer"]) for row in rows)
    deal_count = sum(bool(row["isDeal"]) for row in rows)
    routes = route_rows(rows)
    return {
        "date": analysis_date.isoformat(),
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "order_count": order_count,
        "query_record_count": query_count,
        "matched_query_order_count": query_matched_count,
        "unmatched_order_count": order_count - query_matched_count,
        "query_extra_record_count": query_count - len(used_queries),
        "auto_offer_order_count": auto_offer_count,
        "auto_offer_miss_order_count": query_matched_count - auto_offer_count,
        "deal_order_count": deal_count,
        "query_match_rate": percent(query_matched_count, order_count),
        "auto_offer_rate": percent(auto_offer_count, order_count),
        "auto_offer_rate_among_queried": percent(auto_offer_count, query_matched_count),
        "deal_rate": percent(deal_count, order_count),
        "route_count": len(routes),
        "auto_offer_route_count": sum(row["auto_offer_count"] > 0 for row in routes),
        "by_channel": channel_rows(rows),
        "top_routes": routes[:20],
    }


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(rows[0]) if rows else ["orderNo"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def build_report(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [
        f"# {summary['date']} 汽车托运自动报价日报",
        "",
        "## 核心结论",
        f"- 当天下单 {summary['order_count']} 单，自动报价命中 {summary['auto_offer_order_count']} 单，命中率 {percent_text(summary['auto_offer_rate'])}。",
        f"- 已进入系统查价 {summary['matched_query_order_count']} 单，覆盖率 {percent_text(summary['query_match_rate'])}；已查价未命中 {summary['auto_offer_miss_order_count']} 单。",
        f"- 订单涉及 {summary['route_count']} 条线路，其中自动报价覆盖 {summary['auto_offer_route_count']} 条。",
        f"- 成单 {summary['deal_order_count']} 单，成单率 {percent_text(summary['deal_rate'])}。",
        "",
        "## 总体指标",
        "",
        "| 指标 | 数值 |",
        "| --- | ---: |",
    ]
    for label, value in (("下单数量", summary["order_count"]), ("进入系统查价", summary["matched_query_order_count"]), ("系统查价覆盖率", percent_text(summary["query_match_rate"])), ("自动报价命中", summary["auto_offer_order_count"]), ("自动报价命中率", percent_text(summary["auto_offer_rate"])), ("自动报价未命中", summary["auto_offer_miss_order_count"]), ("未进入系统查价", summary["unmatched_order_count"]), ("成单数量", summary["deal_order_count"])):
        lines.append(f"| {label} | {value} |")
    lines.extend(["", "## 按渠道汇总", "", "| 渠道 | 下单 | 查价覆盖率 | 自动报价命中 | 自动报价率 | 成单 |", "| --- | ---: | ---: | ---: | ---: | ---: |"])
    for item in summary["by_channel"]:
        lines.append(f"| {item['channel']} | {item['order_count']} | {percent_text(item['query_coverage_rate'])} | {item['auto_offer_count']} | {percent_text(item['auto_offer_rate'])} | {item['deal_count']} |")
    misses = [row for row in route_rows(rows) if row["auto_offer_miss_count"]]
    lines.extend(["", "## 自动报价未命中线路", "", "| 线路 | 订单数 | 未命中订单 |", "| --- | ---: | ---: |"])
    for item in misses[:20]:
        lines.append(f"| {item['route']} | {item['order_count']} | {item['auto_offer_miss_count']} |")
    lines.extend(["", "## 分析口径", "", "以散户订单为主表；查价记录按完全一致省市线路、车辆数和下单前 5 分钟至后 30 分钟时间窗口匹配。查价表额外记录只作审计披露，未计入核心指标。"])
    return "\n".join(lines) + "\n"


def output_folder(output_dir: Path, analysis_date: date) -> Path:
    return output_dir / f"{analysis_date.strftime('%m%d')}_api_analysis"


def project_scripts() -> dict[str, Path]:
    runtime = Path(__file__).resolve().parent / "runtime"
    scripts = {
        "analysis": runtime / "analyze_0708_api_metrics.py",
        "line_updates": runtime / "analyze_auto_bid_line_updates.py",
        "dashboard": runtime / "build_0708_visual_dashboard.py",
        "weekly": runtime / "build_weekly_visual_dashboard.py",
        "diagnostics": runtime / "anomaly_diagnostics.py",
    }
    missing = [str(path) for path in scripts.values() if not path.is_file()]
    if missing:
        raise RuntimeError(
            f"The installed reporting runtime is incomplete; reinstall auto-quote-daily. Missing: {', '.join(missing)}"
        )
    return scripts


def project_environment(analysis_date: date, *, fetch: bool = True) -> dict[str, str]:
    environment = os.environ.copy()
    if fetch:
        token, base_url = settings()
        environment["DMS_ACCESS_TOKEN"] = token
        environment["DMS_BASE_URL"] = base_url
    environment["ANALYSIS_DATE"] = analysis_date.isoformat()
    environment["AUTO_QUOTE_WORKSPACE"] = str(PROJECT_ROOT)
    return environment


def run_project_script(script: Path, environment: dict[str, str]) -> None:
    PROJECT_ROOT.mkdir(parents=True, exist_ok=True)
    module = f"auto_quote_daily.runtime.{script.stem}"
    subprocess.run([sys.executable, "-m", module], cwd=PROJECT_ROOT, env=environment, check=True)


def ensure_complete(analysis_date: date) -> None:
    folder = output_folder(PROJECT_ROOT / "outputs", analysis_date)
    required = ("summary", "matched_orders", "raw_bid_groups", "raw_bid_group_carriers", "enrich_errors")
    for stem in required:
        path = folder / f"{stem}_{analysis_date:%Y%m%d}.json"
        if not path.is_file():
            raise RuntimeError(f"Missing snapshot: {path}. Refresh this date before building the report.")
    errors = json.loads((folder / f"enrich_errors_{analysis_date:%Y%m%d}.json").read_text(encoding="utf-8"))
    if errors:
        raise RuntimeError(f"Collection has {len(errors)} enrichment errors for {analysis_date}. Resolve them before reporting.")


def run_rebuild(args: argparse.Namespace) -> int:
    analysis_date = date.fromisoformat(args.date)
    ensure_complete(analysis_date)
    run_project_script(project_scripts()["dashboard"], project_environment(analysis_date, fetch=False))
    return 0


def run_diagnose(args: argparse.Namespace) -> int:
    analysis_date = date.fromisoformat(args.date)
    ensure_complete(analysis_date)
    run_project_script(project_scripts()["diagnostics"], project_environment(analysis_date))
    return run_rebuild(args)


def run_rebuild_weekly(args: argparse.Namespace) -> int:
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end) if args.end else start + timedelta(days=6)
    if end < start:
        raise ValueError("--end must be on or after --start")
    for offset in range((end - start).days + 1):
        ensure_complete(start + timedelta(days=offset))
    environment = project_environment(end, fetch=False)
    environment["WEEK_START"] = start.isoformat()
    environment["WEEK_END"] = end.isoformat()
    run_project_script(project_scripts()["weekly"], environment)
    return 0


def run_daily(args: argparse.Namespace) -> int:
    analysis_date = date.fromisoformat(args.date)
    scripts = project_scripts()
    environment = project_environment(analysis_date)
    run_project_script(scripts["analysis"], environment)
    ensure_complete(analysis_date)
    run_project_script(scripts["line_updates"], environment)
    run_project_script(scripts["dashboard"], environment)
    folder = PROJECT_ROOT / "outputs" / f"{analysis_date:%m%d}_api_analysis"
    dashboard = folder / f"{analysis_date:%m%d}_visual_dashboard.html"
    print(json.dumps({"date": args.date, "output": str(folder), "dashboard": str(dashboard),
                      "analysis_context": str(folder / f"operational_analysis_context_{analysis_date:%Y%m%d}.json"),
                      "operational_analysis": str(folder / f"operational_analysis_{analysis_date:%Y%m%d}.json")}, ensure_ascii=False, indent=2))
    return 0


def run_weekly(args: argparse.Namespace) -> int:
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end) if args.end else start + timedelta(days=6)
    if end < start:
        raise ValueError("--end must be on or after --start")
    scripts = project_scripts()
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        environment = project_environment(day)
        run_project_script(scripts["analysis"], environment)
        ensure_complete(day)
        run_project_script(scripts["line_updates"], environment)
        run_project_script(scripts["dashboard"], environment)
    environment = project_environment(end)
    environment["WEEK_START"] = start.isoformat()
    environment["WEEK_END"] = end.isoformat()
    run_project_script(scripts["weekly"], environment)
    if start == end:
        output = PROJECT_ROOT / "outputs" / f"{start:%Y%m%d}_daily_dashboard" / f"{start:%m%d}_日报看板.html"
    else:
        output = PROJECT_ROOT / "outputs" / f"{start:%Y%m%d}_{end:%Y%m%d}_weekly_analysis" / f"{start:%m%d}_{end:%m%d}_weekly_dashboard.html"
    print(json.dumps({"start": start.isoformat(), "end": end.isoformat(), "dashboard": str(output)}, ensure_ascii=False, indent=2))
    return 0


def load_analysis(output_dir: Path, analysis_date: date) -> tuple[dict[str, Any], list[dict[str, Any]], Path]:
    folder = output_folder(output_dir, analysis_date)
    compact = analysis_date.strftime("%Y%m%d")
    try:
        summary = json.loads((folder / f"summary_{compact}.json").read_text(encoding="utf-8"))
        rows = json.loads((folder / f"matched_orders_{compact}.json").read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"No local analysis for {analysis_date}. Run `auto-quote daily --date {analysis_date}` first.") from exc
    return summary, rows, folder


def answer_question(summary: dict[str, Any], rows: list[dict[str, Any]], question: str) -> dict[str, Any]:
    question = clean(question)
    if any(term in question for term in ("渠道", "channel")):
        ranking = channel_rows(rows)
        metric = "auto_offer_rate"
        if "成单" in question:
            metric = "deal_rate"
        ordered = sorted(ranking, key=lambda item: (item[metric], item["channel"])) if any(term in question for term in ("最低", "最差", "lowest")) else sorted(ranking, key=lambda item: (-item[metric], item["channel"]))
        lead = ordered[0] if ordered else None
        return {"answer": f"{lead['channel']} 的{('成单率' if metric == 'deal_rate' else '自动报价率')}为 {percent_text(lead[metric])}。" if lead else "当日没有渠道数据。", "data": ordered}
    if "未命中" in question or "没报价" in question:
        ranked = sorted((item for item in route_rows(rows) if item["auto_offer_miss_count"]), key=lambda item: (-item["auto_offer_miss_count"], item["route"]))
        miss_count = summary.get("auto_offer_miss_order_count", sum(item["auto_offer_miss_count"] for item in ranked))
        return {"answer": f"已查价未命中 {miss_count} 单。", "data": ranked[:20]}
    if "线路" in question or "route" in question:
        return {"answer": f"当天涉及 {summary['route_count']} 条线路。", "data": route_rows(rows)[:20]}
    if "成单" in question or "成交" in question:
        return {"answer": f"当天成单 {summary['deal_order_count']} 单，成单率 {percent_text(summary['deal_rate'])}。", "data": {key: summary[key] for key in ("order_count", "deal_order_count", "deal_rate")}}
    return {"answer": f"当天共下单 {summary['order_count']} 单，自动报价命中 {summary['auto_offer_order_count']} 单，命中率 {percent_text(summary['auto_offer_rate'])}。", "data": {key: summary[key] for key in ("order_count", "matched_query_order_count", "auto_offer_order_count", "auto_offer_rate", "deal_order_count", "deal_rate")}}


def run_ask(args: argparse.Namespace) -> int:
    analysis_date = date.fromisoformat(args.date)
    summary, rows, folder = load_analysis(PROJECT_ROOT / "outputs", analysis_date)
    answer = answer_question(summary, rows, args.question)
    print(json.dumps({"date": args.date, "question": args.question, "source": str(folder), **answer}, ensure_ascii=False, indent=2))
    return 0


def run_query(args: argparse.Namespace) -> int:
    analysis_date = date.fromisoformat(args.date)
    summary, rows, folder = load_analysis(PROJECT_ROOT / "outputs", analysis_date)
    if args.group_by == "channel":
        data: Any = channel_rows(rows)[: args.limit]
    elif args.group_by == "route":
        data = route_rows(rows)[: args.limit]
    else:
        data = summary
    print(json.dumps({"date": args.date, "source": str(folder), "data": data}, ensure_ascii=False, indent=2))
    return 0


def run_auth_check(args: argparse.Namespace) -> int:
    analysis_date = date.fromisoformat(args.date)
    client = DmsClient()
    # Small read-only request: success proves the token can access the retail order endpoint.
    client.post("/dms-boot/order/toRetail/getOrderList", {"page": 1, "pageSize": 1, "orderType": 5, "startDate": f"{analysis_date} 00:00:00", "endDate": f"{analysis_date} 23:59:59", "dateType": 1, "tabType": 7})
    print(json.dumps({"ok": True, "message": "DMS token accepted for a read-only retail-order request."}, ensure_ascii=False))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="auto-quote", description="DMS auto-quotation daily and weekly analysis")
    parser.add_argument("--workspace", type=Path, default=PROJECT_ROOT,
                        help="Writable data directory (default: AUTO_QUOTE_WORKSPACE or current directory)")
    subparsers = parser.add_subparsers(dest="command", required=True)
    today = date.today().isoformat()
    auth = subparsers.add_parser("auth-check", help="Validate the locally configured DMS token")
    auth.add_argument("--date", default=today)
    daily = subparsers.add_parser("daily", help="Refresh one day and generate its dashboard")
    daily.add_argument("--date", required=True)
    rebuild = subparsers.add_parser("rebuild", help="Rebuild a daily dashboard from local snapshots without API requests")
    rebuild.add_argument("--date", required=True)
    diagnose = subparsers.add_parser("diagnose", help="Fetch evidence for the top price anomalies, then rebuild")
    diagnose.add_argument("--date", required=True)
    weekly = subparsers.add_parser("weekly", help="Refresh each day in a period and generate a weekly dashboard")
    weekly.add_argument("--start", required=True)
    weekly.add_argument("--end", help="Inclusive end date; defaults to six days after --start")
    cached_weekly = subparsers.add_parser("rebuild-weekly", help="Rebuild a period from complete local snapshots without fetching")
    cached_weekly.add_argument("--start", required=True)
    cached_weekly.add_argument("--end", help="Inclusive end date; defaults to six days after --start")
    ask = subparsers.add_parser("ask", help="Answer a common natural-language question from local artifacts")
    ask.add_argument("--date", required=True)
    ask.add_argument("--question", required=True)
    query = subparsers.add_parser("query", help="Return deterministic aggregate data for an agent")
    query.add_argument("--date", required=True)
    query.add_argument("--group-by", choices=("summary", "channel", "route"), default="summary")
    query.add_argument("--limit", type=int, default=20)
    return parser.parse_args()


def main() -> None:
    global PROJECT_ROOT
    args = parse_args()
    PROJECT_ROOT = args.workspace.expanduser().resolve()
    try:
        if args.command == "auth-check":
            result = run_auth_check(args)
        elif args.command == "daily":
            result = run_daily(args)
        elif args.command == "weekly":
            result = run_weekly(args)
        elif args.command == "rebuild":
            result = run_rebuild(args)
        elif args.command == "rebuild-weekly":
            result = run_rebuild_weekly(args)
        elif args.command == "diagnose":
            result = run_diagnose(args)
        elif args.command == "ask":
            result = run_ask(args)
        else:
            result = run_query(args)
    except (RuntimeError, ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2) from exc
    raise SystemExit(result)


if __name__ == "__main__":
    main()
