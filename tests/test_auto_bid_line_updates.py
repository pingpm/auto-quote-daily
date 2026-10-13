from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from auto_quote_daily.runtime import analyze_auto_bid_line_updates as line_updates  # noqa: E402


class AutoBidLineUpdateTest(unittest.TestCase):
    def test_update_time_prefers_child_price_and_main_line_on_tie(self) -> None:
        child_newer = {"modifyTime": "2026-09-16 09:00:00", "linePriceModifyTime": "2026-09-16 10:00:00"}
        same_time = {"modifyTime": "2026-09-16 10:00:00", "linePriceModifyTime": "2026-09-16 10:00:00"}
        main_newer = {"modifyTime": "2026-09-16 11:00:00", "linePriceModifyTime": "2026-09-16 10:00:00"}

        self.assertEqual(line_updates.update_time(child_newer), datetime(2026, 9, 16, 10, 0, 0))
        self.assertEqual(line_updates.update_time_source(child_newer), "最新子线路")
        self.assertEqual(line_updates.update_time(same_time), datetime(2026, 9, 16, 10, 0, 0))
        self.assertEqual(line_updates.update_time_source(same_time), "主线路")
        self.assertEqual(line_updates.update_time(main_newer), datetime(2026, 9, 16, 11, 0, 0))
        self.assertEqual(line_updates.update_time_source(main_newer), "主线路")


if __name__ == "__main__":
    unittest.main()
