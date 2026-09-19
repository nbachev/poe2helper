"""Фильтры по характеристикам вещи: разбор чисел, расчёт ДПС, сборка запроса."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import (  # noqa: E402
    CURRENCY,
    RARE_BODY_ARMOUR,
    RARE_BOW,
    RARE_GLOVES,
    SHIELD_WITH_BLOCK,
    STATS_PAYLOAD,
)
from poe2helper.parser.item import parse_item  # noqa: E402
from poe2helper.parser.stats_db import StatsDB  # noqa: E402
from poe2helper.trade.query import (  # noqa: E402
    build_equipment_filters,
    build_mod_filters,
    build_query,
    default_options_for,
    item_equipment_values,
)


class TestDamageParsing(unittest.TestCase):
    def setUp(self):
        self.bow = parse_item(RARE_BOW)

    def test_physical_average(self):
        # (44 + 82) / 2
        self.assertEqual(self.bow.equip.phys_avg, 63.0)

    def test_elemental_sums_all_ranges(self):
        # (12+24)/2 = 18 огонь, (5+9)/2 = 7 молния -> 25
        self.assertEqual(self.bow.equip.ele_avg, 25.0)

    def test_aps_and_crit(self):
        self.assertEqual(self.bow.equip.aps, 1.25)
        self.assertEqual(self.bow.equip.crit, 6.5)

    def test_dps_math(self):
        eq = self.bow.equip
        self.assertEqual(eq.pdps, round(63.0 * 1.25, 1))  # 78.8
        self.assertEqual(eq.edps, round(25.0 * 1.25, 1))  # 31.2
        self.assertEqual(eq.dps, round(88.0 * 1.25, 1))  # 110.0
        self.assertIsNone(eq.cdps)

    def test_damage_lines_still_parsed_as_mods(self):
        texts = [m.text for m in self.bow.mods]
        self.assertIn("Adds 12 to 24 Fire Damage", texts)
        self.assertIn("72% increased Physical Damage", texts)
        # свойства предмета в моды попасть не должны
        self.assertFalse(any("Attacks per Second" in t for t in texts))
        self.assertFalse(any(t.startswith("Physical Damage:") for t in texts))

    def test_flags(self):
        self.assertTrue(self.bow.is_weapon)
        self.assertFalse(self.bow.is_armour)
        self.assertTrue(self.bow.equip.has_damage)
        self.assertFalse(self.bow.equip.has_defence)
        self.assertEqual(self.bow.category, "weapon.bow")


class TestDefenceParsing(unittest.TestCase):
    def test_body_armour(self):
        item = parse_item(RARE_BODY_ARMOUR)
        eq = item.equip
        self.assertEqual(eq.armour, 512.0)
        self.assertEqual(eq.evasion, 120.0)
        self.assertEqual(eq.energy_shield, 44.0)
        self.assertTrue(eq.has_defence)
        self.assertFalse(eq.has_damage)
        self.assertTrue(item.is_armour)

    def test_shield_block_and_spirit(self):
        item = parse_item(SHIELD_WITH_BLOCK)
        self.assertEqual(item.equip.block, 30.0)
        self.assertEqual(item.equip.spirit, 25.0)
        self.assertEqual(item.equip.evasion, 210.0)

    def test_item_without_equipment_stats(self):
        self.assertEqual(item_equipment_values(parse_item(CURRENCY)), {})
        gloves = parse_item(RARE_GLOVES)
        values = item_equipment_values(gloves)
        self.assertIn("ar", values)
        self.assertNotIn("dps", values)


class TestEquipmentFilters(unittest.TestCase):
    def test_only_present_stats_are_offered(self):
        filters = build_equipment_filters(parse_item(RARE_BODY_ARMOUR))
        keys = [f.key for f in filters]
        self.assertEqual(keys, ["ar", "ev", "es"])
        self.assertTrue(all(not f.enabled for f in filters))

    def test_order_matches_declaration(self):
        filters = build_equipment_filters(parse_item(RARE_BOW))
        self.assertEqual([f.key for f in filters], ["dps", "pdps", "edps", "crit", "aps"])

    def test_min_is_prefilled_with_item_value(self):
        filters = {f.key: f for f in build_equipment_filters(parse_item(RARE_BOW))}
        self.assertEqual(filters["pdps"].min_value, 78.8)
        self.assertIsNone(filters["pdps"].max_value)

    def test_default_enabled_from_config(self):
        filters = {
            f.key: f for f in build_equipment_filters(parse_item(RARE_BOW), ["pdps", "dps"])
        }
        self.assertTrue(filters["pdps"].enabled)
        self.assertTrue(filters["dps"].enabled)
        self.assertFalse(filters["crit"].enabled)


class TestQueryWithEquipment(unittest.TestCase):
    def setUp(self):
        self.db = StatsDB.from_api_payload(STATS_PAYLOAD)

    def _query_for(self, text, cfg_search=None):
        item = parse_item(text)
        opts = default_options_for(item, cfg_search or {})
        mods = build_mod_filters(item, self.db, default_kinds=[])
        return item, opts, build_query(item, mods, opts)

    def test_pdps_lands_in_equipment_filters(self):
        _, _, query = self._query_for(
            RARE_BOW, {"default_equipment_filters": ["pdps"]}
        )
        eq = query["query"]["filters"]["equipment_filters"]["filters"]
        self.assertEqual(eq["pdps"], {"min": 78.8})
        self.assertNotIn("dps", eq)
        self.assertNotIn("crit", eq)

    def test_disabled_stats_are_not_sent(self):
        _, _, query = self._query_for(RARE_BOW, {"default_equipment_filters": []})
        filters = query["query"]["filters"]
        self.assertNotIn("equipment_filters", filters)

    def test_armour_keys(self):
        _, opts, _ = self._query_for(RARE_BODY_ARMOUR)
        for equip in opts.equipment:
            equip.enabled = True
        query = build_query(parse_item(RARE_BODY_ARMOUR), [], opts)
        eq = query["query"]["filters"]["equipment_filters"]["filters"]
        self.assertEqual(eq["ar"], {"min": 512})
        self.assertEqual(eq["ev"], {"min": 120})
        self.assertEqual(eq["es"], {"min": 44})

    def test_max_bound_is_sent_too(self):
        item, opts, _ = self._query_for(RARE_BOW)
        pdps = next(e for e in opts.equipment if e.key == "pdps")
        pdps.enabled = True
        pdps.min_value = 70
        pdps.max_value = 120
        query = build_query(item, [], opts)
        eq = query["query"]["filters"]["equipment_filters"]["filters"]
        self.assertEqual(eq["pdps"], {"min": 70, "max": 120})

    def test_sockets_and_equipment_coexist(self):
        item, opts, _ = self._query_for(RARE_BOW)
        opts.sockets_min = 2
        next(e for e in opts.equipment if e.key == "dps").enabled = True
        query = build_query(item, [], opts)
        eq = query["query"]["filters"]["equipment_filters"]["filters"]
        self.assertIn("rune_sockets", eq)
        self.assertIn("dps", eq)

    def test_search_any_base_of_the_class(self):
        """Снятая галочка «База» -> ищем любой лук, а не ту же базу."""
        item, opts, _ = self._query_for(RARE_BOW, {"default_equipment_filters": ["pdps"]})
        opts.use_type = False
        query = build_query(item, [], opts)
        self.assertNotIn("type", query["query"])
        self.assertEqual(
            query["query"]["filters"]["type_filters"]["filters"]["category"]["option"],
            "weapon.bow",
        )
        self.assertIn("pdps", query["query"]["filters"]["equipment_filters"]["filters"])


if __name__ == "__main__":
    unittest.main()
