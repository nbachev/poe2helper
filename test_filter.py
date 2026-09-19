import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import FILTER_SAMPLE  # noqa: E402
from poe2helper.filters.parse import FilterFile, join_values, split_values  # noqa: E402
from poe2helper.filters.retier import (  # noqa: E402
    EMPTY_PLACEHOLDER,
    adapt_thresholds,
    detect_groups,
    norm_name,
    retier,
    tier_for_price,
)
from poe2helper.trade.ninja import PriceInfo, _parse_overview  # noqa: E402


def price(name: str, exalted: float) -> PriceInfo:
    return PriceInfo(name=name, divine=exalted / 400, exalted=exalted, chaos=exalted * 8)


PRICES = {
    "Mirror of Kalandra": price("Mirror of Kalandra", 50000),
    "Divine Orb": price("Divine Orb", 400),
    "Exalted Orb": price("Exalted Orb", 1),
    "Chaos Orb": price("Chaos Orb", 0.12),
    "Orb of Alchemy": price("Orb of Alchemy", 0.05),
}

THRESHOLDS = {"currency": [40, 10, 3, 1, 0.3, 0.1, 0.03]}


class TestFilterParse(unittest.TestCase):
    def setUp(self):
        self.ff = FilterFile.parse_text(FILTER_SAMPLE)

    def test_values_roundtrip(self):
        self.assertEqual(split_values('"Divine Orb" "Chaos Orb"'), ["Divine Orb", "Chaos Orb"])
        self.assertEqual(split_values("Gold"), ["Gold"])
        self.assertEqual(join_values(["A", "B"]), '"A" "B"')

    def test_blocks_found(self):
        self.assertEqual(len(self.ff.blocks), 6)
        self.assertEqual(self.ff.blocks[0].action, "Show")
        self.assertEqual(self.ff.blocks[-1].action, "Hide")

    def test_tags(self):
        block = self.ff.blocks[0]
        self.assertEqual(block.type_tag, "currency")
        self.assertEqual(block.tier_tag, "t1")
        self.assertEqual(block.tier_number, 1)
        self.assertIsNone(self.ff.blocks[-1].tier_number)

    def test_conditions(self):
        block = self.ff.blocks[0]
        self.assertEqual(block.base_types, ["Mirror of Kalandra", "Orb of Alchemy"])
        self.assertEqual(block.classes, ["Stackable Currency"])
        self.assertTrue(block.has_condition("SetFontSize"))
        self.assertFalse(block.has_condition("StackSize"))
        self.assertTrue(self.ff.blocks[3].has_condition("StackSize"))

    def test_render_is_lossless(self):
        self.assertEqual(self.ff.render(), FILTER_SAMPLE)

    def test_set_values_keeps_indent_and_operator(self):
        block = self.ff.blocks[1]
        block.set_condition_values("BaseType", ["A", "B"])
        line = [l for l in block.lines if "BaseType" in l][0]
        self.assertEqual(line, '\tBaseType == "A" "B"')

    def test_known_types(self):
        self.assertEqual(self.ff.known_types(), ["currency", "gold"])


class TestThresholds(unittest.TestCase):
    def test_adapt_shrinks_and_grows(self):
        self.assertEqual(adapt_thresholds([40, 10, 3, 1], 3), [40, 10])
        grown = adapt_thresholds([40], 4)
        self.assertEqual(len(grown), 3)
        self.assertEqual(grown[0], 40)
        self.assertAlmostEqual(grown[1], 40 / 3)

    def test_tier_for_price(self):
        th = [40, 10, 3]
        self.assertEqual(tier_for_price(100, th), 0)
        self.assertEqual(tier_for_price(40, th), 0)
        self.assertEqual(tier_for_price(11, th), 1)
        self.assertEqual(tier_for_price(3, th), 2)
        self.assertEqual(tier_for_price(0.1, th), 3)

    def test_norm_name(self):
        self.assertEqual(norm_name("Perfect Jeweller’s Orb"), "perfect jeweller's orb")


