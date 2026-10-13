from __future__ import annotations

import html
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .analyze_0708_api_metrics import corrected_quote_close_rate_metrics, full_auto_quote_metrics, second_bid_metrics
from .operational_analysis import build_context, render_analysis, validate_analysis


ROOT = Path(os.environ.get("AUTO_QUOTE_WORKSPACE", Path.cwd())).expanduser().resolve()
ANALYSIS_DATE = datetime.strptime(os.environ.get("ANALYSIS_DATE", "2026-07-08"), "%Y-%m-%d")
DATE_COMPACT = ANALYSIS_DATE.strftime("%Y%m%d")
DATE_SHORT = ANALYSIS_DATE.strftime("%m%d")
DATA_DIR = ROOT / "outputs" / f"{DATE_SHORT}_api_analysis"
SUMMARY_PATH = DATA_DIR / f"summary_{DATE_COMPACT}.json"
ROWS_PATH = DATA_DIR / f"matched_orders_{DATE_COMPACT}.json"
BID_GROUPS_PATH = DATA_DIR / f"raw_bid_groups_{DATE_COMPACT}.json"
BID_GROUP_CARRIERS_PATH = DATA_DIR / f"raw_bid_group_carriers_{DATE_COMPACT}.json"
ANOMALY_DIAGNOSTICS_PATH = DATA_DIR / f"anomaly_diagnostics_{DATE_COMPACT}.json"
ANALYSIS_CONTEXT_PATH = DATA_DIR / f"operational_analysis_context_{DATE_COMPACT}.json"
OPERATING_ANALYSIS_PATH = DATA_DIR / f"operational_analysis_{DATE_COMPACT}.json"
LINE_UPDATE_DIR = ROOT / "outputs" / f"{DATE_SHORT}_auto_bid_line_updates"
LINE_UPDATE_SUMMARY_PATH = LINE_UPDATE_DIR / f"summary_{DATE_COMPACT}.json"
OUTPUT_PATH = DATA_DIR / f"{DATE_SHORT}_visual_dashboard.html"
ANALYSIS_REPORT_OUTPUT_PATH = DATA_DIR / f"{DATE_SHORT}_图文分析报告.html"
MAINTAINED_LINE_DIR = ROOT / "运力维护线路"
TREND_DAY_COUNT = 15


def esc(value: object) -> str:
    if value is None or value == "":
        return "-"
    return html.escape(str(value), quote=True)


def clean_text(value: object) -> str:
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


def chart_attr(option: dict[str, Any]) -> str:
    return html.escape(json.dumps(option, ensure_ascii=False), quote=True)


def render_echart(option: dict[str, Any], extra_class: str = "") -> str:
    return f'<div class="echart {esc(extra_class)}" data-chart="{chart_attr(option)}"></div>'


