"""Тестовые данные: образцы буфера обмена и кусок фильтра."""

RARE_GLOVES = """Item Class: Gloves
Rarity: Rare
Havoc Grasp
Feathered Gauntlets
--------
Quality: +20% (augmented)
Armour: 88 (augmented)
Evasion Rating: 45
--------
Requirements:
Level: 45
Str: 45
Dex: 45
--------
Sockets: S S
--------
Item Level: 68
--------
+15% to Cold Resistance (rune)
--------
+25 to maximum Life
15% increased Attack Speed
Adds 5 to 9 Physical Damage to Attacks
10% reduced Attribute Requirements
--------
Corrupted
"""

CURRENCY = """Item Class: Stackable Currency
Rarity: Currency
Divine Orb
--------
Stack Size: 3/10
--------
Randomises the numeric values of the modifiers on an item
--------
Right click this item then left click a magic, rare or unique item to apply it.
"""

UNIQUE_AMULET = """Item Class: Amulets
Rarity: Unique
Astramentis
Stellar Amulet
--------
Requirements:
Level: 20
--------
Item Level: 74
--------
+12 to all Attributes (implicit)
--------
+82 to all Attributes
-4 to all Attributes
"""

MAGIC_WAND = """Item Class: Wands
Rarity: Magic
Chaotic Attuned Wand of the Magus
--------
Requirements:
Level: 45
Int: 76
--------
Item Level: 62
--------
Grants Skill: Level 8 Chaos Bolt
--------
28% increased Spell Damage
+35 to maximum Mana
"""

NOT_AN_ITEM = "просто текст из буфера обмена, никакого предмета тут нет"


STATS_PAYLOAD = {
    "result": [
        {
            "id": "explicit",
            "label": "Explicit",
            "entries": [
                {"id": "explicit.stat_life", "text": "+# to maximum Life", "type": "explicit"},
                {
                    "id": "explicit.stat_attack_speed",
                    "text": "#% increased [Attack] Speed",
                    "type": "explicit",
                },
                {
                    "id": "explicit.stat_phys",
                    "text": "Adds # to # Physical Damage to Attacks",
                    "type": "explicit",
                },
                {
                    "id": "explicit.stat_attr_req",
                    "text": "#% increased Attribute Requirements",
                    "type": "explicit",
                },
                {
                    "id": "explicit.stat_all_attributes",
                    "text": "+# to all Attributes",
                    "type": "explicit",
                },
                {
                    "id": "explicit.stat_spell_damage",
                    "text": "#% increased Spell Damage",
                    "type": "explicit",
                },
                {"id": "explicit.stat_mana", "text": "+# to maximum Mana", "type": "explicit"},
                {
                    "id": "explicit.stat_allocates",
                    "text": "Allocates #",
                    "type": "explicit",
                    "option": {
                        "options": [
                            {"id": 1, "text": "Ancestral Knowledge"},
                            {"id": 2, "text": "Heavy Draw"},
                        ]
                    },
                },
            ],
        },
        {
            "id": "implicit",
            "label": "Implicit",
            "entries": [
                {
                    "id": "implicit.stat_all_attributes",
                    "text": "+# to all Attributes",
                    "type": "implicit",
                }
            ],
        },
        {
            "id": "rune",
            "label": "Rune",
            "entries": [
                {
                    "id": "rune.stat_cold_res",
                    "text": "+#% to [Resistance|Cold Resistance]",
                    "type": "rune",
                }
            ],
        },
    ]
}


FILTER_SAMPLE = """#===============================================================================
# NeverSink-подобный фильтр (урезанный образец для тестов)
#===============================================================================

Show # %D5 $type->currency $tier->t1
	Class "Stackable Currency"
	BaseType == "Mirror of Kalandra" "Orb of Alchemy"
	SetFontSize 45
	SetTextColor 255 0 0 255
	PlayEffect Red

Show # %D4 $type->currency $tier->t2
	Class "Stackable Currency"
	BaseType == "Divine Orb"
	SetFontSize 42
	SetTextColor 255 100 0 255

Show # %D3 $type->currency $tier->t3
	Class "Stackable Currency"
	BaseType == "Exalted Orb" "Chaos Orb"
	SetFontSize 38

Show # %D2 $type->currency $tier->stack1
	Class "Stackable Currency"
	StackSize >= 20
	BaseType == "Orb of Alchemy"
	SetFontSize 36

Show # $type->gold $tier->stack3
	StackSize >= 5000
	BaseType == "Gold"
	SetFontSize 40

Hide # прочее
	Class "Stackable Currency"
	SetFontSize 18
"""
