"""Сквозной тест обновления фильтра: цены -> перетиринг -> бэкап -> файл."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import FILTER_SAMPLE  # noqa: E402
from poe2helper.config import Config  # noqa: E402
from poe2helper.filters import update as update_mod  # noqa: E402
from poe2helper.filters.update import run_filter_update  # noqa: E402
from poe2helper.trade.ninja import PriceInfo  # noqa: E402


def price(name: str, exalted: float) -> PriceInfo:
    return PriceInfo(name=name, divine=exalted / 400, exalted=exalted, chaos=exalted * 8)


PRICES = {
    "Mirror of Kalandra": price("Mirror of Kalandra", 50000),
    "Divine Orb": price("Divine Orb", 400),
    "Exalted Orb": price("Exalted Orb", 1),
    "Chaos Orb": price("Chaos Orb", 0.12),
    "Orb of Alchemy": price("Orb of Alchemy", 0.05),
}


class FakeNinja:
    def __init__(self, prices=None, league="Forbidden Rites"):
        self._prices = prices if prices is not None else PRICES
        self._league = league
        self.calls = 0

    def default_league(self):
        return self._league

    def collect_prices(self, league, types=None, include_uniques=False):
        self.calls += 1
        return dict(self._prices)


class TestUpdatePipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.filter_path = Path(self.tmp.name) / "my.filter"
        self.filter_path.write_text(FILTER_SAMPLE, encoding="utf-8")

        self.backups = Path(self.tmp.name) / "backups"
        self.backups.mkdir()
        self._orig_backup_dir = update_mod.backup_dir
        update_mod.backup_dir = lambda: self.backups

        self.cfg = Config()
        self.cfg.set("league", "Forbidden Rites")
        self.cfg.set("filter.path", str(self.filter_path))
        self.cfg.set("filter.groups", ["currency"])

    def tearDown(self):
        update_mod.backup_dir = self._orig_backup_dir
        self.tmp.cleanup()

    def test_dry_run_does_not_touch_file(self):
        before = self.filter_path.read_text(encoding="utf-8")
        result = run_filter_update(self.cfg, FakeNinja(), dry_run=True)
        self.assertTrue(result.ok)
        self.assertIsNone(result.written_path)
        self.assertEqual(self.filter_path.read_text(encoding="utf-8"), before)
        self.assertTrue(result.diff)
        self.assertTrue(result.report.moves)

    def test_writes_in_place_with_backup(self):
        result = run_filter_update(self.cfg, FakeNinja(), dry_run=False)
        self.assertTrue(result.ok, result.message)
        self.assertEqual(result.written_path, self.filter_path)
        self.assertIsNotNone(result.backup_path)
        self.assertTrue(result.backup_path.exists())
        self.assertEqual(result.backup_path.read_text(encoding="utf-8"), FILTER_SAMPLE)

        text = self.filter_path.read_text(encoding="utf-8")
        self.assertNotEqual(text, FILTER_SAMPLE)
        self.assertIn("SetTextColor 255 0 0 255", text)
        self.assertIn('BaseType == "Mirror of Kalandra" "Divine Orb"', text)
        # блок со StackSize не тронут
        self.assertIn('\tStackSize >= 20\n\tBaseType == "Orb of Alchemy"', text)

    def test_separate_file_mode(self):
        self.cfg.set("filter.write_in_place", False)
        result = run_filter_update(self.cfg, FakeNinja(), dry_run=False)
        self.assertTrue(result.ok)
        self.assertEqual(result.written_path.name, "my.autopriced.filter")
        self.assertTrue(result.written_path.exists())
        self.assertEqual(self.filter_path.read_text(encoding="utf-8"), FILTER_SAMPLE)

    def test_second_run_is_noop(self):
        run_filter_update(self.cfg, FakeNinja(), dry_run=False)
        result = run_filter_update(self.cfg, FakeNinja(), dry_run=False)
        self.assertTrue(result.ok)
        self.assertIn("актуален", result.message)

    def test_missing_file(self):
        self.cfg.set("filter.path", str(Path(self.tmp.name) / "нет-такого.filter"))
        result = run_filter_update(self.cfg, FakeNinja(), dry_run=False)
        self.assertFalse(result.ok)
        self.assertIn("не найден", result.message)

    def test_empty_prices_aborts(self):
        result = run_filter_update(self.cfg, FakeNinja(prices={}), dry_run=False)
        self.assertFalse(result.ok)
        self.assertEqual(self.filter_path.read_text(encoding="utf-8"), FILTER_SAMPLE)

    def test_no_filter_selected(self):
        self.cfg.set("filter.path", "")
        result = run_filter_update(self.cfg, FakeNinja(), dry_run=False)
        self.assertFalse(result.ok)
        self.assertIn("Не выбран", result.message)

    def test_progress_messages(self):
        seen: list[str] = []
        run_filter_update(self.cfg, FakeNinja(), dry_run=True, progress=seen.append)
        self.assertTrue(any("poe.ninja" in m for m in seen))

    def test_crlf_preserved(self):
        self.filter_path.write_text(FILTER_SAMPLE.replace("\n", "\r\n"), encoding="utf-8", newline="")
        run_filter_update(self.cfg, FakeNinja(), dry_run=False)
        raw = self.filter_path.read_bytes()
        self.assertIn(b"\r\n", raw)
        # каждый перевод строки должен остаться CRLF, без смешения стилей
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))


if __name__ == "__main__":
    unittest.main()
