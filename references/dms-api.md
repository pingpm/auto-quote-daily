# Used DMS API Contract

Default base URL: `https://dms.iyunche.com`, configurable with `DMS_BASE_URL`. All requests are read-only and send the user-provided `x-access-token`. Do not record the token in source code, commands, artifacts, or reports.

| Endpoint | Method | Purpose and fields used |
| --- | --- | --- |
| `/dms-boot/order/toRetail/getOrderList` | POST | Daily retail-order population: IDs, `createTime`, `acceptTime`, status, route, vehicle count, channel, owner, `bidMode`, and sales amount. |
| `/dms-boot/order/toRetail/getOrderDetail` | POST | Supplements final `bidMode` when the list value is incomplete. |
| `/dms-boot/autoPrice/getQueryList` | POST | Query number, route, vehicle count, query time, `isOffer`, `freightAmt`, `trunkAmt`, and total amount. |
| `/dms-boot/tBid/getBidGroupList` | POST | Bid groups for an order; select `confirmStatus=1` when comparing price or calculating cost. |
| `/dms-boot/tBid/getBidGroupCarrierList` | POST | Carrier bid details. Sum `trunkAmt` for carrier trunk price; do not compare `payableAmt` directly with automatic trunk price. |
| `/dms-boot/order/getOrderLog` | GET | Order `查价` events for exact query linkage and `推送运力竞价` events for sales-push analysis. |
| `/dms-boot/tOrder/getOrderList` | POST | Closed carrier-order fallback. For a closed S order absent from inquiry bid data, use its `profitAmt` with business `orderAmount` to derive confirmed cost. |
| `/dms-boot/autoBidLine/getLineList` | POST | Automatic main-line list, latest child price update time, main-line update time, status, existence flag, and updater for daily line-update statistics. |
| `/dms-boot/autoPrice/getQueryDetail` | POST | Anomaly evidence: matched child-line identifier, automatic quote time, hit price and route. |
| `/dms-boot/autoBidLine/getLinePriceList` | POST | Anomaly evidence: child-line price history, update time, updater and current line-library state for the hit main line. |

The collector persists raw local snapshots for audit: order list, query records, order details, bid groups, carrier details, order logs, carrier-order fallbacks, and collection errors. Keep them local because they can contain customer or employee data.

This standalone package supports daily and weekly/interval refreshes. Month-specific collectors from the original project are not part of this distribution.
