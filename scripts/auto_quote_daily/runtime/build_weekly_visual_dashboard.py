from __future__ import annotations

import html
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import build_0708_visual_dashboard as daily
from . import analyze_0708_api_metrics as metrics


ROOT = Path(os.environ.get("AUTO_QUOTE_WORKSPACE", Path.cwd())).expanduser().resolve()
REPORT_DATE_FORMAT = "%Y-%m-%d"


def parse_report_date(value: str) -> datetime:
    return datetime.strptime(value, REPORT_DATE_FORMAT)


def default_report_end(start: datetime) -> datetime:
    return start + timedelta(days=6)


def iter_report_days(start: datetime, end: datetime) -> list[datetime]:
    if end < start:
        raise ValueError(f"WEEK_END must be on or after WEEK_START: {start:%Y-%m-%d} > {end:%Y-%m-%d}")
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def report_period_label(start: datetime, end: datetime) -> str:
    span = (end - start).days
    if span == 6:
        return "周"
    if span == 0:
        return "日"
    return "区间"


WEEK_START = parse_report_date(os.environ.get("WEEK_START", "2026-07-06"))
WEEK_END = parse_report_date(os.environ["WEEK_END"]) if os.environ.get("WEEK_END") else default_report_end(WEEK_START)
REPORT_PERIOD_LABEL = report_period_label(WEEK_START, WEEK_END)
IS_SINGLE_DAY = (WEEK_END - WEEK_START).days == 0
if IS_SINGLE_DAY:
    OUT_DIR = ROOT / "outputs" / f"{WEEK_START:%Y%m%d}_daily_dashboard"
    OUTPUT_PATH = OUT_DIR / f"{WEEK_START:%m%d}_日报看板.html"
else:
    OUT_DIR = ROOT / "outputs" / f"{WEEK_START:%Y%m%d}_{WEEK_END:%Y%m%d}_weekly_analysis"
    OUTPUT_PATH = OUT_DIR / f"{WEEK_START:%m%d}_{WEEK_END:%m%d}_weekly_dashboard.html"


def esc(value: object) -> str:
    if value is None or value == "":
        return "-"
    return html.escape(str(value), quote=True)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\u3000", " ").strip()


def pct(value: float, digits: int = 1) -> str:
    return f"{value * 100:.{digits}f}%"


def metric_count(value: int | float) -> str:
    value = float(value)
    if value.is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def numerator_denominator(numerator: int | float, denominator: int | float) -> str:
    return f"分子 {metric_count(numerator)} / 分母 {metric_count(denominator)}"


def width(value: float, total: float) -> str:
    if total <= 0:
        return "0%"
    return f"{max(0, min(100, value / total * 100)):.3f}%"


def metric_attr(metric_id: str | None) -> str:
    return f' data-metric="{esc(metric_id)}"' if metric_id else ""


def money(value: float) -> str:
    return f"{value:,.0f}"


def signed_money(value: float) -> str:
    if value > 0:
        return f"+{money(value)}"
    return money(value)


def chart_attr(option: dict[str, Any]) -> str:
    return html.escape(json.dumps(option, ensure_ascii=False), quote=True)


def render_echart(option: dict[str, Any], extra_class: str = "") -> str:
    class_name = f"echart {extra_class}".strip()
    return f'<div class="{esc(class_name)}" data-chart="{chart_attr(option)}"></div>'


def pie_data(items: list[tuple[str, int | float]]) -> list[dict[str, Any]]:
    return [
        {"name": name, "value": round(float(value), 4)}
        for name, value in items
        if float(value) > 0
    ]


def render_pie_chart(items: list[tuple[str, int | float]], title: str = "") -> str:
    data = pie_data(items)
    if not data:
        return '<div class="empty">暂无构成数据</div>'
    return render_echart(
        {
            "color": ["#2563eb", "#0f766e", "#b45309", "#be123c", "#6d28d9", "#15803d", "#64748b", "#0891b2"],
            "tooltip": {"trigger": "item", "formatter": "{b}<br/>{c} 单 ({d}%)"},
            "legend": {"bottom": 0, "left": "center", "type": "scroll", "textStyle": {"color": "#667085"}},
            "series": [
                {
                    "name": title,
                    "type": "pie",
                    "radius": ["44%", "68%"],
                    "center": ["50%", "43%"],
                    "avoidLabelOverlap": True,
                    "label": {"formatter": "{b}\n{d}%", "color": "#344054"},
                    "labelLine": {"length": 12, "length2": 8},
                    "data": data,
                }
            ],
        },
        "pie-chart",
    )


def render_composition_legend(items: list[tuple[str, int | float, str | None]]) -> str:
    total = sum(float(value) for _, value, _ in items)
    return "\n".join(
        f"""
        <div class="composition-row"{metric_attr(metric_id)}>
          <strong>{esc(label)}</strong>
          <span>{money(float(value))} 单 / {pct(float(value) / total if total else 0)}</span>
        </div>
        """
        for label, value, metric_id in items
    )


def day_paths(day: datetime) -> dict[str, Path]:
    compact = day.strftime("%Y%m%d")
    short = day.strftime("%m%d")
    base = ROOT / "outputs" / f"{short}_api_analysis"
    return {
        "summary": base / f"summary_{compact}.json",
        "rows": base / f"matched_orders_{compact}.json",
        "bid_groups": base / f"raw_bid_groups_{compact}.json",
        "bid_group_carriers": base / f"raw_bid_group_carriers_{compact}.json",
        "errors": base / f"enrich_errors_{compact}.json",
    }


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_week_data() -> list[dict[str, Any]]:
    days: list[dict[str, Any]] = []
    for day in iter_report_days(WEEK_START, WEEK_END):
        paths = day_paths(day)
        missing = [name for name, path in paths.items() if not path.exists()]
        if missing:
            raise FileNotFoundError(f"{day:%Y-%m-%d} missing files: {', '.join(missing)}")
        errors = load_json(paths["errors"])
        if errors:
            raise RuntimeError(f"{day:%Y-%m-%d} enrich errors: {errors}")
        days.append(
            {
                "date": day.strftime("%Y-%m-%d"),
                "label": day.strftime("%m-%d"),
                "summary": load_json(paths["summary"]),
                "rows": load_json(paths["rows"]),
                "bid_groups": load_json(paths["bid_groups"]),
                "bid_group_carriers": load_json(paths["bid_group_carriers"]),
            }
        )
    return days


def load_trend_days(max_days: int = 14) -> list[dict[str, Any]]:
    """单日看板用：向前回看 max_days 天，跳过数据缺失的日期，用于趋势图。"""
    trend_days: list[dict[str, Any]] = []
    for offset in range(max_days - 1, -1, -1):
        day = WEEK_END - timedelta(days=offset)
        paths = day_paths(day)
        if any(not path.exists() for path in paths.values()):
            continue
        try:
            errors = load_json(paths["errors"])
        except (OSError, ValueError):
            continue
        if errors:
            continue
        trend_days.append(
            {
                "date": day.strftime("%Y-%m-%d"),
                "label": day.strftime("%m-%d"),
                "summary": load_json(paths["summary"]),
                "rows": load_json(paths["rows"]),
                "bid_groups": load_json(paths["bid_groups"]),
                "bid_group_carriers": load_json(paths["bid_group_carriers"]),
            }
        )
    return trend_days


