"""Урон оружия и ДПС на реальной паре предметов.

Белая основа Fanatic Bow: физический урон 47–79, скорость 1.20.
Она же с модами (179% физа, +31–56 физа, 17% скорости) и качеством 20%
показывает в игре 262–452 и 1.40.

Эти два предмета проверяют друг друга: из редкого лука восстанавливается
база, и она обязана совпасть с белым. Формула та же, что у защит —
качество отдельным множителем::

    (47 + 31) * 2.79 * 1.2 = 261.1 -> 262
    (79 + 56) * 2.79 * 1.2 = 452.0 -> 452

Вариант «качество слагаемым к процентам» дал бы 233 и 404 — мимо.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import BOW_CRAFTED, BOW_WHITE  # noqa: E402
from poe2helper.parser.item import parse_item  # noqa: E402
from poe2helper.trade.projection import item_totals, project  # noqa: E402


class TestPathOfBuildingFormat(unittest.TestCase):
    """Экспорт PoB отличается от буфера игры — парсер должен его понимать."""

    def test_crafted_item_is_not_the_name(self):
        item = parse_item(BOW_WHITE)
        self.assertEqual(item.base_type, "Fanatic Bow")
        self.assertNotEqual(item.name, "Crafted Item")

    def test_critical_strike_chance_alias(self):
        """В PoB крит называется Critical Strike Chance, в игре — Hit."""
        item = parse_item(BOW_WHITE)
        self.assertEqual(item.equip.crit, 5.0)
        self.assertEqual(item.mods, [], "свойство не должно попасть в моды")

    def test_added_elemental_derived_from_mods(self):
        """Строки «Elemental Damage:» в PoB нет — считаем из мода."""
        item = parse_item(BOW_CRAFTED)
        self.assertEqual(item.equip.ele_avg, 91.5)  # (73+110)/2

    def test_no_double_counting_when_property_exists(self):
        """Если игра показала свойство, мод второй раз не добавляется."""
        text = BOW_CRAFTED.replace(
            "Physical Damage: 262-452",
            "Physical Damage: 262-452\nElemental Damage: 73-110",
        )
        item = parse_item(text)
        self.assertEqual(item.equip.ele_avg, 91.5)


class TestWhiteBow(unittest.TestCase):
    def setUp(self):
        self.item = parse_item(BOW_WHITE)

    def test_base_damage(self):
        self.assertEqual(self.item.equip.phys_avg, 63.0)  # (47+79)/2
        self.assertEqual(self.item.equip.aps, 1.2)
        self.assertIsNone(self.item.quality)

    def test_dps_without_mods(self):
        self.assertEqual(self.item.equip.pdps, 75.6)  # 63 * 1.2
        self.assertIsNone(self.item.equip.edps)


class TestCraftedBow(unittest.TestCase):
    """Числа, которые игра показывает на самом деле."""

    PHYS_AVG = 357.0  # (262+452)/2
    ELE_AVG = 91.5  # (73+110)/2
    APS = 1.4

    def setUp(self):
        self.item = parse_item(BOW_CRAFTED)

    def test_parsed_values(self):
        self.assertEqual(self.item.equip.phys_avg, self.PHYS_AVG)
        self.assertEqual(self.item.equip.ele_avg, self.ELE_AVG)
        self.assertEqual(self.item.equip.aps, self.APS)
        self.assertEqual(self.item.quality, 20)

    def test_physical_dps(self):
        self.assertAlmostEqual(self.item.equip.pdps, 499.8, places=1)

    def test_elemental_dps(self):
        self.assertAlmostEqual(self.item.equip.edps, 128.1, places=1)

    def test_full_dps(self):
        self.assertAlmostEqual(self.item.equip.dps, 627.9, places=1)

    def test_full_dps_is_the_sum_of_parts(self):
        eq = self.item.equip
        self.assertAlmostEqual(eq.dps, eq.pdps + eq.edps, places=1)


class TestBaseRecoveredFromCraftedBow(unittest.TestCase):
    """Главная проверка: редкий лук должен «вспомнить» белый."""

    WHITE_BASE_AVG = 63.0
    FLAT_FROM_MOD = 43.5  # «Adds 31 to 56 Physical Damage» -> (31+56)/2

    def setUp(self):
        self.totals = item_totals(parse_item(BOW_CRAFTED))["phys"]

    def test_quality_is_a_separate_multiplier(self):
        self.assertAlmostEqual(self.totals.inc_multiplier(), 2.79)
        self.assertAlmostEqual(self.totals.quality_multiplier, 1.2)
        self.assertAlmostEqual(self.totals.multiplier, 2.79 * 1.2)
        # качество слагаемым дало бы 2.99 и базу мимо белого лука
        self.assertNotAlmostEqual(self.totals.multiplier, 2.99, places=2)

    def test_recovered_base_matches_white_bow(self):
        recovered = self.totals.flat_sum - self.FLAT_FROM_MOD
        # расхождение только от округления игрой вверх
        self.assertAlmostEqual(recovered, self.WHITE_BASE_AVG, delta=0.5)

    def test_forward_check_matches_game(self):
        import math

        for base, flat, shown in ((47, 31, 262), (79, 56, 452)):
            value = (base + flat) * self.totals.multiplier
            self.assertEqual(math.ceil(value), shown)


class TestWeaponProjectionOnRealBow(unittest.TestCase):
    def setUp(self):
        self.item = parse_item(BOW_CRAFTED)

    def test_baseline_reproduces_item(self):
        result = project(self.item, [])
        self.assertAlmostEqual(result.values["pdps"], 499.8, places=1)
        self.assertAlmostEqual(result.values["edps"], 128.1, places=1)
        self.assertAlmostEqual(result.values["dps"], 627.9, places=1)

    def test_more_attack_speed_scales_every_dps(self):
        """+10% скорости: ДПС растёт ровно пропорционально."""
        result = project(self.item, [("17% increased Attack Speed", [17], 27)])
        expected_aps = 1.4 / 1.17 * 1.27
        self.assertAlmostEqual(result.values["aps"], expected_aps, places=6)
        self.assertAlmostEqual(result.values["pdps"], 357.0 * expected_aps, places=1)
        # стихийный урон скоростью тоже разгоняется
        self.assertAlmostEqual(result.values["edps"], 91.5 * expected_aps, places=1)

    def test_more_physical_percent_does_not_touch_elemental(self):
        result = project(self.item, [("179% increased Physical Damage", [179], 200)])
        self.assertGreater(result.values["pdps"], 499.8)
        self.assertAlmostEqual(result.values["edps"], 128.1, places=1)

    def test_added_flat_physical_is_multiplied(self):
        """+20 среднего физа проходит через проценты и качество."""
        result = project(self.item, [("Adds # to # Physical Damage", [], 20)])
        expected_phys = (357.0 / (2.79 * 1.2) + 20) * 2.79 * 1.2
        self.assertAlmostEqual(result.values["phys"], expected_phys, places=6)
        self.assertAlmostEqual(result.values["phys"] - 357.0, 20 * 3.348, places=4)


if __name__ == "__main__":
    unittest.main()
