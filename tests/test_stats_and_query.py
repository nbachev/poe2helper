import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import RARE_GLOVES, STATS_PAYLOAD, UNIQUE_AMULET  # noqa: E402
from poe2helper.parser.item import parse_item  # noqa: E402
from poe2helper.parser.stats_db import StatsDB, expand_brackets, normalize  # noqa: E402
from poe2helper.trade.query import (  # noqa: E402
    ModFilter,
    QueryOptions,
    build_mod_filters,
    build_query,
    default_options_for,
    suggest_bounds,
)


class TestNormalize(unittest.TestCase):
    def test_brackets(self):
        self.assertEqual(expand_brackets("#% increased [Attack] Speed"), "#% increased Attack Speed")
        self.assertEqual(
            expand_brackets("+#% to [Resistance|Cold Resistance]"), "+#% to Cold Resistance"
        )

    def test_normalize_signs_and_case(self):
        self.assertEqual(normalize("+25 to maximum Life"), "# to maximum life")
        self.assertEqual(normalize("+# to maximum Life"), "# to maximum life")
        self.assertEqual(normalize("-4 to all Attributes"), "# to all attributes")


class TestStatsDB(unittest.TestCase):
    def setUp(self):
        self.db = StatsDB.from_api_payload(STATS_PAYLOAD)

    def test_loaded(self):
        self.assertFalse(self.db.is_empty)
        expected = sum(len(g["entries"]) for g in STATS_PAYLOAD["result"])
        self.assertEqual(len(self.db.entries), expected)

    def test_exact_match(self):
        entry, mult, opt = self.db.match("+25 to maximum Life", "explicit")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.id, "explicit.stat_life")
        self.assertEqual(mult, 1.0)
        self.assertIsNone(opt)

    def test_bracket_match(self):
        entry, _, _ = self.db.match("15% increased Attack Speed", "explicit")
        self.assertEqual(entry.id, "explicit.stat_attack_speed")

        entry, _, _ = self.db.match("+15% to Cold Resistance", "rune")
        self.assertEqual(entry.id, "rune.stat_cold_res")

    def test_kind_disambiguation(self):
        entry, _, _ = self.db.match("+82 to all Attributes", "explicit")
        self.assertEqual(entry.id, "explicit.stat_all_attributes")
        entry, _, _ = self.db.match("+12 to all Attributes", "implicit")
        self.assertEqual(entry.id, "implicit.stat_all_attributes")

    def test_reduced_to_increased(self):
        entry, mult, _ = self.db.match("10% reduced Attribute Requirements", "explicit")
        self.assertEqual(entry.id, "explicit.stat_attr_req")
        self.assertEqual(mult, -1.0)

    def test_option_match(self):
        entry, mult, option = self.db.match("Allocates Ancestral Knowledge", "explicit")
        self.assertEqual(entry.id, "explicit.stat_allocates")
        self.assertEqual(option, 1)

    def test_no_match(self):
        entry, _, _ = self.db.match("Совершенно выдуманный мод", "explicit")
        self.assertIsNone(entry)

    def test_search(self):
        found = self.db.search("life")
        self.assertTrue(any(e.id == "explicit.stat_life" for e in found))
        found = self.db.search("attack speed", kinds=["explicit"])
        self.assertEqual(found[0].id, "explicit.stat_attack_speed")


class TestFixtureCoverage(unittest.TestCase):
    """Пул модов в фикстурах обязан покрывать моды всех предметов-фикстур.

    Если какой-то мод не опознаётся, он выпадает из расчётов — и тесты,
    которые на нём завязаны, ведут себя не как настоящая программа
    с полным пулом от торговой площадки. Такие расхождения раньше
    всплывали только в CI, на Qt-тестах. Этот сторож ловит их сразу.
    """

    def test_every_fixture_mod_is_in_the_pool(self):
        import fixtures

        db = StatsDB.from_api_payload(STATS_PAYLOAD)
        names = [
            name
            for name in dir(fixtures)
            if name.isupper()
            and isinstance(getattr(fixtures, name), str)
            and "Rarity:" in getattr(fixtures, name)
        ]
        self.assertTrue(names, "фикстуры предметов не найдены")

        unmatched: list[str] = []
        for name in sorted(names):
            item = parse_item(getattr(fixtures, name))
            if item is None or item.is_currency_like:
                continue  # у валюты моды — это описание эффекта, stat-id им не положен
            for mod in item.mods:
                if db.match(mod.text, mod.kind)[0] is None:
                    unmatched.append(f"{name}: [{mod.kind}] {mod.text}")

        self.assertEqual(
            unmatched,
            [],
            "добавь эти моды в STATS_PAYLOAD:\n  " + "\n  ".join(unmatched),
        )


