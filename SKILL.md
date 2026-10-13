---
name: auto-quote-daily
description: Generate DMS auto-quotation daily or weekly dashboards when the user asks about auto-quote coverage, corrected conversion, secondary bidding, price comparison, sales pushes, or line updates.
---

# Auto-Quote Daily

Use this standalone skill for DMS auto-quotation daily and weekly dashboards. Its collectors and report builders are bundled in `scripts/auto_quote_daily/`. Install the Python runtime with `python -m pip install /path/to/this/skill` in a virtual environment (Python 3.10+). Activate that environment before running `auto-quote`; the original project checkout is not required.

Use `auto-quote --workspace /path/to/local-analysis ...` to select a writable data directory. Otherwise `AUTO_QUOTE_WORKSPACE`, then the current directory, is used. Keep different years in separate workspaces because HTML filenames retain the month-day template convention. All output paths below are relative to this workspace.

## Authorization

The user must provide an authorized DMS `x-access-token` as `DMS_ACCESS_TOKEN`, either in the local agent environment or in `~/.config/auto-quote-daily/.env` with user-only permissions. Never acquire a token, ask for a password, print a token, put it on a command line, or add it to a report or raw artifact. Run `auto-quote auth-check` before the first fetch. If it fails, ask the user to refresh their authorized token.

## Commands

```bash
auto-quote auth-check
auto-quote daily --date YYYY-MM-DD
auto-quote weekly --start YYYY-MM-DD --end YYYY-MM-DD
auto-quote rebuild --date YYYY-MM-DD
auto-quote rebuild-weekly --start YYYY-MM-DD --end YYYY-MM-DD
auto-quote diagnose --date YYYY-MM-DD
auto-quote ask --date YYYY-MM-DD --question "哪个渠道的自动报价率最低？"
auto-quote query --date YYYY-MM-DD --group-by channel
```

`daily` refreshes the requested day AND its preceding 14 calendar days (15 inclusive days), then calculates automatic line updates for the report day and writes its HTML dashboard and Markdown report to `outputs/MMDD_api_analysis/`. `weekly` refreshes every inclusive date in the requested range before generating the weekly dashboard. Do not reuse an old daily page or summary as a substitute for a refresh.

## Required 15-Day History

Every new daily analysis must fetch and validate all 15 days before building the report or generating AI analysis. This is required even on a new installation and even when local historical snapshots already exist, because historical orders can acquire new deal statuses and confirmed costs. For a report dated `2026-10-12`, the inclusive history is `2026-09-28` through `2026-10-12`, not the 15 days before the report day and not a window ending on the execution date.

For each date, refresh retail orders, query records, bid groups, carrier details and the other collector enrichment inputs, and persist `summary_YYYYMMDD.json`, `matched_orders_YYYYMMDD.json`, `raw_bid_groups_YYYYMMDD.json`, `raw_bid_group_carriers_YYYYMMDD.json` and `enrich_errors_YYYYMMDD.json`. All dates must have matching summary dates and empty enrichment errors. A genuine zero-order day still has complete snapshots and occupies a point in the time series; missing or failed dates must not be filled with zero or silently skipped.

The bundled `daily` command performs this refresh automatically. Do not replace it with a single-day collector invocation. After it succeeds, check that the operational-analysis context contains exactly 15 consecutive history dates ending on the report date and that the overview, automatic-quote, secondary-bid and price-comparison trends use this range. If any date fails, resolve that date and rerun; do not deliver a partially refreshed report as complete. Generate AI conclusions only after the history is complete; regenerate old conclusions when the refreshed context fingerprint changes. Historical deal cohorts have different observation durations even when fetched in the same run.

The report day's core metrics still use only that day's orders. Historical data supplies trends and analysis context, not the daily metric denominator. Presentation-only `rebuild` continues to use saved data without API requests; it does not fill missing history. Older runtime versions must be upgraded to obtain the automatic refresh behavior.

`rebuild` and `rebuild-weekly` read saved snapshots without API requests. `diagnose` fetches evidence for the Top10 absolute price differences and rebuilds the daily dashboard; use it when an anomaly investigation is requested or required for a full analysis report. The bundled API reference covers those endpoints. Resolve collector enrichment errors before delivering a report. Per-order diagnosis errors remain visible as evidence limitations and do not block the factual dashboard.

After daily data calculation and validation, follow [the operational-analysis workflow and prompt](references/operational-analysis.md). Read the generated context packet, produce and save evidence-based AI conclusions and actions, then rebuild the dashboard so it validates and displays the analysis. A CLI run alone does not generate AI commentary. Do not report the AI analysis complete while the page still shows pending analysis; reuse a saved analysis only when its data fingerprint matches.

For questions about an already processed date, use `summary_YYYYMMDD.json` and `matched_orders_YYYYMMDD.json` in that date's output directory. State the date and artifact path in the answer. Do not invent a metric that is absent from the artifacts.

## Dashboard Generation And Updates

Read [the current dashboard template](references/dashboard.md) before generating or changing a daily dashboard. It defines the four persistent summary groups, five business tabs, contribution placement, expanded details, price filters and filtered exports, fixed table headers, explanatory footer, and full-report/print behavior.

For a user-authorized presentation-only update to an existing date, reuse its saved snapshots with `auto-quote --workspace /path/to/local-analysis rebuild --date YYYY-MM-DD`. Preserve a saved AI analysis only when the regenerated context fingerprint matches; otherwise regenerate it using the analysis workflow. New daily or weekly analyses still require fresh data under the commands above.

Verify the requested interactions on desktop and narrow/mobile layouts, and confirm filtered exports match displayed orders. Use the template's delivery checks; keep the existing metric calculations and data scope intact when changing presentation.

## Required Data Rules

- Retail orders are the base population. Extra query records never enter core totals.
- First match an order to the `queryNo` found in its order-log `查价` event. Only when that is unavailable, use the exact province/city route, vehicle count, and the order-time window from five minutes before through thirty minutes after.
- An auto-quote hit requires `isOffer = 1`. A deal requires `acceptTime`, or status `2`, `3`, or `4`.
- Full-auto quoting means an auto-quote-hit order with `bidMode!=S`, regardless of deal status. Subtract all auto-hit S orders from auto-quote orders, including equal or missing-price S orders; do not subtract only price-qualified effective secondary bids. Its rate uses all orders as the denominator.
- An effective secondary-bid order requires `bidMode = S`, an auto-quote hit, and a positive automatic trunk price. Compare it with the confirmed bid group's carrier-detail `trunkAmt` total. An unavailable confirmed bid amount is marked temporarily incomparable.
- For a closed secondary-bid order missing from the inquiry bid data, query the carrier order list and use `orderAmount - profitAmt` as the confirmed cost fallback. This prevents closed S orders from dropping out of corrected attribution.
- Price comparison is full scope only: all orders with both an automatic trunk price and a confirmed carrier trunk price. Do not show, calculate, or label a “表格线路内” comparison.
- Report automatic-line updates by the latest child-line update time; use the main-line `modifyTime` when it is equal or later. Count effective (`status=1` and `isExist=1`) main lines once; label the remainder as 已停用线路.

Read [metric definitions](references/metrics.md) before answering conversion, contribution, or secondary-bidding questions. Read [DMS API contract](references/dms-api.md) before changing API collection. Read [security guidance](references/security.md) before moving the skill to another host or distributing artifacts.
