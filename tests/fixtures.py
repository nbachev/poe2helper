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

RARE_BOW = """Item Class: Bows
Rarity: Rare
Woe Fletch
Advanced Dualstring Bow
--------
Quality: +20% (augmented)
Physical Damage: 44-82 (augmented)
Elemental Damage: 12-24 (augmented), 5-9 (augmented)
Critical Hit Chance: 6.50%
Attacks per Second: 1.25
--------
Requirements:
Level: 62
Dex: 152
--------
Sockets: S S
--------
Item Level: 78
--------
72% increased Physical Damage
Adds 12 to 24 Fire Damage
Adds 5 to 9 Lightning Damage
+25 to maximum Life
"""

RARE_BODY_ARMOUR = """Item Class: Body Armours
Rarity: Rare
Doom Guard
Advanced Vaal Cuirass
--------
Quality: +20% (augmented)
Armour: 512 (augmented)
Evasion Rating: 120
Energy Shield: 44
--------
Requirements:
Level: 65
Str: 133
--------
Item Level: 81
--------
+82 to maximum Life
+15% to Cold Resistance
"""

SHIELD_WITH_BLOCK = """Item Class: Shields
Rarity: Rare
Bramble Ward
Advanced Wooden Buckler
--------
Block chance: 30%
Evasion Rating: 210
Spirit: 25
--------
Item Level: 74
--------
+40 to maximum Life
"""

# Предмет, скопированный с включёнными расширенными описаниями модов
# (Advanced Mod Descriptions) — именно в таком виде игра отдаёт буфер,
# если опция включена в настройках.
# Реальный буфер из игры (скопирован пользователем), ничего не отредактировано:
# руна отдельной секцией с суффиксом (rune), аффиксы с аннотациями,
# дробный разброс «16.1(13.1-18)» и хвостовой пробел в строке сокетов.
ADVANCED_BOOTS = """Item Class: Boots
Rarity: Rare
Corruption Span
Carved Greaves
--------
Armour: 368 (augmented)
--------
Requires: Level 59, 78 Str
--------
Sockets: S
--------
Item Level: 81
--------
5% increased Movement Speed (rune)
--------
{ Prefix Modifier "Cheetah's" (Tier: 2) — Speed }
30% increased Movement Speed
{ Prefix Modifier "Rotund" (Tier: 3) — Life }
+97(85-99) to maximum Life
{ Prefix Modifier "Buttressed" (Tier: 4) — Armour }
65(56-67)% increased Armour
{ Suffix Modifier "of the Tempest" (Tier: 4) — Elemental, Lightning, Resistance }
+29(26-30)% to Lightning Resistance
{ Suffix Modifier "of Magma" (Tier: 2) — Elemental, Fire, Resistance }
+36(36-40)% to Fire Resistance
{ Suffix Modifier "of Convalescence" (Tier: 2) — Life }
16.1(13.1-18) Life Regeneration per second
"""

ADVANCED_WEAPON = """Item Class: Bows
Rarity: Rare
Blood Song
Advanced Dualstring Bow
--------
Physical Damage: 44(40-48)-82(75-90) (augmented)
Critical Hit Chance: 6.50%
Attacks per Second: 1.20
--------
Item Level: 80
--------
{ Implicit Modifier — Damage }
12(10-15)% increased Damage
--------
{ Prefix Modifier "Cruel" (Tier: 1) — Damage, Physical }
120(110-129)% increased Physical Damage
"""

# Ещё один реальный буфер. Здесь две особенности:
#  1. Игра вставила служебную строку туда, где обычно имя предмета,
#     а имя с базой уехали в следующую секцию.
#  2. Аффикс «Mammoth's» гибридный — одна аннотация, две строки статов.
SHIELD_ADVANCED = """Item Class: Shields
Rarity: Rare
You cannot use this item. Its stats will be ignored
--------
Carrion Bastion
Tawhoan Tower Shield
--------
Quality: +20% (augmented)
Block chance: 26%
Armour: 1480 (augmented)
--------
Requires: Level 80, 115 Str
--------
Sockets: S
--------
Item Level: 82
--------
18% increased Armour, Evasion and Energy Shield (rune)
--------
Grants Skill: Raise Shield
--------
{ Prefix Modifier "Enveloped" (Tier: 3) — Armour }
+216(191-221) to Armour
{ Prefix Modifier "Impregnable" (Tier: 2) — Armour }
99(92-100)% increased Armour
{ Prefix Modifier "Mammoth's" (Tier: 1) }
40(39-42)% increased Armour
+123(95-136) to Stun Threshold
{ Suffix Modifier "of Granite Skin" (Tier: 5) }
+122(98-124) to Stun Threshold
{ Suffix Modifier "of the Maelstrom" (Tier: 3) — Elemental, Lightning, Resistance }
+35(31-35)% to Lightning Resistance
{ Suffix Modifier "of the Gorilla" (Tier: 4) — Attribute }
+21(21-24) to Strength
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
                {
                    "id": "explicit.stat_movement_speed",
                    "text": "#% increased Movement Speed",
                    "type": "explicit",
                },
                {
                    "id": "explicit.stat_armour_pct",
                    "text": "#% increased Armour",
                    "type": "explicit",
                },
                {
                    "id": "explicit.stat_lightning_res",
                    "text": "+#% to [Resistance|Lightning Resistance]",
                    "type": "explicit",
                },
                {
                    "id": "explicit.stat_phys_pct",
                    "text": "#% increased Physical Damage",
                    "type": "explicit",
                },
                {
                    "id": "explicit.stat_fire_res",
                    "text": "+#% to [Resistance|Fire Resistance]",
                    "type": "explicit",
                },
                {
                    "id": "explicit.stat_life_regen",
                    "text": "# Life Regeneration per second",
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
                },
                {
                    "id": "rune.stat_movement_speed",
                    "text": "#% increased Movement Speed",
                    "type": "rune",
                },
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
