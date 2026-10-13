from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from bs4 import BeautifulSoup
from auto_quote_daily.runtime import analyze_0708_api_metrics as metrics


class PortableCliTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="auto quote portable ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "data workspace"
        self.env = os.environ.copy()
        for key in ("DMS_ACCESS_TOKEN", "DMS_BASE_URL", "AUTO_QUOTE_WORKSPACE", "PYTHONPATH"):
            self.env.pop(key, None)
        self.env["XDG_CONFIG_HOME"] = str(self.root / "empty config")

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "auto_quote_daily.cli", "--workspace", str(self.workspace), *args],
            cwd=self.root, env=self.env, text=True, capture_output=True, timeout=60,
        )

    def snapshots(self, day="2026-10-09"):
        compact = day.replace("-", "")
        short = compact[4:]
        folder = self.workspace / "outputs" / f"{short}_api_analysis"
        folder.mkdir(parents=True, exist_ok=True)
        orders = [{"orderNo": f"TEST-{i}", "createTime": f"{day} 10:00:00"} for i in range(4)]
        rows, used = metrics.build_rows(orders, [], {}, {})
        for row, (hit, mode, amount) in zip(rows, [(1, "A", 1000), (1, "S", 1000), (1, "S", None), (0, "B", None)]):
            row.update(isAutoOffer=hit, queryMatched=hit, bidMode=mode, autoTrunkAmt=amount,
                       sourceRetailName="TEST-CHANNEL", isDeal=bool(hit), hasBidGroup=bool(amount))
        groups = {"TEST-0": [{"pkId": "GROUP-0", "confirmStatus": 1, "payableAmt": 1200}],
                  "TEST-1": [{"pkId": "GROUP-1", "confirmStatus": 1, "payableAmt": 700}]}
        carriers = {"TEST-0": {"GROUP-0": [{"trunkAmt": 1200}]},
                    "TEST-1": {"GROUP-1": [{"trunkAmt": 700}]}}
        summary = metrics.summarize(rows, [], used, groups, carriers)
        summary["date"] = day
        for stem, value in (("summary", summary), ("matched_orders", rows), ("raw_bid_groups", groups),
                            ("raw_bid_group_carriers", carriers), ("enrich_errors", {})):
            (folder / f"{stem}_{compact}.json").write_text(json.dumps(value), encoding="utf-8")
        return folder

    def test_missing_token_fails_before_fetch_or_output_creation(self):
        result = self.cli("daily", "--date", "2026-10-09")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("DMS_ACCESS_TOKEN", result.stderr)
        self.assertNotIn("order_analysis", result.stderr)
        self.assertFalse(self.workspace.exists())

    def test_installed_rebuild_and_ai_validation_from_unrelated_directory(self):
        folder = self.snapshots()
        result = self.cli("rebuild", "--date", "2026-10-09")
        self.assertEqual(result.returncode, 0, result.stderr)
        page = folder / "1009_visual_dashboard.html"
        soup = BeautifulSoup(page.read_text(), "html.parser")
        self.assertEqual(len(soup.select('[role="tab"]')), 5)
        self.assertTrue(soup.select('[data-focus-id="full-auto-rate"]'))
        self.assertTrue(soup.select('[data-price-diff]'))
        context = json.loads((folder / "operational_analysis_context_20261009.json").read_text())
        self.assertEqual(context["facts"]["full_auto_rate"]["numerator"], 1)
        report = {
            "date": "2026-10-09", "dataFingerprint": context["dataFingerprint"],
            "generatedAt": "2026-10-13T12:00:00+08:00", "overall": "Synthetic verified analysis.",
            "conclusions": [{"id": "coverage", "title": "Coverage", "evidence": ["auto_rate", "full_auto_rate"],
                             "interpretation": "Review secondary pushes."}],
            "actions": [], "limitations": [],
        }
        report_path = folder / "operational_analysis_20261009.json"
        report_path.write_text(json.dumps(report))
        result = self.cli("rebuild", "--date", "2026-10-09")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("运营分析：已校验并展示", result.stdout)
        self.assertIn("Synthetic verified analysis.", page.read_text())
        report["dataFingerprint"] = "stale"
        report_path.write_text(json.dumps(report))
        result = self.cli("rebuild", "--date", "2026-10-09")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Synthetic verified analysis.", page.read_text())

    def test_period_rebuild_query_and_collection_errors(self):
        folder = self.snapshots()
        self.snapshots("2026-10-10")
        result = self.cli("rebuild-weekly", "--start", "2026-10-09", "--end", "2026-10-10")
        self.assertEqual(result.returncode, 0, result.stderr)
        summary_path = self.workspace / "outputs" / "20261009_20261010_weekly_analysis" / "summary_20261009_20261010.json"
        summary = json.loads(summary_path.read_text())["weekly"]
        self.assertEqual(summary["full_auto_offer_order_count"], 2)
        self.assertEqual(summary["full_auto_offer_rate"], 0.25)
        result = self.cli("query", "--date", "2026-10-09")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["data"]["order_count"], 4)
        (folder / "enrich_errors_20261009.json").write_text('{"TEST-0": "synthetic failure"}')
        result = self.cli("rebuild-weekly", "--start", "2026-10-09", "--end", "2026-10-10")
        self.assertEqual(result.returncode, 2)
        self.assertIn("enrichment errors", result.stderr)

    def test_local_config_base_url_reaches_child_runtime(self):
        from auto_quote_daily import cli
        from unittest.mock import patch

        config = Path(self.env["XDG_CONFIG_HOME"]) / "auto-quote-daily" / ".env"
        config.parent.mkdir(parents=True)
        config.write_text("DMS_ACCESS_TOKEN=synthetic-test-only\nDMS_BASE_URL=http://127.0.0.1:12345/\n")
        with patch.dict(os.environ, self.env, clear=True):
            environment = cli.project_environment(cli.date(2026, 10, 9))
        self.assertEqual(environment["DMS_BASE_URL"], "http://127.0.0.1:12345")
        self.assertEqual(environment["DMS_ACCESS_TOKEN"], "synthetic-test-only")

    def test_daily_refresh_against_local_synthetic_api(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from threading import Thread

        requests_seen = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(handler):
                payload = json.loads(handler.rfile.read(int(handler.headers["Content-Length"])))
                requests_seen.append((handler.path, payload, handler.headers.get("x-access-token")))
                body = json.dumps({"success": True, "result": {"pages": 1, "records": []}}).encode()
                handler.send_response(200)
                handler.send_header("Content-Type", "application/json")
                handler.end_headers()
                handler.wfile.write(body)

            def log_message(handler, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.env["DMS_ACCESS_TOKEN"] = "synthetic-test-only"
        self.env["DMS_BASE_URL"] = f"http://127.0.0.1:{server.server_port}"
        try:
            result = self.cli("daily", "--date", "2026-10-09")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual({path for path, _, _ in requests_seen}, {
            "/dms-boot/order/toRetail/getOrderList", "/dms-boot/autoPrice/getQueryList",
            "/dms-boot/autoBidLine/getLineList",
        })
        self.assertTrue(all(token == "synthetic-test-only" for _, _, token in requests_seen))
        self.assertTrue((self.workspace / "outputs" / "1009_api_analysis" / "1009_visual_dashboard.html").is_file())


if __name__ == "__main__":
    unittest.main()
