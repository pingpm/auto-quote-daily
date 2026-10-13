from __future__ import annotations

import csv
import json
import os
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests


ROOT = Path(os.environ.get("AUTO_QUOTE_WORKSPACE", Path.cwd())).expanduser().resolve()
BASE_URL = os.environ.get("DMS_BASE_URL", "https://dms.iyunche.com").rstrip("/")
LINE_LIST_URL = f"{BASE_URL}/dms-boot/autoBidLine/getLineList"
PAGE_SIZE = 1000
ANALYSIS_DATE = datetime.strptime(os.environ.get("ANALYSIS_DATE", "2026-09-16"), "%Y-%m-%d")
DATE_COMPACT = ANALYSIS_DATE.strftime("%Y%m%d")
DATE_SHORT = ANALYSIS_DATE.strftime("%m%d")
OUT_DIR = ROOT / "outputs" / f"{DATE_SHORT}_auto_bid_line_updates"


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\u3000", " ").strip()


def parse_dt(value: Any) -> datetime | None:
    text = clean_text(value)
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def safe_int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def request_json(session: requests.Session, payload: dict[str, Any]) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = session.post(LINE_LIST_URL, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            if data.get("success"):
                return data
            raise RuntimeError(f"API returned success=false: {data}")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"line list request failed: {last_error}")


def fetch_all_line_list(session: requests.Session) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    page = 1
    pages = 1
    while page <= pages:
        data = request_json(session, {"page": page, "pageSize": PAGE_SIZE, "linePriceNo": None})
        result = data.get("result") or {}
        records.extend(result.get("records") or [])
        pages = int(result.get("pages") or 1)
        print(f"fetched line list {page}/{pages}, records={len(records)}", flush=True)
        page += 1
    return records


def line_identity(row: dict[str, Any]) -> str:
    return clean_text(row.get("pkId") or row.get("lineNo")) or "|".join(
        clean_text(row.get(field))
        for field in ("startProvId", "startCityId", "endProvId", "endCityId")
    )


def route_label(row: dict[str, Any]) -> str:
    return (
        f"{clean_text(row.get('startProvName'))}{clean_text(row.get('startCityName'))}"
        f" -> {clean_text(row.get('endProvName'))}{clean_text(row.get('endCityName'))}"
    )


def price_summary(row: dict[str, Any]) -> str:
    parts = []
    for item in row.get("minLinePrice") or []:
        label = clean_text(item.get("lineTypeText"))
        price = item.get("unitPrice")
        if label and price not in (None, ""):
            parts.append(f"{label} {float(price):,.0f}")
    return "；".join(parts)


def is_effective(row: dict[str, Any]) -> bool:
    return safe_int(row.get("status")) == 1 and safe_int(row.get("isExist")) == 1


def main_line_update_time(row: dict[str, Any]) -> datetime | None:
    return parse_dt(row.get("modifyTime"))


def child_line_update_time(row: dict[str, Any]) -> datetime | None:
    return parse_dt(row.get("linePriceModifyTime"))


def update_time(row: dict[str, Any]) -> datetime | None:
    """Use the latest child-price update; use the main-line time on ties or as fallback."""
    main_time = main_line_update_time(row)
    child_time = child_line_update_time(row)
    if main_time is not None and (child_time is None or main_time >= child_time):
        return main_time
    return child_time


def update_time_source(row: dict[str, Any]) -> str:
    main_time = main_line_update_time(row)
    child_time = child_line_update_time(row)
    if main_time is not None and (child_time is None or main_time >= child_time):
        return "主线路"
    if child_time is not None:
        return "最新子线路"
    return ""


