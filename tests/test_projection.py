"""Пересчёт брони и ДПС с учётом выбранных модов.

Проверяется главное свойство: плоские прибавки и проценты складываются
как в игре, а не арифметически. Формула::

    показанное = (база + плоские) * (1 + проценты/100) * (1 + качество/100)

Качество — отдельный множитель, это проверено на реальном предмете
(см. TestShieldTotals). Из показанного значения восстанавливается
скобка (база + плоские), поэтому знать базу предмета не требуется.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import RARE_BOW, SHIELD_ADVANCED, STATS_PAYLOAD  # noqa: E402
from poe2helper.parser.item import parse_item  # noqa: E402
from poe2helper.parser.stats_db import StatsDB  # noqa: E402
from poe2helper.trade.projection import (  # noqa: E402
    classify,
    item_totals,
    mod_amount,
    project,
    project_from_filters,
)
from poe2helper.trade.query import ModFilter, build_mod_filters  # noqa: E402


class TestClassify(unittest.TestCase):
    def test_flat_defences(self):
        self.assertEqual(classify("+216 to Armour").targets, ("ar",))
        self.assertEqual(classify("+216 to Armour").kind, "flat")
        self.assertEqual(classify("+40 to Evasion Rating").targets, ("ev",))
        self.assertEqual(classify("+30 to maximum Energy Shield").targets, ("es",))

    def test_hybrid_defences(self):
        self.assertEqual(classify("18% increased Armour, Evasion and Energy Shield").targets,
                         ("ar", "ev", "es"))
        self.assertEqual(classify("25% increased Armour and Evasion").targets, ("ar", "ev"))
        self.assertEqual(classify("+50 to Armour and Evasion").kind, "flat")

    def test_longer_wording_wins(self):
        """«increased Armour» не должен съедать «increased Armour and Evasion»."""
        self.assertEqual(classify("99% increased Armour").targets, ("ar",))
        self.assertEqual(classify("99% increased Armour and Evasion").targets, ("ar", "ev"))

    def test_weapon(self):
        self.assertEqual(classify("72% increased Physical Damage").targets, ("phys",))
        self.assertEqual(classify("Adds 5 to 9 Physical Damage").kind, "flat")
        self.assertEqual(classify("Adds 12 to 24 Fire Damage").targets, ("ele",))
        self.assertEqual(classify("15% increased Attack Speed").targets, ("aps",))

    def test_pool_text_with_placeholders(self):
        """Мод из пула приходит с «#» и скобочными синонимами."""
        self.assertEqual(classify("#% increased [Attack] Speed").targets, ("aps",))
        self.assertEqual(classify("+# to Armour").targets, ("ar",))

    def test_irrelevant_mods(self):
        self.assertIsNone(classify("+97 to maximum Life"))
        self.assertIsNone(classify("30% increased Movement Speed"))
        self.assertIsNone(classify("+35% to Lightning Resistance"))

    def test_amount_of_range_mod(self):
        self.assertEqual(mod_amount("Adds 5 to 9 Physical Damage", [5, 9]), 7.0)
        self.assertEqual(mod_amount("+216 to Armour", [216]), 216.0)


