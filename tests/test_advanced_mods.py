"""Расширенные описания модов (Advanced Mod Descriptions).

Если опция включена в игре, буфер выглядит так::

    { Prefix Modifier "Rotund" (Tier: 3) — Life }
    +97(85-99) to maximum Life

Строку в скобках надо забрать как справку об аффиксе, а разброс ролла
вырезать из значения — иначе мод не совпадёт с пулом торговой площадки
и его чекбокс в оверлее останется серым.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import ADVANCED_BOOTS, ADVANCED_WEAPON, RARE_GLOVES, STATS_PAYLOAD  # noqa: E402
from poe2helper.parser.item import parse_item, strip_roll_ranges  # noqa: E402
from poe2helper.parser.stats_db import StatsDB  # noqa: E402
from poe2helper.trade.query import build_mod_filters  # noqa: E402


class TestStripRollRanges(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(
            strip_roll_ranges("+97(85-99) to maximum Life"), "+97 to maximum Life"
        )
        self.assertEqual(
            strip_roll_ranges("65(56-67)% increased Armour"), "65% increased Armour"
        )
        self.assertEqual(
            strip_roll_ranges("Adds 5(4-6) to 9(8-11) Physical Damage"),
            "Adds 5 to 9 Physical Damage",
        )

    def test_single_value_range(self):
        self.assertEqual(strip_roll_ranges("+1(1) to Level of all Skills"), "+1 to Level of all Skills")

    def test_leaves_normal_text_alone(self):
        for text in (
            "+25 to maximum Life",
            "Armour: 368 (augmented)",
            "Grants Skill: Level 8 Chaos Bolt",
            "15% increased Attack Speed",
        ):
            self.assertEqual(strip_roll_ranges(text), text)


class TestAdvancedBoots(unittest.TestCase):
    def setUp(self):
        self.item = parse_item(ADVANCED_BOOTS)

    def test_annotations_are_not_mods(self):
        texts = [m.text for m in self.item.mods]
        self.assertFalse(
            any(t.startswith("{") for t in texts), f"аннотации попали в моды: {texts}"
        )
        self.assertEqual(len(self.item.mods), 4)

    def test_requires_line_is_a_property(self):
        texts = [m.text for m in self.item.mods]
        self.assertFalse(any(t.startswith("Requires") for t in texts))
        self.assertIn("requires", self.item.properties)

    def test_roll_ranges_stripped(self):
        texts = [m.text for m in self.item.mods]
        self.assertIn("+97 to maximum Life", texts)
        self.assertIn("65% increased Armour", texts)
        self.assertIn("+30% to Lightning Resistance", texts)
        self.assertIn("5% increased Movement Speed", texts)

    def test_values_are_the_actual_roll(self):
        life = next(m for m in self.item.mods if "maximum Life" in m.text)
        self.assertEqual(life.values, [97.0])
        self.assertEqual(life.value, 97.0)

    def test_affix_info_captured(self):
        life = next(m for m in self.item.mods if "maximum Life" in m.text)
        self.assertEqual(life.affix, 'Prefix "Rotund" (Tier: 3)')
        self.assertEqual(life.tier, 3)
        res = next(m for m in self.item.mods if "Lightning Resistance" in m.text)
        self.assertEqual(res.tier, 4)
        self.assertTrue(res.affix.startswith("Suffix"))

    def test_kind_from_annotation(self):
        self.assertTrue(all(m.kind == "explicit" for m in self.item.mods))

    def test_armour_property_still_parsed(self):
        self.assertEqual(self.item.equip.armour, 368.0)
        self.assertEqual(self.item.item_level, 81)
        self.assertEqual(self.item.sockets, 1)


class TestAdvancedWeapon(unittest.TestCase):
    def setUp(self):
        self.item = parse_item(ADVANCED_WEAPON)

    def test_damage_with_ranges(self):
        # «44(40-48)-82(75-90)» -> среднее по 44-82
        self.assertEqual(self.item.equip.phys_avg, 63.0)
        self.assertEqual(self.item.equip.aps, 1.2)
        self.assertEqual(self.item.equip.pdps, 75.6)

    def test_implicit_kind_from_annotation(self):
        implicit = next(m for m in self.item.mods if "increased Damage" == m.text[4:] or "increased Damage" in m.text and m.kind == "implicit")
        self.assertEqual(implicit.kind, "implicit")
        self.assertEqual(implicit.text, "12% increased Damage")

    def test_explicit_kind(self):
        phys = next(m for m in self.item.mods if "Physical Damage" in m.text)
        self.assertEqual(phys.kind, "explicit")
        self.assertEqual(phys.text, "120% increased Physical Damage")
        self.assertEqual(phys.tier, 1)


class TestMatchingAfterFix(unittest.TestCase):
    """Главная проверка: чекбоксы в оверлее становятся кликабельными."""

    def setUp(self):
        self.db = StatsDB.from_api_payload(STATS_PAYLOAD)

    def test_all_boot_mods_matched(self):
        item = parse_item(ADVANCED_BOOTS)
        filters = build_mod_filters(item, self.db, default_kinds=["explicit"])
        unmatched = [f.text for f in filters if not f.matched]
        self.assertEqual(unmatched, [], f"не сопоставились: {unmatched}")
        self.assertTrue(all(f.enabled for f in filters))

    def test_min_bound_uses_real_roll(self):
        item = parse_item(ADVANCED_BOOTS)
        filters = {f.text: f for f in build_mod_filters(item, self.db, default_kinds=["explicit"])}
        life = filters["+97 to maximum Life"]
        self.assertEqual(life.stat_id, "explicit.stat_life")
        self.assertEqual(life.min_value, 87.3)  # 97 * 0.9

    def test_plain_item_still_works(self):
        """Обычный режим описаний не должен сломаться от правок."""
        item = parse_item(RARE_GLOVES)
        filters = build_mod_filters(item, self.db, default_kinds=["explicit"])
        matched = [f for f in filters if f.matched]
        self.assertGreaterEqual(len(matched), 4)


if __name__ == "__main__":
    unittest.main()
