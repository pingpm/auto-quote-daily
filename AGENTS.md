# Repository Agent Instructions

This repository is a standalone skill and Python runtime. Keep all runtime modules under `scripts/auto_quote_daily/`, use package-relative imports, and write data only under the selected `AUTO_QUOTE_WORKSPACE`. Verify installation and CLI rebuilds from an unrelated directory when changing packaging.

`DMS_ACCESS_TOKEN` is a bearer credential. Never request a password, acquire a token automatically, put it in a command line, persist it in this repository, print it, or transmit it. The user supplies it locally; `auth-check` is read-only.

Use the metric definitions in `references/metrics.md` as the single source of truth. In particular, secondary-bid S orders are assigned individually by their actual price state: equal orders follow the automatic path, changed orders follow the manual path. Do not reintroduce ratio allocation or a table-scoped price comparison.

Keep raw snapshots, generated reports, customer data, and employee data local. Do not commit or publish `outputs/` without explicit authorization. When extending collection, document each endpoint and the response fields actually used in `references/dms-api.md` before calling it.