class TestShieldTotals(unittest.TestCase):
    """Эталон на реальных данных из игры.

    Белая основа Tawhoan Tower Shield даёт Armour: 264. На предмете
    пользователя та же основа с +216 плоской брони, процентами
    99 + 40 + 18 (последние — с руны) и качеством 20% показывает 1480.
    Эти числа и закрепляем: они однозначно задают формулу.
    """

    WHITE_BASE = 264.0  # значение с белой основы, проверено в игре
    FLAT_ON_ITEM = 216.0
    DISPLAYED = 1480.0

    def setUp(self):
        self.item = parse_item(SHIELD_ADVANCED)
        self.totals = item_totals(self.item)

    def test_percentages_collected(self):
        # 99 + 40 на броню плюс 18 от руны на все защиты
        self.assertAlmostEqual(self.totals["ar"].inc_on_item, 157.0)
        self.assertAlmostEqual(self.totals["ev"].inc_on_item, 18.0)

    def test_quality_is_a_separate_multiplier(self):
        totals = self.totals["ar"]
        self.assertAlmostEqual(totals.quality, 20.0)
        self.assertTrue(totals.quality_multiplies)
        self.assertAlmostEqual(totals.inc_multiplier(), 2.57)
        self.assertAlmostEqual(totals.quality_multiplier, 1.2)
        self.assertAlmostEqual(totals.multiplier, 2.57 * 1.2)
        # старая (неверная) модель дала бы 2.77
        self.assertNotAlmostEqual(totals.multiplier, 2.77, places=2)

    def test_recovered_base_matches_the_white_item(self):
        """Главная проверка: восстановленная база совпадает с игрой."""
        recovered_base = self.totals["ar"].flat_sum - self.FLAT_ON_ITEM
        self.assertAlmostEqual(recovered_base, self.WHITE_BASE, delta=0.5)

    def test_forward_check(self):
        """Обратный ход: из базы получаем ровно то, что показывает игра."""
        totals = self.totals["ar"]
        value = (self.WHITE_BASE + self.FLAT_ON_ITEM) * totals.multiplier
        self.assertEqual(round(value), self.DISPLAYED)
        self.assertEqual(int(value), self.DISPLAYED)  # и floor, и round дают 1480


class TestProjection(unittest.TestCase):
    def setUp(self):
        self.item = parse_item(SHIELD_ADVANCED)

    def test_no_changes_keeps_displayed(self):
        result = project(self.item, [])
        self.assertAlmostEqual(result.values["ar"], 1480.0)

    def test_flat_addition_is_multiplied_by_percentages(self):
        """+100 плоской брони на предмете с ×3.084 даёт +308, а не +100."""
        result = project(self.item, [("+# to Armour", [], 100)])
        self.assertAlmostEqual(result.values["ar"], 1480 + 100 * 2.57 * 1.2, places=6)

    def test_percent_addition_applies_to_flat(self):
        """+50% применяется к скобке (база+плоские), а не к показанным 1480."""
        result = project(self.item, [("#% increased Armour", [], 50)])
        expected = (1480 / (2.57 * 1.2)) * (2.57 + 0.5) * 1.2
        self.assertAlmostEqual(result.values["ar"], expected, places=6)

    def test_flat_and_percent_together(self):
        """Порядок важен: плоское складывается до умножения."""
        result = project(
            self.item,
            [("+# to Armour", [], 100), ("#% increased Armour", [], 50)],
        )
        expected = (1480 / (2.57 * 1.2) + 100) * (2.57 + 0.5) * 1.2
        self.assertAlmostEqual(result.values["ar"], expected, places=6)
        # наивное сложение дало бы другое число
        self.assertNotAlmostEqual(result.values["ar"], 1480 + 100 + 1480 * 0.5, places=0)

    def test_raising_existing_mod(self):
        """Поднять «99% increased Armour» до 110 — это +11 процентов."""
        result = project(self.item, [("99% increased Armour", [99], 110)])
        expected = (1480 / (2.57 * 1.2)) * (2.57 + 0.11) * 1.2
        self.assertAlmostEqual(result.values["ar"], expected, places=6)

    def test_lowering_existing_mod(self):
        result = project(self.item, [("+216 to Armour", [216], 194)])
        expected = (1480 / (2.57 * 1.2) - 22) * 2.57 * 1.2
        self.assertAlmostEqual(result.values["ar"], expected, places=6)
        self.assertLess(result.values["ar"], 1480)

    def test_hybrid_mod_feeds_every_defence(self):
        result = project(self.item, [("#% increased Armour, Evasion and Energy Shield", [], 20)])
        self.assertGreater(result.values["ar"], 1480)
        # уклонения и энергощита у щита нет — пересчитывать нечего
        self.assertNotIn("ev", result.values)

    def test_unrelated_mod_changes_nothing(self):
        result = project(self.item, [("+97 to maximum Life", [97], 150)])
        self.assertAlmostEqual(result.values["ar"], 1480.0)

    def test_explanation_is_filled(self):
        result = project(self.item, [("+# to Armour", [], 100)])
        self.assertIn("ar", result.explain)
        self.assertIn("плоские", result.explain["ar"])


