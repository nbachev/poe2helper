"""Гибридные моды и служебные строки в шапке предмета.

Один аффикс может давать несколько строк статов::

    { Prefix Modifier "Mammoth's" (Tier: 1) }
    40(39-42)% increased Armour
    +123(95-136) to Stun Threshold

В оверлее это одна строка с общей галочкой, но в запрос уходят обе
характеристики по отдельности — торговая площадка ищет именно так.

Отдельно проверяется случай, когда игра пишет в шапке служебный текст
(«You cannot use this item…»), а имя и база уезжают в следующую секцию.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import ADVANCED_BOOTS, RARE_GLOVES, SHIELD_ADVANCED, STATS_PAYLOAD  # noqa: E402
from poe2helper.parser.item import parse_item  # noqa: E402
from poe2helper.parser.stats_db import StatsDB  # noqa: E402
from poe2helper.trade.query import (  # noqa: E402
    ModFilter,
    QueryOptions,
    build_mod_filters,
    build_query,
    group_filters,
)


class TestHeaderWithServiceLine(unittest.TestCase):
    def setUp(self):
        self.item = parse_item(SHIELD_ADVANCED)

    def test_real_name_and_base(self):
        self.assertEqual(self.item.name, "Carrion Bastion")
        self.assertEqual(self.item.base_type, "Tawhoan Tower Shield")
        self.assertTrue(self.item.base_type_certain)

    def test_service_line_is_not_a_mod(self):
        texts = [m.text for m in self.item.mods]
        self.assertFalse(any("cannot use this item" in t.lower() for t in texts))
        self.assertNotIn("Carrion Bastion", texts)
        self.assertNotIn("Tawhoan Tower Shield", texts)

    def test_properties(self):
        self.assertEqual(self.item.item_class, "Shields")
        self.assertEqual(self.item.category, "armour.shield")
        self.assertEqual(self.item.equip.armour, 1480.0)
        self.assertEqual(self.item.equip.block, 26.0)
        self.assertEqual(self.item.item_level, 82)
        self.assertEqual(self.item.quality, 20)
        self.assertEqual(self.item.properties.get("grants skill"), "Raise Shield")

    def test_grants_skill_is_not_a_mod(self):
        self.assertFalse(any("Raise Shield" in m.text for m in self.item.mods))


class TestHybridGrouping(unittest.TestCase):
    def setUp(self):
        self.item = parse_item(SHIELD_ADVANCED)

    def test_all_stat_lines_present(self):
        self.assertEqual(len(self.item.mods), 8)

    def test_hybrid_shares_one_group(self):
        groups: dict[int, list] = {}
        for mod in self.item.mods:
            groups.setdefault(mod.group_id, []).append(mod)
        self.assertEqual(len(groups), 7)

        hybrid = next(g for g in groups.values() if len(g) > 1)
        self.assertEqual(
            [m.text for m in hybrid],
            ["40% increased Armour", "+123 to Stun Threshold"],
        )

    def test_both_halves_keep_the_affix(self):
        hybrid = [m for m in self.item.mods if m.affix.startswith('Prefix "Mammoth')]
        self.assertEqual(len(hybrid), 2)
        self.assertTrue(all(m.tier == 1 for m in hybrid))

    def test_same_stat_from_different_affixes_stays_separate(self):
        """Два «Stun Threshold» из разных аффиксов склеиваться не должны."""
        stun = [m for m in self.item.mods if "Stun Threshold" in m.text]
        self.assertEqual(len(stun), 2)
        self.assertNotEqual(stun[0].group_id, stun[1].group_id)

    def test_rune_is_its_own_group(self):
        rune = next(m for m in self.item.mods if m.kind == "rune")
        same = [m for m in self.item.mods if m.group_id == rune.group_id]
        self.assertEqual(same, [rune])


class TestGroupFilters(unittest.TestCase):
    def test_groups_by_id_preserving_order(self):
        mods = [
            ModFilter(stat_id="a", text="a", group_id=1),
            ModFilter(stat_id="b", text="b", group_id=2),
            ModFilter(stat_id="c", text="c", group_id=2),
            ModFilter(stat_id="d", text="d", group_id=3),
        ]
        groups = group_filters(mods)
        self.assertEqual([[m.stat_id for m in g] for g in groups], [["a"], ["b", "c"], ["d"]])

    def test_zero_group_id_never_merges(self):
        mods = [ModFilter(stat_id=x, text=x) for x in "abc"]
        groups = group_filters(mods)
        self.assertEqual(len(groups), 3)

    def test_empty(self):
        self.assertEqual(group_filters([]), [])


class TestHybridInQuery(unittest.TestCase):
    def setUp(self):
        self.db = StatsDB.from_api_payload(STATS_PAYLOAD)
        self.item = parse_item(SHIELD_ADVANCED)

    def test_filters_keep_group_id(self):
        filters = build_mod_filters(self.item, self.db, default_kinds=["explicit"])
        self.assertEqual(len(filters), len(self.item.mods))
        groups = group_filters(filters)
        self.assertEqual(len(groups), 7)
        self.assertTrue(any(len(g) == 2 for g in groups))

    def test_both_halves_go_into_the_query_separately(self):
        """Галочка одна, а характеристик в запросе две."""
        armour = ModFilter(
            stat_id="explicit.stat_armour_pct", text="40% increased Armour",
            enabled=True, min_value=36, group_id=4,
        )
        stun = ModFilter(
            stat_id="explicit.stat_stun", text="+123 to Stun Threshold",
            enabled=True, min_value=110, group_id=4,
        )
        query = build_query(None, [armour, stun], QueryOptions())
        sent = query["query"]["stats"][0]["filters"]
        self.assertEqual(
            sent,
            [
                {"id": "explicit.stat_armour_pct", "value": {"min": 36}},
                {"id": "explicit.stat_stun", "value": {"min": 110}},
            ],
        )


class TestNoRegressions(unittest.TestCase):
    def test_plain_item_one_group_per_mod(self):
        item = parse_item(RARE_GLOVES)
        ids = [m.group_id for m in item.mods]
        self.assertEqual(len(set(ids)), len(ids), "обычные моды не должны склеиваться")

    def test_advanced_boots_unchanged(self):
        item = parse_item(ADVANCED_BOOTS)
        ids = [m.group_id for m in item.mods]
        self.assertEqual(len(set(ids)), len(ids))
        self.assertEqual(len(item.mods), 7)


if __name__ == "__main__":
    unittest.main()
