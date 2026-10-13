"""Evidence-bound inputs and saved AI commentary for the daily dashboard."""

from __future__ import annotations

import hashlib
import html
import json
from datetime import datetime
from typing import Any


def build_context(summary, trend, comparison, diagnoses, line_updates, source_snapshot=None):
    facts: dict[str, dict[str, Any]] = {}

    def add(key, label, value, unit="单"):
        facts[key] = {"label": label, "value": value, "unit": unit}

    def rate(key, label, numerator, denominator):
        facts[key] = {"label": label, "value": numerator / denominator if denominator else None,
                      "unit": "%", "numerator": numerator, "denominator": denominator}

    labels = {
        "order_count": "下单", "auto_offer_order_count": "自动报价订单",
        "full_auto_offer_order_count": "全自动报价订单", "deal_order_count": "成单",
        "second_bid_order_count": "有效二次竞价订单", "second_bid_equal_count": "二次竞价持平",
        "second_bid_higher_count": "二次竞价涨价", "second_bid_lower_count": "二次竞价降价",
        "second_bid_uncomparable_count": "二次竞价暂不可比",
        "second_bid_mark_anomaly_count": "二次竞价标记异常",
        "sales_second_bid_push_order_count": "日志确认销售手动推送订单",
        "sales_second_bid_push_route_count": "手动推送涉及线路",
        "sales_second_bid_push_single_order_route_count": "仅推送一单的线路",
    }
    for key, label in labels.items():
        if key in summary:
            add(key, label, summary[key], "条" if "route_count" in key else "单")
    total = summary["order_count"]
    for key, label, count_key in [
        ("auto_rate", "自动报价率", "auto_offer_order_count"),
        ("full_auto_rate", "全自动报价率", "full_auto_offer_order_count"),
        ("deal_rate", "成单率", "deal_order_count"),
    ]:
        if count_key in summary:
            rate(key, label, summary[count_key], total)
    if "full_auto_offer_order_count" in summary:
        marked = summary["auto_offer_order_count"] - summary["full_auto_offer_order_count"]
        add("auto_hit_s_count", "自动报价命中且标记二次竞价", marked)
        rate("auto_hit_s_rate", "自动报价中二次竞价标记占比", marked, summary["auto_offer_order_count"])
    for path, name in [("auto", "自动报价"), ("manual", "人工报价")]:
        key = f"corrected_{path}_quote_close_rate"
        if key in summary:
            numerator = summary.get(f"corrected_{path}_quote_close_deal_count")
            denominator = summary.get(f"corrected_{path}_quote_order_count")
            if numerator is not None and denominator is not None:
                rate(key, f"{name}路径成单率（修正）", numerator, denominator)
            else:
                add(key, f"{name}路径成单率（修正）", summary[key], "%")
    for key, label, numerator_key in [
        ("auto_contribution", "自动报价成单贡献率", "auto_offer_deal_count"),
        ("manual_contribution", "人工竞价成单贡献率", "manual_bid_deal_count"),
        ("corrected_auto_contribution", "自动报价成单贡献率（修正）", "corrected_auto_quote_deal_count"),
        ("corrected_manual_contribution", "人工竞价成单贡献率（修正）", "corrected_manual_bid_deal_count"),
    ]:
        if numerator_key in summary:
            rate(key, label, summary[numerator_key], total)
    for day in trend:
        for key, label, unit in [("order_count", "下单", "单"), ("auto_offer_rate", "自动报价率", "%"),
                                  ("full_auto_offer_rate", "全自动报价率", "%"), ("deal_rate", "成单率", "%")]:
            if key in day:
                add(f"history_{day['date']}_{key}", f"{day['date']}·{label}", day[key], unit)
    for i, channel in enumerate(sorted(summary.get("by_channel", []), key=lambda r: -r["下单数量"])):
        for field, label in [("下单数量", "下单"), ("自动报价订单数量", "自动报价订单"),
                             ("全自动报价订单数量", "全自动报价订单"), ("成单数量", "成单")]:
            if field in channel:
                add(f"channel_{i}_{field}", f"{channel['渠道']}·{label}", channel[field])
        rate(f"channel_{i}_deal_rate", f"{channel['渠道']}·成单率", channel["成单数量"], channel["下单数量"])
    for mode, name in [("auto_quote", "自动报价利润样本"), ("manual_quote", "人工竞价利润样本")]:
        for field, label, unit in [("order_count", "订单", "单"), ("sales_amount", "销售额", "元"),
                                   ("carrier_cost", "运力成本", "元"), ("total_profit", "利润", "元"),
                                   ("avg_profit", "单均利润", "元"), ("profit_rate", "利润率", "%")]:
            value = summary.get("profit_by_quote_mode", {}).get(mode, {}).get(field)
            if value is not None:
                add(f"profit_{mode}_{field}", f"{name}·{label}", value, unit)
    for status in ["total", "高于", "低于", "持平"]:
        if status in comparison.get("overall", {}):
            add(f"price_{status}", "全量可比订单" if status == "total" else f"竞价{status}自动报价", comparison["overall"][status])
    anomalies = sorted(comparison.get("details", []), key=lambda r: -abs(r["diff"]))[:10]
    if anomalies:
        add("price_max_abs_diff", "最大干线差价绝对值", abs(anomalies[0]["diff"]), "元")
    context = {
        "schemaVersion": 1, "date": summary["date"], "facts": facts,
        "history": trend,
        "dimensions": {key: summary.get(key, []) for key in [
            "by_channel", "sales_second_bid_push_by_owner", "sales_second_bid_push_by_distance",
            "sales_second_bid_push_by_route", "second_bid_start_province_distribution",
            "second_bid_end_province_distribution"]},
        "anomalies": [{"orderNo": r["orderNo"], "route": r["route"], "diff": r["diff"],
                       "diagnosis": diagnoses.get(r["orderNo"], {})} for r in anomalies],
        "lineUpdates": line_updates,
        "limitations": ["订单状态和价格来自保存快照，分析生成时间不是数据刷新时间。",
                        "历史成单结果的观察时长可能不同，不据此断言当天转化变差。",
                        "二次竞价标记与日志确认的销售手动推送是不同口径，不能混用。"],
    }
    if source_snapshot is not None:
        context["sourceFingerprint"] = hashlib.sha256(
            json.dumps(source_snapshot, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
        ).hexdigest()
    context["dataFingerprint"] = hashlib.sha256(
        json.dumps(context, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()
    return context


def validate_analysis(report, context):
    if not isinstance(report, dict) or report.get("date") != context["date"] or report.get("dataFingerprint") != context["dataFingerprint"]:
        raise ValueError("运营分析与当前数据不一致，需要重新生成")

    def text(value):
        if not isinstance(value, str) or not value.strip() or len(value) > 800:
            raise ValueError("运营分析文本缺失或过长")

    text(report.get("overall"))
    text(report.get("generatedAt"))
    try:
        if datetime.fromisoformat(report["generatedAt"]).tzinfo is None:
            raise ValueError("分析生成时间需要时区")
    except (TypeError, ValueError) as exc:
        raise ValueError("分析生成时间必须是含时区的 ISO 时间") from exc
    conclusions, actions = report.get("conclusions"), report.get("actions")
    if not isinstance(conclusions, list) or not 1 <= len(conclusions) <= 5:
        raise ValueError("运营结论需要 1 到 5 条")
    if not isinstance(actions, list) or len(actions) > 3:
        raise ValueError("优先行动最多 3 条")
    ids = set()
    for item in conclusions:
        if not isinstance(item, dict):
            raise ValueError("结论格式不正确")
        for key in ["id", "title", "interpretation"]:
            text(item.get(key))
        if item["id"] in ids:
            raise ValueError("结论 ID 重复")
        ids.add(item["id"])
        evidence = item.get("evidence")
        if not isinstance(evidence, list) or not evidence or any(not isinstance(key, str) or key not in context["facts"] for key in evidence):
            raise ValueError("结论必须引用存在的指标证据")
    for item in actions:
        if not isinstance(item, dict) or item.get("priority") not in ["P1", "P2", "P3"]:
            raise ValueError("行动优先级需要 P1、P2 或 P3")
        for key in ["target", "action", "verification"]:
            text(item.get(key))
        related = item.get("relatedConclusions")
        if not isinstance(related, list) or not related or any(not isinstance(key, str) or key not in ids for key in related):
            raise ValueError("行动必须关联已有结论")
    limitations = report.get("limitations", [])
    if not isinstance(limitations, list) or len(limitations) > 3:
        raise ValueError("数据限制最多 3 条")
    for value in limitations:
        text(value)


def evidence_text(fact):
    value, unit = fact["value"], fact["unit"]
    if value is None:
        return f"{fact['label']}：暂无有效样本"
    display = f"{value * 100:.1f}%" if unit == "%" else f"{value:,.0f} {unit}"
    if "denominator" in fact:
        display += f"（分子 {fact['numerator']} / 分母 {fact['denominator']}）"
    return f"{fact['label']}：{display}"


def render_analysis(report, context):
    validate_analysis(report, context)
    escape = lambda value: html.escape(str(value), quote=True)
    conclusions = "".join(
        f'<li><h3>{escape(item["title"])}</h3><p class="analysis-evidence">'
        + escape("；".join(evidence_text(context["facts"][key]) for key in item["evidence"]))
        + f'</p><p>{escape(item["interpretation"])}</p></li>' for item in report["conclusions"]
    )
    actions = "".join(
        f'<li><h3><span class="action-priority">{escape(item["priority"])}</span> {escape(item["target"])}</h3>'
        f'<p>{escape(item["action"])}</p><p class="analysis-evidence">后续观察：{escape(item["verification"])}</p></li>'
        for item in sorted(report["actions"], key=lambda item: item["priority"])
    )
    limitations = "".join(f'<li>{escape(value)}</li>' for value in report.get("limitations", []))
    return (
        '<section class="operating-analysis" aria-label="运营分析">'
        f'<div class="section-head"><h2>运营分析</h2><p class="section-note">AI 分析 · {escape(report["date"])}</p></div>'
        f'<p class="analysis-overall">{escape(report["overall"])}</p>'
        '<div class="analysis-columns"><div><h3>运营结论</h3><ol class="analysis-list">'
        f'{conclusions}</ol></div><div><h3>优先行动</h3><ol class="analysis-list">'
        f'{actions or "<li>暂无需要优先处理的行动。</li>"}</ol></div></div>'
        + (f'<div class="analysis-limitations"><h3>数据说明</h3><ul>{limitations}</ul></div>' if limitations else "")
        + f'<p class="section-note">分析生成时间：{escape(report["generatedAt"])}</p></section>'
    )