def merge_distribution(days: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for day in days:
        for item in day["summary"].get(key, []):
            province = str(item.get("province") or "")
            if province:
                counter[province] += int(item.get("count", 0))
    total = sum(counter.values())
    return [
        {"province": province, "count": count, "rate": count / total if total else 0}
        for province, count in counter.most_common()
    ]


def merge_profit(days: list[dict[str, Any]]) -> dict[str, dict[str, float | int]]:
    result = {
        "auto_quote": {"order_count": 0, "sales_amount": 0.0, "carrier_cost": 0.0, "total_profit": 0.0},
        "manual_quote": {"order_count": 0, "sales_amount": 0.0, "carrier_cost": 0.0, "total_profit": 0.0},
    }
    for day in days:
        profit = day["summary"].get("profit_by_quote_mode") or {}
        for key in result:
            item = profit.get(key) or {}
            result[key]["order_count"] += int(item.get("order_count", 0))
            result[key]["sales_amount"] += float(item.get("sales_amount", 0))
            result[key]["carrier_cost"] += float(item.get("carrier_cost", 0))
            result[key]["total_profit"] += float(item.get("total_profit", 0))
    for item in result.values():
        order_count = int(item["order_count"])
        sales_amount = float(item["sales_amount"])
        total_profit = float(item["total_profit"])
        item["sales_amount"] = round(sales_amount, 2)
        item["carrier_cost"] = round(float(item["carrier_cost"]), 2)
        item["total_profit"] = round(total_profit, 2)
        item["avg_profit"] = round(total_profit / order_count, 2) if order_count else 0.0
        item["profit_rate"] = total_profit / sales_amount if sales_amount else 0.0
    return result


def aggregate_week(days: list[dict[str, Any]]) -> dict[str, Any]:
    summary_keys = [
        "order_count",
        "auto_offer_order_count",
        "deal_order_count",
        "auto_offer_deal_count",
        "auto_offer_direct_deal_count",
        "auto_offer_non_second_bid_deal_count",
        "bid_deal_count",
        "second_bid_deal_count",
        "manual_bid_order_count",
        "direct_manual_bid_order_count",
        "manual_bid_deal_count",
        "auto_offer_orders_deal_count",
        "bid_order_count",
        "query_record_count",
        "second_bid_order_count",
        "second_bid_mark_anomaly_count",
        "second_bid_comparable_count",
        "second_bid_uncomparable_count",
        "second_bid_equal_count",
        "second_bid_changed_count",
        "second_bid_higher_count",
        "second_bid_lower_count",
        "second_bid_equal_deal_count",
        "second_bid_changed_deal_count",
        "second_bid_higher_deal_count",
        "second_bid_lower_deal_count",
    ]
    totals = {}
    for key in summary_keys:
        if key == "direct_manual_bid_order_count":
            # Daily summaries generated before this field was added only have
            # B/S combined orders, so retain a correct historical fallback.
            totals[key] = sum(
                int(
                    day["summary"].get(
                        key,
                        max(
                            0,
                            int(day["summary"].get("manual_bid_order_count", 0))
                            - int(day["summary"].get("second_bid_order_count", 0)),
                        ),
                    )
                )
                for day in days
            )
        else:
            totals[key] = sum(int(day["summary"].get(key, 0)) for day in days)
    all_rows = [row for day in days for row in day["rows"]]
    totals["full_auto_offer_order_count"] = metrics.full_auto_quote_metrics(all_rows)["full_auto_offer_order_count"]
    route_count = len({row.get("routeKey") for row in all_rows if row.get("routeKey")})
    auto_route_count = len({row.get("routeKey") for row in all_rows if row.get("isAutoOffer") and row.get("routeKey")})
    totals.update(
        {
            "auto_offer_rate": totals["auto_offer_order_count"] / totals["order_count"] if totals["order_count"] else 0,
            "full_auto_offer_rate": totals["full_auto_offer_order_count"] / totals["order_count"] if totals["order_count"] else 0,
            "deal_rate": totals["deal_order_count"] / totals["order_count"] if totals["order_count"] else 0,
            "auto_offer_deal_rate": totals["auto_offer_direct_deal_count"] / totals["auto_offer_order_count"] if totals["auto_offer_order_count"] else 0,
            "auto_offer_final_deal_rate": totals["auto_offer_orders_deal_count"] / totals["auto_offer_order_count"] if totals["auto_offer_order_count"] else 0,
            "auto_quote_close_rate": totals["auto_offer_direct_deal_count"] / totals["auto_offer_order_count"] if totals["auto_offer_order_count"] else 0,
            "manual_bid_close_rate": totals["manual_bid_deal_count"] / totals["manual_bid_order_count"] if totals["manual_bid_order_count"] else 0,
            "auto_quote_deal_contribution_rate": totals["auto_offer_deal_count"] / totals["order_count"] if totals["order_count"] else 0,
            "manual_bid_deal_contribution_rate": totals["manual_bid_deal_count"] / totals["order_count"] if totals["order_count"] else 0,
            "second_bid_rate": totals["second_bid_order_count"] / totals["auto_offer_order_count"] if totals["auto_offer_order_count"] else 0,
            "second_bid_equal_rate": totals["second_bid_equal_count"] / totals["second_bid_order_count"] if totals["second_bid_order_count"] else 0,
            "second_bid_changed_rate": totals["second_bid_changed_count"] / totals["second_bid_order_count"] if totals["second_bid_order_count"] else 0,
            "second_bid_higher_rate": totals["second_bid_higher_count"] / totals["second_bid_order_count"] if totals["second_bid_order_count"] else 0,
            "second_bid_lower_rate": totals["second_bid_lower_count"] / totals["second_bid_order_count"] if totals["second_bid_order_count"] else 0,
            "second_bid_uncomparable_rate": totals["second_bid_uncomparable_count"] / totals["second_bid_order_count"] if totals["second_bid_order_count"] else 0,
            "route_count": route_count,
            "auto_offer_route_count": auto_route_count,
            "bid_auto_diff_start_province_distribution": merge_distribution(days, "bid_auto_diff_start_province_distribution"),
            "bid_auto_diff_end_province_distribution": merge_distribution(days, "bid_auto_diff_end_province_distribution"),
            "second_bid_start_province_distribution": merge_distribution(days, "second_bid_start_province_distribution"),
            "second_bid_end_province_distribution": merge_distribution(days, "second_bid_end_province_distribution"),
            "auto_without_second_bid_start_province_distribution": merge_distribution(days, "auto_without_second_bid_start_province_distribution"),
            "auto_without_second_bid_end_province_distribution": merge_distribution(days, "auto_without_second_bid_end_province_distribution"),
            "profit_by_quote_mode": merge_profit(days),
        }
    )
    totals.update(
        metrics.corrected_deal_contribution_metrics(
            totals["order_count"],
            totals["auto_offer_non_second_bid_deal_count"],
            totals["bid_deal_count"],
            totals["second_bid_equal_deal_count"],
            totals["second_bid_changed_deal_count"],
        )
    )
    totals.update(
        metrics.corrected_quote_close_rate_metrics(
            totals["order_count"],
            totals["auto_offer_order_count"],
            totals["auto_offer_non_second_bid_deal_count"],
            totals["bid_deal_count"],
            totals["second_bid_equal_count"],
            totals["second_bid_changed_count"],
            totals["second_bid_equal_deal_count"],
            totals["second_bid_changed_deal_count"],
        )
    )
    return totals


def build_day_metrics(days: list[dict[str, Any]]) -> list[dict[str, Any]]:
    day_metrics: list[dict[str, Any]] = []
    for day in days:
        summary = day["summary"]
        order_count = int(summary["order_count"])
        auto_count = int(summary["auto_offer_order_count"])
        full_auto_count = metrics.full_auto_quote_metrics(day["rows"])["full_auto_offer_order_count"]
        deal_count = int(summary["deal_order_count"])
        day_metrics.append(
            {
                "date": day["date"],
                "label": day["label"],
                "order_count": order_count,
                "auto_offer_order_count": auto_count,
                "full_auto_offer_order_count": full_auto_count,
                "full_auto_offer_rate": full_auto_count / order_count if order_count else 0,
                "deal_order_count": deal_count,
                "auto_offer_rate": auto_count / order_count if order_count else 0,
                "deal_rate": deal_count / order_count if order_count else 0,
                "auto_offer_deal_count": int(summary["auto_offer_deal_count"]),
                "bid_deal_count": int(summary["bid_deal_count"]),
                "second_bid_deal_count": int(summary["second_bid_deal_count"]),
                "second_bid_order_count": int(summary.get("second_bid_order_count", 0)),
                "second_bid_rate": float(summary.get("second_bid_rate", 0)),
                "second_bid_equal_count": int(summary.get("second_bid_equal_count", 0)),
                "second_bid_changed_count": int(summary.get("second_bid_changed_count", 0)),
                "second_bid_higher_count": int(summary.get("second_bid_higher_count", 0)),
                "second_bid_lower_count": int(summary.get("second_bid_lower_count", 0)),
            }
        )
    return day_metrics


def add_date_to_details(comparison: dict[str, Any], date_label: str) -> dict[str, Any]:
    copied = {
        "overall": dict(comparison["overall"]),
        "deal": dict(comparison["deal"]),
        "details": [],
    }
    for item in comparison["details"]:
        copied_item = dict(item)
        copied_item["date"] = date_label
        copied["details"].append(copied_item)
    return copied


def merge_comparisons(comparisons: list[dict[str, Any]]) -> dict[str, Any]:
    result = daily.empty_compare_result()
    for comparison in comparisons:
        for status in ["高于", "低于", "持平"]:
            result["overall"][status] += int(comparison["overall"][status])
            result["deal"][status] += int(comparison["deal"][status])
        result["overall"]["total"] += int(comparison["overall"]["total"])
        result["deal"]["total"] += int(comparison["deal"]["total"])
        result["details"].extend(comparison["details"])
    daily.sort_compare_details(result)
    return result


def build_week_comparisons(days: list[dict[str, Any]]) -> dict[str, Any]:
    comparisons: list[dict[str, Any]] = []
    for day in days:
        comparisons.append(
            add_date_to_details(
                daily.build_price_comparison(
                    day["rows"],
                    day["bid_groups"],
                    day["bid_group_carriers"],
                ),
                day["label"],
            )
        )
    return {
        "bid_auto": {
            "daily": comparisons,
            "weekly": merge_comparisons(comparisons),
        },
    }


def render_kpi(label: str, value: str, note: str, tone: str = "", metric_id: str | None = None) -> str:
    return f"""
    <article class="kpi {tone}"{metric_attr(metric_id)}>
      <span class="kpi-label">{esc(label)}{daily.render_metric_help(daily.metric_help_text(metric_id, note))}</span>
      <strong>{esc(value)}</strong>
      <p>{esc(note)}</p>
    </article>
    """


def render_week_second_bid_chart(weekly: dict[str, Any]) -> str:
    auto_total = int(weekly.get("auto_offer_order_count", 0))
    second_total = int(weekly.get("second_bid_order_count", 0))
    pushed_items = [
        ("二次竞价推送", second_total),
        ("未二次竞价", max(0, auto_total - second_total)),
    ]
    changed_items = [
        ("推送后持平", int(weekly.get("second_bid_equal_count", 0)), "weekly-second-bid-equal"),
        ("价格变高", int(weekly.get("second_bid_higher_count", 0)), "weekly-second-bid-higher"),
        ("价格变低", int(weekly.get("second_bid_lower_count", 0)), "weekly-second-bid-lower"),
        ("暂不可比", int(weekly.get("second_bid_uncomparable_count", 0)), "weekly-second-bid-uncomparable"),
    ]
    return f"""
    <div class="composition-grid">
      <div class="composition-card"{metric_attr("weekly-second-bid-pushed")}>
        <div class="compare-title"><strong>自动报价订单构成</strong><span>{auto_total} 单</span></div>
        {render_pie_chart(pushed_items, "自动报价订单构成")}
        <div class="composition-list">
          {render_composition_legend([("自动报价订单", auto_total, "weekly-second-bid-auto"), ("二次竞价推送订单", second_total, "weekly-second-bid-pushed")])}
        </div>
      </div>
      <div class="composition-card">
        <div class="compare-title"><strong>二次竞价后价格构成</strong><span>{second_total} 单</span></div>
        {render_pie_chart([(label, value) for label, value, _ in changed_items], "二次竞价后价格构成")}
        <div class="composition-list">
          {render_composition_legend(changed_items + [("推送后变化", int(weekly.get("second_bid_changed_count", 0)), "weekly-second-bid-changed")])}
        </div>
      </div>
    </div>
    """


def render_second_bid_push_trend(metrics: list[dict[str, Any]]) -> str:
    labels = [item["label"] for item in metrics]
    option = {
        "color": ["#0f766e", "#6d28d9", "#be123c"],
        "tooltip": {"trigger": "axis"},
        "legend": {"top": 0, "left": "center", "textStyle": {"color": "#667085"}},
        "grid": {"left": 46, "right": 48, "top": 54, "bottom": 30},
        "xAxis": {"type": "category", "boundaryGap": False, "data": labels, "axisLabel": {"color": "#667085"}},
        "yAxis": [
            {"type": "value", "name": "单量", "axisLabel": {"color": "#667085"}},
            {"type": "value", "name": "推送率", "axisLabel": {"formatter": "{value}%", "color": "#667085"}},
        ],
        "series": [
            {"name": "自动报价订单", "type": "line", "smooth": True, "symbolSize": 7, "data": [item["auto_offer_order_count"] for item in metrics]},
            {"name": "推送二次竞价订单", "type": "line", "smooth": True, "symbolSize": 7, "data": [item["second_bid_order_count"] for item in metrics]},
            {"name": "推送率", "type": "line", "smooth": True, "symbolSize": 7, "yAxisIndex": 1, "data": [round(item["second_bid_rate"] * 100, 2) for item in metrics]},
        ],
    }
    return render_echart(option, "line-chart")


def render_day_trend(metrics: list[dict[str, Any]]) -> str:
    labels = [item["label"] for item in metrics]
    option = {
        "color": ["#2563eb", "#0f766e", "#b45309", "#6d28d9", "#be123c"],
        "tooltip": {"trigger": "axis"},
        "legend": {"top": 0, "left": "center", "textStyle": {"color": "#667085"}},
        "grid": {"left": 46, "right": 48, "top": 54, "bottom": 30},
        "xAxis": {"type": "category", "boundaryGap": False, "data": labels, "axisLabel": {"color": "#667085"}},
        "yAxis": [
            {"type": "value", "name": "单量", "axisLabel": {"color": "#667085"}},
            {"type": "value", "name": "比率", "axisLabel": {"formatter": "{value}%", "color": "#667085"}},
        ],
        "series": [
            {"name": "下单", "type": "line", "smooth": True, "symbolSize": 7, "data": [item["order_count"] for item in metrics]},
            {"name": "自动报价", "type": "line", "smooth": True, "symbolSize": 7, "data": [item["auto_offer_order_count"] for item in metrics]},
            {"name": "成单", "type": "line", "smooth": True, "symbolSize": 7, "data": [item["deal_order_count"] for item in metrics]},
            {"name": "自动报价率", "type": "line", "smooth": True, "symbolSize": 7, "yAxisIndex": 1, "data": [round(item["auto_offer_rate"] * 100, 2) for item in metrics]},
            {"name": "全自动报价率", "type": "line", "smooth": True, "symbolSize": 7, "yAxisIndex": 1, "data": [round(item["full_auto_offer_rate"] * 100, 1) if item.get("full_auto_offer_rate") is not None else None for item in metrics]},
            {"name": "成单率", "type": "line", "smooth": True, "symbolSize": 7, "yAxisIndex": 1, "data": [round(item["deal_rate"] * 100, 2) for item in metrics]},
        ],
    }
    return render_echart(option, "line-chart")


def line_points(values: list[int], max_value: int, width_px: int = 680, height_px: int = 180) -> str:
    if not values:
        return ""
    top = 18
    bottom = 32
    left = 36
    plot_w = width_px - left - 16
    plot_h = height_px - top - bottom
    denom = max(1, len(values) - 1)
    points = []
    for index, value in enumerate(values):
        x = left + plot_w * index / denom
        y = top + plot_h * (1 - (value / max_value if max_value else 0))
        points.append(f"{x:.1f},{y:.1f}")
    return " ".join(points)


def render_compare_line_chart(daily_comparisons: list[dict[str, Any]], labels: list[str]) -> str:
    option = {
        "color": ["#be123c", "#15803d", "#2563eb"],
        "tooltip": {"trigger": "axis"},
        "legend": {"top": 0, "left": "center", "textStyle": {"color": "#667085"}},
        "grid": {"left": 42, "right": 24, "top": 52, "bottom": 28},
        "xAxis": {"type": "category", "boundaryGap": False, "data": labels, "axisLabel": {"color": "#667085"}},
        "yAxis": {"type": "value", "name": "单量", "axisLabel": {"color": "#667085"}},
        "series": [
            {"name": "高于", "type": "line", "smooth": True, "symbolSize": 7, "data": [int(item["overall"]["高于"]) for item in daily_comparisons]},
            {"name": "低于", "type": "line", "smooth": True, "symbolSize": 7, "data": [int(item["overall"]["低于"]) for item in daily_comparisons]},
            {"name": "持平", "type": "line", "smooth": True, "symbolSize": 7, "data": [int(item["overall"]["持平"]) for item in daily_comparisons]},
        ],
    }
    return render_echart(option, "line-chart compact-chart")


def render_compare_rows(group: dict[str, int], target_label: str) -> str:
    total = int(group["total"])
    items = [
        (f"高于{target_label}", int(group["高于"]), None),
        (f"低于{target_label}", int(group["低于"]), None),
        (f"持平{target_label}", int(group["持平"]), None),
    ]
    return f"""
    {render_pie_chart([(label, value) for label, value, _ in items], f"{target_label}构成")}
    <div class="composition-list">{render_composition_legend(items)}</div>
    """


def render_price_detail_table(details: list[dict[str, Any]], result: str) -> str:
    rows = [item for item in details if item["result"] == result]
    if not rows:
        return '<div class="empty">无明细</div>'
    table_rows = []
    for item in rows:
        deal_tag = '<span class="deal-tag">成单</span>' if item.get("isDeal") else ""
        table_rows.append(
            f"""
            <tr>
              <td>{esc(item.get("date"))}</td>
              <th>{esc(item["orderNo"])} {deal_tag}</th>
              <td>{daily.render_route(item["route"])}</td>
              <td>{money(float(item["leftAmt"]))}</td>
              <td>{money(float(item["rightAmt"]))}</td>
              <td class="diff {'positive' if item['diff'] > 0 else 'negative'}">{signed_money(float(item["diff"]))}</td>
            </tr>
            """
        )
    left_label = rows[0]["leftLabel"]
    right_label = rows[0]["rightLabel"]
    return f"""
    <table class="detail-table">
      <thead>
        <tr>
          <th>日期</th>
          <th>订单号</th>
          <th>线路</th>
          <th>{esc(left_label)}</th>
          <th>{esc(right_label)}</th>
          <th>差价</th>
        </tr>
      </thead>
      <tbody>{"".join(table_rows)}</tbody>
    </table>
    """


def route_rank(details: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for item in details:
        if item["result"] == "持平":
            continue
        route = item["route"]
        entry = grouped.setdefault(route, {"route": route, "count": 0, "sum_abs": 0.0, "max_abs": 0.0})
        diff_abs = abs(float(item["diff"]))
        entry["count"] += 1
        entry["sum_abs"] += diff_abs
        entry["max_abs"] = max(entry["max_abs"], diff_abs)
    rows = list(grouped.values())
    rows.sort(key=lambda item: (item["count"], item["sum_abs"], item["max_abs"]), reverse=True)
    return rows[:10]


def render_route_rank(details: list[dict[str, Any]]) -> str:
    rows = route_rank(details)
    if not rows:
        return '<div class="empty">无高于/低于线路</div>'
    table_rows = []
    for item in rows:
        table_rows.append(
            f"""
            <tr>
              <th>{daily.render_route(item["route"])}</th>
              <td>{item["count"]}</td>
              <td>{money(item["sum_abs"] / item["count"])}</td>
              <td>{money(item["max_abs"])}</td>
            </tr>
            """
        )
    return f"""
    <table class="rank-table">
      <thead><tr><th>线路</th><th>次数</th><th>平均差价</th><th>最大差价</th></tr></thead>
      <tbody>{"".join(table_rows)}</tbody>
    </table>
    """


def value_span(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(max(values) - min(values), 2)


def route_price_trend_points(values: list[float], min_value: float, max_value: float, width_px: int = 680, height_px: int = 180) -> str:
    if not values:
        return ""
    top = 18
    bottom = 34
    left = 48
    plot_w = width_px - left - 18
    plot_h = height_px - top - bottom
    denom = max(1, len(values) - 1)
    span = max(max_value - min_value, 1)
    points = []
    for index, value in enumerate(values):
        x = left + plot_w * index / denom
        y = top + plot_h * (1 - ((value - min_value) / span))
        points.append(f"{x:.1f},{y:.1f}")
    return " ".join(points)


def render_route_price_trend_chart(items: list[dict[str, Any]]) -> str:
    labels = [
        f"{clean_text(item.get('date'))} {clean_text(item.get('orderNo'))[-4:]}"
        for item in items
    ]
    option = {
        "color": ["#0f766e", "#2563eb", "#be123c"],
        "tooltip": {"trigger": "axis"},
        "legend": {"top": 0, "left": "center", "textStyle": {"color": "#667085"}},
        "grid": {"left": 48, "right": 50, "top": 54, "bottom": 40},
        "xAxis": {"type": "category", "boundaryGap": False, "data": labels, "axisLabel": {"color": "#667085"}},
        "yAxis": [
            {"type": "value", "name": "价格", "axisLabel": {"color": "#667085"}},
            {"type": "value", "name": "差价", "axisLabel": {"color": "#667085"}},
        ],
        "series": [
            {"name": "自动报价趋势", "type": "line", "smooth": True, "symbolSize": 7, "data": [float(item.get("rightAmt") or 0) for item in items]},
            {"name": "运力竞价趋势", "type": "line", "smooth": True, "symbolSize": 7, "data": [float(item.get("leftAmt") or 0) for item in items]},
            {"name": "差价趋势", "type": "line", "smooth": True, "symbolSize": 7, "yAxisIndex": 1, "data": [float(item.get("diff") or 0) for item in items]},
        ],
    }
    return render_echart(option, "line-chart route-line-chart")


def render_route_price_trend_table(items: list[dict[str, Any]]) -> str:
    rows = []
    for item in items:
        carrier_names = item.get("carrierNames") or []
        carrier_text = "、".join(str(name) for name in carrier_names) if carrier_names else "-"
        deal_tag = '<span class="deal-tag">成单</span>' if item.get("isDeal") else ""
        rows.append(
            f"""
            <tr>
              <td>{esc(item.get("date"))}</td>
              <th>{esc(item.get("orderNo"))} {deal_tag}</th>
              <td>{money(float(item.get("rightAmt") or 0))}</td>
              <td>{money(float(item.get("leftAmt") or 0))}</td>
              <td class="diff {'positive' if float(item.get("diff") or 0) > 0 else 'negative'}">{signed_money(float(item.get("diff") or 0))}</td>
              <td>{esc(carrier_text)}</td>
              <td>{esc(item.get("bidderName"))}</td>
              <td>{esc(item.get("confirmTime") or item.get("bidTime"))}</td>
            </tr>
            """
        )
    return f"""
    <div class="table-scroll">
      <table class="data-table route-trend-table">
        <thead><tr><th>日期</th><th>订单号</th><th>自动报价</th><th>运力竞价</th><th>差价</th><th>承运商</th><th>竞价人</th><th>确认时间</th></tr></thead>
        <tbody>{"".join(rows)}</tbody>
      </table>
    </div>
    """


def render_route_price_trends(details: list[dict[str, Any]]) -> str:
    ranked_routes = route_rank(details)[:5]
    if not ranked_routes:
        return '<div class="empty">无差异线路趋势</div>'
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in details:
        grouped[item["route"]].append(item)
    panels = []
    for ranked in ranked_routes:
        route = ranked["route"]
        items = sorted(
            grouped.get(route, []),
            key=lambda item: (str(item.get("date") or ""), str(item.get("confirmTime") or item.get("bidTime") or ""), str(item.get("orderNo") or "")),
        )
        if not items:
            continue
        auto_values = [float(item.get("rightAmt") or 0) for item in items]
        bid_values = [float(item.get("leftAmt") or 0) for item in items]
        diff_values = [float(item.get("diff") or 0) for item in items]
        carrier_names = sorted({str(name) for item in items for name in (item.get("carrierNames") or []) if str(name)})
        panels.append(
            f"""
            <article class="route-trend-card" data-route-trend="{esc(route)}">
              <div class="compare-title">
                <strong>{daily.render_route(route)}</strong>
                <span>{len(items)} 单 / 承运商 {len(carrier_names)} 个</span>
              </div>
              <div class="route-trend-summary">
                <span>自动报价波动 {money(value_span(auto_values))}</span>
                <span>运力竞价波动 {money(value_span(bid_values))}</span>
                <span>差价区间 {signed_money(min(diff_values))} ~ {signed_money(max(diff_values))}</span>
              </div>
              {render_route_price_trend_chart(items)}
              {render_route_price_trend_table(items)}
            </article>
            """
        )
    return "\n".join(panels) if panels else '<div class="empty">无差异线路趋势</div>'


def render_compare_panel(
    panel_id: str,
    target_label: str,
    high_title: str,
    low_title: str,
    weekly: dict[str, Any],
    daily_items: list[dict[str, Any]],
    labels: list[str],
) -> str:
    overall = weekly["overall"]
    deal = weekly["deal"]
    return f"""
    <div class="tab-panel" id="{esc(panel_id)}">
      <div class="panel chart-panel">
        <div class="compare-title">
          <strong>每日高于/低于/持平趋势</strong>
          <span>全部可比订单 {overall["total"]} 单</span>
        </div>
        {render_compare_line_chart(daily_items, labels)}
      </div>
      <div class="compare-grid">
        <div class="panel">
          <div class="compare-title"><strong>周汇总</strong><span>{overall["total"]} 单</span></div>
          {render_compare_rows(overall, target_label)}
        </div>
        <div class="panel">
          <div class="compare-title"><strong>成单中的周汇总</strong><span>{deal["total"]} 单</span></div>
          {render_compare_rows(deal, target_label)}
        </div>
      </div>
      <div class="panel">
        <div class="compare-title"><strong>差异线路排行</strong><span>高于/低于 Top 10</span></div>
        {render_route_rank(weekly["details"])}
      </div>
      <div class="route-trend-section">
        <div class="section-head compact-head">
          <h3>差异线路价格趋势</h3>
          <p class="section-note">按差异线路排行 Top 5 展示订单级自动报价、运力竞价和差价趋势</p>
        </div>
        {render_route_price_trends(weekly["details"])}
      </div>
      <div class="detail-grid">
        <div class="panel detail-panel">
          <div class="compare-title"><strong>{esc(high_title)}</strong><span>{overall["高于"]} 单</span></div>
          {render_price_detail_table(weekly["details"], "高于")}
        </div>
        <div class="panel detail-panel">
          <div class="compare-title"><strong>{esc(low_title)}</strong><span>{overall["低于"]} 单</span></div>
          {render_price_detail_table(weekly["details"], "低于")}
        </div>
      </div>
    </div>
    """


def render_distribution_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<tr><td colspan="3" class="empty-cell">暂无数据</td></tr>'
    return "\n".join(
        f"""
        <tr>
          <th>{esc(item.get("province"))}</th>
          <td>{int(item.get("count", 0))}</td>
          <td>{pct(float(item.get("rate", 0)))}</td>
        </tr>
        """
        for item in rows[:8]
    )


def render_distribution_table(title: str, rows: list[dict[str, Any]]) -> str:
    top_rows = rows[:8]
    other_count = sum(int(item.get("count", 0)) for item in rows[8:])
    pie_items = [(clean_text(item.get("province")), int(item.get("count", 0))) for item in top_rows]
    if other_count > 0:
        pie_items.append(("其他", other_count))
    return f"""
    <div class="panel table-scroll">
      <div class="compare-title"><strong>{esc(title)}</strong><span>TOP 8</span></div>
      {render_pie_chart(pie_items, f"{title}构成")}
      <table class="data-table">
        <thead><tr><th>省份</th><th>订单</th><th>占比</th></tr></thead>
        <tbody>{render_distribution_rows(rows)}</tbody>
      </table>
    </div>
    """


def render_week_province_section(weekly: dict[str, Any]) -> str:
    groups = [
        ("运力竞价与自动报价有差异", "bid_auto_diff_start_province_distribution", "bid_auto_diff_end_province_distribution"),
        ("运力二次竞价", "second_bid_start_province_distribution", "second_bid_end_province_distribution"),
        ("自动报价未二次竞价", "auto_without_second_bid_start_province_distribution", "auto_without_second_bid_end_province_distribution"),
    ]
    return "\n".join(
        f"""
        <article class="province-group">
          <div class="section-head compact-head"><h3>{esc(title)}</h3></div>
          <div class="province-grid">
            {render_distribution_table("始发省", weekly.get(start_key, []))}
            {render_distribution_table("目的省", weekly.get(end_key, []))}
          </div>
        </article>
        """
        for title, start_key, end_key in groups
    )


def render_week_profit_table(weekly: dict[str, Any]) -> str:
    profit = weekly.get("profit_by_quote_mode") or {}
    rows = [
        ("自动报价利润", profit.get("auto_quote") or {}),
        ("手动报价利润", profit.get("manual_quote") or {}),
    ]
    table_rows = "\n".join(
        f"""
        <tr>
          <th>{esc(label)}</th>
          <td>{int(item.get("order_count", 0))}</td>
          <td>{money(float(item.get("sales_amount", 0)))}</td>
          <td>{money(float(item.get("carrier_cost", 0)))}</td>
          <td>{money(float(item.get("total_profit", 0)))}</td>
          <td>{money(float(item.get("avg_profit", 0)))}</td>
          <td>{pct(float(item.get("profit_rate", 0)))}</td>
        </tr>
        """
        for label, item in rows
    )
    return f"""
    <table class="data-table">
      <thead><tr><th>类型</th><th>订单数</th><th>销售额</th><th>运力成本</th><th>总利润</th><th>单均利润</th><th>利润率</th></tr></thead>
      <tbody>{table_rows}</tbody>
    </table>
    """


def aggregate_channels(days: list[dict[str, Any]]) -> list[dict[str, Any]]:
    channels: dict[str, Counter] = defaultdict(Counter)
    for day in days:
        for item in day["summary"]["by_channel"]:
            channel = item["渠道"]
            channels[channel]["下单"] += int(item["下单数量"])
            channels[channel]["自动报价"] += int(item["自动报价订单数量"])
            channel_rows = [row for row in day["rows"] if (row.get("sourceRetailName") or "未知") == channel]
            channels[channel]["全自动报价"] += metrics.full_auto_quote_metrics(channel_rows)["full_auto_offer_order_count"]
            channels[channel]["成单"] += int(item["成单数量"])
    rows = []
    for channel, counts in channels.items():
        orders = counts["下单"]
        auto = counts["自动报价"]
        full_auto = counts["全自动报价"]
        deal = counts["成单"]
        rows.append(
            {
                "渠道": channel,
                "下单": orders,
                "自动报价": auto,
                "全自动报价": full_auto,
                "成单": deal,
                "自动报价率": auto / orders if orders else 0,
                "全自动报价率": full_auto / orders if orders else 0,
                "成单率": deal / orders if orders else 0,
            }
        )
    rows.sort(key=lambda item: item["下单"], reverse=True)
    return rows


def render_channel_table(channels: list[dict[str, Any]]) -> str:
    max_orders = max((item["下单"] for item in channels), default=1)
    top_channels = channels[:8]
    other_count = sum(int(item["下单"]) for item in channels[8:])
    pie_items = [(clean_text(item["渠道"]), int(item["下单"])) for item in top_channels]
    if other_count > 0:
        pie_items.append(("其他", other_count))
    table_rows = []
    for item in channels:
        table_rows.append(
            f"""
            <tr>
              <th>{esc(item["渠道"])}</th>
              <td><div class="metric-cell"><span>{item["下单"]}</span><div class="mini-track order"><i style="width:{width(item["下单"], max_orders)}"></i></div></div></td>
              <td>{item["自动报价"]}</td>
              <td>{item["全自动报价"]}</td>
              <td>{item["成单"]}</td>
              <td>{pct(item["自动报价率"])}</td>
              <td>{pct(item["全自动报价率"])}</td>
              <td>{pct(item["成单率"])}</td>
            </tr>
            """
        )
    return f"""
    <div class="channel-chart">
      {render_pie_chart(pie_items, "渠道下单构成")}
    </div>
    <table class="data-table">
      <thead><tr><th>渠道</th><th>下单</th><th>自动报价</th><th>全自动报价</th><th>成单</th><th>自动报价率</th><th>全自动报价率</th><th>成单率</th></tr></thead>
      <tbody>{"".join(table_rows)}</tbody>
    </table>
    """




def build_html(days: list[dict[str, Any]], trend_metrics: list[dict[str, Any]] | None = None) -> str:
    weekly = aggregate_week(days)
    metrics = build_day_metrics(days) if trend_metrics is None else trend_metrics
    comparisons = build_week_comparisons(days)
    labels = [day["label"] for day in days]
    channels = aggregate_channels(days)
    auto_rate = pct(weekly["auto_offer_rate"], 2)
    full_auto_rate = pct(weekly["full_auto_offer_rate"])
    deal_rate = pct(weekly["deal_rate"], 2)
    second_bid_rate = pct(weekly.get("second_bid_rate", 0), 2)
    auto_quote_deal_contribution_rate = pct(float(weekly.get("auto_quote_deal_contribution_rate", 0)), 2)
    manual_bid_deal_contribution_rate = pct(float(weekly.get("manual_bid_deal_contribution_rate", 0)), 2)
    corrected_auto_quote_deal_contribution_rate = pct(
        float(weekly.get("corrected_auto_quote_deal_contribution_rate", 0)), 2
    )
    corrected_manual_bid_deal_contribution_rate = pct(
        float(weekly.get("corrected_manual_bid_deal_contribution_rate", 0)), 2
    )
    corrected_auto_quote_close_rate = pct(float(weekly.get("corrected_auto_quote_close_rate", 0)), 2)
    corrected_manual_quote_close_rate = pct(float(weekly.get("corrected_manual_quote_close_rate", 0)), 2)
    corrected_auto_contribution_deal_count = float(weekly.get("corrected_auto_quote_deal_count", 0))
    corrected_manual_contribution_deal_count = float(weekly.get("corrected_manual_bid_deal_count", 0))
    corrected_auto_deal_count = float(weekly.get("corrected_auto_quote_close_deal_count", 0))
    corrected_manual_deal_count = float(weekly.get("corrected_manual_quote_close_deal_count", 0))
    corrected_auto_order_count = float(weekly.get("corrected_auto_quote_order_count", 0))
    corrected_manual_order_count = float(weekly.get("corrected_manual_quote_order_count", 0))
    auto_deal_share = pct(weekly["auto_offer_deal_count"] / weekly["order_count"] if weekly["order_count"] else 0, 2)
    period_label = REPORT_PERIOD_LABEL
    period_title = {"周": "周报", "日": "日报"}.get(period_label, "区间统计看板")
    period_heading = {"周": "周统计看板", "日": "当日统计看板"}.get(period_label, "区间统计看板")
    period_core_title = f"{period_label}核心指标"
    period_summary_note = {
        "周": "自然周汇总，接口数据重新生成",
        "日": "当日汇总，接口数据重新生成",
    }.get(period_label, "区间汇总，接口数据重新生成")
    period_rate_text = f"{period_label}自动报价率"
    period_stat_text = f"按{period_label}统计"
    order_time_note = f"订单列表 createTime 在{'本' + period_label if period_label != '区间' else '本区间'}"
    day_trend_note = {
        "周": "先看本周每天的下单、自动报价、成单表现，再看最终成单方式结构",
        "日": "左图看近两周每日的下单、自动报价、成单走势，右图为当日成单方式结构",
    }.get(period_label, "先看区间内每天的下单、自动报价、成单表现，再看最终成单方式结构")
    trend_section_title = "近两周经营趋势" if IS_SINGLE_DAY else "每日经营趋势"
    day_trend_heading = "近两周每日趋势" if IS_SINGLE_DAY else "每日趋势"
    method_note = f"{period_label} A/B/S 结构"
    route_rank_note = f"按{period_label}下单数量排序"
    title_period_text = (
        f"{WEEK_START:%Y-%m-%d}"
        if IS_SINGLE_DAY
        else f"{WEEK_START:%Y-%m-%d} 至 {WEEK_END:%Y-%m-%d}"
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>{title_period_text} 汽车托运订单{period_title}</title>
  <style>
    :root {{
      color-scheme: light;
      --page: #f4f6f8;
      --surface: #ffffff;
      --ink: #172033;
      --muted: #667085;
      --line: #d8e0ea;
      --blue: #2563eb;
      --blue-soft: #e8f0ff;
      --teal: #0f766e;
      --amber: #b45309;
      --green: #15803d;
      --rose: #be123c;
      --violet: #6d28d9;
      --shadow: 0 16px 38px rgba(23, 32, 51, 0.08);
      --radius: 8px;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
      color: var(--ink);
      background: var(--page);
      line-height: 1.5;
    }}
    .page {{
      width: min(1380px, calc(100% - 32px));
      margin: 0 auto;
      padding: 28px 0 40px;
    }}
    header {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 20px;
      align-items: end;
      padding: 20px 0 24px;
      border-bottom: 1px solid var(--line);
    }}
    h1 {{ margin: 0; font-size: 34px; line-height: 1.12; letter-spacing: 0; }}
    h2 {{ margin: 0; font-size: 18px; letter-spacing: 0; }}
    h3 {{ margin: 0; font-size: 16px; letter-spacing: 0; }}
    .subtitle {{ margin: 8px 0 0; color: var(--muted); font-size: 14px; }}
    .date-pill {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      border: 1px solid var(--line);
      background: var(--surface);
      border-radius: 999px;
      padding: 8px 12px;
      color: #344054;
      font-size: 13px;
      white-space: nowrap;
    }}
    .date-pill::before {{ content: ""; width: 8px; height: 8px; border-radius: 50%; background: var(--teal); }}
    section {{ margin-top: 22px; }}
    .section-head {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: baseline;
      margin-bottom: 12px;
    }}
    .section-note {{ margin: 0; color: var(--muted); font-size: 13px; }}
    .insight-grid, .trend-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }}
    .province-section {{
      display: grid;
      gap: 14px;
    }}
    .province-group {{
      display: grid;
      gap: 10px;
    }}
    .compact-head {{
      margin-bottom: 0;
    }}
    .province-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }}
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }}
    .panel, .kpi, .insight {{
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: var(--surface);
      box-shadow: var(--shadow);
      padding: 16px;
    }}
    .insight {{ min-height: 112px; }}
    .insight strong {{ display: block; font-size: 19px; margin-bottom: 8px; }}
    .insight p {{ margin: 0; color: #475467; font-size: 14px; }}
    .kpi {{ min-height: 124px; display: flex; flex-direction: column; justify-content: space-between; }}
    .kpi > .kpi-label {{
      display: inline-flex;
      align-items: center;
      align-self: flex-start;
      gap: 6px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 700;
    }}
    .metric-help {{ position: relative; display: inline-flex; flex: 0 0 auto; }}
    .metric-help button {{
      width: 17px;
      height: 17px;
      padding: 0;
      border: 1px solid #98a2b3;
      border-radius: 50%;
      background: #fff;
      color: #475467;
      font: inherit;
      font-size: 11px;
      font-weight: 800;
      line-height: 15px;
      text-align: center;
      cursor: help;
    }}
    .metric-help button:focus-visible {{ outline: 2px solid #2563eb; outline-offset: 2px; }}
    .metric-help-tooltip {{
      position: absolute;
      z-index: 30;
      top: calc(100% + 8px);
      left: 0;
      width: min(320px, calc(100vw - 64px));
      padding: 10px 12px;
      border: 1px solid #cbd5e1;
      border-radius: var(--radius);
      background: #172033;
      color: #f8fafc;
      box-shadow: 0 10px 24px rgba(15, 23, 42, 0.2);
      font-size: 12px;
      font-weight: 500;
      line-height: 1.55;
      opacity: 0;
      pointer-events: none;
      transform: translateY(-3px);
      transition: opacity 120ms ease, transform 120ms ease;
    }}
    .metric-help:hover .metric-help-tooltip,
    .metric-help:focus-within .metric-help-tooltip {{ opacity: 1; transform: translateY(0); }}
    .kpi strong {{ display: block; margin-top: 8px; font-size: 38px; line-height: 1; letter-spacing: 0; }}
    .kpi p {{ margin: 10px 0 0; color: #475467; font-size: 13px; }}
    .kpi.auto strong {{ color: var(--teal); }}
    .kpi.deal strong {{ color: var(--blue); }}
    .kpi.rate strong {{ color: var(--violet); }}
    .kpi.route strong {{ color: var(--amber); }}
    .data-table, .detail-table, .rank-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
      background: var(--surface);
    }}
    .data-table th, .data-table td, .detail-table th, .detail-table td, .rank-table th, .rank-table td {{
      padding: 10px 12px;
      border-bottom: 1px solid #eef2f6;
      text-align: right;
      white-space: nowrap;
      vertical-align: middle;
    }}
    .data-table th:first-child, .data-table td:first-child,
    .detail-table th:nth-child(-n+3), .detail-table td:nth-child(-n+3),
    .rank-table th:first-child, .rank-table td:first-child {{ text-align: left; }}
    .data-table thead th, .detail-table thead th, .rank-table thead th {{
      color: #475467;
      background: #f8fafc;
      font-weight: 700;
    }}
    .metric-cell {{
      min-width: 112px;
      display: grid;
      grid-template-columns: 42px 1fr;
      gap: 8px;
      align-items: center;
    }}
    .mini-track, .bar-track {{
      height: 10px;
      border-radius: 999px;
      background: #edf2f7;
      overflow: hidden;
    }}
    .mini-track i, .bar-track i {{ display: block; height: 100%; border-radius: inherit; }}
    .mini-track.order i {{ background: var(--blue); }}
    .mini-track.auto i {{ background: var(--teal); }}
    .compare-tabs {{
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: var(--surface);
      box-shadow: var(--shadow);
      padding: 14px;
    }}
    .compare-tabs input {{ position: absolute; opacity: 0; pointer-events: none; }}
    .compare-grid, .detail-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin-top: 12px;
    }}
    .compare-title {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: baseline;
      margin-bottom: 10px;
    }}
    .compare-title span {{ color: var(--muted); font-size: 13px; }}
    .compare-row {{ padding: 11px 0; border-top: 1px solid #eef2f6; }}
    .compare-row div:first-child {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 8px;
    }}
    .compare-row span {{ color: var(--muted); font-size: 13px; }}
    .compare-high i {{ background: var(--rose); }}
    .compare-low i {{ background: var(--green); }}
    .compare-equal i {{ background: var(--blue); }}
    .route-trend-section {{
      display: grid;
      gap: 12px;
      margin-top: 12px;
    }}
    .route-trend-card {{
      border: 1px solid #e5ebf3;
      border-radius: var(--radius);
      background: #fbfcfe;
      padding: 14px;
    }}
    .route-trend-summary {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 10px;
      color: #475467;
      font-size: 12px;
      font-weight: 700;
    }}
    .route-trend-summary span {{
      border: 1px solid #e5ebf3;
      border-radius: 999px;
      background: var(--surface);
      padding: 4px 8px;
    }}
    .route-trend-table td:nth-child(6) {{
      max-width: 220px;
      white-space: normal;
      line-height: 1.35;
    }}
    .chart-panel {{ margin-bottom: 12px; }}
    .echart {{
      width: 100%;
      height: 320px;
      min-height: 260px;
    }}
    .echart.compact-chart {{ height: 280px; }}
    .echart.pie-chart {{ height: 300px; min-height: 260px; }}
    .echart.route-line-chart {{ height: 300px; }}
    .echart.is-chart-unavailable {{
      display: grid;
      place-items: center;
      min-height: 180px;
      border: 1px dashed #cad5e2;
      border-radius: var(--radius);
      color: var(--muted);
      background: #f8fafc;
      font-size: 13px;
    }}
    .composition-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }}
    .composition-card {{
      border: 1px solid #e5ebf3;
      border-radius: var(--radius);
      background: #fbfcfe;
      padding: 14px;
    }}
    .composition-list {{
      display: grid;
      gap: 6px;
      margin-top: 8px;
    }}
    .composition-row {{
      display: flex;
      justify-content: space-between;
      gap: 10px;
      min-height: 32px;
      align-items: center;
      border: 1px solid #eef2f6;
      border-radius: var(--radius);
      background: var(--surface);
      padding: 7px 9px;
      font-size: 13px;
    }}
    .composition-row span {{ color: var(--muted); white-space: nowrap; }}
    .channel-chart {{ margin-bottom: 12px; }}
    .detail-table {{ table-layout: fixed; font-size: 12px; }}
    .detail-table th:first-child, .detail-table td:first-child {{ width: 56px; }}
    .detail-table th:nth-child(2), .detail-table td:nth-child(2) {{ width: 176px; }}
    .detail-table th:nth-child(3), .detail-table td:nth-child(3) {{ width: 138px; white-space: normal; }}
    .detail-table th:nth-child(4), .detail-table td:nth-child(4),
    .detail-table th:nth-child(5), .detail-table td:nth-child(5) {{ width: 88px; }}
    .detail-table th:nth-child(6), .detail-table td:nth-child(6) {{ width: 72px; }}
    .route-split {{
      display: inline-grid;
      grid-template-rows: auto auto auto;
      gap: 2px;
      text-align: center;
      line-height: 1.25;
      width: 100%;
    }}
    .route-split i {{ color: var(--muted); font-style: normal; font-size: 12px; line-height: 1; }}
    .route-plain {{ display: inline-block; max-width: 220px; white-space: normal; line-height: 1.35; }}
    .diff.positive {{ color: var(--rose); }}
    .diff.negative {{ color: var(--green); }}
    .deal-tag {{
      display: inline-flex;
      margin-left: 5px;
      padding: 1px 5px;
      border-radius: 999px;
      background: var(--blue-soft);
      color: var(--blue);
      font-size: 11px;
      font-weight: 700;
      vertical-align: middle;
    }}
    .empty {{ color: var(--muted); font-size: 13px; padding: 12px; background: #f8fafc; border-radius: var(--radius); }}
    .empty-cell {{ color: var(--muted); text-align: center !important; }}
    footer {{ margin-top: 20px; color: var(--muted); font-size: 12px; text-align: right; }}
    @media (max-width: 920px) {{
      header, .insight-grid, .trend-grid, .compare-grid, .detail-grid, .province-grid, .composition-grid {{ grid-template-columns: 1fr; }}
      .kpi-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .tab-labels {{ grid-template-columns: 1fr; }}
      .table-scroll {{ overflow-x: auto; }}
      .echart, .echart.pie-chart, .echart.route-line-chart {{ height: 300px; }}
    }}
    @media (max-width: 620px) {{
      .page {{ width: min(100% - 20px, 1380px); padding-top: 16px; }}
      h1 {{ font-size: 25px; }}
      .kpi-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <header>
      <div>
        <h1>汽车托运订单{period_heading}</h1>
        <p class="subtitle">{period_label}下单、自动报价、成单与价格差异趋势</p>
      </div>
      <span class="date-pill">{WEEK_START:%Y-%m-%d}{'' if IS_SINGLE_DAY else f' ~ {WEEK_END:%Y-%m-%d}'}</span>
    </header>

    <section>
      <div class="insight-grid">
        <article class="insight">
          <strong>{weekly["order_count"]} 单下单，{weekly["auto_offer_order_count"]} 单自动报价</strong>
          <p>{period_rate_text} {auto_rate}，覆盖 {weekly["auto_offer_route_count"]} 条自动报价线路。</p>
        </article>
        <article class="insight">
          <strong>{weekly["deal_order_count"]} 单成单，成单率 {deal_rate}</strong>
          <p>自动报价成单 {weekly["auto_offer_deal_count"]} 单，运力竞价成单 {weekly["bid_deal_count"]} 单，二次竞价成单 {weekly["second_bid_deal_count"]} 单。</p>
        </article>
      </div>
    </section>

    <section>
      <div class="section-head">
        <h2>{period_core_title}</h2>
        <p class="section-note">{period_summary_note}</p>
      </div>
      <div class="kpi-grid">
        {render_kpi(f"{period_label}下单数量", str(weekly["order_count"]), order_time_note, "order", "weekly-core-order")}
        {render_kpi(f"{period_label}自动报价订单", str(weekly["auto_offer_order_count"]), f"自动报价率 {auto_rate}；{numerator_denominator(weekly['auto_offer_order_count'], weekly['order_count'])}", "auto", "weekly-core-auto")}
        {render_kpi(f"{period_label}全自动报价订单", str(weekly["full_auto_offer_order_count"]), f"全自动报价率 {full_auto_rate}；{numerator_denominator(weekly['full_auto_offer_order_count'], weekly['order_count'])}", "auto", "weekly-core-full-auto")}
        {render_kpi(f"{period_label}成单数量", str(weekly["deal_order_count"]), f"成单率 {deal_rate}；{numerator_denominator(weekly['deal_order_count'], weekly['order_count'])}", "deal", "weekly-core-deal")}
        {render_kpi("二次竞价订单", str(weekly["second_bid_order_count"]), f"{period_stat_text}，二次竞价占比 {second_bid_rate}；{numerator_denominator(weekly['second_bid_order_count'], weekly['auto_offer_order_count'])}", "rate", "weekly-core-second-bid")}
        {render_kpi("二次竞价标记异常", str(weekly["second_bid_mark_anomaly_count"]), "bidMode=S 但自动报价干线价为空", "route", "weekly-core-second-anomaly")}
        {render_kpi("订单涉及线路", str(weekly["route_count"]), f"自动报价覆盖 {weekly['auto_offer_route_count']} 条", "route", "weekly-core-route")}
        {render_kpi("自动报价方式成单贡献率", auto_quote_deal_contribution_rate, numerator_denominator(weekly['auto_offer_deal_count'], weekly['order_count']), "auto", "weekly-core-auto-close-rate")}
        {render_kpi("人工竞价方式成单贡献率", manual_bid_deal_contribution_rate, numerator_denominator(weekly['manual_bid_deal_count'], weekly['order_count']), "route", "weekly-core-manual-close-rate")}
        {render_kpi("自动报价方式成单贡献率（修正）", corrected_auto_quote_deal_contribution_rate, numerator_denominator(corrected_auto_contribution_deal_count, weekly['order_count']), "auto", "weekly-core-corrected-auto-close-rate")}
        {render_kpi("人工竞价方式成单贡献率（修正）", corrected_manual_bid_deal_contribution_rate, numerator_denominator(corrected_manual_contribution_deal_count, weekly['order_count']), "route", "weekly-core-corrected-manual-close-rate")}
        {render_kpi("自动报价成单率（修正）", corrected_auto_quote_close_rate, numerator_denominator(corrected_auto_deal_count, corrected_auto_order_count), "auto", "weekly-core-corrected-auto-quote-close-rate")}
        {render_kpi("人工报价成单率（修正）", corrected_manual_quote_close_rate, numerator_denominator(corrected_manual_deal_count, corrected_manual_order_count), "route", "weekly-core-corrected-manual-quote-close-rate")}
      </div>
    </section>

    <section>
      <div class="section-head">
        <h2>{trend_section_title}</h2>
        <p class="section-note">{day_trend_note}</p>
      </div>
      <div class="trend-grid">
        <div class="panel table-scroll"{metric_attr("weekly-day-trend")}>
          <div class="section-head">
            <h3>{day_trend_heading}</h3>
            <p class="section-note">下单、自动报价、成单率</p>
          </div>
          {render_day_trend(metrics)}
        </div>
        <div class="panel"{metric_attr("weekly-method")}>
          <div class="section-head">
            <h3>成单方式</h3>
            <p class="section-note">{method_note}</p>
          </div>
          {render_compare_rows({"total": weekly["deal_order_count"], "高于": weekly["auto_offer_deal_count"], "低于": weekly["bid_deal_count"], "持平": weekly["second_bid_deal_count"]}, "成单方式").replace("高于成单方式", "自动报价成单").replace("低于成单方式", "运力竞价成单").replace("持平成单方式", "二次竞价成单")}
        </div>
      </div>
    </section>

    <section>
      <div class="section-head">
        <h2>渠道与利润</h2>
        <p class="section-note">从订单来源和成单利润看业务质量</p>
      </div>
      <div class="trend-grid">
        <div class="panel table-scroll"{metric_attr("weekly-channel")}>
          <div class="section-head">
            <h3>渠道表现</h3>
            <p class="section-note">{route_rank_note}</p>
          </div>
          {render_channel_table(channels)}
        </div>
        <div class="panel table-scroll"{metric_attr("weekly-profit")}>
          <div class="section-head">
            <h3>销售利润分析</h3>
            <p class="section-note">利润=销售价格-确认运力竞价成本</p>
          </div>
          {render_week_profit_table(weekly)}
        </div>
      </div>
    </section>

    <section>
      <div class="section-head">
        <h2>二次竞价跟进</h2>
        <p class="section-note">先看自动报价后是否推送二次竞价，再看推送后价格状态的订单数构成</p>
      </div>
      <div class="panel">
        {render_week_second_bid_chart(weekly)}
      </div>
      <div class="panel chart-panel"{metric_attr("weekly-second-bid-push-trend")}>
        <div class="compare-title">
          <strong>{'近两周每日' if IS_SINGLE_DAY else '每日'}订单自动报价后推送运力二次竞价趋势</strong>
          <span>自动报价订单 / 推送二次竞价订单 / 推送率</span>
        </div>
        {render_second_bid_push_trend(metrics)}
      </div>
    </section>

    <section>
      <div class="section-head">
        <h2>价格对比</h2>
        <p class="section-note">全量订单按干线价格对比，不含提车/送车费用；差价=运力竞价干线价 - 自动报价干线价</p>
      </div>
      <div class="compare-tabs"{metric_attr("weekly-price-compare")}>
        {render_compare_panel("panel-bid-auto", "自动报价", "竞价高于自动报价明细", "竞价低于自动报价明细", comparisons["bid_auto"]["weekly"], comparisons["bid_auto"]["daily"], labels)}
      </div>
    </section>

    <section class="province-section"{metric_attr("weekly-province")}>
      <div class="section-head">
        <h2>省份分布</h2>
        <p class="section-note">最后定位差异订单、二次竞价和未二次竞价自动报价订单集中在哪些始发/目的省</p>
      </div>
      {render_week_province_section(weekly)}
    </section>

    <footer>数据来源：DMS 接口分析结果，生成文件：{OUTPUT_PATH.name}</footer>
  </main>
  <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
  <script>
    (() => {{
      const chartNodes = Array.from(document.querySelectorAll('.echart[data-chart]'));
      const chartInstances = [];
      if (window.echarts) {{
        chartNodes.forEach((node) => {{
          try {{
            const chart = echarts.init(node, null, {{ renderer: 'canvas' }});
            chart.setOption(JSON.parse(node.dataset.chart));
            chartInstances.push(chart);
          }} catch (error) {{
            node.classList.add('is-chart-unavailable');
            node.textContent = '图表数据加载失败';
          }}
        }});
      }} else {{
        chartNodes.forEach((node) => {{
          node.classList.add('is-chart-unavailable');
          node.textContent = 'ECharts 未加载，无法显示图表';
        }});
      }}
      const resizeCharts = () => {{
        chartInstances.forEach((chart) => chart.resize());
      }};
      window.addEventListener('resize', resizeCharts);
      document
        .querySelectorAll('input[name="compare-tabs"]')
        .forEach((input) => input.addEventListener('change', () => setTimeout(resizeCharts, 80)));

    }})();
  </script>
</body>
</html>
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    days = load_week_data()
    trend_metrics = build_day_metrics(load_trend_days()) if IS_SINGLE_DAY else None
    html_text = build_html(days, trend_metrics)
    OUTPUT_PATH.write_text(html_text, encoding="utf-8")
    summary = {
        "week_start": WEEK_START.strftime("%Y-%m-%d"),
        "week_end": WEEK_END.strftime("%Y-%m-%d"),
        "output": str(OUTPUT_PATH),
        "weekly": aggregate_week(days),
    }
    summary_name = (
        f"summary_{WEEK_START:%Y%m%d}_daily_dashboard.json"
        if IS_SINGLE_DAY
        else f"summary_{WEEK_START:%Y%m%d}_{WEEK_END:%Y%m%d}.json"
    )
    (OUT_DIR / summary_name).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
