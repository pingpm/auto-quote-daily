# Security and Distribution

This skill runs only with a user-authorized `DMS_ACCESS_TOKEN` stored in the local environment or a user-only `~/.config/auto-quote-daily/.env` file. It is a bearer credential and must never appear in source, a command line, a report, an output artifact, a prompt, or a conversation response.

The standalone distribution bundles its required collectors and report builders. Distribute only reviewed source or the allowlisted installation archive, never a populated analysis workspace. Runtime outputs go under the selected workspace rather than the installed package. Private GitHub access and locally authorized DMS access must be configured separately by each recipient.

Daily collection creates raw API snapshots for reconciliation. They can contain customer, carrier, sales, and operational details. Keep them on approved local storage, exclude them from source control, and follow the organization's retention policy.
