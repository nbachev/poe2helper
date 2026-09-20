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
        from poe2helper.trade.projection import project_from_filters
        from poe2helper.ui.overlay import PriceCheckOverlay

        ctx = FakeCtx()
        ctx.cfg.set("search.default_equipment_filters", ["pdps"])
        overlay = PriceCheckOverlay(ctx)
        overlay.show_item(parse_item(RARE_BOW))

        self.assertTrue(overlay.equip_box.isVisibleTo(overlay))
        keys = [r.equip.key for r in overlay.equip_rows]
        self.assertEqual(keys, ["dps", "pdps", "edps", "crit", "aps"])

        item = parse_item(RARE_BOW)
        pdps_row = next(r for r in overlay.equip_rows if r.equip.key == "pdps")
        self.assertTrue(pdps_row.check.isChecked())

        # Значение пересчитано по выбранным модам, а не взято сырым.
        # Ожидание считаем из той же функции, что и код, — иначе тест
        # протухнет при следующей правке математики.
        expected = project_from_filters(item, overlay.mod_filters).values["pdps"]
        self.assertAlmostEqual(pdps_row.min_spin.bound(), round(expected, 1), places=1)
        self.assertLess(
            pdps_row.min_spin.bound(),
            item.equip.pdps,
            "границы модов ниже роллов, значит и ДПС должен выйти ниже",
        )

        # С выключенным пересчётом — ровно то, что показывает предмет
        ctx.cfg.set("search.equipment_from_mods", False)
        overlay.show_item(item)
        raw_row = next(r for r in overlay.equip_rows if r.equip.key == "pdps")
        self.assertFalse(overlay.chk_equip_auto.isChecked())
        self.assertEqual(raw_row.min_spin.bound(), item.equip.pdps)
        ctx.cfg.set("search.equipment_from_mods", True)

        # правка границы доезжает до модели
        raw_row.min_spin.set_bound(90)
        raw_row.min_spin.valueChanged.emit(90)
        self.assertEqual(raw_row.equip.min_value, 90)

        # «Снять все» гасит и параметры вещи
        overlay._set_all(False)
        self.assertFalse(any(e.enabled for e in overlay.options.equipment))

        # у перчаток оружейных строк быть не должно
        overlay.show_item(parse_item(RARE_GLOVES))
        self.assertEqual([r.equip.key for r in overlay.equip_rows], ["ar", "ev"])

        overlay.hide()
        overlay.deleteLater()

    def test_bound_field_placeholder_is_not_a_value(self):
        """«мин»/«макс» — подсказка, а не содержимое поля."""
        from poe2helper.ui.widgets import BoundSpin

        spin = BoundSpin("мин")
        self.assertEqual(spin.text(), "", "поле должно быть пустым")
        self.assertEqual(spin.placeholderText(), "мин")
        self.assertIsNone(spin.bound())

        spin.set_bound(78.8)
        self.assertEqual(spin.text(), "78.8")
        self.assertEqual(spin.bound(), 78.8)

        spin.clear_bound()
        self.assertEqual(spin.text(), "")
        self.assertIsNone(spin.bound())
        spin.deleteLater()

    def test_bound_field_applies_without_enter(self):
        """Значение доходит до модели по мере ввода, без Enter."""
        from poe2helper.ui.widgets import BoundSpin

        spin = BoundSpin("мин")
        seen: list[float] = []
        spin.valueChanged.connect(seen.append)

        # программная установка сигналов не поднимает
        spin.set_bound(10)
        self.assertEqual(seen, [])

        # ввод пользователя — сигнал сразу
        spin.setText("120")
        spin.textEdited.emit("120")
        self.assertTrue(seen)
        self.assertEqual(spin.bound(), 120)

        # потеря фокуса тоже применяет и нормализует текст
        seen.clear()
        spin.setText("15.50")
        spin.editingFinished.emit()
        self.assertEqual(spin.text(), "15.5")
        self.assertEqual(spin.bound(), 15.5)
        self.assertTrue(seen)
        spin.deleteLater()

    def test_bound_field_accepts_comma_and_rounds(self):
        from poe2helper.ui.widgets import BoundSpin

        spin = BoundSpin("мин")
        spin.setText("78,5")  # запятая на русской раскладке
        self.assertEqual(spin.bound(), 78.5)

        spin.setDecimals(0)  # броня — целое
        spin.setText("1500.7")
        self.assertEqual(spin.bound(), 1501)

        for junk in ("", "-", "."):
            spin.setText(junk)
            self.assertIsNone(spin.bound(), f"«{junk}» — это не значение")
        spin.deleteLater()

    def test_typing_into_mod_row_updates_equipment(self):
        """Ввод в поле мода пересчитывает параметры вещи без Enter."""
        from fixtures import SHIELD_ADVANCED
        from poe2helper.ui.overlay import PriceCheckOverlay

        ctx = FakeCtx()
        overlay = PriceCheckOverlay(ctx)
        overlay.show_item(parse_item(SHIELD_ADVANCED))

        armour_row = next(r for r in overlay.equip_rows if r.equip.key == "ar")
        before = armour_row.equip.min_value

        flat_row = next(r for r in overlay.rows if r.mod.text == "+216 to Armour")
        flat_row.min_spin.setText("300")
        flat_row.min_spin.textEdited.emit("300")

        self.assertEqual(flat_row.mod.min_value, 300)
        self.assertGreater(armour_row.equip.min_value, before)

        overlay.hide()
        overlay.deleteLater()

    def test_sale_type_selector(self):
        """Instant Buyout по умолчанию, выбор запоминается в настройках."""
        from poe2helper.ui.overlay import STATUS_OPTIONS, PriceCheckOverlay

        ctx = FakeCtx()
        overlay = PriceCheckOverlay(ctx)
        overlay.show_item(parse_item(RARE_GLOVES))

        self.assertEqual(overlay.cmb_status.count(), len(STATUS_OPTIONS))
        self.assertEqual(overlay.cmb_status.currentData(), "securable")
        self.assertEqual(overlay.options.status, "securable")

        # переключаем на In Person
        index = overlay.cmb_status.findData("onlineleague")
        self.assertGreaterEqual(index, 0)
        overlay.cmb_status.setCurrentIndex(index)

        self.assertEqual(overlay.options.status, "onlineleague")
        self.assertEqual(ctx.cfg.get("search.status"), "onlineleague")

        # и новый предмет открывается уже с этим выбором
        overlay.show_item(parse_item(RARE_GLOVES))
        self.assertEqual(overlay.cmb_status.currentData(), "onlineleague")

        overlay.hide()
        overlay.deleteLater()

    def test_numeric_filters_have_no_arrows(self):
        """Тогглы ±1 у полей оверлея убраны."""
        from PySide6.QtWidgets import QAbstractSpinBox

        from poe2helper.ui.overlay import PriceCheckOverlay

        ctx = FakeCtx()
        overlay = PriceCheckOverlay(ctx)
        for spin in (overlay.spn_ilvl, overlay.spn_quality, overlay.spn_sockets):
            self.assertEqual(
                spin.buttonSymbols(),
                QAbstractSpinBox.ButtonSymbols.NoButtons,
                "у поля остались стрелки",
            )
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

    def test_equipment_recalculated_from_mods(self):
        from fixtures import SHIELD_ADVANCED
        from poe2helper.trade.projection import project_from_filters
        from poe2helper.trade.query import ModFilter
        from poe2helper.ui.overlay import PriceCheckOverlay

        ctx = FakeCtx()
        overlay = PriceCheckOverlay(ctx)
        item = parse_item(SHIELD_ADVANCED)
        overlay.show_item(item)

        armour_row = next(r for r in overlay.equip_rows if r.equip.key == "ar")
        expected = project_from_filters(item, overlay.mod_filters).values["ar"]
        self.assertEqual(armour_row.equip.min_value, round(expected))
        self.assertEqual(armour_row.min_spin.bound(), round(expected))

        # добавляем плоскую броню — значение обязано вырасти
        before = armour_row.equip.min_value
        added = ModFilter(
            stat_id="explicit.stat_armour_flat", text="+# to Armour",
            enabled=True, matched=True, min_value=100, group_id=99,
        )
        overlay.mod_filters.append(added)
        overlay._recalc_equipment()
        self.assertGreater(armour_row.equip.min_value, before)

        overlay.hide()
        overlay.deleteLater()

    def test_manual_edit_turns_off_auto_recalc(self):
        from fixtures import SHIELD_ADVANCED
        from poe2helper.ui.overlay import PriceCheckOverlay

        ctx = FakeCtx()
        overlay = PriceCheckOverlay(ctx)
        overlay.show_item(parse_item(SHIELD_ADVANCED))
        self.assertTrue(overlay.chk_equip_auto.isChecked())

        armour_row = next(r for r in overlay.equip_rows if r.equip.key == "ar")
        armour_row.min_spin.set_bound(2000)
        armour_row.min_spin.valueChanged.emit(2000)

        self.assertFalse(overlay.chk_equip_auto.isChecked())
        self.assertEqual(armour_row.equip.min_value, 2000)

        # пересчёт выключен, значение пользователя не затирается
        overlay._recalc_equipment()
        self.assertEqual(armour_row.equip.min_value, 2000)

        overlay.hide()
        overlay.deleteLater()

    def test_roll_range_shown_in_row(self):
        from fixtures import SHIELD_ADVANCED
        from poe2helper.ui.overlay import PriceCheckOverlay

        ctx = FakeCtx()
        overlay = PriceCheckOverlay(ctx)
        overlay.show_item(parse_item(SHIELD_ADVANCED))

        row = next(r for r in overlay.rows if r.mod.text == "+216 to Armour")
        self.assertIn("191–221", row.label.text())
        self.assertIn("ролл", row.label.toolTip())

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