class TestRetier(unittest.TestCase):
    def setUp(self):
        self.ff = FilterFile.parse_text(FILTER_SAMPLE)

    def test_moves_items_between_tiers(self):
        report = retier(self.ff, PRICES, THRESHOLDS, groups=["currency"])
        self.assertIn("currency", report.groups_processed)

        tiers = {b.tier_number: b.base_types for b in self.ff.blocks if b.type_tag == "currency" and b.tier_number}
        # 50000 ex и 400 ex -> в первый тир; 1 ex -> средний; дешёвые -> в последний
        self.assertIn("Mirror of Kalandra", tiers[1])
        self.assertIn("Divine Orb", tiers[1])
        self.assertIn("Exalted Orb", tiers[3])
        self.assertIn("Chaos Orb", tiers[3])
        self.assertIn("Orb of Alchemy", tiers[3])

        moved = {m.name for m in report.moves}
        self.assertIn("Divine Orb", moved)
        self.assertIn("Orb of Alchemy", moved)

    def test_stacksize_block_untouched(self):
        before = list(self.ff.blocks[3].lines)
        retier(self.ff, PRICES, THRESHOLDS, groups=["currency"])
        self.assertEqual(self.ff.blocks[3].lines, before)

    def test_unknown_items_stay(self):
        prices = {"Divine Orb": PRICES["Divine Orb"]}
        report = retier(self.ff, prices, THRESHOLDS, groups=["currency"])
        self.assertIn("Mirror of Kalandra", report.unknown)
        tier1 = self.ff.blocks[0].base_types
        self.assertIn("Mirror of Kalandra", tier1)

    def test_empty_tier_gets_placeholder(self):
        prices = {name: price(name, 50000) for name in PRICES}
        retier(self.ff, prices, THRESHOLDS, groups=["currency"])
        tier2 = self.ff.blocks[1]
        self.assertEqual(tier2.base_types, [EMPTY_PLACEHOLDER])

    def test_unknown_group_reported(self):
        report = retier(
            self.ff, PRICES, {"essences": [1]}, groups=["essences"], auto_groups=False
        )
        self.assertIn("essences", report.groups_skipped)
        self.assertEqual(report.moves, [])

    def test_detect_groups(self):
        detected = detect_groups(self.ff)
        # gold — единственный блок и со StackSize, значит в перетиринг не годится
        self.assertEqual(list(detected), ["currency"])
        self.assertEqual(detected["currency"]["tiers"], [1, 2, 3])
        self.assertIn("Divine Orb", detected["currency"]["base_types"])

    def test_auto_groups_picks_up_renamed_tags(self):
        text = FILTER_SAMPLE.replace("$type->currency", "$type->economy->currency->any")
        ff = FilterFile.parse_text(text)
        # в настройках такой группы нет — помогает только автоопределение
        report = retier(ff, PRICES, {"currency": [40, 10, 3]}, groups=["currency"])
        self.assertIn("currency", report.groups_skipped)
        self.assertIn("economy->currency->any", report.groups_autodetected)
        self.assertTrue(report.moves)

    def test_auto_groups_skips_groups_without_prices(self):
        text = FILTER_SAMPLE.replace("$type->currency", "$type->bases")
        ff = FilterFile.parse_text(text)
        report = retier(ff, {}, {"currency": [40, 10, 3]}, groups=[])
        self.assertIn("bases", report.groups_skipped)
        self.assertEqual(report.moves, [])
        self.assertEqual(ff.render(), text)

    def test_auto_groups_can_be_disabled(self):
        report = retier(self.ff, PRICES, THRESHOLDS, groups=[], auto_groups=False)
        self.assertEqual(report.moves, [])
        self.assertEqual(self.ff.render(), FILTER_SAMPLE)

    def test_structure_preserved(self):
        before_lines = len(self.ff.render().splitlines())
        retier(self.ff, PRICES, THRESHOLDS, groups=["currency"])
        after = self.ff.render()
        self.assertEqual(len(after.splitlines()), before_lines)
        self.assertIn("SetTextColor 255 0 0 255", after)
        self.assertIn("$type->gold $tier->stack3", after)
        self.assertIn("PlayEffect Red", after)

    def test_idempotent(self):
        retier(self.ff, PRICES, THRESHOLDS, groups=["currency"])
        once = self.ff.render()
        second = retier(self.ff, PRICES, THRESHOLDS, groups=["currency"])
        self.assertEqual(self.ff.render(), once)
        self.assertEqual(second.moves, [])


class TestNinjaParsing(unittest.TestCase):
    def test_parse_overview(self):
        payload = {
            "core": {"rates": {"exalted": 444.7, "chaos": 8.36}, "primary": "divine"},
            "lines": [
                {"id": "alch", "primaryValue": 0.007415, "sparkline": {"totalChange": 26.41}},
                {"id": "exalted", "primaryValue": 0.002249},
                {"id": "no-meta", "primaryValue": 1.0},
            ],
            "items": [
                {"id": "alch", "name": "Orb of Alchemy", "category": "Currency"},
                {"id": "exalted", "name": "Exalted Orb", "category": "Currency"},
            ],
        }
        prices = _parse_overview(payload, "Currency")
        self.assertIn("Orb of Alchemy", prices)
        self.assertNotIn("no-meta", prices)  # без имени — пропускаем
        exalted = prices["Exalted Orb"]
        self.assertAlmostEqual(exalted.exalted, 1.0, places=2)
        self.assertAlmostEqual(exalted.divine, 0.002249)
        self.assertAlmostEqual(prices["Orb of Alchemy"].change, 26.41)
        self.assertAlmostEqual(prices["Orb of Alchemy"].value("chaos"), 0.007415 * 8.36)


if __name__ == "__main__":
    unittest.main()