class TestQuery(unittest.TestCase):
    def setUp(self):
        self.db = StatsDB.from_api_payload(STATS_PAYLOAD)

    def test_bounds(self):
        self.assertEqual(suggest_bounds(100, 0.1, min_only=True), (90, None))
        self.assertEqual(suggest_bounds(100, 0.1, min_only=False), (90, 110))
        lo, hi = suggest_bounds(-4, 0.1, min_only=True)
        self.assertIsNone(lo)
        self.assertLess(hi, 0)

    def test_build_mod_filters(self):
        item = parse_item(RARE_GLOVES)
        filters = build_mod_filters(item, self.db, default_kinds=["explicit"])
        by_text = {f.text: f for f in filters}

        life = by_text["+25 to maximum Life"]
        self.assertTrue(life.enabled)
        self.assertEqual(life.stat_id, "explicit.stat_life")
        self.assertEqual(life.min_value, 22.5)

        rune = by_text["+15% to Cold Resistance"]
        self.assertFalse(rune.enabled)  # руны по умолчанию выключены
        self.assertTrue(rune.matched)

        attr = by_text["10% reduced Attribute Requirements"]
        self.assertEqual(attr.source_value, -10.0)

    def test_build_query_rare(self):
        item = parse_item(RARE_GLOVES)
        filters = build_mod_filters(item, self.db, default_kinds=["explicit"])
        opts = default_options_for(item, {"include_corrupted": True, "include_rarity": True})
        query = build_query(item, filters, opts)

        self.assertEqual(query["sort"], {"price": "asc"})
        self.assertEqual(query["query"]["type"], "Feathered Gauntlets")
        self.assertNotIn("name", query["query"])
        stats = query["query"]["stats"][0]["filters"]
        self.assertTrue(stats)
        ids = {f["id"] for f in stats}
        self.assertIn("explicit.stat_life", ids)
        self.assertNotIn("rune.stat_cold_res", ids)

        type_filters = query["query"]["filters"]["type_filters"]["filters"]
        self.assertEqual(type_filters["category"]["option"], "armour.gloves")
        self.assertEqual(type_filters["rarity"]["option"], "nonunique")
        misc = query["query"]["filters"]["misc_filters"]["filters"]
        self.assertEqual(misc["corrupted"]["option"], "true")

    def test_build_query_unique_uses_name(self):
        item = parse_item(UNIQUE_AMULET)
        opts = default_options_for(item, {})
        query = build_query(item, [], opts)
        self.assertEqual(query["query"]["name"], "Astramentis")
        self.assertEqual(query["query"]["type"], "Stellar Amulet")
        self.assertEqual(
            query["query"]["filters"]["type_filters"]["filters"]["rarity"]["option"], "unique"
        )

    def test_default_sale_type_is_instant_buyout(self):
        """По умолчанию ищем только то, что можно купить моментально."""
        query = build_query(None, [], QueryOptions())
        self.assertEqual(query["query"]["status"], {"option": "securable"})

    def test_sale_type_comes_from_config(self):
        item = parse_item(RARE_GLOVES)
        opts = default_options_for(item, {"status": "onlineleague"})
        self.assertEqual(opts.status, "onlineleague")
        query = build_query(item, [], opts)
        self.assertEqual(query["query"]["status"], {"option": "onlineleague"})

    def test_sale_type_values_are_valid_api_options(self):
        """Подписи в оверлее обязаны ссылаться на реальные значения API.

        Список взят из типа listingType в Exiled-Exchange-2, который
        работает с тем же trade2: any | online | onlineleague |
        securable | available.
        """
        valid = {"any", "online", "onlineleague", "securable", "available"}
        from poe2helper.config import DEFAULTS

        self.assertIn(DEFAULTS["search"]["status"], valid)

        try:
            from poe2helper.ui.overlay import STATUS_OPTIONS
        except ImportError:
            self.skipTest("PySide6 не установлен")
        values = [value for _, value in STATUS_OPTIONS]
        self.assertTrue(set(values) <= valid, f"недопустимые значения: {values}")
        self.assertEqual(values[0], "securable", "первым идёт вариант по умолчанию")
        self.assertEqual(len(values), len(set(values)), "значения не должны повторяться")

    def test_disabled_mods_are_dropped(self):
        mf_on = ModFilter(stat_id="a", text="a", enabled=True, min_value=5)
        mf_off = ModFilter(stat_id="b", text="b", enabled=False, min_value=5)
        query = build_query(None, [mf_on, mf_off], QueryOptions())
        filters = query["query"]["stats"][0]["filters"]
        self.assertEqual([f["id"] for f in filters], ["a"])
        self.assertEqual(filters[0]["value"], {"min": 5})

    def test_option_filter_serialises_option(self):
        mf = ModFilter(stat_id="explicit.stat_allocates", text="Allocates X", enabled=True, option_id=1)
        query = build_query(None, [mf], QueryOptions())
        self.assertEqual(query["query"]["stats"][0]["filters"][0]["value"], {"option": 1})


if __name__ == "__main__":
    unittest.main()