def load_recent_trend_metrics(day_count: int = TREND_DAY_COUNT) -> list[dict[str, Any]]:
    """Load daily summaries from the report day and its preceding days."""
    metrics = []
    for offset in range(day_count - 1, -1, -1):
        day = ANALYSIS_DATE - timedelta(days=offset)
        path = ROOT / "outputs" / f"{day:%m%d}_api_analysis" / f"summary_{day:%Y%m%d}.json"
        if not path.exists():
            continue
        try:
            summary = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if summary.get("date") != day.strftime("%Y-%m-%d"):
            continue
        order_count = int(summary.get("order_count", 0))
        auto_offer_count = int(summary.get("auto_offer_order_count", 0))
        deal_count = int(summary.get("deal_order_count", 0))
        full_auto_rate = summary.get("full_auto_offer_rate")
        full_auto_count = summary.get("full_auto_offer_order_count")
        corrected_auto_close_rate = summary.get("corrected_auto_quote_close_rate")
        corrected_manual_close_rate = summary.get("corrected_manual_quote_close_rate")
        # Recalculate when snapshots are present so historical trend points
        # consistently use the current per-order S attribution formula.
        rows_path = path.with_name(f"matched_orders_{day:%Y%m%d}.json")
        try:
            rows = json.loads(rows_path.read_text(encoding="utf-8"))
            bid_groups = json.loads(
                path.with_name(f"raw_bid_groups_{day:%Y%m%d}.json").read_text(encoding="utf-8")
            )
            bid_group_carriers = json.loads(
                path.with_name(f"raw_bid_group_carriers_{day:%Y%m%d}.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            rows = []
            bid_groups = {}
            bid_group_carriers = {}
        if rows:
            full_auto = full_auto_quote_metrics(rows)
            full_auto_count = full_auto["full_auto_offer_order_count"]
            full_auto_rate = full_auto["full_auto_offer_rate"]
            second_bid = second_bid_metrics(rows, bid_groups, bid_group_carriers)
            corrected_rates = corrected_quote_close_rate_metrics(
                order_count,
                auto_offer_count,
                sum(1 for row in rows if row.get("isAutoOffer") and row.get("isDeal") and clean_text(row.get("bidMode")) != "S"),
                int(summary.get("bid_deal_count", 0)),
                int(second_bid.get("second_bid_equal_count", 0)),
                int(second_bid.get("second_bid_changed_count", 0)),
                int(second_bid.get("second_bid_equal_deal_count", 0)),
                int(second_bid.get("second_bid_changed_deal_count", 0)),
            )
            corrected_auto_close_rate = corrected_rates["corrected_auto_quote_close_rate"]
            corrected_manual_close_rate = corrected_rates["corrected_manual_quote_close_rate"]
        metrics.append(
            {
                "date": day.strftime("%Y-%m-%d"),
                "label": day.strftime("%m-%d"),
                "order_count": order_count,
                "auto_offer_order_count": auto_offer_count,
                "full_auto_offer_order_count": full_auto_count,
                "full_auto_offer_rate": full_auto_rate,
                "deal_order_count": deal_count,
                "auto_offer_rate": auto_offer_count / order_count if order_count else 0,
                "deal_rate": deal_count / order_count if order_count else 0,
                "second_bid_order_count": int(summary.get("second_bid_order_count", 0)),
                "second_bid_rate": float(summary.get("second_bid_rate", 0)),
                "corrected_auto_quote_close_rate": float(corrected_auto_close_rate or 0),
                "corrected_manual_quote_close_rate": float(corrected_manual_close_rate or 0),
            }
        )
    return metrics


def load_recent_price_trend_comparisons(day_count: int = TREND_DAY_COUNT) -> list[dict[str, Any]]:
    """Rebuild the weekly price-comparison trend inputs from daily snapshots."""
    items = []
    for offset in range(day_count - 1, -1, -1):
        day = ANALYSIS_DATE - timedelta(days=offset)
        data_dir = ROOT / "outputs" / f"{day:%m%d}_api_analysis"
        paths = {
            "rows": data_dir / f"matched_orders_{day:%Y%m%d}.json",
            "bid_groups": data_dir / f"raw_bid_groups_{day:%Y%m%d}.json",
            "bid_group_carriers": data_dir / f"raw_bid_group_carriers_{day:%Y%m%d}.json",
        }
        if any(not path.exists() for path in paths.values()):
            continue
        try:
            rows = json.loads(paths["rows"].read_text(encoding="utf-8"))
            bid_groups = json.loads(paths["bid_groups"].read_text(encoding="utf-8"))
            bid_group_carriers = json.loads(paths["bid_group_carriers"].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        items.append(
            {
                "date": day.strftime("%Y-%m-%d"),
                "label": day.strftime("%m-%d"),
                "bid_auto": build_price_comparison(rows, bid_groups, bid_group_carriers),
            }
        )
    return items


def render_recent_trend(metrics: list[dict[str, Any]], mode: str = "all") -> str:
    if not metrics:
        return '<div class="empty-chart">未找到可用于趋势图的日报汇总数据</div>'
    option = {
        "color": ["#2563eb", "#0f766e", "#b45309", "#6d28d9", "#be123c"],
        "tooltip": {"trigger": "axis"},
        "legend": {"top": 0, "left": "center", "textStyle": {"color": "#667085"}},
        "grid": {"left": 46, "right": 48, "top": 54, "bottom": 30},
        "xAxis": {
            "type": "category",
            "boundaryGap": False,
            "data": [item["label"] for item in metrics],
            "axisLabel": {"color": "#667085"},
        },
        "yAxis": [
            {"type": "value", "name": "单量", "axisLabel": {"color": "#667085"}},
            {"type": "value", "name": "比率", "axisLabel": {"formatter": "{value}%", "color": "#667085"}},
        ],
        "series": [
            {"name": "下单", "type": "line", "smooth": True, "symbolSize": 7, "data": [item["order_count"] for item in metrics]},
            {"name": "自动报价", "type": "line", "smooth": True, "symbolSize": 7, "data": [item["auto_offer_order_count"] for item in metrics]},
            {"name": "全自动报价", "type": "line", "smooth": True, "symbolSize": 7, "data": [item.get("full_auto_offer_order_count") for item in metrics]},
            {"name": "成单", "type": "line", "smooth": True, "symbolSize": 7, "data": [item["deal_order_count"] for item in metrics]},
            {"name": "自动报价率", "type": "line", "smooth": True, "symbolSize": 7, "yAxisIndex": 1, "data": [round(item["auto_offer_rate"] * 100, 2) for item in metrics]},
            {"name": "全自动报价率", "type": "line", "smooth": True, "symbolSize": 7, "yAxisIndex": 1, "data": [round(item["full_auto_offer_rate"] * 100, 1) if item.get("full_auto_offer_rate") is not None else None for item in metrics]},
            {"name": "成单率", "type": "line", "smooth": True, "symbolSize": 7, "yAxisIndex": 1, "data": [round(item["deal_rate"] * 100, 2) for item in metrics]},
        ],
    }
    if mode != "all":
        names = {"下单", "成单", "成单率"} if mode == "overview" else {"自动报价", "全自动报价", "自动报价率", "全自动报价率"}
        option["series"] = [series for series in option["series"] if series["name"] in names]
    return render_echart(option, "line-chart")


def render_second_bid_push_trend(metrics: list[dict[str, Any]]) -> str:
    if not metrics:
        return '<div class="empty-chart">未找到可用于趋势图的日报汇总数据</div>'
    option = {
        "color": ["#0f766e", "#6d28d9", "#be123c"],
        "tooltip": {"trigger": "axis"},
        "legend": {"top": 0, "left": "center", "textStyle": {"color": "#667085"}},
        "grid": {"left": 46, "right": 48, "top": 54, "bottom": 30},
        "xAxis": {"type": "category", "boundaryGap": False, "data": [item["label"] for item in metrics], "axisLabel": {"color": "#667085"}},
        "yAxis": [
            {"type": "value", "name": "单量", "axisLabel": {"color": "#667085"}},
            {"type": "value", "name": "推送率", "axisLabel": {"formatter": "{value}%", "color": "#667085"}},
        ],
        "series": [
            {"name": "自动报价订单", "type": "line", "smooth": True, "symbolSize": 7, "data": [item["auto_offer_order_count"] for item in metrics]},
            {"name": "推送二次竞价订单", "type": "line", "smooth": True, "symbolSize": 7, "data": [int(item.get("second_bid_order_count", 0)) for item in metrics]},
            {"name": "推送率", "type": "line", "smooth": True, "symbolSize": 7, "yAxisIndex": 1, "data": [round(float(item.get("second_bid_rate", 0)) * 100, 2) for item in metrics]},
        ],
    }
    return render_echart(option, "line-chart")


def render_price_status_trend(items: list[dict[str, Any]], comparison_key: str) -> str:
    if not items:
        return '<div class="empty-chart">未找到可用于趋势图的价格对比快照</div>'
    option = {
        "color": ["#be123c", "#15803d", "#2563eb"],
        "tooltip": {"trigger": "axis"},
        "legend": {"top": 0, "left": "center", "textStyle": {"color": "#667085"}},
        "grid": {"left": 42, "right": 24, "top": 52, "bottom": 28},
        "xAxis": {"type": "category", "boundaryGap": False, "data": [item["label"] for item in items], "axisLabel": {"color": "#667085"}},
        "yAxis": {"type": "value", "name": "单量", "axisLabel": {"color": "#667085"}},
        "series": [
            {"name": "高于", "type": "line", "smooth": True, "symbolSize": 7, "data": [int(item[comparison_key]["overall"]["高于"]) for item in items]},
            {"name": "低于", "type": "line", "smooth": True, "symbolSize": 7, "data": [int(item[comparison_key]["overall"]["低于"]) for item in items]},
            {"name": "持平", "type": "line", "smooth": True, "symbolSize": 7, "data": [int(item[comparison_key]["overall"]["持平"]) for item in items]},
        ],
    }
    return render_echart(option, "line-chart compact-chart")


def render_quote_close_rate_trend(metrics: list[dict[str, Any]]) -> str:
    if not metrics:
        return '<div class="empty-chart">未找到可用于趋势图的日报汇总数据</div>'
    option = {
        "color": ["#0f766e", "#b45309", "#2563eb"],
        "tooltip": {"trigger": "axis"},
        "legend": {"top": 0, "left": "center", "textStyle": {"color": "#667085"}},
        "grid": {"left": 46, "right": 24, "top": 54, "bottom": 30},
        "xAxis": {
            "type": "category",
            "boundaryGap": False,
            "data": [item["label"] for item in metrics],
            "axisLabel": {"color": "#667085"},
        },
        "yAxis": {"type": "value", "name": "成单率", "axisLabel": {"formatter": "{value}%", "color": "#667085"}},
        "series": [
            {"name": "自动报价成单率（修正）", "type": "line", "smooth": True, "symbolSize": 7, "data": [round(item["corrected_auto_quote_close_rate"] * 100, 2) for item in metrics]},
            {"name": "人工报价成单率（修正）", "type": "line", "smooth": True, "symbolSize": 7, "data": [round(item["corrected_manual_quote_close_rate"] * 100, 2) for item in metrics]},
            {"name": "总成单率", "type": "line", "smooth": True, "symbolSize": 7, "data": [round(item["deal_rate"] * 100, 2) for item in metrics]},
        ],
    }
    return render_echart(option, "line-chart")


def render_pie_chart(items: list[tuple[str, int | float]], title: str) -> str:
    data = [{"name": name, "value": value} for name, value in items if value > 0]
    if not data:
        return '<div class="empty-chart">暂无构成数据</div>'
    return render_echart(
        {
            "color": ["#2563eb", "#0f766e", "#b45309", "#be123c", "#6d28d9", "#15803d", "#64748b", "#0891b2"],
            "tooltip": {"trigger": "item", "formatter": "{b}<br/>{c} 单 ({d}%)"},
            "legend": {"bottom": 0, "left": "center", "type": "scroll", "textStyle": {"color": "#667085"}},
            "series": [
                {
                    "name": title,
                    "type": "pie",
                    "radius": ["42%", "66%"],
                    "center": ["50%", "42%"],
                    "avoidLabelOverlap": True,
                    "label": {"formatter": "{b}\n{d}%", "color": "#344054"},
                    "labelLine": {"length": 10, "length2": 8},
                    "data": data,
                }
            ],
        },
        "pie-chart",
    )


def metric_attr(metric_id: str | None) -> str:
    return f' data-metric="{esc(metric_id)}"' if metric_id else ""


METRIC_HELP_TEXT = {
    "full-auto": "公式：全自动报价订单数量 = 自动报价订单数量 - 其中 bidMode=S 的订单数量；全自动报价率 = 全自动报价订单数量 / 下单数量。\n算法：统计命中自动报价且 bidMode!=S 的订单，不要求成单；S 订单无论干线价是否缺失或竞价是否持平均排除。\n解释：截至本次订单快照，命中自动报价且未标记二次竞价的订单规模。",
    "order": "公式：下单数量 = 统计周期内 createTime 落入范围的散户订单数。\n算法：以订单主表为准，每条订单记录计 1 单。\n解释：反映统计周期内新增下单需求。",
    "auto": "公式：自动报价订单数量 = 命中查价且 isOffer=1 的订单数；自动报价率 = 自动报价订单数量 / 下单数量。\n算法：订单先按线路、车辆数和时间窗口匹配查价记录，再判断是否自动报价。\n解释：反映系统线路库对真实订单的自动报价覆盖能力。",
    "deal": "公式：成单数量 = acceptTime 有值，或订单状态为待派单、运输中、已完成的订单数；成单率 = 成单数量 / 下单数量。\n算法：以订单成单状态判断，不以查价或竞价记录替代。\n解释：反映下单最终转化为运输订单的比例。",
    "second-bid": "公式：有效二次竞价订单数 = bidMode=S 且命中自动报价干线价大于 0 的订单数；二次竞价占比 = 有效二次竞价订单数 / 自动报价订单数。\n算法：自动报价干线价优先取匹配查价 freightAmt，缺失时取 trunkAmt。\n解释：反映自动报价后仍进入运力二次竞价的规模。",
    "second-anomaly": "公式：二次竞价标记异常订单数 = bidMode=S，但未命中自动报价、自动报价干线价为空或小于等于 0 的订单数。\n算法：异常订单不纳入有效二次竞价及价格变化分布。\n解释：用于识别可能存在的系统标记或数据链路异常。",
    "route": "公式：订单涉及线路 = 起始省市 + 目的省市完全一致的订单去重数。\n算法：不做省市简称、行政区或模糊归并。\n解释：反映实际订单需求的线路广度。",
    "auto-close-rate": "公式：自动报价方式成单贡献率 = bidMode=A 的成单数 / 全部订单数。\n算法：二次竞价 S 成单不计入该指标。\n解释：衡量直接按自动报价方式成交对全部下单的贡献。",
    "manual-close-rate": "公式：人工竞价方式成单贡献率 = bidMode 为 B 或 S 的成单数 / 全部订单数。\n算法：全部二次竞价 S 成单均归入人工竞价。\n解释：这是未修正的原始归因口径。",
    "corrected-auto-close-rate": "公式：自动报价方式成单贡献率（修正） = [自动报价命中且非二次竞价成单数 + 二次竞价持平订单中的成单数] / 全部下单数。\n算法：有效且可比的 S 订单逐笔判断；持平成单归自动报价，不按整体比例分摊。\n解释：衡量自动报价路径对全部下单的实际成单贡献。",
    "corrected-manual-close-rate": "公式：人工竞价方式成单贡献率（修正） = [直接人工竞价 B 成单数 + 二次竞价价格变化订单中的成单数] / 全部下单数。\n算法：有效且可比的 S 订单逐笔判断；价格变化成单归人工竞价，不按整体比例分摊。\n解释：衡量人工竞价路径对全部下单的实际成单贡献。",
    "corrected-auto-quote-close-rate": "公式：自动报价成单率（修正） = [自动报价命中且非二次竞价成单数 + 二次竞价持平订单中的成单数] / [自动报价订单数 - 二次竞价价格变化订单数]。\n算法：S 订单逐笔按实际持平或变化、以及是否成单归因；仅纳入有效且可比的二次竞价订单。\n解释：价格未变化的二次竞价仍归自动报价路径。",
    "corrected-manual-quote-close-rate": "公式：人工报价成单率（修正） = [直接人工竞价 B 成单数 + 二次竞价价格变化订单中的成单数] / [未命中自动报价订单数 + 二次竞价价格变化订单数]。\n算法：未命中自动报价订单数 = 下单数 - 自动报价订单数；S 订单逐笔归因，不按比例分摊。\n解释：价格变化的二次竞价归人工报价路径。",
    "auto-line-update": "公式：自动报价线路更新数 = 指定日期内最新子线路 linePriceModifyTime 落入当天、且 status=1 且 isExist=1 的主线路去重数。\n算法：按主线路 ID 去重；主线路 modifyTime 与子线路时间相同或更晚时，以主线路时间为准。\n解释：反映当天有效自动报价线路的价格维护规模，不代表完整操作次数。",
}


def metric_help_text(metric_id: str | None, fallback: str) -> str:
    if not metric_id:
        return fallback
    key = metric_id.removeprefix("weekly-core-").removeprefix("core-")
    return METRIC_HELP_TEXT.get(key, fallback)


def render_metric_help(text: str) -> str:
    body = esc(text).replace("\n", "<br>")
    return f'''<span class="metric-help"><button type="button" aria-label="查看指标计算口径">?</button><span class="metric-help-tooltip" role="tooltip">{body}</span></span>'''


def load_line_update_summary() -> dict[str, Any]:
    if not LINE_UPDATE_SUMMARY_PATH.exists():
        return {"available": False}
    try:
        payload = json.loads(LINE_UPDATE_SUMMARY_PATH.read_text(encoding="utf-8"))
        summary = payload.get("summary") or {}
        if summary.get("date") != ANALYSIS_DATE.strftime("%Y-%m-%d"):
            return {"available": False}
        return {"available": True, **summary}
    except (OSError, json.JSONDecodeError):
        return {"available": False}


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def hour_counts(rows: list[dict[str, Any]], field: str, predicate=None) -> list[int]:
    counts = Counter()
    for row in rows:
        if predicate and not predicate(row):
            continue
        dt = parse_dt(row.get(field))
        if dt:
            counts[dt.hour] += 1
    return [counts.get(hour, 0) for hour in range(24)]


def time_range(rows: list[dict[str, Any]], field: str, predicate=None) -> str:
    values = []
    for row in rows:
        if predicate and not predicate(row):
            continue
        dt = parse_dt(row.get(field))
        if dt:
            values.append(dt)
    if not values:
        return "-"
    return f"{min(values):%Y-%m-%d %H:%M:%S} ~ {max(values):%Y-%m-%d %H:%M:%S}"


def render_kpi(label: str, value: str, note: str, tone: str = "", metric_id: str | None = None) -> str:
    return f"""
    <article class="kpi {tone}"{metric_attr(metric_id)}>
      <span class="kpi-label">{esc(label)}{render_metric_help(metric_help_text(metric_id, note))}</span>
      <strong>{esc(value)}</strong>
      <p>{esc(note)}</p>
    </article>
    """


def render_focus_metrics_showcase(summary: dict[str, Any]) -> str:
    orders = int(summary.get("order_count", 0))
    auto = int(summary.get("auto_offer_order_count", 0))
    full_auto = summary.get("full_auto_offer_order_count")
    deals = int(summary.get("deal_order_count", 0))
    items = [
        ("order", "下单数量", str(orders), f"涉及 {summary.get('route_count', 0)} 条线路", "", "core-order"),
        ("auto-rate", "自动报价率", pct(auto / orders if orders else 0),
         f"{auto} 单自动报价", numerator_denominator(auto, orders), "core-auto"),
        ("full-auto-rate", "全自动报价率", pct(full_auto / orders if orders else 0) if full_auto is not None else "-",
         f"{full_auto} 单全自动报价" if full_auto is not None else "缺少订单明细",
         numerator_denominator(full_auto, orders) if full_auto is not None else "", "core-full-auto"),
        ("deal-rate", "成单率", pct(deals / orders if orders else 0),
         f"{deals} 单成单", numerator_denominator(deals, orders), "core-deal"),
    ]
    cards = []
    for key, label, value, count, fraction, metric_id in items:
        cards.append(f"""
        <article class="summary-item {key}" data-focus-id="{key}"{metric_attr(metric_id)}>
          <div class="summary-label">{esc(label)}{render_metric_help(metric_help_text(metric_id, label))}</div>
          <strong class="summary-value">{esc(value)}</strong>
          <p class="summary-count">{esc(count)}</p>
          <p class="summary-fraction">{esc(fraction)}</p>
        </article>
        """)
    return '<div class="business-summary-grid">' + "".join(cards) + "</div>"


BUSINESS_TABS = [
    ("overview", "经营总览"),
    ("auto", "自动报价"),
    ("second", "二次竞价"),
    ("deals", "成单与利润"),
    ("prices", "价格与异常"),
]


def render_business_navigation() -> str:
    buttons = "".join(
        f'<button type="button" role="tab" id="business-tab-{key}" aria-controls="business-{key}" '
        f'aria-selected="{str(key == "overview").lower()}" tabindex="{0 if key == "overview" else -1}" '
        f'data-business-tab="{key}">{label}</button>'
        for key, label in BUSINESS_TABS
    )
    return f'<nav class="business-navigation" aria-label="业务分析"><div role="tablist" aria-label="业务维度">{buttons}</div></nav>'


def render_business_panel(key: str, content: str, full_report: bool) -> str:
    hidden = "" if key == "overview" or full_report else " hidden"
    return (
        f'<section class="business-panel" id="business-{key}" role="tabpanel" '
        f'aria-labelledby="business-tab-{key}" data-business-panel="{key}" tabindex="0"{hidden}>'
        f'{content}</section>'
    )


def render_detail_block(label: str, content: str) -> str:
    return f'<details class="business-details" open><summary>{esc(label)}</summary>{content}</details>'



def render_funnel_row(label: str, value: int, total: int, note: str, tone: str, metric_id: str | None = None) -> str:
    return f"""
    <div class="funnel-row {tone}" style="--funnel-width:{width(value, total)}"{metric_attr(metric_id)}>
      <div class="funnel-shape">
        <div class="funnel-label">
          <strong>{esc(label)}</strong>
          <b>{value}</b>
          <span>{esc(note)}</span>
        </div>
      </div>
    </div>
    """


def render_method_chart(summary: dict[str, Any]) -> str:
    chart = render_pie_chart(
        [
            ("自动报价成单", int(summary["auto_offer_deal_count"])),
            ("运力竞价成单", int(summary["bid_deal_count"])),
            ("二次竞价成单", int(summary["second_bid_deal_count"])),
        ],
        "成单方式",
    )
    return f'<div class="method-chart"{metric_attr("method-chart")}>{chart}</div>'


def render_corrected_deal_attribution_chart(summary: dict[str, Any]) -> str:
    auto_count = round(float(summary.get("corrected_auto_quote_deal_count", 0)), 2)
    manual_count = round(float(summary.get("corrected_manual_bid_deal_count", 0)), 2)
    chart = render_pie_chart(
        [
            ("自动报价成单（修正）", auto_count),
            ("人工竞价成单（修正）", manual_count),
        ],
        "修正后成单归因",
    )
    return f'<div class="corrected-method-chart"{metric_attr("corrected-method-chart")}>{chart}</div>'


def render_line_update_section(line_updates: dict[str, Any]) -> str:
    if not line_updates.get("available"):
        return '<div class="empty-chart">未生成当日自动报价主线路更新快照</div>'
    effective = int(line_updates.get("effective_updated_line_count", line_updates.get("effective_updated_main_line_count", 0)))
    inactive = int(line_updates.get("inactive_or_missing_updated_line_count", line_updates.get("inactive_or_missing_updated_main_line_count", 0)))
    total = int(line_updates.get("updated_main_line_count", 0))
    updater_counts = line_updates.get("updater_counts") or {}
    updater_text = "、".join(f"{name} {count} 条" for name, count in updater_counts.items()) or "当天无有效更新"
    return f"""
    <div class="line-update-grid">
      <article class="line-update-stat effective"><span>有效线路更新</span><strong>{effective}</strong><small>status=1 且 isExist=1</small></article>
      <article class="line-update-stat inactive"><span>已停用线路更新</span><strong>{inactive}</strong><small>不计入有效更新</small></article>
      <article class="line-update-stat total"><span>线路更新总数</span><strong>{total}</strong><small>按主线路去重后</small></article>
    </div>
    <p class="line-update-note">更新人：{esc(updater_text)}。统计按最新子线路更新时间；主线路时间相同或更晚时以主线路时间为准。</p>
    """


def render_second_bid_change_chart(summary: dict[str, Any]) -> str:
    auto_total = int(summary.get("auto_offer_order_count", 0))
    second_total = int(summary.get("second_bid_order_count", 0))
    items = [
        ("自动报价订单", auto_total, auto_total, "method-auto", "second-bid-auto"),
        ("二次推送订单", second_total, auto_total, "method-second", "second-bid-pushed"),
        ("推送后持平", int(summary.get("second_bid_equal_count", 0)), second_total, "compare-equal", "second-bid-equal"),
        ("推送后变化", int(summary.get("second_bid_changed_count", 0)), second_total, "method-second", "second-bid-changed"),
        ("价格变高", int(summary.get("second_bid_higher_count", 0)), second_total, "compare-high", "second-bid-higher"),
        ("价格变低", int(summary.get("second_bid_lower_count", 0)), second_total, "compare-low", "second-bid-lower"),
        ("暂不可比", int(summary.get("second_bid_uncomparable_count", 0)), second_total, "compare-equal", "second-bid-uncomparable"),
    ]
    composition = render_pie_chart(
        [
            ("推送后持平", int(summary.get("second_bid_equal_count", 0))),
            ("价格变高", int(summary.get("second_bid_higher_count", 0))),
            ("价格变低", int(summary.get("second_bid_lower_count", 0))),
            ("暂不可比", int(summary.get("second_bid_uncomparable_count", 0))),
        ],
        "二次竞价价格状态",
    )
    bars = "\n".join(
        f"""
        <div class="method-item {tone}"{metric_attr(metric_id)}>
          <div>
            <strong>{esc(name)}</strong>
            <span>{count} 单 / {pct(count / denominator if denominator else 0)}</span>
          </div>
          <div class="bar-track" aria-hidden="true"><i style="width:{width(count, denominator)}"></i></div>
        </div>
        """
        for name, count, denominator, tone, metric_id in items
    )
    return f'<div class="second-bid-chart"><div class="second-bid-bars">{bars}</div>{composition}</div>'


def render_sales_second_bid_push_section(summary: dict[str, Any]) -> str:
    rows = summary.get("sales_second_bid_push_by_owner") or []
    if not rows:
        return '<div class="empty-chart">当天暂无销售订单统计</div>'
    names = [clean_text(item.get("销售")) for item in rows]
    chart = render_echart(
        {
            "color": ["#475467", "#0891b2", "#2563eb", "#be123c", "#15803d", "#98a2b3"],
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
            "legend": {"bottom": 0, "textStyle": {"color": "#667085"}},
            "grid": {"left": 48, "right": 20, "top": 28, "bottom": 60},
            "xAxis": {"type": "category", "data": names, "axisLabel": {"color": "#667085", "interval": 0}},
            "yAxis": {"type": "value", "minInterval": 1, "axisLabel": {"color": "#667085"}, "splitLine": {"lineStyle": {"color": "#eef2f6"}}},
            "series": [
                {"name": "总订单", "type": "bar", "data": [item.get("总订单数") for item in rows]},
                {"name": "自动报价订单", "type": "bar", "data": [item.get("自动报价订单数") for item in rows]},
                {"name": "持平", "type": "bar", "stack": "推送订单", "data": [int(item.get("持平", 0)) for item in rows]},
                {"name": "价格增高", "type": "bar", "stack": "推送订单", "data": [int(item.get("价格增高", 0)) for item in rows]},
                {"name": "价格降低", "type": "bar", "stack": "推送订单", "data": [int(item.get("价格降低", 0)) for item in rows]},
                {"name": "暂不可比", "type": "bar", "stack": "推送订单", "data": [int(item.get("暂不可比", 0)) for item in rows]},
            ],
        },
        "sales-push-chart",
    )
    table_rows = "\n".join(
        f"""
        <tr>
          <th>{esc(item.get("销售"))}</th>
          <td>{esc(item.get("总订单数"))}</td>
          <td>{esc(item.get("自动报价订单数"))}</td>
          <td>{int(item.get("推送订单数", 0))}</td>
          <td>{pct(float(item['二次推送率'])) if item.get('自动报价订单数') and item.get('二次推送率') is not None else '-'}</td>
          <td>{esc(item.get("未二次推送订单数"))}</td>
          <td>{int(item.get("持平", 0))}</td>
          <td>{int(item.get("价格增高", 0))}</td>
          <td>{int(item.get("价格降低", 0))}</td>
          <td>{int(item.get("暂不可比", 0))}</td>
          <td>{pct(float(item.get("持平占比", 0)))}</td>
        </tr>
        """
        for item in rows
    )
    return f"""
    <div class="sales-push-chart-scroll">{chart}</div>
    <details class="business-details" open><summary>销售推送明细</summary>
    <div class="channel-scroll">
      <table class="channel-table sales-push-table">
        <thead>
          <tr>
            <th>订单归属销售</th>
            <th>总订单</th>
            <th>自动报价订单</th>
            <th>二次推送订单</th>
            <th>二次推送率</th>
            <th>未二次推送订单</th>
            <th>持平</th>
            <th>价格增高</th>
            <th>价格降低</th>
            <th>暂不可比</th>
            <th>持平占比</th>
          </tr>
        </thead>
        <tbody>{table_rows}</tbody>
      </table>
    </div>
    </details>
    """


def render_distance_second_bid_push_section(summary: dict[str, Any]) -> str:
    rows = summary.get("sales_second_bid_push_by_distance") or []
    if not rows:
        return '<div class="empty-chart">未生成订单公里数区间统计</div>'
    chart = render_echart({
        "color": ["#475467", "#2563eb", "#b8dce2", "#be123c"],
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "legend": {"bottom": 0, "textStyle": {"color": "#667085"}},
        "grid": {"left": 48, "right": 60, "top": 28, "bottom": 70},
        "xAxis": {"type": "category", "data": [item["公里数区间"] for item in rows],
                  "axisLabel": {"interval": 0, "fontSize": 11, "color": "#667085"}},
        "yAxis": [
            {"type": "value", "name": "订单数", "minInterval": 1,
             "splitLine": {"lineStyle": {"color": "#eef2f6"}}},
            {"type": "value", "name": "推送率", "min": 0, "max": 100,
             "axisLabel": {"formatter": "{value}%"}, "splitLine": {"show": False}},
        ],
        "series": [
            {"name": "总订单", "type": "bar", "data": [item["总订单数"] for item in rows]},
            {"name": "二次推送订单", "type": "bar", "stack": "自动报价订单",
             "data": [item["二次推送订单数"] for item in rows]},
            {"name": "未二次推送订单", "type": "bar", "stack": "自动报价订单",
             "data": [item["未二次推送订单数"] for item in rows]},
            {"name": "二次推送率", "type": "line", "yAxisIndex": 1, "connectNulls": False,
             "data": [round(item["二次推送率"] * 100, 1) if item["自动报价订单数"] else None for item in rows]},
        ],
    }, "distance-push-chart")
    table_rows = "\n".join(
        f"<tr><th>{esc(item['公里数区间'])}</th><td>{item['总订单数']}</td>"
        f"<td>{item['自动报价订单数']}</td><td>{item['二次推送订单数']}</td>"
        f"<td>{item['未二次推送订单数']}</td>"
        f"<td>{pct(item['二次推送率']) if item['自动报价订单数'] else '-'}</td>"
        f"<td>{pct(item['推送分布占比']) if summary.get('sales_second_bid_push_order_count', sum(row['二次推送订单数'] for row in rows)) else '-'}</td></tr>"
        for item in rows
    )
    samples = [item for item in rows if item["公里数区间"] != "公里数未知" and item["自动报价订单数"] >= 10]
    insight = ""
    if len(samples) >= 2:
        highest = max(samples, key=lambda item: item["二次推送率"])
        lowest = min(samples, key=lambda item: item["二次推送率"])
        insight = (
            f"自动报价样本不少于 10 单的区间中，{esc(highest['公里数区间'])} 公里推送率最高："
            f"{pct(highest['二次推送率'])}（{highest['二次推送订单数']}/{highest['自动报价订单数']} 单）；"
            f"{esc(lowest['公里数区间'])} 公里最低：{pct(lowest['二次推送率'])}"
            f"（{lowest['二次推送订单数']}/{lowest['自动报价订单数']} 单）。"
        )
    return f"""
    <p class="section-note">有效公里数 {int(summary.get('order_distance_valid_count', 0))} 单，公里数未知 {int(summary.get('order_distance_unknown_count', 0))} 单；距离单位：公里</p>
    <div class="sales-push-chart-scroll">{chart}</div>
    <details class="business-details" open><summary>公里数区间明细</summary>
    <div class="channel-scroll">
      <table class="channel-table distance-push-table">
        <thead><tr><th>公里数区间</th><th>总订单</th><th>自动报价订单</th><th>二次推送订单</th><th>未二次推送订单</th><th>二次推送率</th><th>推送分布占比</th></tr></thead>
        <tbody>{table_rows}</tbody>
      </table>
    </div>
    </details>
    <p class="section-note">{insight}</p>
    <p class="section-note">公里数取本次订单快照；单日区间差异需结合销售、渠道和线路构成判断，不代表距离导致二次推送。</p>
    """


def render_route_second_bid_push_section(summary: dict[str, Any]) -> str:
    rows = summary.get("sales_second_bid_push_by_route") or []
    if not rows:
        return '<div class="empty-chart">未生成二次推送线路统计</div>'
    pushed = [item for item in rows if item["二次推送订单数"]]
    visible = pushed[:50]
    total_pushes = sum(item["二次推送订单数"] for item in rows)
    top10 = sum(item["二次推送订单数"] for item in pushed[:10])
    top50 = sum(item["二次推送订单数"] for item in visible)
    single_routes = sum(item["二次推送订单数"] == 1 for item in pushed)
    chart = render_echart({
        "color": ["#2563eb", "#b8dce2", "#be123c"], "animation": False,
        "tooltip": {"trigger": "axis", "confine": True, "axisPointer": {"type": "shadow"}},
        "legend": {"bottom": 0},
        "grid": {"left": 290, "right": 65, "top": 48, "bottom": 62},
        "xAxis": [
            {"type": "value", "name": "订单数", "minInterval": 1},
            {"type": "value", "name": "推送率", "min": 0, "max": 100, "position": "top",
             "axisLabel": {"formatter": "{value}%"}, "splitLine": {"show": False}},
        ],
        "yAxis": {"type": "category", "inverse": True, "data": [item["线路"] for item in visible],
                  "axisLabel": {"width": 265, "overflow": "truncate", "fontSize": 11}},
        "dataZoom": [{"type": "slider", "yAxisIndex": 0, "right": 4, "width": 14,
                      "start": 0, "end": min(100, 15 / max(len(visible), 1) * 100), "showDetail": False}],
        "series": [
            {"name": "二次推送订单", "type": "bar", "stack": "自动报价订单",
             "data": [item["二次推送订单数"] for item in visible]},
            {"name": "未二次推送订单", "type": "bar", "stack": "自动报价订单",
             "data": [item["未二次推送订单数"] for item in visible]},
            {"name": "二次推送率", "type": "scatter", "xAxisIndex": 1, "symbolSize": 8,
             "data": [[round(item["二次推送率"] * 100, 1), i] for i, item in enumerate(visible)]},
        ],
    }, "route-push-chart")
    table_rows = "\n".join(
        f'<tr data-route-key="{esc(item["routeKey"])}"><td>{i}</td><th>{esc(item["线路"])}</th>'
        f'<td>{item["总订单数"]}</td><td>{item["自动报价订单数"]}</td>'
        f'<td>{item["二次推送订单数"]}</td><td>{item["未二次推送订单数"]}</td>'
        f'<td>{pct(item["二次推送率"])}</td><td>{pct(item["推送分布占比"])}</td>'
        f'<td>{"样本较少" if item["自动报价订单数"] < 5 else "-"}</td></tr>'
        for i, item in enumerate(visible, 1)
    )
    share = lambda count: pct(count / total_pushes) if total_pushes else "-"
    return f"""
    <div class="route-push-explorer" data-route-rows="{chart_attr(rows)}">
      <p class="section-note route-push-overview">{total_pushes} 单二次推送涉及 {len(pushed)} 条线路，其中 {single_routes} 条仅推送 1 单；Top10 占 {share(top10)}，Top50 占 {share(top50)}。</p>
      <div class="route-push-controls">
        <label>范围 <select data-route-scope><option value="pushed">有二次推送线路</option><option value="auto">全部自动报价线路</option></select></label>
        <label>显示 <select data-route-limit><option value="50" selected>Top50</option><option value="100">Top100</option><option value="all">全部线路</option></select></label>
        <label>排序 <select data-route-sort><option value="count">推送单量</option><option value="rate">推送率</option></select></label>
        <label>最少自动报价 <select data-route-min-sample><option value="1">不限</option><option value="3">3 单</option><option value="5">5 单</option><option value="10">10 单</option></select></label>
        <label>线路 <input type="search" data-route-search placeholder="省份或城市" aria-label="搜索线路"></label>
      </div>
      <p class="section-note route-push-result" aria-live="polite">展示 {len(visible)}/{len(pushed)} 条线路，涉及 {top50} 单推送，占全部二次推送 {share(top50)}</p>
      <div class="sales-push-chart-scroll">{chart}</div>
      <details class="business-details" open><summary>二次推送线路明细</summary>
      <div class="channel-scroll route-push-table-scroll">
        <table class="channel-table route-push-table">
          <colgroup><col class="route-rank-col"><col class="route-name-col"><col span="4" class="route-count-col"><col span="2" class="route-rate-col"><col class="route-sample-col"></colgroup>
          <thead><tr><th>排名</th><th>线路</th><th>总订单</th><th>自动报价订单</th><th>二次推送订单</th><th>未二次推送订单</th><th>推送率</th><th>推送分布占比</th><th>样本</th></tr></thead>
          <tbody>{table_rows}</tbody>
        </table>
      </div>
      </details>
      <p class="section-note">自动报价样本不足 5 单的线路标记为样本较少；推送率以该线路自动报价订单为分母，分布占比以当天全部二次推送为分母。</p>
    </div>
    """


def render_channel_rows(summary: dict[str, Any], order_rows: list[dict[str, Any]] | None = None) -> str:
    rows = sorted(summary["by_channel"], key=lambda item: item["下单数量"], reverse=True)
    max_orders = max((item["下单数量"] for item in rows), default=1)
    html_rows = []
    for item in rows:
        orders = int(item["下单数量"])
        auto = int(item["自动报价订单数量"])
        full_auto = item.get("全自动报价订单数量")
        if order_rows is not None:
            full_auto = full_auto_quote_metrics([row for row in order_rows if (row.get("sourceRetailName") or "未知") == item["渠道"]])["full_auto_offer_order_count"]
        full_auto_rate = pct(full_auto / orders if orders else 0) if full_auto is not None else "-"
        deal = int(item["成单数量"])
        html_rows.append(
            f"""
            <tr>
              <th>{esc(item["渠道"])}</th>
              <td>
                <div class="metric-cell">
                  <span>{orders}</span>
                  <div class="mini-track order" aria-hidden="true"><i style="width:{width(orders, max_orders)}"></i></div>
                </div>
              </td>
              <td>
                <div class="metric-cell">
                  <span>{auto}</span>
                  <div class="mini-track auto" aria-hidden="true"><i style="width:{width(auto, orders)}"></i></div>
                </div>
              </td>
              <td>{full_auto if full_auto is not None else '-'}</td>
              <td>{deal}</td>
              <td>{pct(auto / orders if orders else 0)}</td>
              <td>{full_auto_rate}</td>
              <td>{pct(deal / orders if orders else 0)}</td>
            </tr>
            """
        )
    return "\n".join(html_rows)


def render_distribution_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<tr><td colspan="3" class="empty-cell">暂无数据</td></tr>'
    table_rows = []
    for item in rows[:8]:
        count = int(item.get("count", 0))
        rate = float(item.get("rate", 0))
        table_rows.append(
            f"""
            <tr>
              <th>{esc(item.get("province"))}</th>
              <td>{count}</td>
              <td>
                <div class="metric-cell province-rate">
                  <span>{pct(rate)}</span>
                  <div class="mini-track auto" aria-hidden="true"><i style="width:{width(rate, 1)}"></i></div>
                </div>
              </td>
            </tr>
            """
        )
    return "\n".join(table_rows)


def render_distribution_table(title: str, rows: list[dict[str, Any]], metric_id: str) -> str:
    top_rows = rows[:8]
    other_count = sum(int(item.get("count", 0)) for item in rows[8:])
    pie_items = [(clean_text(item.get("province")), int(item.get("count", 0))) for item in top_rows]
    if other_count:
        pie_items.append(("其他", other_count))
    return f"""
    <div class="panel province-panel"{metric_attr(metric_id)}>
      <div class="compare-title">
        <strong>{esc(title)}</strong>
        <span>TOP 8</span>
      </div>
      {render_pie_chart(pie_items, f"{title}构成")}
      <table class="province-table">
        <thead>
          <tr>
            <th>省份</th>
            <th>订单</th>
            <th>占比</th>
          </tr>
        </thead>
        <tbody>
          {render_distribution_rows(rows)}
        </tbody>
      </table>
    </div>
    """


def render_province_distribution_section(summary: dict[str, Any], scene: str | None = None) -> str:
    groups = [
        (
            "运力竞价与自动报价有差异",
            "bid_auto_diff_start_province_distribution",
            "bid_auto_diff_end_province_distribution",
            "province-bid-auto-diff",
        ),
        (
            "运力二次竞价",
            "second_bid_start_province_distribution",
            "second_bid_end_province_distribution",
            "province-second-bid",
        ),
        (
            "自动报价未二次竞价",
            "auto_without_second_bid_start_province_distribution",
            "auto_without_second_bid_end_province_distribution",
            "province-auto-without-second",
        ),
    ]
    rendered_groups = []
    for title, start_key, end_key, metric_prefix in groups:
        if scene is not None and metric_prefix != scene:
            continue
        rendered_groups.append(
            f"""
            <article class="province-group">
              <div class="section-head compact-head">
                <h3>{esc(title)}</h3>
              </div>
              <div class="province-grid">
                {render_distribution_table("始发省", summary.get(start_key, []), f"{metric_prefix}-start")}
                {render_distribution_table("目的省", summary.get(end_key, []), f"{metric_prefix}-end")}
              </div>
            </article>
            """
        )
    return "\n".join(rendered_groups)


def render_profit_rows(summary: dict[str, Any]) -> str:
    profit = summary.get("profit_by_quote_mode") or {}
    rows = [
        ("自动报价利润", profit.get("auto_quote") or {}, "profit-auto"),
        ("手动报价利润", profit.get("manual_quote") or {}, "profit-manual"),
    ]
    html_rows = []
    for label, item, metric_id in rows:
        order_count = int(item.get("order_count", 0))
        html_rows.append(
            f"""
            <tr{metric_attr(metric_id)}>
              <th>{esc(label)}</th>
              <td>{order_count}</td>
              <td>{money(float(item.get("sales_amount", 0)))}</td>
              <td>{money(float(item.get("carrier_cost", 0)))}</td>
              <td>{money(float(item.get("total_profit", 0)))}</td>
              <td>{money(float(item.get("avg_profit", 0)))}</td>
              <td>{pct(float(item.get("profit_rate", 0)))}</td>
            </tr>
            """
        )
    return "\n".join(html_rows)


def render_profit_section(summary: dict[str, Any]) -> str:
    profit = summary.get("profit_by_quote_mode") or {}
    auto_profit = profit.get("auto_quote") or {}
    manual_profit = profit.get("manual_quote") or {}
    profit_chart = render_echart(
        {
            "color": ["#2563eb", "#0f766e", "#b45309"],
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
            "legend": {"bottom": 0, "textStyle": {"color": "#667085"}},
            "grid": {"left": 54, "right": 20, "top": 28, "bottom": 42},
            "xAxis": {"type": "category", "data": ["自动报价", "人工竞价"], "axisLabel": {"color": "#667085"}},
            "yAxis": {"type": "value", "axisLabel": {"color": "#667085"}, "splitLine": {"lineStyle": {"color": "#eef2f6"}}},
            "series": [
                {"name": "销售额", "type": "bar", "data": [float(auto_profit.get("sales_amount", 0)), float(manual_profit.get("sales_amount", 0))]},
                {"name": "运力成本", "type": "bar", "data": [float(auto_profit.get("carrier_cost", 0)), float(manual_profit.get("carrier_cost", 0))]},
                {"name": "总利润", "type": "bar", "data": [float(auto_profit.get("total_profit", 0)), float(manual_profit.get("total_profit", 0))]},
            ],
        },
        "profit-chart",
    )
    return f"""
    {profit_chart}
    <div class="channel-scroll"{metric_attr("profit-summary")}>
      <table class="channel-table profit-table">
        <thead>
          <tr>
            <th>类型</th>
            <th>订单数</th>
            <th>销售额</th>
            <th>运力成本</th>
            <th>总利润</th>
            <th>单均利润</th>
            <th>利润率</th>
          </tr>
        </thead>
        <tbody>
          {render_profit_rows(summary)}
        </tbody>
      </table>
    </div>
    """


def render_channel_chart(summary: dict[str, Any]) -> str:
    rows = sorted(summary.get("by_channel") or [], key=lambda item: int(item.get("下单数量", 0)), reverse=True)
    top_rows = rows[:8]
    other_count = sum(int(item.get("下单数量", 0)) for item in rows[8:])
    items = [(clean_text(item.get("渠道")), int(item.get("下单数量", 0))) for item in top_rows]
    if other_count:
        items.append(("其他", other_count))
    return render_pie_chart(items, "渠道下单构成")


def chosen_bid_group(groups: list[dict[str, Any]]) -> dict[str, Any] | None:
    priced = [group for group in groups if group.get("payableAmt") is not None]
    confirmed = [group for group in priced if int(group.get("confirmStatus") or 0) == 1]
    if not confirmed:
        return None
    return sorted(
        confirmed,
        key=lambda group: group.get("confirmTime") or group.get("modifyTime") or group.get("bidTime") or "",
    )[0]


def safe_float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def bid_carrier_rows(
    order_no: str,
    bid_group: dict[str, Any],
    bid_group_carriers_by_order: dict[str, dict[str, list[dict[str, Any]]]],
) -> list[dict[str, Any]]:
    bid_id = str(bid_group.get("pkId") or "")
    if not bid_id:
        return []
    return list((bid_group_carriers_by_order.get(order_no) or {}).get(bid_id) or [])


def bid_carrier_names(carrier_rows: list[dict[str, Any]]) -> list[str]:
    names = sorted(
        {
            str(item.get("carrierName") or item.get("carrierId") or "").strip()
            for item in carrier_rows
            if str(item.get("carrierName") or item.get("carrierId") or "").strip()
        }
    )
    return names


def bid_trunk_amt(
    order_no: str,
    bid_group: dict[str, Any],
    bid_group_carriers_by_order: dict[str, dict[str, list[dict[str, Any]]]],
) -> float | None:
    carrier_rows = bid_carrier_rows(order_no, bid_group, bid_group_carriers_by_order)
    values = [
        value
        for value in (safe_float_or_none(item.get("trunkAmt")) for item in carrier_rows)
        if value is not None
    ]
    if not values:
        return None
    return round(sum(values), 2)


def auto_trunk_amt(row: dict[str, Any]) -> float | None:
    return safe_float_or_none(row.get("autoTrunkAmt"))


def compare_price(auto_amt: float, bid_amt: float) -> tuple[str, float]:
    diff = round(float(bid_amt) - float(auto_amt), 2)
    if abs(diff) < 0.01:
        return "持平", diff
    if diff > 0:
        return "高于", diff
    return "低于", diff


def build_price_comparison(
    rows: list[dict[str, Any]],
    bid_groups_by_order: dict[str, list[dict[str, Any]]],
    bid_group_carriers_by_order: dict[str, dict[str, list[dict[str, Any]]]],
) -> dict[str, Any]:
    result = empty_compare_result()
    for row in rows:
        auto_amt = auto_trunk_amt(row)
        if not row.get("isAutoOffer") or not row.get("hasBidGroup") or auto_amt is None:
            continue
        bid_group = chosen_bid_group(bid_groups_by_order.get(row["orderNo"], []))
        if not bid_group:
            continue
        carrier_rows = bid_carrier_rows(row["orderNo"], bid_group, bid_group_carriers_by_order)
        bid_amt = bid_trunk_amt(row["orderNo"], bid_group, bid_group_carriers_by_order)
        if bid_amt is None:
            continue
        status, diff = compare_price(auto_amt, bid_amt)
        add_compare_item(
            result,
            {
                "result": status,
                "orderNo": row["orderNo"],
                "route": row["route"],
                "routeKey": row.get("routeKey"),
                "leftLabel": "运力竞价干线价",
                "rightLabel": "自动报价干线价",
                "leftAmt": bid_amt,
                "rightAmt": auto_amt,
                "diff": diff,
                "isDeal": bool(row.get("isDeal")),
                "bidTime": bid_group.get("bidTime") or bid_group.get("createTime"),
                "confirmTime": bid_group.get("confirmTime") or bid_group.get("modifyTime"),
                "bidderName": bid_group.get("bidderName") or bid_group.get("createUserName"),
                "carrierNames": bid_carrier_names(carrier_rows),
                "carrierCount": len(bid_carrier_names(carrier_rows)),
            },
        )
    sort_compare_details(result)
    return result


def build_bid_vs_table_comparison(
    rows: list[dict[str, Any]],
    bid_groups_by_order: dict[str, list[dict[str, Any]]],
    bid_group_carriers_by_order: dict[str, dict[str, list[dict[str, Any]]]],
    maintained_lines: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    result = empty_compare_result()
    for row in rows:
        if row["routeKey"] not in maintained_lines or not row.get("hasBidGroup"):
            continue
        auto_amt = auto_trunk_amt(row)
        if not row.get("isAutoOffer") or auto_amt is None:
            continue
        bid_group = chosen_bid_group(bid_groups_by_order.get(row["orderNo"], []))
        if not bid_group:
            continue
        carrier_rows = bid_carrier_rows(row["orderNo"], bid_group, bid_group_carriers_by_order)
        bid_amt = bid_trunk_amt(row["orderNo"], bid_group, bid_group_carriers_by_order)
        if bid_amt is None:
            continue
        status, diff = compare_amount(bid_amt, auto_amt)
        add_compare_item(
            result,
            {
                "result": status,
                "orderNo": row["orderNo"],
                "route": row["route"],
                "routeKey": row.get("routeKey"),
                "leftLabel": "运力竞价干线价",
                "rightLabel": "自动报价干线价",
                "leftAmt": bid_amt,
                "rightAmt": auto_amt,
                "diff": diff,
                "isDeal": bool(row.get("isDeal")),
                "bidTime": bid_group.get("bidTime") or bid_group.get("createTime"),
                "confirmTime": bid_group.get("confirmTime") or bid_group.get("modifyTime"),
                "bidderName": bid_group.get("bidderName") or bid_group.get("createUserName"),
                "carrierNames": bid_carrier_names(carrier_rows),
                "carrierCount": len(bid_carrier_names(carrier_rows)),
            },
        )
    sort_compare_details(result)
    return result


def build_auto_vs_table_comparison(
    rows: list[dict[str, Any]],
    maintained_lines: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    result = empty_compare_result()
    for row in rows:
        line = maintained_lines.get(row["routeKey"])
        auto_amt = auto_trunk_amt(row)
        if not line or not row.get("isAutoOffer") or auto_amt is None:
            continue
        table_amt = float(line["tablePrice"])
        status, diff = compare_amount(auto_amt, table_amt)
        add_compare_item(
            result,
            {
                "result": status,
                "orderNo": row["orderNo"],
                "route": row["route"],
                "leftLabel": "自动查价干线价",
                "rightLabel": "表格线路价格",
                "leftAmt": auto_amt,
                "rightAmt": table_amt,
                "diff": diff,
                "isDeal": bool(row.get("isDeal")),
            },
        )
    sort_compare_details(result)
    return result


def render_compare_rows(group: dict[str, int], target_label: str = "自动报价", metric_prefix: str | None = None) -> str:
    total = int(group["total"])
    items = [
        (f"高于{target_label}", int(group["高于"]), "compare-high", "high"),
        (f"低于{target_label}", int(group["低于"]), "compare-low", "low"),
        (f"持平{target_label}", int(group["持平"]), "compare-equal", "equal"),
    ]
    return "\n".join(
        f"""
        <div class="compare-row {klass}"{metric_attr(f"{metric_prefix}-{metric_key}" if metric_prefix else None)}>
          <div>
            <strong>{esc(name)}</strong>
            <span>{count} 单 / {pct(count / total if total else 0)}</span>
          </div>
          <div class="bar-track" aria-hidden="true"><i style="width:{width(count, total)}"></i></div>
        </div>
        """
        for name, count, klass, metric_key in items
    )


def money(value: float) -> str:
    return f"{value:,.0f}"


def signed_money(value: float) -> str:
    if value > 0:
        return f"+{money(value)}"
    return money(value)


def render_route(value: str) -> str:
    if " -> " not in value:
        return f'<span class="route-plain">{esc(value)}</span>'
    start, end = value.split(" -> ", 1)
    return (
        f'<span class="route-split">'
        f'<span>{esc(start)}</span>'
        f'<i>→</i>'
        f'<span>{esc(end)}</span>'
        f"</span>"
    )


def route_key_from_parts(start_prov: Any, start_city: Any, end_prov: Any, end_city: Any) -> str:
    return "|".join(str(value).strip() for value in [start_prov, start_city, end_prov, end_city])


def load_maintained_lines() -> dict[str, dict[str, Any]]:
    lines: dict[str, dict[str, Any]] = {}
    if not MAINTAINED_LINE_DIR.exists():
        return lines

    import pandas as pd

    for path in sorted(
        item
        for item in MAINTAINED_LINE_DIR.glob("*.xlsx")
        if not item.name.startswith(".~") and not item.name.startswith("~$")
    ):
        raw = pd.read_excel(path, sheet_name=0, header=None, engine="openpyxl")
        header_idx = None
        for index in range(min(10, len(raw))):
            values = [str(value).strip() for value in raw.iloc[index].tolist()]
            if "起始地省份" in values and "起始地城市" in values and "单台运价" in values:
                header_idx = index
                break
        if header_idx is None:
            continue

        df = pd.read_excel(path, sheet_name=0, header=header_idx, engine="openpyxl")
        df.columns = [str(column).strip() for column in df.columns]
        required = ["起始地省份", "起始地城市", "目的地省份", "目的地城市", "单台运价"]
        if any(column not in df.columns for column in required):
            continue

        for _, row in df.iterrows():
            values = [row.get(column) for column in required]
            if any(pd.isna(value) for value in values):
                continue
            try:
                price = float(row["单台运价"])
            except (TypeError, ValueError):
                continue
            key = route_key_from_parts(
                row["起始地省份"],
                row["起始地城市"],
                row["目的地省份"],
                row["目的地城市"],
            )
            lines[key] = {
                "routeKey": key,
                "route": f"{row['起始地省份']}{row['起始地城市']} -> {row['目的地省份']}{row['目的地城市']}",
                "tablePrice": price,
                "sourceFile": path.name,
            }
    return lines


def compare_amount(value: float, reference: float) -> tuple[str, float]:
    diff = round(float(value) - float(reference), 2)
    if abs(diff) < 0.01:
        return "持平", diff
    if diff > 0:
        return "高于", diff
    return "低于", diff


def empty_compare_result() -> dict[str, Any]:
    return {
        "overall": {"total": 0, "高于": 0, "低于": 0, "持平": 0},
        "deal": {"total": 0, "高于": 0, "低于": 0, "持平": 0},
        "details": [],
    }


def add_compare_item(result: dict[str, Any], detail: dict[str, Any]) -> None:
    status = detail["result"]
    result["overall"]["total"] += 1
    result["overall"][status] += 1
    if detail.get("isDeal"):
        result["deal"]["total"] += 1
        result["deal"][status] += 1
    result["details"].append(detail)


def sort_compare_details(result: dict[str, Any]) -> None:
    result["details"].sort(
        key=lambda item: (
            0 if item["result"] == "高于" else (1 if item["result"] == "低于" else 2),
            -abs(float(item["diff"])),
            item["orderNo"],
        )
    )


def render_price_detail_table(details: list[dict[str, Any]], result: str) -> str:
    rows = [item for item in details if item["result"] == result]
    if not rows:
        return """
        <div class="panel detail-panel">
          <div class="compare-title"><strong>无明细</strong><span>0 单</span></div>
        </div>
        """
    table_rows = []
    for item in rows:
        deal_tag = '<span class="deal-tag">成单</span>' if item["isDeal"] else ""
        table_rows.append(
            f"""
            <tr data-price-diff="{esc(float(item['diff']))}">
              <th>{esc(item["orderNo"])} {deal_tag}</th>
              <td>{render_route(item["route"])}</td>
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
          <th>订单号</th>
          <th>线路</th>
          <th>{esc(left_label)}</th>
          <th>{esc(right_label)}</th>
          <th>差价</th>
        </tr>
      </thead>
      <tbody>
        {"".join(table_rows)}
      </tbody>
    </table>
    """


def render_compare_panel(
    panel_id: str,
    target_label: str,
    high_title: str,
    low_title: str,
    comparison: dict[str, Any],
) -> str:
    overall = comparison["overall"]
    deal = comparison["deal"]
    return f"""
    <div class="tab-panel" id="{esc(panel_id)}">
      <div class="compare-grid">
        <div class="panel">
          <div class="compare-title">
            <strong>全部可比订单</strong>
            <span>{overall["total"]} 单</span>
          </div>
          {render_compare_rows(overall, target_label, f"{panel_id}-overall")}
        </div>
        <div class="panel">
          <div class="compare-title">
            <strong>成单中的可比订单</strong>
            <span>{deal["total"]} 单</span>
          </div>
          {render_compare_rows(deal, target_label, f"{panel_id}-deal")}
        </div>
      </div>
      <div class="detail-grid">
        <details class="business-details detail-panel" open>
          <summary class="compare-title">
            <strong>{esc(high_title)}</strong>
            <span>{overall["高于"]} 单</span>
          </summary>
          <div class="table-scroll">
          {render_price_detail_table(comparison["details"], "高于")}
          </div>
        </details>
        <details class="business-details detail-panel" open>
          <summary class="compare-title">
            <strong>{esc(low_title)}</strong>
            <span>{overall["低于"]} 单</span>
          </summary>
          <div class="table-scroll">
          {render_price_detail_table(comparison["details"], "低于")}
          </div>
        </details>
      </div>
    </div>
    """


def render_hour_chart(rows: list[dict[str, Any]]) -> str:
    series = [
        ("下单", hour_counts(rows, "createTime"), "hour-order", "hour-order"),
        ("自动报价", hour_counts(rows, "autoOfferTime", lambda row: row["isAutoOffer"]), "hour-auto", "hour-auto"),
        ("成单", hour_counts(rows, "acceptTime", lambda row: row["isDeal"]), "hour-deal", "hour-deal"),
        ("运力竞价", hour_counts(rows, "firstBidTime", lambda row: row["hasBidGroup"]), "hour-bid", "hour-bid"),
    ]
    max_value = max(max(values) for _, values, _, _ in series)
    blocks = []
    for label, values, klass, metric_id in series:
        bars = []
        for hour, value in enumerate(values):
            bars.append(
                f"""
                <div class="hour-slot">
                  <i class="{klass}" style="height:{width(value, max_value)}" title="{hour:02d}:00 {label} {value}"></i>
                </div>
                """
            )
        blocks.append(
            f"""
            <div class="hour-series"{metric_attr(metric_id)}>
              <strong>{esc(label)}</strong>
              <div class="hour-bars" aria-label="{esc(label)}按小时分布">
                {"".join(bars)}
              </div>
            </div>
            """
        )
    labels = "".join(f"<span>{hour:02d}</span>" for hour in range(0, 24, 3))
    return f"""
    <div class="hour-wrap">
      {"".join(blocks)}
      <div class="hour-axis">{labels}</div>
    </div>
    """


def ratio_text(value: int, total: int) -> str:
    return pct(value / total if total else 0)


def compare_share(overall: dict[str, int], key: str) -> str:
    return ratio_text(int(overall.get(key, 0)), int(overall.get("total", 0)))


def compare_net_diff(comparison: dict[str, Any]) -> float:
    return round(sum(float(item.get("diff") or 0) for item in comparison.get("details", [])), 2)


def top_channels(summary: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    rows = list(summary.get("by_channel") or [])
    top_order = max(rows, key=lambda item: int(item.get("下单数量", 0)), default=None)
    comparable = [item for item in rows if int(item.get("下单数量", 0)) >= 5]
    best_deal = max(
        comparable,
        key=lambda item: int(item.get("成单数量", 0)) / int(item.get("下单数量", 1)),
        default=None,
    )
    return top_order, best_deal


def render_report_metric(label: str, value: str, note: str, tone: str = "") -> str:
    return f"""
    <div class="report-metric {tone}">
      <span>{esc(label)}</span>
      <strong>{esc(value)}</strong>
      <small>{esc(note)}</small>
    </div>
    """


def render_report_compare_chart(title: str, overall: dict[str, int], target_label: str = "自动报价") -> str:
    total = int(overall.get("total", 0))
    rows = [
        ("高于", int(overall.get("高于", 0)), "report-high"),
        ("低于", int(overall.get("低于", 0)), "report-low"),
        ("持平", int(overall.get("持平", 0)), "report-equal"),
    ]
    bars = "\n".join(
        f"""
        <div class="report-bar-row {klass}">
          <div><b>{esc(name)}{esc(target_label)}</b><span>{count} 单 / {ratio_text(count, total)}</span></div>
          <i><em style="width:{width(count, total)}"></em></i>
        </div>
        """
        for name, count, klass in rows
    )
    return f"""
    <div class="report-chart">
      <div class="report-chart-title"><strong>关键图表：{esc(title)}</strong><span>{total} 单</span></div>
      {bars}
    </div>
    """




def anomaly_judgement(diff: float) -> tuple[str, str]:
    if diff > 0:
        return "自动报价偏低", "复核价格来源"
    if diff < 0:
        return "自动报价偏高", "优先校准线路价"
    return "持平", "持续观察"


def clean_diagnosis_text(value: Any, max_len: int = 64) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def render_anomaly_table(
    details: list[dict[str, Any]],
    limit: int = 10,
    diagnostics_by_order: dict[str, dict[str, Any]] | None = None,
) -> str:
    diagnostics_by_order = diagnostics_by_order or {}
    anomalies = sorted(
        [item for item in details if abs(float(item.get("diff") or 0)) > 0],
        key=lambda item: abs(float(item.get("diff") or 0)),
        reverse=True,
    )[:limit]
    if not anomalies:
        return '<div class="report-empty">暂无价格差异订单。</div>'
    rows = []
    for item in anomalies:
        diff = float(item.get("diff") or 0)
        judgement, suggestion = anomaly_judgement(diff)
        diagnosis = diagnostics_by_order.get(str(item.get("orderNo") or "")) or {}
        diagnosis_text = clean_diagnosis_text(diagnosis.get("diagnosis") or "证据不足，需人工复核")
        current_status = clean_diagnosis_text(diagnosis.get("currentLinePriceStatus") or "-", max_len=48)
        current_evidence = clean_diagnosis_text(diagnosis.get("currentLinePriceEvidence") or "", max_len=130)
        current_text = current_status if not current_evidence else f"{current_status}：{current_evidence}"
        freshness_text = clean_diagnosis_text(diagnosis.get("priceFreshness") or "-", max_len=90)
        updates_text = clean_diagnosis_text(diagnosis.get("laterUpdates") or "-", max_len=120)
        evidence_text = clean_diagnosis_text(diagnosis.get("evidence") or suggestion, max_len=120)
        suggestion_text = clean_diagnosis_text(diagnosis.get("currentLinePriceSuggestion") or suggestion, max_len=90)
        deal = '<span class="report-deal">已成单</span>' if item.get("isDeal") else ""
        rows.append(
            f"""
            <tr>
              <td class="order-no">{esc(item.get("orderNo"))}</td>
              <th>{render_route(str(item.get("route") or ""))}</th>
              <td>{money(float(item.get("leftAmt") or 0))}</td>
              <td>{money(float(item.get("rightAmt") or 0))}</td>
              <td class="diff {'positive' if diff > 0 else 'negative'}">{signed_money(diff)}</td>
              <td>{esc(judgement)} {deal}</td>
              <td class="wrap-text">{esc(diagnosis_text)}</td>
              <td class="wrap-text">{esc(current_text)}</td>
              <td class="wrap-text">{esc(freshness_text)}</td>
              <td class="wrap-text">{esc(updates_text)}</td>
              <td class="wrap-text">{esc(suggestion_text)}</td>
              <td class="wrap-text">{esc(evidence_text)}</td>
            </tr>
            """
        )
    return f"""
    <table class="anomaly-table">
      <thead>
        <tr>
          <th>订单号</th>
          <th>线路</th>
          <th>竞价</th>
          <th>自动报价</th>
          <th>差价</th>
          <th>判断</th>
          <th>初步归因</th>
          <th>当前线路库状态</th>
          <th>价格时效</th>
          <th>后续更新</th>
          <th>建议</th>
          <th>证据</th>
        </tr>
      </thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
    """



def render_actionable_route_recommendations(price_compare: dict[str, Any]) -> str:
    details = price_compare.get("details") or []
    items = [item for item in details if item.get("result") in ("高于", "低于")]
    if not items:
        return ""
    items = sorted(items, key=lambda item: (-abs(float(item["diff"])), str(item["orderNo"])))
    higher_count = sum(item["result"] == "高于" for item in items)
    lower_count = len(items) - higher_count

    rows = []
    for item in items:
        rows.append(f"""
        <tr>
          <td class="order-no">{esc(item['orderNo'])}</td>
          <td><strong>{render_route(item['route'])}</strong></td>
          <td>{money(float(item['leftAmt']))}</td>
          <td>{money(float(item['rightAmt']))}</td>
          <td class="diff {'positive' if item['diff'] > 0 else 'negative'}">{signed_money(float(item['diff']))}</td>
        </tr>
        """)

    return f"""
    <div class="actionable-card">
      <div class="actionable-head">
        <div>
          <span class="actionable-badge">价格差异明细</span>
          <h3>竞价高于、低于自动报价的全部订单</h3>
        </div>
        <p class="actionable-desc">共 {len(items)} 单：高于 {higher_count} 单，低于 {lower_count} 单</p>
      </div>
      <div class="table-scroll">
        <table class="actionable-table">
          <thead>
            <tr>
              <th>订单号</th>
              <th>线路</th>
              <th>运力竞价干线价</th>
              <th>自动报价干线价</th>
              <th>差价</th>
            </tr>
          </thead>
          <tbody>
            {"".join(rows)}
          </tbody>
        </table>
      </div>
    </div>
    """

def render_operational_report(
    summary: dict[str, Any],
    diagnostics_by_order: dict[str, dict[str, Any]] | None = None,
) -> str:
    orders = int(summary.get("order_count", 0))
    auto = int(summary.get("auto_offer_order_count", 0))
    full_auto = summary.get("full_auto_offer_order_count")
    full_auto_text = (
        f"其中 {full_auto} 单未标记二次竞价，占全部下单 {pct(full_auto / orders if orders else 0)}。"
        if full_auto is not None else ""
    )
    return f"""
    <div class="business-conclusions">
      <h2>经营概况</h2>
      <ul>
        <li>下单 {orders} 单，自动报价命中 {auto} 单，自动报价率 {pct(auto / orders if orders else 0)}。{full_auto_text}</li>
        <li>成单 {summary.get('deal_order_count', 0)} 单，成单率 {pct(float(summary.get('deal_rate', 0)))}；自动报价 A / 运力竞价 B / 二次竞价 S 成单分别为 {summary.get('auto_offer_deal_count', 0)} / {summary.get('bid_deal_count', 0)} / {summary.get('second_bid_deal_count', 0)} 单。</li>
        <li>有效二次竞价 {summary.get('second_bid_order_count', 0)} 单：持平 {summary.get('second_bid_equal_count', 0)} 单、降价 {summary.get('second_bid_lower_count', 0)} 单、涨价 {summary.get('second_bid_higher_count', 0)} 单，暂不可比 {summary.get('second_bid_uncomparable_count', 0)} 单。</li>
      </ul>
    </div>
    """


def build_html(
    summary: dict[str, Any],
    rows: list[dict[str, Any]],
    bid_groups_by_order: dict[str, list[dict[str, Any]]],
    bid_group_carriers_by_order: dict[str, dict[str, list[dict[str, Any]]]],
    include_operational_report: bool = False,
    trend_metrics: list[dict[str, Any]] | None = None,
    price_trend_comparisons: list[dict[str, Any]] | None = None,
    operating_analysis: dict[str, Any] | None = None,
    analysis_context: dict[str, Any] | None = None,
) -> str:
    if rows or not summary["order_count"]:
        summary = {**summary, **full_auto_quote_metrics(rows)}
    order_count = int(summary["order_count"])
    auto_count = int(summary["auto_offer_order_count"])
    full_auto_count = summary.get("full_auto_offer_order_count")
    full_auto_rate = pct(full_auto_count / order_count if order_count else 0) if full_auto_count is not None else "-"
    full_auto_note = f"全自动报价率 {full_auto_rate}；{numerator_denominator(full_auto_count, order_count)}" if full_auto_count is not None else "缺少订单明细，暂不可计算"
    deal_count = int(summary["deal_order_count"])
    auto_deal = int(summary["auto_offer_deal_count"])
    auto_orders_final_deal = int(summary["auto_offer_orders_deal_count"])
    second_bid = int(summary["second_bid_deal_count"])
    second_bid_order = int(summary.get("second_bid_order_count", 0))
    second_bid_anomaly = int(summary.get("second_bid_mark_anomaly_count", 0))
    auto_offer_rate = pct(float(summary["auto_offer_rate"]), 2)
    auto_quote_deal_contribution_rate = pct(float(summary.get("auto_quote_deal_contribution_rate", 0)), 2)
    manual_bid_deal_contribution_rate = pct(float(summary.get("manual_bid_deal_contribution_rate", 0)), 2)
    corrected_auto_quote_deal_contribution_rate = pct(
        float(summary.get("corrected_auto_quote_deal_contribution_rate", 0)), 2
    )
    corrected_manual_bid_deal_contribution_rate = pct(
        float(summary.get("corrected_manual_bid_deal_contribution_rate", 0)), 2
    )
    corrected_auto_quote_close_rate = pct(float(summary.get("corrected_auto_quote_close_rate", 0)), 2)
    corrected_manual_quote_close_rate = pct(float(summary.get("corrected_manual_quote_close_rate", 0)), 2)
    manual_bid_deal_count = int(summary.get("manual_bid_deal_count", summary.get("bid_deal_count", 0) + second_bid))
    corrected_auto_contribution_deal_count = float(summary.get("corrected_auto_quote_deal_count", 0))
    corrected_manual_contribution_deal_count = float(summary.get("corrected_manual_bid_deal_count", 0))
    corrected_auto_deal_count = float(summary.get("corrected_auto_quote_close_deal_count", 0))
    corrected_manual_deal_count = float(summary.get("corrected_manual_quote_close_deal_count", 0))
    corrected_auto_order_count = float(summary.get("corrected_auto_quote_order_count", 0))
    corrected_manual_order_count = float(summary.get("corrected_manual_quote_order_count", 0))
    trend_metrics = [] if trend_metrics is None else trend_metrics
    price_trend_comparisons = [] if price_trend_comparisons is None else price_trend_comparisons
    trend_period = (
        f"{trend_metrics[0]['date']} 至 {trend_metrics[-1]['date']}"
        if trend_metrics
        else "暂无日报汇总数据"
    )
    line_updates = load_line_update_summary()
    effective_line_update_count = int(line_updates.get("effective_updated_line_count", line_updates.get("effective_updated_main_line_count", 0)))
    effective_line_update_value = str(effective_line_update_count) if line_updates.get("available") else "-"
    second_bid_rate = pct(float(summary.get("second_bid_rate", 0)), 2)
    deal_rate = pct(float(summary["deal_rate"]), 2)
    auto_route_note = f"自动报价覆盖 {summary['auto_offer_route_count']} 条"
    price_compare = build_price_comparison(rows, bid_groups_by_order, bid_group_carriers_by_order)
    diagnostics_by_order: dict[str, dict[str, Any]] = {}
    if ANOMALY_DIAGNOSTICS_PATH.exists():
        diagnostics = json.loads(ANOMALY_DIAGNOSTICS_PATH.read_text(encoding="utf-8"))
        diagnostics_by_order = {str(item.get("orderNo") or ""): item for item in diagnostics}
    page_title = "汽车托运订单自动报价图文分析报告" if include_operational_report else "汽车托运订单自动报价看板"
    page_subtitle = (
        "AI 运营结论、解释、关键图表与详细数据看板"
        if include_operational_report
        else "下单、自动报价、成单与运力竞价的单日运营表现"
    )

    overview_content = f"""
      {render_analysis(operating_analysis, analysis_context) if operating_analysis is not None and analysis_context is not None else render_operational_report(summary) + '<p class="section-note">运营分析待生成；当前展示经营事实。</p>'}
      <div class="business-module"{metric_attr("recent-trend")}>
        <div class="section-head"><h2>最近15天经营趋势</h2><p class="section-note">{esc(trend_period)}，已加载 {len(trend_metrics)}/{TREND_DAY_COUNT} 天</p></div>
        {render_recent_trend(trend_metrics, "overview")}
      </div>
      <div class="business-module table-scroll"{metric_attr("channel-table")}>
        <div class="section-head"><h2>渠道表现</h2><p class="section-note">按下单数量排序</p></div>
        <div class="channel-overview">
          {render_channel_chart(summary)}
          <div class="table-scroll">
            <table class="channel-table">
              <thead><tr><th>渠道</th><th>下单</th><th>自动报价</th><th>全自动报价</th><th>成单</th><th>自动报价率</th><th>全自动报价率</th><th>成单率</th></tr></thead>
              <tbody>{render_channel_rows(summary, rows if rows else None)}</tbody>
            </table>
          </div>
        </div>
      </div>
      <div class="business-module">
        <div class="section-head"><h2>成单方式</h2><p class="section-note">A 自动报价 / B 运力竞价 / S 二次竞价</p></div>
        {render_method_chart(summary)}
      </div>
      {render_detail_block("小时分布", render_hour_chart(rows))}
    """
    auto_content = f"""
      <div class="section-head"><h2>自动报价</h2><p class="section-note">统计当天下单，二次竞价按当前订单标记判断</p></div>
      <div class="kpi-grid">
        {render_kpi("未自动报价订单", str(order_count - auto_count), f"占下单 {pct((order_count - auto_count) / order_count if order_count else 0)}", "bid")}
        {render_kpi("订单涉及线路", str(summary["route_count"]), auto_route_note, "auto", "core-route")}
        {render_kpi("自动报价线路更新数", effective_line_update_value, "按最新子线路更新时间统计有效更新", "auto", "core-auto-line-update")}
      </div>
      <div class="business-module">
        <div class="section-head"><h2>自动报价构成</h2></div>
        {render_pie_chart([("全自动报价", int(full_auto_count)), ("已标记二次竞价", auto_count - int(full_auto_count))], "自动报价构成") if full_auto_count is not None else '<div class="empty-chart">缺少订单明细，暂不可计算</div>'}
      </div>
      <div class="business-module"{metric_attr("auto-quote-trend")}>
        <div class="section-head"><h2>最近15天自动报价趋势</h2><p class="section-note">已加载 {len(trend_metrics)}/{TREND_DAY_COUNT} 天</p></div>
        {render_recent_trend(trend_metrics, "auto")}
      </div>
      <div class="business-module line-update-section"{metric_attr("line-update-summary")}>
        <div class="section-head"><h2>自动报价线路更新</h2></div>
        {render_line_update_section(line_updates)}
      </div>
      <div class="business-module province-section">
        <div class="section-head"><h2>全自动报价省份分布</h2></div>
        {render_province_distribution_section(summary, "province-auto-without-second")}
      </div>
      <a class="data-download" href="matched_orders_{DATE_COMPACT}.csv" download>订单明细 CSV</a>
    """
    second_content = f"""
      <div class="section-head"><h2>二次竞价跟进</h2><p class="section-note">价格状态统计有效二次竞价；销售推送统计操作日志中的手动推送</p></div>
      <div class="kpi-grid">
        {render_kpi("有效二次竞价订单", str(second_bid_order), f"二次竞价占比 {second_bid_rate}；{numerator_denominator(second_bid_order, auto_count)}", "bid", "core-second-bid")}
        {render_kpi("销售手动推送订单", str(summary.get("sales_second_bid_push_order_count", 0)), "自动报价命中且由非系统用户推送，同订单只计一次", "bid")}
        {render_kpi("二次竞价标记异常", str(second_bid_anomaly), "未命中自动报价或自动报价干线价非正数", "rate", "core-second-anomaly")}
      </div>
      <div class="business-module"><div class="section-head"><h2>二次竞价价格状态</h2></div>{render_second_bid_change_chart(summary)}</div>
      <div class="business-module"{metric_attr("second-bid-push-trend")}>
        <div class="section-head"><h2>最近15天二次竞价推送趋势</h2></div>{render_second_bid_push_trend(trend_metrics)}
      </div>
      <div class="business-module sales-second-bid-push-panel"{metric_attr("sales-second-bid-push")}>
        <div class="section-head"><h2>销售手动推送分布</h2><p class="section-note">按订单归属销售统计</p></div>{render_sales_second_bid_push_section(summary)}
      </div>
      <div class="business-module distance-second-bid-push-panel"{metric_attr("distance-second-bid-push")}>
        <div class="section-head"><h2>订单公里数与二次推送</h2></div>{render_distance_second_bid_push_section(summary)}
      </div>
      <div class="business-module route-second-bid-push-panel"{metric_attr("route-second-bid-push")}>
        <div class="section-head"><h2>二次推送线路分布</h2></div>{render_route_second_bid_push_section(summary)}
      </div>
      <div class="business-module province-section">
        <div class="section-head"><h2>二次竞价省份分布</h2></div>{render_province_distribution_section(summary, "province-second-bid")}
      </div>
      <a class="data-download" href="sales_second_bid_push_{DATE_COMPACT}.csv" download>销售二次推送明细 CSV</a>
    """
    deals_content = f"""
      <div class="section-head"><h2>成单与利润</h2><p class="section-note">成单状态与确认运力成本均取本次保存的数据</p></div>
      <div class="section-head"><h3>成单贡献率</h3><p class="section-note">原口径与修正口径对照；分母均为全部下单数</p></div>
      <div class="kpi-grid contribution-grid">
        {render_kpi("自动报价方式成单贡献率", auto_quote_deal_contribution_rate, numerator_denominator(auto_deal, order_count), "auto", "core-auto-close-rate")}
        {render_kpi("人工竞价方式成单贡献率", manual_bid_deal_contribution_rate, numerator_denominator(manual_bid_deal_count, order_count), "bid", "core-manual-close-rate")}
        {render_kpi("自动报价方式成单贡献率（修正）", corrected_auto_quote_deal_contribution_rate, numerator_denominator(corrected_auto_contribution_deal_count, order_count), "auto", "core-corrected-auto-close-rate")}
        {render_kpi("人工竞价方式成单贡献率（修正）", corrected_manual_bid_deal_contribution_rate, numerator_denominator(corrected_manual_contribution_deal_count, order_count), "bid", "core-corrected-manual-close-rate")}
      </div>
      <div class="business-module">
      <div class="section-head"><h3>报价路径成单率</h3><p class="section-note">分母为各路径订单数</p></div>
      <div class="kpi-grid">
        {render_kpi("自动报价成单率（修正）", corrected_auto_quote_close_rate, numerator_denominator(corrected_auto_deal_count, corrected_auto_order_count), "auto", "core-corrected-auto-quote-close-rate")}
        {render_kpi("人工报价成单率（修正）", corrected_manual_quote_close_rate, numerator_denominator(corrected_manual_deal_count, corrected_manual_order_count), "bid", "core-corrected-manual-quote-close-rate")}
      </div>
      </div>
      <div class="business-module"{metric_attr("quote-close-rate-trend")}>
        <div class="section-head"><h2>报价成单率趋势</h2><p class="section-note">自动 / 人工逐单修正归因</p></div>{render_quote_close_rate_trend(trend_metrics)}
      </div>
      <div class="business-module">
        <div class="section-head"><h2>修正后成单归因</h2></div>{render_corrected_deal_attribution_chart(summary)}
      </div>
      <div class="business-module table-scroll"{metric_attr("profit-summary")}>
        <div class="section-head"><h2>销售利润分析</h2><p class="section-note">销售价 - 确认运力成本；仅计有确认成本的已成单订单</p></div>{render_profit_section(summary)}
      </div>
      <div class="business-module">
        <div class="section-head"><h2>转化漏斗</h2></div>
        <div class="funnel-stack">
          {render_funnel_row("下单数量", order_count, order_count, "100.0%", "funnel-order", "funnel-order")}
          {render_funnel_row("成单数量", deal_count, order_count, deal_rate, "funnel-deal", "funnel-deal")}
        </div>
      </div>
    """
    prices_content = f"""
      <div class="section-head"><h2>价格对比</h2><p class="section-note">干线价，不含提送车费；差价 = 竞价 - 自动报价</p></div>
      {render_compare_panel("panel-bid-auto", "自动报价", "竞价高于自动报价明细", "竞价低于自动报价明细", price_compare)}
      <div class="business-module"{metric_attr("price-compare-trend")}>
        <div class="section-head"><h2>最近15天价格对比趋势</h2></div>{render_price_status_trend(price_trend_comparisons, "bid_auto")}
      </div>
      <div class="business-module">
        <div class="section-head"><h2>少数异常线路价差较大，需要优先复核</h2><p class="section-note">按绝对价差排序 Top10</p></div>
        <div class="table-scroll">{render_anomaly_table(price_compare["details"], diagnostics_by_order=diagnostics_by_order)}</div>
      </div>
      <div class="business-module province-section">
        <div class="section-head"><h2>价差订单省份分布</h2></div>{render_province_distribution_section(summary, "province-bid-auto-diff")}
      </div>
    """
    business_panels = "".join(
        render_business_panel(key, content, include_operational_report)
        for key, content in [("overview", overview_content), ("auto", auto_content), ("second", second_content),
                             ("deals", deals_content), ("prices", prices_content)]
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>{ANALYSIS_DATE:%Y-%m-%d} {page_title}</title>
  <style>
    :root {{
      color-scheme: light;
      --page: #f8fafc;
      --surface: #ffffff;
      --surface-subtle: #f8fafc;
      --ink: #0f172a;
      --ink-secondary: #334155;
      --muted: #64748b;
      --line: #e2e8f0;
      --line-soft: #f1f5f9;
      --blue: #2563eb;
      --blue-soft: #eff6ff;
      --blue-dark: #1d4ed8;
      --teal: #0d9488;
      --teal-soft: #f0fdfa;
      --amber: #d97706;
      --amber-soft: #fffbeb;
      --green: #059669;
      --green-soft: #ecfdf5;
      --rose: #e11d48;
      --rose-soft: #fff1f2;
      --violet: #7c3aed;
      --violet-soft: #f5f3ff;
      --shadow-sm: 0 1px 3px rgba(15, 23, 42, 0.05), 0 1px 2px rgba(15, 23, 42, 0.03);
      --shadow: 0 4px 20px -2px rgba(15, 23, 42, 0.06), 0 2px 6px -1px rgba(15, 23, 42, 0.03);
      --shadow-lg: 0 10px 25px -3px rgba(15, 23, 42, 0.08), 0 4px 10px -2px rgba(15, 23, 42, 0.04);
      --radius-sm: 6px;
      --radius: 12px;
      --radius-lg: 16px;
    }}

    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      color: var(--ink);
      background: var(--page);
      line-height: 1.6;
      -webkit-font-smoothing: antialiased;
    }}
    .page {{
      width: min(1380px, calc(100% - 48px));
      margin: 0 auto;
      padding: 32px 0 60px;
    }}
    header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      padding: 0 0 22px;
      border-bottom: 1px solid var(--line);
    }}
    h1 {{
      margin: 0;
      font-size: 28px;
      font-weight: 800;
      line-height: 1.2;
      color: var(--ink);
      letter-spacing: -0.02em;
    }}
    .subtitle {{
      margin: 6px 0 0;
      color: var(--muted);
      font-size: 13.5px;
    }}
    .date-pill {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      border: 1px solid var(--line);
      background: var(--surface);
      border-radius: 999px;
      padding: 8px 16px;
      color: var(--ink-secondary);
      font-size: 13px;
      font-weight: 600;
      box-shadow: var(--shadow-sm);
      white-space: nowrap;
    }}
    .date-pill::before {{
      content: "";
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #10b981;
      box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.2);
    }}
    section {{ margin-top: 26px; }}
    .wide-section {{
      width: 100%;
      margin-left: 0;
    }}

    /* Executive Summary Hero Card */
    .report-section {{
      display: grid;
      gap: 16px;
    }}
    .executive-summary-card {{
      padding: 24px 28px;
      border: 1px solid #bfdbfe;
      border-radius: var(--radius-lg);
      background: linear-gradient(135deg, #ffffff 0%, #f0f7ff 100%);
      box-shadow: var(--shadow);
      position: relative;
      overflow: hidden;
    }}
    .executive-summary-card::before {{
      content: "";
      position: absolute;
      left: 0;
      top: 0;
      bottom: 0;
      width: 5px;
      background: linear-gradient(180deg, var(--blue) 0%, var(--teal) 100%);
    }}
    .executive-summary-badge-row {{
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 12px;
    }}
    .badge-primary {{
      display: inline-flex;
      padding: 4px 10px;
      border-radius: 999px;
      background: var(--blue-soft);
      color: var(--blue);
      font-size: 11.5px;
      font-weight: 700;
      letter-spacing: 0.04em;
      border: 1px solid rgba(37, 99, 235, 0.2);
    }}
    .badge-neutral {{
      font-size: 12px;
      color: var(--muted);
      font-weight: 500;
    }}
    .executive-headline {{
      font-size: 20px;
      font-weight: 800;
      color: var(--ink);
      margin: 0 0 16px;
      line-height: 1.35;
    }}
    .executive-insights-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 16px;
    }}
    .executive-insight-item {{
      display: flex;
      gap: 12px;
      align-items: flex-start;
      padding: 14px 16px;
      background: rgba(255, 255, 255, 0.82);
      border: 1px solid rgba(226, 232, 240, 0.85);
      border-radius: var(--radius);
      backdrop-filter: blur(8px);
    }}
    .insight-icon-dot {{
      width: 10px;
      height: 10px;
      border-radius: 50%;
      flex-shrink: 0;
      margin-top: 5px;
    }}
    .insight-icon-dot.blue {{ background: var(--blue); box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.15); }}
    .insight-icon-dot.amber {{ background: var(--amber); box-shadow: 0 0 0 3px rgba(217, 119, 6, 0.15); }}
    .insight-icon-dot.emerald {{ background: var(--green); box-shadow: 0 0 0 3px rgba(5, 150, 105, 0.15); }}
    .executive-insight-item strong {{
      display: block;
      font-size: 13.5px;
      font-weight: 700;
      color: var(--ink);
      margin-bottom: 4px;
    }}
    .executive-insight-item p {{
      margin: 0;
      color: var(--ink-secondary);
      font-size: 12.5px;
      line-height: 1.55;
    }}
    .executive-insight-item b {{
      color: var(--ink);
    }}

    /* Section Headings */
    .section-head {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: baseline;
      margin-bottom: 12px;
    }}
    h2 {{
      margin: 0;
      font-size: 18px;
      font-weight: 800;
      color: var(--ink);
      letter-spacing: -0.01em;
    }}
    .section-note {{
      margin: 0;
      color: var(--muted);
      font-size: 12.5px;
    }}

    /* Insight Grid */
    .insight-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }}
    .insight {{
      min-height: 96px;
      padding: 16px 20px;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: var(--surface);
      box-shadow: var(--shadow-sm);
      display: flex;
      flex-direction: column;
      justify-content: center;
    }}
    .insight strong {{
      display: block;
      font-size: 18px;
      font-weight: 800;
      color: var(--ink);
      margin-bottom: 4px;
    }}
    .insight p {{
      margin: 0;
      color: var(--muted);
      font-size: 13.5px;
    }}

    /* KPI Grid */
    /* Focus Metrics Showcase Styles */
    .focus-metrics-container {{
      background: #ffffff;
      border: 1px solid var(--line);
      border-radius: var(--radius-lg);
      padding: 20px 24px;
      margin-bottom: 20px;
      box-shadow: 0 4px 16px -2px rgba(15, 23, 42, 0.04);
    }}
    .focus-metrics-header {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 16px;
      padding-bottom: 12px;
      border-bottom: 1px solid var(--line-soft);
    }}
    .focus-metrics-title-row {{
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .focus-pulse-dot {{
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #2563eb;
      box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.2);
    }}
    .focus-badge {{
      font-size: 11px;
      font-weight: 700;
      color: #1d4ed8;
      background: #eff6ff;
      border: 1px solid #bfdbfe;
      padding: 2px 8px;
      border-radius: 9999px;
    }}
    .focus-metrics-title-row h3 {{
      margin: 0;
      font-size: 16px;
      font-weight: 700;
      color: var(--ink);
    }}
    .focus-desc {{
      margin: 0;
      font-size: 12px;
      color: var(--muted);
    }}
    .focus-metrics-grid {{
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 16px;
    }}
    .focus-card {{
      min-width: 0;
      overflow-wrap: anywhere;
      background: #ffffff;
      border: 1.5px solid var(--line);
      border-radius: var(--radius);
      padding: 16px 18px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      position: relative;
      transition: all 0.2s ease;
      box-shadow: 0 2px 8px rgba(15, 23, 42, 0.03);
    }}
    .focus-card:hover {{
      transform: translateY(-2px);
      box-shadow: 0 8px 20px -4px rgba(15, 23, 42, 0.08);
    }}
    .focus-card.auto {{
      border-color: #bfdbfe;
      background: linear-gradient(180deg, #eff6ff 0%, #ffffff 40%);
    }}
    .focus-card.full-auto {{
      border-color: #99f6e4;
      background: #f0fdfa;
    }}
    .focus-card.deal {{
      border-color: #a7f3d0;
      background: linear-gradient(180deg, #ecfdf5 0%, #ffffff 40%);
    }}
    .focus-card.auto-close {{
      border-color: #c7d2fe;
      background: linear-gradient(180deg, #eef2ff 0%, #ffffff 40%);
    }}
    .focus-card.manual-close {{
      border-color: #fed7aa;
      background: linear-gradient(180deg, #fff7ed 0%, #ffffff 40%);
    }}
    .focus-card-top {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 8px;
    }}
    .focus-tag {{
      font-size: 11px;
      font-weight: 700;
      padding: 2px 7px;
      border-radius: 4px;
    }}
    .auto-tag {{ color: #1d4ed8; background: #dbeafe; }}
    .full-auto-tag {{ color: #0f766e; background: #ccfbf1; }}
    .deal-tag {{ color: #047857; background: #d1fae5; }}
    .auto-close-tag {{ color: #4338ca; background: #e0e7ff; }}
    .manual-close-tag {{ color: #c2410c; background: #ffedd5; }}
    .focus-sub-badge {{
      font-size: 11px;
      color: var(--muted);
    }}
    .focus-sub-badge.accent {{
      color: var(--ink-soft);
      font-weight: 600;
    }}
    .focus-card-label {{
      display: block;
      font-size: 13.5px;
      font-weight: 600;
      color: var(--ink);
      margin-bottom: 4px;
    }}
    .focus-card-num-row {{
      margin: 4px 0 8px;
    }}
    .focus-number {{
      font-size: 34px;
      font-weight: 800;
      font-family: var(--font-number);
      letter-spacing: 0;
      line-height: 1;
      display: block;
    }}
    .text-auto {{ color: #1d4ed8; }}
    .text-full-auto {{ color: #0f766e; }}
    .text-deal {{ color: #047857; }}
    .text-auto-close {{ color: #4338ca; }}
    .text-manual-close {{ color: #c2410c; }}
    .focus-card-formula {{
      font-size: 12px;
      color: var(--muted);
      display: flex;
      flex-wrap: wrap;
      align-items: baseline;
      gap: 4px;
    }}
    .formula-fraction {{
      font-weight: 700;
      color: var(--ink-soft);
      font-variant-numeric: tabular-nums;
    }}
    .formula-text {{
      font-size: 11px;
      color: var(--muted);
    }}
    .focus-card-foot {{
      margin-top: 12px;
      padding-top: 10px;
      border-top: 1px dashed var(--line-soft);
      font-size: 11.5px;
      color: var(--muted);
      line-height: 1.35;
    }}
    .focus-card-foot b {{
      color: var(--ink-soft);
    }}
    .focus-comparison-banner {{
      margin-top: 16px;
      padding: 12px 16px;
      background: #f8fafc;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      display: flex;
      align-items: flex-start;
      gap: 12px;
    }}
    .compare-lead-tag {{
      background: #0f172a;
      color: #ffffff;
      font-size: 11px;
      font-weight: 700;
      padding: 3px 8px;
      border-radius: 4px;
      white-space: nowrap;
      margin-top: 2px;
    }}
    .compare-lead-content {{
      font-size: 12.5px;
      color: var(--ink-soft);
      line-height: 1.55;
    }}
    .compare-lead-content b {{
      color: var(--ink);
    }}

    /* KPI Grid Focus Highlight */
    .kpi.kpi-focus {{
      position: relative;
      border: 1.5px solid #bfdbfe;
      background: linear-gradient(180deg, #eff6ff 0%, #ffffff 40%);
      box-shadow: 0 4px 12px -2px rgba(37, 99, 235, 0.08);
    }}
    .kpi.kpi-focus.deal {{
      border-color: #a7f3d0;
      background: linear-gradient(180deg, #ecfdf5 0%, #ffffff 40%);
      box-shadow: 0 4px 12px -2px rgba(5, 150, 105, 0.08);
    }}
    .kpi.kpi-focus.bid {{
      border-color: #fed7aa;
      background: linear-gradient(180deg, #fff7ed 0%, #ffffff 40%);
      box-shadow: 0 4px 12px -2px rgba(217, 119, 6, 0.08);
    }}
    .kpi.kpi-focus.auto.core-corrected-auto {{
      border-color: #c7d2fe;
      background: linear-gradient(180deg, #eef2ff 0%, #ffffff 40%);
      box-shadow: 0 4px 12px -2px rgba(79, 70, 229, 0.08);
    }}
    .kpi-focus-badge {{
      position: absolute;
      top: -7px;
      right: 12px;
      background: #2563eb;
      color: #ffffff;
      font-size: 10px;
      font-weight: 700;
      padding: 1px 7px;
      border-radius: 9999px;
      box-shadow: 0 2px 4px rgba(37, 99, 235, 0.25);
    }}
    .kpi.kpi-focus.deal .kpi-focus-badge {{
      background: #059669;
      box-shadow: 0 2px 4px rgba(5, 150, 105, 0.25);
    }}
    .kpi.kpi-focus.bid .kpi-focus-badge {{
      background: #d97706;
      box-shadow: 0 2px 4px rgba(217, 119, 6, 0.25);
    }}
    .kpi.kpi-focus.auto.core-corrected-auto .kpi-focus-badge {{
      background: #4f46e5;
      box-shadow: 0 2px 4px rgba(79, 70, 229, 0.25);
    }}

    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }}
    .kpi {{
      min-height: 114px;
      padding: 16px 18px;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: var(--surface);
      box-shadow: var(--shadow-sm);
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      transition: transform 120ms ease, box-shadow 120ms ease, border-color 120ms ease;
    }}
    .kpi:hover {{
      transform: translateY(-2px);
      box-shadow: var(--shadow);
      border-color: #cbd5e1;
    }}
    .kpi > .kpi-label {{
      display: inline-flex;
      align-items: center;
      align-self: flex-start;
      gap: 6px;
      color: var(--muted);
      font-size: 12.5px;
      font-weight: 600;
    }}
    .metric-help {{ position: relative; display: inline-flex; flex: 0 0 auto; }}
    .metric-help button {{
      width: 16px;
      height: 16px;
      padding: 0;
      border: 1px solid #cbd5e1;
      border-radius: 50%;
      background: #f8fafc;
      color: var(--muted);
      font: inherit;
      font-size: 11px;
      font-weight: 800;
      line-height: 14px;
      text-align: center;
      cursor: help;
    }}
    .metric-help button:focus-visible {{ outline: 2px solid var(--blue); outline-offset: 2px; }}
    .metric-help-tooltip {{
      position: absolute;
      z-index: 30;
      top: calc(100% + 8px);
      left: 0;
      width: min(320px, calc(100vw - 64px));
      padding: 10px 12px;
      border: 1px solid #cbd5e1;
      border-radius: var(--radius-sm);
      background: #0f172a;
      color: #f8fafc;
      box-shadow: var(--shadow-lg);
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
    .kpi strong {{
      display: block;
      margin-top: 6px;
      font-size: 28px;
      font-weight: 800;
      line-height: 1;
      letter-spacing: -0.02em;
      font-variant-numeric: tabular-nums;
      color: var(--ink);
    }}
    .kpi p {{
      margin: 8px 0 0;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.4;
    }}
    .kpi.auto strong {{ color: #0d9488; }}
    .kpi.deal strong {{ color: var(--blue); }}
    .kpi.bid strong {{ color: var(--amber); }}
    .kpi.rate strong {{ color: var(--violet); }}
    .kpi.order strong {{ color: #1e293b; }}

    /* Panels */
    .panel {{
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: var(--surface);
      box-shadow: var(--shadow-sm);
      padding: 20px;
    }}

    /* Grids */
    .dashboard-grid {{
      display: grid;
      grid-template-columns: minmax(0, 1.25fr) repeat(2, minmax(260px, 0.75fr));
      gap: 14px;
    }}
    .channel-profit-grid {{
      display: grid;
      grid-template-columns: minmax(0, 1.25fr) minmax(360px, 0.75fr);
      gap: 14px;
    }}
    .trend-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
      margin-bottom: 14px;
    }}
    .table-scroll {{ overflow-x: auto; }}
    .echart {{ width: 100%; height: 280px; }}
    .echart.pie-chart {{ height: 245px; }}
    .echart.profit-chart {{ height: 270px; }}
    .empty-chart {{
      min-height: 180px;
      display: grid;
      place-items: center;
      color: var(--muted);
      font-size: 13px;
      background: #f8fafc;
      border: 1px dashed #d0d5dd;
      border-radius: var(--radius);
    }}

    /* Line Update Grid */
    .line-update-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }}
    .line-update-stat {{
      min-height: 96px;
      padding: 14px 18px;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: #f8fafc;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }}
    .line-update-stat span, .line-update-stat small {{ color: var(--muted); font-size: 12px; font-weight: 600; }}
    .line-update-stat strong {{ font-size: 28px; font-weight: 800; line-height: 1; font-variant-numeric: tabular-nums; }}
    .line-update-stat.effective strong {{ color: var(--teal); }}
    .line-update-stat.inactive strong {{ color: var(--rose); }}
    .line-update-stat.total strong {{ color: var(--blue); }}
    .line-update-note {{ margin: 12px 0 0; color: var(--muted); font-size: 12.5px; }}

    /* Funnel Stack */
    .funnel-stack {{
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 6px;
      padding-top: 10px;
    }}
    .funnel-row {{
      width: clamp(120px, var(--funnel-width), 100%);
      min-height: 72px;
    }}
    .funnel-shape {{
      display: grid;
      min-height: inherit;
      place-items: center;
      padding: 10px 14px;
      color: #fff;
      text-align: center;
      border-radius: 8px;
    }}
    .funnel-order .funnel-shape {{
      background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
      box-shadow: 0 4px 12px rgba(37, 99, 235, 0.25);
    }}
    .funnel-deal .funnel-shape {{
      background: linear-gradient(135deg, #059669 0%, #047857 100%);
      box-shadow: 0 4px 12px rgba(5, 150, 105, 0.25);
    }}
    .funnel-label strong {{
      display: block;
      font-size: 13.5px;
      font-weight: 700;
      white-space: nowrap;
    }}
    .funnel-label b {{
      display: block;
      margin-top: 2px;
      font-size: 24px;
      font-weight: 800;
      line-height: 1.1;
      font-variant-numeric: tabular-nums;
    }}
    .funnel-label span {{
      display: block;
      margin-top: 2px;
      color: rgba(255, 255, 255, 0.9);
      font-size: 12px;
      white-space: nowrap;
    }}

    /* Second Bid Section */
    .second-bid-chart {{
      display: grid;
      grid-template-columns: minmax(0, 1.2fr) minmax(240px, 0.8fr);
      gap: 24px;
      align-items: center;
    }}
    .second-bid-bars {{ display: grid; gap: 10px; }}
    .method-item {{
      padding: 8px 0;
      border-top: 1px solid var(--line-soft);
    }}
    .method-item:first-child {{ border-top: 0; }}
    .method-item div:first-child {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 6px;
    }}
    .method-item strong {{
      font-size: 13.5px;
      font-weight: 700;
      color: var(--ink);
    }}
    .method-item span {{
      color: var(--muted);
      font-size: 12.5px;
      font-weight: 600;
      font-variant-numeric: tabular-nums;
    }}
    .bar-track, .mini-track {{
      height: 8px;
      border-radius: 999px;
      background: #f1f5f9;
      overflow: hidden;
    }}
    .bar-track i, .mini-track i {{
      display: block;
      height: 100%;
      border-radius: inherit;
    }}
    .method-auto i, .mini-track.auto i {{ background: var(--teal); }}
    .method-second i {{ background: var(--amber); }}
    .compare-equal i {{ background: var(--blue); }}
    .compare-high i {{ background: var(--rose); }}
    .compare-low i {{ background: var(--green); }}
    .mini-track.order i {{ background: var(--blue); }}

    .sales-second-bid-push-panel {{ margin-top: 14px; }}
    .sales-push-chart-scroll {{ overflow-x: auto; }}
    .sales-push-chart {{ min-width: 760px; }}
    .distance-push-chart {{ min-width: 760px; }}
    .route-second-bid-push-panel {{ margin-top: 14px; }}
    .route-push-chart {{ min-width: 960px; height: 520px; }}
    .route-push-controls {{ display: flex; flex-wrap: wrap; gap: 12px; margin: 14px 0; }}
    .route-push-controls label {{ display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted); }}
    .route-push-controls select, .route-push-controls input {{ min-height: 34px; padding: 5px 8px; border: 1px solid var(--line); border-radius: 4px; background: white; color: var(--ink); font: inherit; }}
    .route-push-controls input {{ width: 160px; }}
    .route-push-table-scroll {{ max-height: 640px; margin-bottom: 12px; overflow: auto; }}
    .channel-table.route-push-table {{ min-width: 1120px; table-layout: fixed; overflow: visible; }}
    .route-rank-col {{ width: 56px; }}
    .route-name-col {{ width: 360px; }}
    .route-count-col {{ width: 96px; }}
    .route-rate-col {{ width: 110px; }}
    .route-sample-col {{ width: 100px; }}
    .route-push-table thead th {{ position: sticky; top: 0; z-index: 1; background: #f8fafc; }}
    .route-push-table th:nth-child(2) {{ text-align: left; white-space: normal; overflow-wrap: anywhere; }}
    .chart-panel {{ margin-top: 14px; }}

    /* Actionable Recommendations Card */
    .actionable-card {{
      margin-bottom: 16px;
      padding: 18px 22px;
      border: 1px solid #fed7aa;
      border-radius: var(--radius);
      background: linear-gradient(135deg, #ffffff 0%, #fffbf5 100%);
      box-shadow: var(--shadow-sm);
    }}
    .actionable-head {{
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: flex-start;
      gap: 16px;
      margin-bottom: 12px;
    }}
    .actionable-badge {{
      display: inline-flex;
      padding: 3px 8px;
      border-radius: 4px;
      background: #ffedd5;
      color: #c2410c;
      font-size: 11px;
      font-weight: 800;
      letter-spacing: 0.05em;
      margin-bottom: 4px;
    }}
    .actionable-head h3 {{
      margin: 0;
      font-size: 16px;
      font-weight: 800;
      color: #9a3412;
    }}
    .actionable-desc {{
      margin: 0;
      color: #7c2d12;
      font-size: 12.5px;
    }}
    .actionable-table {{
      width: 100%;
      min-width: 760px;
      border-collapse: collapse;
      font-size: 12.5px;
      background: #ffffff;
      border-radius: var(--radius-sm);
      overflow: hidden;
      border: 1px solid #fed7aa;
    }}
    .actionable-table th, .actionable-table td {{
      padding: 9px 12px;
      text-align: left;
      border-bottom: 1px solid #fed7aa;
      font-variant-numeric: tabular-nums;
    }}
    .actionable-table thead th {{
      background: #fff7ed;
      color: #9a3412;
      font-weight: 700;
    }}
    .action-tag {{
      display: inline-flex;
      padding: 2px 8px;
      border-radius: 4px;
      background: #fee2e2;
      color: #991b1b;
      font-size: 11.5px;
      font-weight: 600;
    }}

    /* Compare Tabs & Panels */
    .compare-tabs {{
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: var(--surface);
      box-shadow: var(--shadow-sm);
      padding: 16px;
    }}
    .compare-tabs input {{
      position: absolute;
      opacity: 0;
      pointer-events: none;
    }}
    .compare-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }}
    .compare-title {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: baseline;
      margin-bottom: 10px;
    }}
    .compare-title strong {{ font-size: 15px; font-weight: 700; color: var(--ink); }}
    .compare-title span {{ color: var(--muted); font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums; }}
    .compare-row {{
      padding: 10px 0;
      border-top: 1px solid var(--line-soft);
    }}
    .compare-row div:first-child {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 6px;
    }}
    .compare-row span {{ color: var(--muted); font-size: 12.5px; font-variant-numeric: tabular-nums; }}
    .detail-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin-top: 14px;
    }}
    .detail-panel {{ min-width: 0; }}
    .detail-table {{
      width: 100%;
      min-width: 700px;
      border-collapse: collapse;
      font-size: 12px;
    }}
    .detail-table th, .detail-table td {{
      padding: 8px 10px;
      border-bottom: 1px solid var(--line-soft);
      text-align: right;
      white-space: nowrap;
      vertical-align: middle;
      font-variant-numeric: tabular-nums;
    }}
    .detail-table th:first-child, .detail-table td:first-child {{
      text-align: left;
      width: 170px;
    }}
    .detail-table th:nth-child(2), .detail-table td:nth-child(2) {{
      white-space: normal;
      width: 138px;
      min-width: 138px;
    }}
    .detail-table thead th {{
      color: var(--muted);
      font-weight: 700;
      background: #f8fafc;
      position: sticky;
      top: 0;
      z-index: 2;
    }}
    .detail-table tbody th {{
      font-weight: 600;
      color: var(--ink);
    }}
    .diff.positive {{ color: var(--rose); font-weight: 700; }}
    .diff.negative {{ color: var(--green); font-weight: 700; }}
    .deal-tag {{
      display: inline-flex;
      margin-left: 4px;
      padding: 1px 6px;
      border-radius: 999px;
      background: var(--green-soft);
      color: var(--green);
      font-size: 10.5px;
      font-weight: 700;
      vertical-align: middle;
    }}

    /* Channel & Profit Tables */
    .channel-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 12.5px;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      overflow: hidden;
    }}
    .channel-table th, .channel-table td {{
      padding: 9px 12px;
      border-bottom: 1px solid var(--line-soft);
      text-align: right;
      white-space: nowrap;
      font-variant-numeric: tabular-nums;
    }}
    .channel-table th:first-child, .channel-table td:first-child {{ text-align: left; }}
    .channel-table thead th {{
      color: var(--muted);
      background: #f8fafc;
      font-weight: 700;
    }}
    .channel-table tbody th {{ font-weight: 600; }}
    .channel-table tbody tr:hover {{ background: #f8fafc; }}
    .metric-cell {{
      min-width: 100px;
      display: grid;
      grid-template-columns: 32px 1fr;
      gap: 8px;
      align-items: center;
    }}

    /* Province Section */
    .province-section {{
      display: grid;
      gap: 14px;
    }}
    .province-group {{ display: grid; gap: 10px; }}
    .compact-head h3 {{
      margin: 0;
      font-size: 15px;
      font-weight: 700;
      color: var(--ink);
    }}
    .province-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }}
    .province-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 12.5px;
    }}
    .province-table th, .province-table td {{
      padding: 8px 10px;
      border-bottom: 1px solid var(--line-soft);
      text-align: right;
      white-space: nowrap;
      font-variant-numeric: tabular-nums;
    }}
    .province-table th:first-child, .province-table td:first-child {{ text-align: left; }}
    .province-table thead th {{
      color: var(--muted);
      background: #f8fafc;
      font-weight: 700;
    }}
    .province-rate {{
      grid-template-columns: 48px 1fr;
      min-width: 104px;
    }}

    /* Time Distribution */
    .time-grid {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 300px;
      gap: 14px;
    }}
    .hour-series {{
      display: grid;
      grid-template-columns: 68px minmax(0, 1fr);
      gap: 10px;
      align-items: end;
      margin-top: 10px;
    }}
    .hour-series:first-child {{ margin-top: 0; }}
    .hour-series strong {{
      font-size: 12.5px;
      font-weight: 600;
      color: var(--muted);
      padding-bottom: 4px;
    }}
    .hour-bars {{
      height: 48px;
      display: grid;
      grid-template-columns: repeat(24, minmax(0, 1fr));
      gap: 3px;
      align-items: end;
      border-bottom: 1px solid var(--line);
    }}
    .hour-slot {{
      height: 44px;
      display: flex;
      align-items: end;
      justify-content: center;
    }}
    .hour-slot i {{
      width: 100%;
      min-height: 2px;
      border-radius: 2px 2px 0 0;
    }}
    .hour-order {{ background: var(--blue); }}
    .hour-auto {{ background: var(--teal); }}
    .hour-deal {{ background: var(--green); }}
    .hour-bid {{ background: var(--amber); }}
    .hour-axis {{
      margin-left: 78px;
      display: grid;
      grid-template-columns: repeat(8, 1fr);
      gap: 0;
      color: var(--muted);
      font-size: 11px;
      padding-top: 4px;
    }}
    .time-list {{
      display: grid;
      gap: 8px;
      align-content: start;
    }}
    .time-item {{
      padding: 10px 14px;
      border-radius: var(--radius);
      border: 1px solid var(--line);
      background: #f8fafc;
    }}
    .time-item strong {{
      display: block;
      font-size: 12.5px;
      font-weight: 700;
      color: var(--ink);
      margin-bottom: 2px;
    }}
    .time-item span {{
      color: var(--muted);
      font-size: 11.5px;
      font-variant-numeric: tabular-nums;
    }}

    /* Anomaly Table Styles */
    .anomaly-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }}
    .anomaly-table th, .anomaly-table td {{
      padding: 8px 10px;
      border-bottom: 1px solid var(--line-soft);
      text-align: right;
      white-space: nowrap;
    }}
    .anomaly-table th:first-child, .anomaly-table td:first-child {{ text-align: left; }}
    .anomaly-table thead th {{
      color: var(--muted);
      background: #f8fafc;
      font-weight: 700;
    }}
    .anomaly-table .wrap-text {{
      white-space: normal;
      overflow-wrap: anywhere;
      word-break: break-word;
      text-align: left;
    }}


    .route-plain {{
      display: inline-block;
      max-width: 220px;
      white-space: normal;
      line-height: 1.35;
    }}
    .route-split {{
      display: inline-grid;
      grid-template-rows: auto auto auto;
      gap: 2px;
      text-align: center;
      line-height: 1.25;
      width: 100%;
    }}
    .route-split i {{
      color: var(--muted);
      font-style: normal;
      font-size: 12px;
      line-height: 1;
    }}

    footer {{
      margin-top: 28px;
      color: var(--muted);
      font-size: 12px;
      text-align: right;
    }}

    @media (max-width: 1024px) {{
      .focus-metrics-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .dashboard-grid, .channel-profit-grid, .time-grid, .second-bid-chart {{
        grid-template-columns: 1fr;
      }}
      .executive-insights-grid {{
        grid-template-columns: 1fr;
      }}
      .kpi-grid {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
    }}
    @media (max-width: 640px) {{
      .focus-metrics-grid {{ grid-template-columns: minmax(0, 1fr); }}
      .focus-metrics-container {{ padding: 16px; }}
      .focus-metrics-title-row {{ flex-wrap: wrap; }}
      .page {{
        width: calc(100% - 24px);
        padding-top: 20px;
      }}
      header {{ flex-direction: column; align-items: flex-start; gap: 12px; }}
      .sales-second-bid-push-panel .section-head, .distance-second-bid-push-panel .section-head, .route-second-bid-push-panel .section-head {{ flex-direction: column; align-items: flex-start; gap: 8px; }}
      .sales-second-bid-push-panel h3, .distance-second-bid-push-panel h3, .route-second-bid-push-panel h3 {{ margin: 0; letter-spacing: 0; }}
      h1 {{ font-size: 22px; }}
      .kpi-grid, .insight-grid, .province-grid, .line-update-grid, .trend-grid, .compare-grid, .detail-grid {{
        grid-template-columns: 1fr;
      }}
    }}
    [hidden] {{ display: none !important; }}
    * {{ letter-spacing: 0; }}
    .business-summary-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }}
    .summary-item {{ min-width: 0; padding: 20px 24px; border-right: 1px solid var(--line); background: white; }}
    .summary-item:last-child {{ border-right: 0; }}
    .summary-item.full-auto-rate {{ background: #f0fdfa; }}
    .summary-label {{ font-size: 14px; color: var(--muted); }}
    .summary-value {{ display: block; margin: 6px 0; font-size: 32px; line-height: 1.2; color: var(--ink); }}
    .auto-rate .summary-value {{ color: #1d4ed8; }} .full-auto-rate .summary-value {{ color: #0f766e; }} .deal-rate .summary-value {{ color: #047857; }}
    .summary-count,.summary-fraction {{ margin: 4px 0 0; font-size: 12px; overflow-wrap: anywhere; }}
    .summary-fraction {{ color: var(--muted); }}
    .report-actions {{ display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }}
    .report-actions button,.table-tools button {{ border: 1px solid var(--line); background: white; border-radius: 4px; padding: 7px 12px; font: inherit; font-size: 13px; color: var(--ink); cursor: pointer; }}
    .report-actions button[aria-pressed="true"] {{ color: #0f766e; border-color: #0f766e; }}
    .business-navigation {{ position: sticky; top: 0; z-index: 10; background: #f8fafc; border-bottom: 1px solid var(--line); margin-top: 20px; }}
    .business-navigation [role="tablist"] {{ display: flex; overflow-x: auto; }}
    .business-navigation button {{ flex-shrink: 0; padding: 14px 22px; border: 0; border-bottom: 3px solid transparent; background: transparent; color: var(--muted); font: inherit; font-size: 14px; cursor: pointer; white-space: nowrap; }}
    .business-navigation button[aria-selected="true"] {{ color: #0f766e; border-bottom-color: #0f766e; font-weight: 600; }}
    .business-navigation button:focus-visible {{ outline: 2px solid #0f766e; outline-offset: -4px; }}
    .business-panel {{ min-width: 0; outline: none; scroll-margin-top: 60px; }}
    .business-module {{ margin-top: 28px; padding-top: 22px; border-top: 1px solid var(--line); min-width: 0; }}
    .business-conclusions ul {{ margin: 12px 0; padding-left: 20px; font-size: 14px; }}
    .business-conclusions li {{ margin: 6px 0; }}
    .analysis-overall {{ margin: 14px 0 22px; font-size: 15px; line-height: 1.8; }}
    .analysis-columns {{ display: grid; grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr); gap: 32px; }}
    .operating-analysis h3 {{ margin: 0 0 8px; font-size: 14px; line-height: 1.6; overflow-wrap: anywhere; }}
    .analysis-list {{ margin: 0; padding-left: 20px; }}
    .analysis-list > li {{ padding: 14px 0; border-bottom: 1px solid var(--line-soft); }}
    .analysis-list p {{ margin: 6px 0; font-size: 13px; line-height: 1.8; overflow-wrap: anywhere; }}
    .analysis-evidence {{ color: var(--muted); font-variant-numeric: tabular-nums; }}
    .action-priority {{ color: #0f766e; font-size: 12px; }}
    .analysis-limitations {{ margin-top: 22px; color: var(--muted); }}
    .analysis-limitations ul {{ padding-left: 20px; margin: 0; font-size: 12px; line-height: 1.8; }}
    @media (max-width: 900px) {{ .analysis-columns {{ grid-template-columns: minmax(0, 1fr); gap: 24px; }} }}
    .business-panel .panel {{ border: 0; box-shadow: none; padding: 0; border-radius: 0; background: transparent; min-width: 0; }}
    .business-panel .kpi {{ border-radius: 8px; box-shadow: none; }}
    .channel-overview {{ display: grid; grid-template-columns: minmax(240px, 1fr) minmax(0, 2fr); gap: 24px; align-items: center; }}
    .channel-overview .channel-table {{ min-width: 700px; }}
    .business-panel .table-scroll,.channel-scroll {{ max-width: 100%; overflow-x: auto; min-width: 0; }}
    .business-panel .detail-panel > .table-scroll {{ max-height: 360px; overflow: auto; }}
    @media (max-width: 900px) {{ .detail-grid {{ grid-template-columns: minmax(0, 1fr); }} }}
    .business-details {{ margin-top: 20px; padding-top: 14px; border-top: 1px solid var(--line); min-width: 0; }}
    .business-details > summary {{ cursor: pointer; color: var(--ink); font-size: 14px; padding: 6px 0; }}
    .business-details > summary.compare-title {{ display: list-item; }}
    .business-details > summary.compare-title span {{ margin-left: 12px; }}
    .business-details > .kpi-grid {{ margin-top: 16px; }}
    .data-notes {{ margin-top: 32px; padding-top: 20px; border-top: 1px solid var(--line); }}
    .data-notes-columns {{ display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr); gap: 32px; }}
    .data-notes h3 {{ margin: 0 0 12px; font-size: 14px; }}
    .data-notes dl {{ margin: 0; font-size: 13px; line-height: 1.7; }}
    .data-notes dl > div {{ display: grid; grid-template-columns: 90px minmax(0, 1fr); gap: 12px; padding: 8px 0; border-bottom: 1px solid var(--line-soft); }}
    .data-notes dt {{ color: var(--ink); font-weight: 600; }}
    .data-notes dd {{ margin: 0; color: var(--muted); overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }}
    @media (max-width: 900px) {{ .data-notes-columns {{ grid-template-columns: minmax(0, 1fr); gap: 24px; }} }}
    @media (max-width: 640px) {{ .data-notes .record-time-list > div {{ grid-template-columns: minmax(0, 1fr); gap: 2px; }} }}
    .table-tools {{ display: flex; gap: 10px; flex-wrap: wrap; margin: 12px 0; }}
    .table-tools input {{ max-width: 100%; width: 240px; padding: 7px 10px; border: 1px solid var(--line); border-radius: 4px; font: inherit; font-size: 13px; }}
    .price-diff-filter {{ display: flex; align-items: center; flex-wrap: wrap; gap: 6px; font-size: 13px; color: var(--ink); }}
    .price-diff-filter input {{ width: 100px; }}
    .table-tools input[aria-invalid="true"] {{ border-color: #be123c; }}
    .table-tools button:disabled {{ opacity: 0.5; cursor: default; }}
    .table-filter-result {{ flex-basis: 100%; margin: 0; font-size: 12px; color: var(--muted); }}
    .data-download {{ display: inline-block; margin-top: 18px; color: #0f766e; font-size: 13px; }}
    .metric-help-tooltip {{ display: none; position: fixed; left: 16px; right: 16px; top: 16px; width: auto; max-width: 360px; z-index: 30; }}
    .metric-help:hover .metric-help-tooltip,.metric-help:focus-within .metric-help-tooltip {{ display: block; }}
    @media (max-width: 1024px) {{ .channel-overview {{ grid-template-columns: minmax(0, 1fr); }} }}
    @media (max-width: 640px) {{
      .business-summary-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .summary-item {{ padding: 14px 16px; border-bottom: 1px solid var(--line); }}
      .summary-item:nth-child(2n) {{ border-right: 0; }}
      .summary-item:nth-last-child(-n+2) {{ border-bottom: 0; }}
      .summary-value {{ font-size: 28px; }}
      .business-navigation button {{ padding: 12px 16px; }}
      .business-panel .section-head {{ flex-wrap: wrap; }}
      .report-actions {{ width: 100%; }}
    }}
    @media print {{
      body {{ background: white; }} .page {{ width: 100%; padding: 0; }}
      .business-navigation,.report-actions button,.table-tools {{ display: none !important; }}
      .business-panel[hidden] {{ display: block !important; }}
      .business-panel {{ break-before: page; }}
      .table-scroll,.channel-scroll {{ overflow: visible !important; }}
      .business-panel .detail-panel > .table-scroll {{ max-height: none; }}
      .detail-table thead th {{ position: static; }}
      .business-module {{ break-inside: auto; }}
      .echart,.kpi,.summary-item {{ break-inside: avoid; }}
    }}
    </style>
</head>
<body>
  <main class="page" data-report-mode="{str(include_operational_report).lower()}">
    <header>
      <div><h1>{page_title}</h1><p class="subtitle">{page_subtitle}</p></div>
      <div class="report-actions">
        <span class="date-pill">{ANALYSIS_DATE:%Y-%m-%d}</span>
        <button type="button" data-full-report aria-pressed="{str(include_operational_report).lower()}">{"分类查看" if include_operational_report else "完整报告"}</button>
        <button type="button" data-print-report>打印</button>
      </div>
    </header>
    <section class="business-summary" aria-label="经营摘要">
      <div class="section-head"><h2>经营摘要</h2><p class="section-note">按当天下单统计</p></div>
      {render_focus_metrics_showcase(summary)}
    </section>
    {render_business_navigation()}
    {business_panels}
    <section class="data-notes" data-metric="time-range" aria-label="数据口径与时间范围">
      <div class="section-head"><h2>数据口径与时间范围</h2></div>
      <div class="data-notes-columns">
        <div>
          <h3>统计口径</h3>
          <dl>
            <div><dt>订单范围</dt><dd>{ANALYSIS_DATE:%Y-%m-%d} 下单的订单；所有总体比例以这批订单为基础。</dd></div>
            <div><dt>订单状态</dt><dd>成单及二次竞价标记反映本次保存的订单状态。</dd></div>
            <div><dt>未自动报价</dt><dd>包括未匹配到查价记录和查价未命中的订单。</dd></div>
            <div><dt>全自动报价</dt><dd>命中自动报价且未标记二次竞价的订单，不要求成单；全自动报价率 = 全自动报价订单数 / 总下单数。</dd></div>
            <div><dt>成单贡献率</dt><dd>自动报价或人工竞价归因成单数 / 总下单数；路径成单率则以对应路径订单数为分母。</dd></div>
          </dl>
        </div>
        <div>
          <h3>记录时间范围</h3>
          <dl class="record-time-list">
            <div><dt>下单时间</dt><dd>{esc(time_range(rows, "createTime"))}</dd></div>
            <div><dt>自动报价时间</dt><dd>{esc(time_range(rows, "autoOfferTime", lambda row: row["isAutoOffer"]))}</dd></div>
            <div><dt>成单时间</dt><dd>{esc(time_range(rows, "acceptTime", lambda row: row["isDeal"]))}</dd></div>
            <div><dt>运力竞价时间</dt><dd>{esc(time_range(rows, "firstBidTime", lambda row: row["hasBidGroup"]))}</dd></div>
          </dl>
          <p class="section-note">以上为这批订单的事件时间，报价、竞价或成单可能发生在下单日之后。</p>
        </div>
      </div>
    </section>
    <footer>数据来源：DMS 已保存接口数据，{DATE_SHORT}_visual_dashboard.html</footer>
  </main>
  <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
  <script>
    (() => {{
      const chartNodes = Array.from(document.querySelectorAll('.echart[data-chart]'));
      const chartInstances = new Map();
      const initializeCharts = () => {{
        if (!window.echarts) {{
          chartNodes.forEach((node) => {{ node.textContent = 'ECharts 未加载，无法显示图表'; }});
          return;
        }}
        chartNodes.forEach((node) => {{
          if (chartInstances.has(node) || !node.offsetWidth || !node.offsetHeight) return;
          try {{
            const chart = echarts.init(node, null, {{ renderer: 'canvas' }});
            chart.setOption(JSON.parse(node.dataset.chart));
            chartInstances.set(node, chart);
          }} catch (error) {{
            node.classList.add('is-chart-unavailable');
            node.textContent = '图表数据加载失败';
          }}
        }});
      }};
      const resizeCharts = () => {{
        initializeCharts();
        chartInstances.forEach((chart, node) => {{ if (node.offsetWidth && node.offsetHeight) chart.resize(); }});
      }};
      initializeCharts();
      window.addEventListener('resize', resizeCharts);
      document.querySelectorAll('.route-push-explorer').forEach((explorer) => {{
        const rows = JSON.parse(explorer.dataset.routeRows);
        const rank = new Map(rows.map((row, index) => [row.routeKey, index]));
        const totalPushes = rows.reduce((sum, row) => sum + row['二次推送订单数'], 0);
        const limit = explorer.querySelector('[data-route-limit]');
        const scope = explorer.querySelector('[data-route-scope]');
        const sort = explorer.querySelector('[data-route-sort]');
        const minimum = explorer.querySelector('[data-route-min-sample]');
        const search = explorer.querySelector('[data-route-search]');
        const body = explorer.querySelector('tbody');
        const chartNode = explorer.querySelector('.route-push-chart');
        const percent = (value) => `${{(value * 100).toFixed(1)}}%`;
        const escapeText = (value) => {{
          const span = document.createElement('span');
          span.textContent = value;
          return span.innerHTML;
        }};
        const render = () => {{
          const term = search.value.trim().toLowerCase();
          const candidates = rows.filter((row) =>
            row['自动报价订单数'] >= Number(minimum.value) &&
            (scope.value === 'auto' || row['二次推送订单数'] > 0) &&
            row['线路'].toLowerCase().includes(term)
          ).sort((a, b) =>
            (sort.value === 'rate' ? b['二次推送率'] - a['二次推送率'] : 0) ||
            b['二次推送订单数'] - a['二次推送订单数'] ||
            b['自动报价订单数'] - a['自动报价订单数'] || rank.get(a.routeKey) - rank.get(b.routeKey)
          );
          const visible = limit.value === 'all' ? candidates : candidates.slice(0, Number(limit.value));
          const shownPushes = visible.reduce((sum, row) => sum + row['二次推送订单数'], 0);
          explorer.querySelector('.route-push-result').textContent =
            `展示 ${{visible.length}}/${{candidates.length}} 条线路，涉及 ${{shownPushes}} 单推送，占全部二次推送 ${{totalPushes ? percent(shownPushes / totalPushes) : '-'}}`;
          body.replaceChildren();
          visible.forEach((row, index) => {{
            const tr = document.createElement('tr');
            tr.dataset.routeKey = row.routeKey;
            const values = [index + 1, row['线路'], row['总订单数'], row['自动报价订单数'],
              row['二次推送订单数'], row['未二次推送订单数'], percent(row['二次推送率']),
              totalPushes ? percent(row['推送分布占比']) : '-', row['自动报价订单数'] < 5 ? '样本较少' : '-'];
            values.forEach((value, column) => {{
              const cell = document.createElement(column === 1 ? 'th' : 'td');
              cell.textContent = String(value);
              tr.appendChild(cell);
            }});
            body.appendChild(tr);
          }});
          if (!visible.length) {{
            const tr = document.createElement('tr');
            const cell = document.createElement('td');
            cell.colSpan = 9;
            cell.textContent = '暂无符合条件的线路';
            tr.appendChild(cell);
            body.appendChild(tr);
          }}
          const chart = window.echarts && echarts.getInstanceByDom(chartNode);
          if (chart) {{
            chart.setOption({{
              title: {{ text: visible.length ? '' : '暂无符合条件的线路', left: 'center', top: 'middle', textStyle: {{ fontSize: 14 }} }},
              yAxis: {{ data: visible.map((row) => row['线路']) }},
              dataZoom: [{{ start: 0, end: Math.min(100, 15 / Math.max(visible.length, 1) * 100) }}],
              series: [
                {{ data: visible.map((row) => row['二次推送订单数']) }},
                {{ data: visible.map((row) => row['未二次推送订单数']) }},
                {{ data: visible.map((row, i) => [Number((row['二次推送率'] * 100).toFixed(1)), i]) }}
              ],
              tooltip: {{ formatter: (params) => {{
                const row = visible[params[0]?.dataIndex];
                return row ? `${{escapeText(row['线路'])}}<br>自动报价订单：${{row['自动报价订单数']}}<br>二次推送：${{row['二次推送订单数']}}<br>推送率：${{percent(row['二次推送率'])}}` : '';
              }} }}
            }});
          }}
        }};
        [limit, scope, sort, minimum].forEach((control) => control.addEventListener('change', render));
        search.addEventListener('input', render);
        render();
      }});
      const tabs = [...document.querySelectorAll('[data-business-tab]')];
      const panels = [...document.querySelectorAll('[data-business-panel]')];
      const fullButton = document.querySelector('[data-full-report]');
      const main = document.querySelector('main');
      let fullReport = main.dataset.reportMode === 'true';
      let activeTab = 'overview';
      const showView = () => {{
        main.dataset.reportMode = String(fullReport);
        panels.forEach((panel) => {{ panel.hidden = !fullReport && panel.dataset.businessPanel !== activeTab; }});
        tabs.forEach((tab) => {{
          const selected = tab.dataset.businessTab === activeTab;
          tab.setAttribute('aria-selected', String(selected));
          tab.tabIndex = selected ? 0 : -1;
        }});
        fullButton.setAttribute('aria-pressed', String(fullReport));
        fullButton.textContent = fullReport ? '分类查看' : '完整报告';
        requestAnimationFrame(resizeCharts);
      }};
      const selectTab = (tab) => {{
        activeTab = tab.dataset.businessTab;
        fullReport = false;
        showView();
        tab.scrollIntoView({{block: 'nearest', inline: 'nearest'}});
      }};
      tabs.forEach((tab, index) => {{
        tab.addEventListener('click', () => selectTab(tab));
        tab.addEventListener('keydown', (event) => {{
          let target;
          if (event.key === 'ArrowRight') target = tabs[(index + 1) % tabs.length];
          if (event.key === 'ArrowLeft') target = tabs[(index + tabs.length - 1) % tabs.length];
          if (event.key === 'Home') target = tabs[0];
          if (event.key === 'End') target = tabs[tabs.length - 1];
          if (target) {{ event.preventDefault(); selectTab(target); target.focus(); }}
        }});
      }});
      fullButton.addEventListener('click', () => {{ fullReport = !fullReport; showView(); }});
      document.querySelectorAll('details').forEach((detail) => detail.addEventListener('toggle', resizeCharts));
      document.querySelectorAll('.business-details').forEach((detail) => {{
        const table = detail.querySelector('table');
        if (!table) return;
        const tools = document.createElement('div');
        tools.className = 'table-tools';
        const search = document.createElement('input');
        search.type = 'search';
        search.placeholder = '搜索订单或线路';
        search.setAttribute('aria-label', '搜索明细');
        const download = document.createElement('button');
        download.type = 'button';
        download.textContent = '导出 CSV';
        tools.append(search);
        let threshold;
        let filterResult;
        if (table.classList.contains('detail-table')) {{
          const label = document.createElement('label');
          label.className = 'price-diff-filter';
          threshold = document.createElement('input');
          threshold.type = 'number';
          threshold.min = '0';
          threshold.step = 'any';
          threshold.placeholder = '不限';
          threshold.setAttribute('aria-label', '差价绝对值大于（元）');
          label.append('差价绝对值大于', threshold, '元');
          tools.append(label);
          filterResult = document.createElement('p');
          filterResult.className = 'table-filter-result';
          filterResult.setAttribute('aria-live', 'polite');
        }}
        tools.append(download);
        if (filterResult) tools.append(filterResult);
        detail.querySelector('summary').after(tools);
        const applyFilters = () => {{
          const term = search.value.trim().toLowerCase();
          const hasThreshold = threshold && threshold.value !== '';
          const amount = hasThreshold ? Number(threshold.value) : 0;
          const valid = !threshold || (threshold.validity.valid && Number.isFinite(amount));
          if (threshold) threshold.setAttribute('aria-invalid', String(!valid));
          const rows = [...table.querySelectorAll('tbody tr')];
          rows.forEach((row) => {{
            const matchesAmount = !hasThreshold || Math.abs(Number(row.dataset.priceDiff)) > amount;
            row.hidden = !valid || !matchesAmount || !row.textContent.toLowerCase().includes(term);
          }});
          if (filterResult) {{
            const count = rows.filter((row) => !row.hidden).length;
            filterResult.textContent = valid ? `符合筛选 ${{count}} / 共 ${{rows.length}} 单` : '请输入大于等于 0 的金额';
            download.disabled = count === 0;
          }}
        }};
        search.addEventListener('input', applyFilters);
        if (threshold) {{ threshold.addEventListener('input', applyFilters); applyFilters(); }}
        download.addEventListener('click', () => {{
          const escapeCell = (cell) => {{
            let value = cell.innerText.trim();
            if (/^[=+@-]/.test(value)) value = "'" + value;
            return '"' + value.replaceAll('"', '""') + '"';
          }};
          const csv = [...table.querySelectorAll('tr')].filter((row) => !row.hidden)
            .map((row) => [...row.children].map(escapeCell).join(',')).join('\\r\\n');
          const url = URL.createObjectURL(new Blob(['\ufeff' + csv], {{type: 'text/csv;charset=utf-8'}}));
          const link = document.createElement('a');
          link.href = url;
          link.download = '订单明细_{DATE_COMPACT}.csv';
          link.click();
          setTimeout(() => URL.revokeObjectURL(url), 1000);
        }});
      }});
      let printState;
      window.addEventListener('beforeprint', () => {{
        printState = {{fullReport, details: [...document.querySelectorAll('details')].map((node) => [node, node.open]), rows: [...document.querySelectorAll('tbody tr')].map((node) => [node, node.hidden])}};
        fullReport = true;
        printState.details.forEach(([node]) => {{ node.open = true; }});
        printState.rows.forEach(([node]) => {{ node.hidden = false; }});
        showView();
        resizeCharts();
      }});
      window.addEventListener('afterprint', () => {{
        if (!printState) return;
        fullReport = printState.fullReport;
        printState.details.forEach(([node, open]) => {{ node.open = open; }});
        printState.rows.forEach(([node, hidden]) => {{ node.hidden = hidden; }});
        showView();
      }});
      document.querySelector('[data-print-report]').addEventListener('click', () => window.print());
      showView();
    }})();
  </script>
</body>
</html>
"""


def main() -> None:
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    rows = json.loads(ROWS_PATH.read_text(encoding="utf-8"))
    bid_groups_by_order = json.loads(BID_GROUPS_PATH.read_text(encoding="utf-8"))
    bid_group_carriers_by_order = json.loads(BID_GROUP_CARRIERS_PATH.read_text(encoding="utf-8"))
    trend_metrics = load_recent_trend_metrics()
    price_trend_comparisons = load_recent_price_trend_comparisons()
    normalized_summary = {**summary, **full_auto_quote_metrics(rows)}
    if summary.get("date") != ANALYSIS_DATE.strftime("%Y-%m-%d"):
        raise ValueError("汇总日期与页面日期不一致")
    diagnostics = json.loads(ANOMALY_DIAGNOSTICS_PATH.read_text(encoding="utf-8")) if ANOMALY_DIAGNOSTICS_PATH.exists() else []
    context = build_context(
        normalized_summary, trend_metrics,
        build_price_comparison(rows, bid_groups_by_order, bid_group_carriers_by_order),
        {str(item.get("orderNo") or ""): item for item in diagnostics}, load_line_update_summary(),
        source_snapshot={"summary": summary, "orders": rows, "bidGroups": bid_groups_by_order,
                         "bidGroupCarriers": bid_group_carriers_by_order},
    )
    ANALYSIS_CONTEXT_PATH.write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8")
    operating_analysis = None
    if OPERATING_ANALYSIS_PATH.exists():
        try:
            candidate = json.loads(OPERATING_ANALYSIS_PATH.read_text(encoding="utf-8"))
            validate_analysis(candidate, context)
            operating_analysis = candidate
        except (OSError, ValueError) as exc:
            print(f"运营分析未采用：{exc}")
    OUTPUT_PATH.write_text(
        build_html(
            summary,
            rows,
            bid_groups_by_order,
            bid_group_carriers_by_order,
            trend_metrics=trend_metrics,
            price_trend_comparisons=price_trend_comparisons,
            operating_analysis=operating_analysis,
            analysis_context=context,
        ),
        encoding="utf-8",
    )
    ANALYSIS_REPORT_OUTPUT_PATH.write_text(
        build_html(
            summary,
            rows,
            bid_groups_by_order,
            bid_group_carriers_by_order,
            include_operational_report=True,
            trend_metrics=trend_metrics,
            price_trend_comparisons=price_trend_comparisons,
            operating_analysis=operating_analysis,
            analysis_context=context,
        ),
        encoding="utf-8",
    )
    print(f"wrote {OUTPUT_PATH}")
    print(f"wrote {ANALYSIS_REPORT_OUTPUT_PATH}")
    print(f"wrote {ANALYSIS_CONTEXT_PATH}")
    print("运营分析：已校验并展示" if operating_analysis else "运营分析：待 AI 生成，参照已安装 skill 的 references/operational-analysis.md")


if __name__ == "__main__":
    main()
