# Metric Definitions

All core denominators use the requested period's retail orders. A day is based on order `createTime`; a weekly range includes both endpoints.

| Metric | Formula and attribution |
| --- | --- |
| Auto-quote order / rate | `isOffer=1` matched orders / all orders. The automatic trunk price is `freightAmt`, falling back to `trunkAmt`. |
| Full-auto-quote order / rate | Auto-quote-hit orders with `bidMode!=S` / all orders, regardless of deal status. Equivalent to auto-quote orders minus auto-quote-hit S orders. Exclude all hit S orders even with missing/zero trunk prices or equal bid prices; use the current order snapshot, without adding push-log checks. |
| Deal / deal rate | Orders with `acceptTime` or status in `2, 3, 4` / all orders. |
| Effective secondary bid | `bidMode=S`, auto-quote hit, and positive automatic trunk price. The carrier price is the confirmed bid group's carrier-detail `trunkAmt` sum. |
| Secondary-bid price state | Equal when `abs(carrier trunk - automatic trunk) < 0.01`; changed otherwise. Changed is split into higher and lower by the signed difference. Missing carrier price is temporarily incomparable, not equal or changed. |
| Auto-quote contribution, original | `bidMode=A` deals / all orders. |
| Manual-bid contribution, original | `bidMode in [B, S]` deals / all orders. All S deals follow the manual path in this original classification. |
| Auto-quote contribution, corrected | `[auto-quote-hit non-S deals + equal S deals] / all orders`. |
| Manual-quote contribution, corrected | `[B deals + changed S deals] / all orders`. |
| Auto-quote close rate, corrected | `[auto-quote-hit non-S deals + equal S deals] / [auto-quote orders - changed S orders]`. Equal S orders remain on the automatic path. |
| Manual-quote close rate, corrected | `[B deals + changed S deals] / [(all orders - auto-quote orders) + changed S orders]`. Changed S orders move to the manual path. |
| Full-scope price comparison | Compare carrier trunk price with automatic trunk price for every order having both values; difference = carrier trunk price - automatic trunk price. Do not restrict this by a maintenance-line spreadsheet. |
| Sales secondary-bid push | An auto-quote-hit order with an order-log event `推送运力竞价` performed by a non-system user on the analysis day. Attribute the order to `custOwnerName`; count one order at its first qualifying push. |
| Order-distance push distribution | Use positive finite order-list `distance` in km, falling back to order-detail `distance`. Group into <500, 500-<1000, 1000-<1500, 1500-<2000, 2000-<3000, >=3000, and unknown. Use the same sales manual-push population; interval push rate = interval pushes / interval auto-quote orders, and push share = interval pushes / all manual pushes. Keep unknown distances in reconciliation. Distance reflects the saved order snapshot rather than the historical push time. |
| Route push distribution | Group the complete retail-order population by the exact directional four-field `routeKey`. Route push rate = route manual pushes / route auto-quote orders; route push share = route pushes / all manual pushes. Default to Top50 pushed routes ranked by pushes then automatic order count; allow Top100/all, rate sorting, minimum sample filters, search, and all auto-quote routes including zero pushes. Filters never change share denominators. Flag fewer than five auto-quote samples and export all routes. |
| Automatic-line update | A main line whose effective update time falls in the requested day. The effective time is latest child `linePriceModifyTime`, except main `modifyTime` wins when equal or later. Deduplicate by main-line ID; only `status=1` and `isExist=1` are effective updates. |

## Reconciliation

For a fully comparable, classified population, corrected auto and manual deal counts must add to total deals. If they do not, enumerate the unclassified deal order numbers and inspect their order logs, query linkage, bid groups, and carrier-order fallback before publishing an explanation.

The query API can contain non-retail activity. `query_extra_record_count` is audit-only and must never be added to coverage, channel, route, conversion, contribution, or price-comparison totals.

Full-auto-quote orders plus auto-quote-hit S orders must equal all auto-quote orders. Do not subtract the price-qualified effective-secondary-bid count or non-hit S orders. Daily, weekly, and monthly core metrics, operating trends, and channel tables include full-auto quoting; period rates use aggregate counts rather than average daily rates. Historical pages derive the metric from saved order rows when the summary lacks the new fields.

## Dashboard Expectations

Use [the current daily dashboard template](dashboard.md) for layout, contribution placement, default-expanded sections, price filters and exports, fixed table headers, explanatory footer, full-report/print behavior, and delivery checks. Generate AI commentary using [the analysis workflow and prompt](operational-analysis.md).

Weekly and monthly reports aggregate the same metric definitions across refreshed daily snapshots. Keep their existing layouts, include full-auto quoting, and omit metric-selection controls; do not average daily rates for period totals.