def latest_by_main_line(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = line_identity(row)
        previous = latest.get(key)
        if previous is None or (update_time(row) or datetime.min) > (update_time(previous) or datetime.min):
            latest[key] = row
    return list(latest.values())


def detail_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "主线路号": clean_text(row.get("lineNo")),
        "主线路pkId": clean_text(row.get("pkId")),
        "线路": route_label(row),
        "统计更新时间": clean_text(update_time(row).strftime("%Y-%m-%d %H:%M:%S") if update_time(row) else ""),
        "时间来源": update_time_source(row),
        "主线路更新时间": clean_text(row.get("modifyTime")),
        "最新子线路更新时间": clean_text(row.get("linePriceModifyTime")),
        "主线路创建时间": clean_text(row.get("createTime")),
        "主线路更新人": clean_text(row.get("modifyUserName")),
        "有效状态": "有效" if is_effective(row) else "已停用线路",
        "线路价格摘要": price_summary(row),
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    raw_snapshot_path = clean_text(os.environ.get("AUTO_BID_LINE_RAW_SNAPSHOT_PATH"))
    if raw_snapshot_path:
        snapshot = Path(raw_snapshot_path)
        raw_rows = json.loads(snapshot.read_text(encoding="utf-8"))
        if not isinstance(raw_rows, list):
            raise RuntimeError("AUTO_BID_LINE_RAW_SNAPSHOT_PATH must contain a JSON array")
        print(f"loaded line list snapshot records={len(raw_rows)}", flush=True)
    else:
        token = clean_text(os.environ.get("DMS_ACCESS_TOKEN"))
        if not token:
            raise RuntimeError("DMS_ACCESS_TOKEN is required when no raw snapshot is supplied")
        session = requests.Session()
        session.headers.update({"x-access-token": token, "Content-Type": "application/json"})
        raw_rows = fetch_all_line_list(session)
    (OUT_DIR / f"raw_auto_bid_line_list_{DATE_COMPACT}.json").write_text(
        json.dumps(raw_rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    start = ANALYSIS_DATE
    end = start + timedelta(days=1)
    date_matches = [
        row for row in raw_rows if (updated_at := update_time(row)) is not None and start <= updated_at < end
    ]
    updated_lines = latest_by_main_line(date_matches)
    effective_lines = [row for row in updated_lines if is_effective(row)]
    inactive_lines = [row for row in updated_lines if not is_effective(row)]
    effective_details = sorted((detail_row(row) for row in effective_lines), key=lambda item: item["统计更新时间"], reverse=True)
    inactive_details = sorted((detail_row(row) for row in inactive_lines), key=lambda item: item["统计更新时间"], reverse=True)
    updater_counts = Counter(item["主线路更新人"] or "未记录" for item in effective_details)

    summary = {
        "date": start.strftime("%Y-%m-%d"),
        "time_window": f"{start:%Y-%m-%d 00:00:00} ~ {end:%Y-%m-%d 00:00:00}（左闭右开）",
        "source": "POST /dms-boot/autoBidLine/getLineList 全量分页后按最新子线路 linePriceModifyTime 优先、主线路 modifyTime 同时或更晚时优先过滤",
        "raw_main_line_records": len(raw_rows),
        "matched_records_before_dedup": len(date_matches),
        "updated_main_line_count": len(updated_lines),
        "effective_updated_line_count": len(effective_lines),
        "inactive_or_missing_updated_line_count": len(inactive_lines),
        "effective_updated_main_line_count": len(effective_lines),
        "inactive_or_missing_updated_main_line_count": len(inactive_lines),
        "updater_counts": dict(updater_counts.most_common()),
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    result = {"summary": summary, "effective_updates": effective_details, "inactive_updates": inactive_details}
    (OUT_DIR / f"summary_{DATE_COMPACT}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(OUT_DIR / f"effective_main_line_updates_{DATE_COMPACT}.csv", effective_details)
    write_csv(OUT_DIR / f"inactive_main_line_updates_{DATE_COMPACT}.csv", inactive_details)

    lines = [
        f"# {start:%Y-%m-%d} 自动报价主线路更新统计",
        "",
        "## 汇总",
        "",
        "| 指标 | 数值 |",
        "| --- | ---: |",
        f"| 有效自动报价线路更新数 | {len(effective_lines)} |",
        f"| 已停用线路更新数 | {len(inactive_lines)} |",
        f"| 更新线路总数（按主线路去重后） | {len(updated_lines)} |",
        f"| 原始主线路记录数 | {len(raw_rows)} |",
        "",
        "## 有效更新明细",
        "",
        "| 主线路号 | 线路 | 统计更新时间 | 时间来源 | 主线路更新时间 | 最新子线路更新时间 | 主线路更新人 | 线路价格摘要 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in effective_details:
        lines.append(
            f"| {row['主线路号']} | {row['线路']} | {row['统计更新时间']} | {row['时间来源']} | "
            f"{row['主线路更新时间'] or '-'} | {row['最新子线路更新时间'] or '-'} | "
            f"{row['主线路更新人'] or '-'} | {row['线路价格摘要'] or '-'} |"
        )
    if not effective_details:
        lines.append("| - | - | - | - | - | - | - | - |")
    lines.extend(
        [
            "",
            "## 统计口径",
            "",
            "- 时间窗口为指定日期 00:00:00 至次日 00:00:00，优先按最新子线路 `linePriceModifyTime` 过滤。",
            "- 当主线路 `modifyTime` 与最新子线路更新时间相同，或主线路时间更晚时，统计时间使用主线路 `modifyTime`。",
            "- 有效线路要求 `status=1` 且 `isExist=1`，并按主线路 ID 去重。",
            "- 该接口反映当前线路记录中的最新价格更新时间，不是完整的线路操作日志次数。",
        ]
    )
    (OUT_DIR / f"{DATE_SHORT}_自动报价主线路更新统计.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"outputs: {OUT_DIR}")


if __name__ == "__main__":
    main()
