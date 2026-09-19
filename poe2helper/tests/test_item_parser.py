import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import CURRENCY, MAGIC_WAND, NOT_AN_ITEM, RARE_GLOVES, UNIQUE_AMULET  # noqa: E402
from poe2helper.parser.item import parse_item  # noqa: E402


class TestItemParser(unittest.TestCase):
    def test_not_an_item(self):
        self.assertIsNone(parse_item(NOT_AN_ITEM))
        self.assertIsNone(parse_item(""))

    def test_rare_gloves(self):
        item = parse_item(RARE_GLOVES)
        self.assertIsNotNone(item)
        self.assertEqual(item.item_class, "Gloves")
        self.assertEqual(item.rarity, "Rare")
        self.assertEqual(item.name, "Havoc Grasp")
        self.assertEqual(item.base_type, "Feathered Gauntlets")
        self.assertEqual(item.item_level, 68)
        self.assertEqual(item.quality, 20)
        self.assertEqual(item.sockets, 2)
        self.assertTrue(item.corrupted)
        self.assertTrue(item.identified)
        self.assertEqual(item.category, "armour.gloves")

        texts = [m.text for m in item.mods]
        self.assertIn("+25 to maximum Life", texts)
        self.assertIn("15% increased Attack Speed", texts)
        self.assertNotIn("Requirements", texts)

        rune = [m for m in item.mods if m.kind == "rune"]
        self.assertEqual(len(rune), 1)
        self.assertEqual(rune[0].text, "+15% to Cold Resistance")

    def test_mod_values_and_pattern(self):
        item = parse_item(RARE_GLOVES)
        life = next(m for m in item.mods if "maximum Life" in m.text)
        self.assertEqual(life.values, [25.0])
        self.assertEqual(life.value, 25.0)
        self.assertEqual(life.pattern, "# to maximum Life")

        phys = next(m for m in item.mods if "Physical Damage" in m.text)
        self.assertEqual(phys.values, [5.0, 9.0])
        self.assertEqual(phys.value, 7.0)  # среднее диапазона

    def test_currency(self):
        item = parse_item(CURRENCY)
        self.assertEqual(item.base_type, "Divine Orb")
        self.assertEqual(item.stack_size, 3)
        self.assertTrue(item.is_currency_like)
        # подсказка про правый клик не должна попасть в моды
        self.assertTrue(all("Right click" not in m.text for m in item.mods))

    def test_unique(self):
        item = parse_item(UNIQUE_AMULET)
        self.assertTrue(item.is_unique)
        self.assertEqual(item.name, "Astramentis")
        self.assertEqual(item.base_type, "Stellar Amulet")
        kinds = {m.kind for m in item.mods}
        self.assertIn("implicit", kinds)
        self.assertIn("explicit", kinds)
        negative = next(m for m in item.mods if m.text.startswith("-4"))
        self.assertEqual(negative.values, [-4.0])

    def test_magic_item_base_is_uncertain(self):
        item = parse_item(MAGIC_WAND)
        self.assertTrue(item.is_magic)
        self.assertFalse(item.base_type_certain)
        self.assertEqual(item.base_type, "Chaotic Attuned Wand")
        self.assertEqual(item.properties.get("grants skill"), "Level 8 Chaos Bolt")
        texts = [m.text for m in item.mods]
        self.assertIn("28% increased Spell Damage", texts)


if __name__ == "__main__":
    unittest.main()
