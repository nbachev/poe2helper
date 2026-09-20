"""Проверка, что окна собираются и не падают.

Запускается там, где установлен PySide6 (в CI — на windows-latest
с ``QT_QPA_PLATFORM=offscreen``). Локально без Qt тест пропускается.
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication

    HAS_QT = True
except ImportError:  # pragma: no cover
    HAS_QT = False

from fixtures import RARE_GLOVES, STATS_PAYLOAD, UNIQUE_AMULET  # noqa: E402
from poe2helper.config import Config  # noqa: E402
from poe2helper.parser.item import parse_item  # noqa: E402
from poe2helper.parser.stats_db import StatsDB  # noqa: E402


class FakeCtx:
    """Минимальная замена AppController для тестов виджетов."""

    def __init__(self):
        self.cfg = Config()
        self.cfg.set("search.auto_search_on_open", False)
        self.cfg.set("league", "Test League")
        self.stats_db = StatsDB.from_api_payload(STATS_PAYLOAD)
        self.league = "Test League"
        self.trade = None
        self.ninja = None
        self.warnings: list[str] = []
        self.notifications: list[tuple[str, str]] = []

    def notify(self, title, message):
        self.notifications.append((title, message))

    def apply_settings(self):
        pass

    def reload_stats(self, silent=True):
        pass

    def refresh_league(self):
        pass


@unittest.skipUnless(HAS_QT, "PySide6 не установлен")
class TestUiSmoke(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_overlay_builds_and_shows_item(self):
        from poe2helper.ui.overlay import PriceCheckOverlay

        ctx = FakeCtx()
        overlay = PriceCheckOverlay(ctx)
        item = parse_item(RARE_GLOVES)
        overlay.show_item(item)

        self.assertEqual(len(overlay.rows), len(item.mods))
        self.assertIn("Havoc Grasp", overlay.lbl_title.text())
        enabled = [m for m in overlay.mod_filters if m.enabled]
        self.assertTrue(enabled, "хотя бы один мод должен быть включён по умолчанию")

        # переключение галочек и границ не должно падать
        overlay._set_all(False)
        self.assertFalse([m for m in overlay.mod_filters if m.enabled])
        overlay._set_all(True)
        overlay._sync_options()
        overlay.rows[0].min_spin.set_bound(10)
        overlay.rows[0].min_spin.valueChanged.emit(10)
        self.assertEqual(overlay.mod_filters[0].min_value, 10)

        # удаление строки
        before = len(overlay.rows)
        overlay._remove_row(overlay.rows[0])
        self.assertEqual(len(overlay.rows), before - 1)

        overlay.hide()
        overlay.deleteLater()

    def test_overlay_handles_unique(self):
        from poe2helper.ui.overlay import PriceCheckOverlay

        ctx = FakeCtx()
        overlay = PriceCheckOverlay(ctx)
        overlay.show_item(parse_item(UNIQUE_AMULET))
        self.assertTrue(overlay.chk_rarity.isChecked())
        self.assertEqual(overlay.cmb_rarity.currentData(), "unique")
        overlay.hide()
        overlay.deleteLater()

    def test_overlay_shows_equipment_rows(self):
        from fixtures import RARE_BOW, RARE_GLOVES
        from poe2helper.ui.overlay import PriceCheckOverlay

        ctx = FakeCtx()
        ctx.cfg.set("search.default_equipment_filters", ["pdps"])
        overlay = PriceCheckOverlay(ctx)
        overlay.show_item(parse_item(RARE_BOW))

        self.assertTrue(overlay.equip_box.isVisibleTo(overlay))
        keys = [r.equip.key for r in overlay.equip_rows]
        self.assertEqual(keys, ["dps", "pdps", "edps", "crit", "aps"])

        pdps_row = next(r for r in overlay.equip_rows if r.equip.key == "pdps")
        self.assertTrue(pdps_row.check.isChecked())
        self.assertEqual(pdps_row.min_spin.bound(), 78.8)

        # правка границы доезжает до модели
        pdps_row.min_spin.set_bound(90)
        pdps_row.min_spin.valueChanged.emit(90)
        self.assertEqual(pdps_row.equip.min_value, 90)

        # «Снять все» гасит и параметры вещи
        overlay._set_all(False)
        self.assertFalse(any(e.enabled for e in overlay.options.equipment))

        # у перчаток оружейных строк быть не должно
        overlay.show_item(parse_item(RARE_GLOVES))
        self.assertEqual([r.equip.key for r in overlay.equip_rows], ["ar", "ev"])

        overlay.hide()
        overlay.deleteLater()

    def test_unmatched_row_offers_manual_pick(self):
        from poe2helper.trade.query import ModFilter
        from poe2helper.ui.widgets import ModRow

        unmatched = ModFilter(stat_id="", text="Совсем незнакомый мод", matched=False)
        row = ModRow(unmatched)
        self.assertFalse(row.check.isEnabled())
        self.assertTrue(row.btn_pick.isVisibleTo(row))

        seen = []
        row.pick_requested.connect(lambda r, m: seen.append((r, m)))
        row.btn_pick.click()
        self.assertEqual(seen, [(row, unmatched)])

        # после ручного сопоставления строка оживает
        unmatched.stat_id = "explicit.stat_life"
        unmatched.matched = True
        unmatched.enabled = True
        unmatched.min_value = 50
        row.refresh()
        self.assertTrue(row.check.isEnabled())
        self.assertTrue(row.check.isChecked())
        self.assertTrue(row.min_spin.isEnabled())
        self.assertEqual(row.min_spin.bound(), 50)
        self.assertFalse(row.btn_pick.isVisibleTo(row))
        row.deleteLater()

    def test_advanced_item_rows_are_all_clickable(self):
        from fixtures import ADVANCED_BOOTS
        from poe2helper.ui.overlay import PriceCheckOverlay

        ctx = FakeCtx()
        overlay = PriceCheckOverlay(ctx)
        overlay.show_item(parse_item(ADVANCED_BOOTS))

        # Ожидания считаем из самой фикстуры: поменяется предмет —
        # тест подстроится сам, а не протухнет, как было.
        item = parse_item(ADVANCED_BOOTS)
        self.assertEqual(len(overlay.rows), len(item.mods))

        for row in overlay.rows:
            self.assertTrue(row.check.isEnabled(), f"серый чекбокс: {row.mod.text}")

        # там, где известен тир аффикса, в колонке справа стоит он
        expected_tiers = sorted(f"T{m.tier}" for m in item.mods if m.tier)
        shown_tiers = sorted(r.tag.text() for r in overlay.rows if r.tag.text().startswith("T"))
        self.assertEqual(shown_tiers, expected_tiers)

        # у руны тира нет — показывается вид мода
        runes = [r for r in overlay.rows if r.mod.kind == "rune"]
        self.assertEqual(len(runes), sum(1 for m in item.mods if m.kind == "rune"))
        for row in runes:
            self.assertEqual(row.tag.text(), "rune")

        overlay.hide()
        overlay.deleteLater()

    def test_hybrid_mod_is_one_row(self):
        from fixtures import SHIELD_ADVANCED
        from poe2helper.ui.overlay import PriceCheckOverlay

        ctx = FakeCtx()
        overlay = PriceCheckOverlay(ctx)
        item = parse_item(SHIELD_ADVANCED)
        overlay.show_item(item)

        # восемь характеристик, но семь строк — гибрид собран в одну
        self.assertEqual(len(overlay.mod_filters), len(item.mods))
        self.assertEqual(len(overlay.rows), 7)

        hybrid = next(r for r in overlay.rows if len(r.mods) > 1)
        self.assertEqual(len(hybrid.parts), 2)
        self.assertEqual(
            [p["mod"].text for p in hybrid.parts],
            ["40% increased Armour", "+123 to Stun Threshold"],
        )
        # галочка одна на обе части
        hybrid.check.setChecked(True)
        self.assertTrue(all(m.enabled for m in hybrid.mods if m.matched))
        hybrid.check.setChecked(False)
        self.assertFalse(any(m.enabled for m in hybrid.mods))

        # границы у частей независимые
        hybrid.parts[0]["min"].set_bound(38)
        hybrid.parts[0]["min"].valueChanged.emit(38)
        hybrid.parts[1]["min"].set_bound(110)
        hybrid.parts[1]["min"].valueChanged.emit(110)
        self.assertEqual(hybrid.mods[0].min_value, 38)
        self.assertEqual(hybrid.mods[1].min_value, 110)

        # крестик убирает аффикс целиком
        before = len(overlay.mod_filters)
        overlay._remove_row(hybrid)
        self.assertEqual(len(overlay.mod_filters), before - 2)
        self.assertEqual(len(overlay.rows), 6)

        overlay.hide()
        overlay.deleteLater()

    def test_shield_name_is_not_the_service_line(self):
        from fixtures import SHIELD_ADVANCED
        from poe2helper.ui.overlay import PriceCheckOverlay

        ctx = FakeCtx()
        overlay = PriceCheckOverlay(ctx)
        overlay.show_item(parse_item(SHIELD_ADVANCED))
        self.assertIn("Carrion Bastion", overlay.lbl_title.text())
        self.assertNotIn("cannot use", overlay.lbl_title.text().lower())
        overlay.hide()
        overlay.deleteLater()

    def test_add_mod_dialog_search(self):
        from poe2helper.ui.addmod import AddModDialog

        ctx = FakeCtx()
        dialog = AddModDialog(ctx.stats_db)
        self.assertGreater(dialog.list.count(), 0)
        dialog.search.setText("attack speed")
        dialog._refresh()
        self.assertGreater(dialog.list.count(), 0)
        dialog._accept()
        self.assertIsNotNone(dialog.selected_entry)
        dialog.deleteLater()

    def test_add_mod_dialog_options(self):
        from poe2helper.ui.addmod import AddModDialog

        ctx = FakeCtx()
        dialog = AddModDialog(ctx.stats_db)
        dialog.search.setText("allocates")
        dialog._refresh()
        self.assertTrue(dialog.option_box.isVisible() or dialog.option_box.count() > 0)
        dialog.deleteLater()

    def test_main_window_builds(self):
        from poe2helper.ui.main_window import MainWindow

        ctx = FakeCtx()
        window = MainWindow(ctx)
        self.assertEqual(window.tabs.count(), 3)
        self.assertIn("Test League", window.lbl_league.text())

        thresholds, groups = window._collect_thresholds()
        self.assertIn("currency", thresholds)
        self.assertTrue(all(isinstance(v, float) for v in thresholds["currency"]))
        self.assertIn("currency", groups)

        window.edit_filter_path.setText("C:/tmp/my.filter")
        window.save_settings(silent=True)
        self.assertEqual(ctx.cfg.get("filter.path"), "C:/tmp/my.filter")
        window.deleteLater()

    def test_main_window_scan_groups(self):
        import tempfile

        from fixtures import FILTER_SAMPLE
        from poe2helper.ui.main_window import MainWindow

        ctx = FakeCtx()
        window = MainWindow(ctx)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.filter"
            path.write_text(FILTER_SAMPLE, encoding="utf-8")
            window.edit_filter_path.setText(str(path))
            window._scan_groups()

        _, groups = window._collect_thresholds()
        self.assertEqual(groups, ["currency"])
        self.assertIn("currency", window.filter_output.toPlainText())
        window.deleteLater()

    def test_icon_renders(self):
        from poe2helper.app import make_icon

        icon = make_icon()
        self.assertFalse(icon.isNull())


if __name__ == "__main__":
    unittest.main()