class TestWeaponProjection(unittest.TestCase):
    def setUp(self):
        self.item = parse_item(RARE_BOW)

    def test_baseline_matches_item(self):
        result = project(self.item, [])
        self.assertAlmostEqual(result.values["pdps"], self.item.equip.pdps)
        self.assertAlmostEqual(result.values["edps"], self.item.equip.edps)

    def test_more_physical_percent_raises_pdps(self):
        # на луке 72% increased Physical Damage и качество 20 -> ×1.72×1.2
        before = self.item.equip.pdps
        result = project(self.item, [("72% increased Physical Damage", [72], 100)])
        self.assertGreater(result.values["pdps"], before)
        expected_phys = (63.0 / (1.72 * 1.2)) * (1.72 + 0.28) * 1.2
        self.assertAlmostEqual(result.values["phys"], expected_phys, places=6)

    def test_attack_speed_raises_all_dps(self):
        result = project(self.item, [("#% increased [Attack] Speed", [], 20)])
        self.assertGreater(result.values["aps"], self.item.equip.aps)
        self.assertGreater(result.values["pdps"], self.item.equip.pdps)
        self.assertGreater(result.values["edps"], self.item.equip.edps)

    def test_added_flat_physical(self):
        result = project(self.item, [("Adds # to # Physical Damage", [], 20)])
        expected_phys = (63.0 / (1.72 * 1.2) + 20) * 1.72 * 1.2
        self.assertAlmostEqual(result.values["phys"], expected_phys, places=6)


class TestProjectFromFilters(unittest.TestCase):
    def setUp(self):
        self.db = StatsDB.from_api_payload(STATS_PAYLOAD)
        self.item = parse_item(SHIELD_ADVANCED)

    def test_disabled_mods_are_ignored(self):
        filters = build_mod_filters(self.item, self.db, default_kinds=[])
        result = project_from_filters(self.item, filters)
        self.assertAlmostEqual(result.values["ar"], 1480.0)

    def test_pool_mod_adds_its_value(self):
        added = ModFilter(
            stat_id="explicit.stat_armour_flat",
            text="+# to Armour",
            enabled=True,
            matched=True,
            min_value=100,
        )
        result = project_from_filters(self.item, [added])
        self.assertAlmostEqual(result.values["ar"], 1480 + 100 * 2.57 * 1.2, places=6)

    def test_mod_without_bound_keeps_item_value(self):
        kept = ModFilter(
            stat_id="x", text="99% increased Armour", enabled=True, matched=True,
            source_value=99, min_value=None,
        )
        result = project_from_filters(self.item, [kept])
        self.assertAlmostEqual(result.values["ar"], 1480.0)


class TestRollRanges(unittest.TestCase):
    def test_ranges_kept_from_advanced_description(self):
        item = parse_item(SHIELD_ADVANCED)
        armour = next(m for m in item.mods if m.text == "+216 to Armour")
        self.assertEqual(armour.ranges, [(191.0, 221.0)])
        self.assertEqual(armour.range_text, "191–221")
        # 216 из диапазона 191..221 — это (216-191)/30
        self.assertAlmostEqual(armour.roll_percent, (216 - 191) / 30 * 100, places=6)

    def test_perfect_roll(self):
        item = parse_item(SHIELD_ADVANCED)
        lightning = next(m for m in item.mods if "Lightning Resistance" in m.text)
        self.assertEqual(lightning.ranges, [(31.0, 35.0)])
        self.assertAlmostEqual(lightning.roll_percent, 100.0)

    def test_no_ranges_without_advanced_mode(self):
        item = parse_item(RARE_BOW)
        self.assertTrue(all(not m.ranges for m in item.mods))
        self.assertEqual(item.mods[0].range_text, "")
        self.assertIsNone(item.mods[0].roll_percent)

    def test_ranges_reach_the_filter(self):
        db = StatsDB.from_api_payload(STATS_PAYLOAD)
        item = parse_item(SHIELD_ADVANCED)
        filters = build_mod_filters(item, db, default_kinds=["explicit"])
        armour = next(f for f in filters if f.text == "+216 to Armour")
        self.assertEqual(armour.range_text, "191–221")
        self.assertIsNotNone(armour.roll_percent)


if __name__ == "__main__":
    unittest.main()
