"""Тёмная тема оверлея."""

from __future__ import annotations

COLORS = {
    "bg": "#15171c",
    "bg_alt": "#1c1f26",
    "border": "#2c313c",
    "text": "#d7d9de",
    "text_dim": "#8b919c",
    "accent": "#c8a55b",
    "accent_dim": "#7a6535",
    "good": "#6fbf73",
    "bad": "#d9695f",
    "magic": "#8888ff",
    "rare": "#e8e337",
    "unique": "#af6025",
    "currency": "#aa9e82",
}

QSS = f"""
QWidget {{
    background-color: {COLORS['bg']};
    color: {COLORS['text']};
    font-family: "Segoe UI", "Noto Sans", sans-serif;
}}
QFrame#Card {{
    background-color: {COLORS['bg']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
}}
QLabel#Title {{
    font-size: 15px;
    font-weight: 600;
    color: {COLORS['accent']};
}}
QLabel#Subtitle {{
    color: {COLORS['text_dim']};
    font-size: 11px;
}}
QLabel#Section {{
    color: {COLORS['text_dim']};
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1px;
}}
QLabel#Hint {{
    color: {COLORS['text_dim']};
    font-size: 11px;
}}
QLabel#Unmatched {{
    color: {COLORS['text_dim']};
    font-style: italic;
}}
QPushButton {{
    background-color: {COLORS['bg_alt']};
    border: 1px solid {COLORS['border']};
    border-radius: 5px;
    padding: 5px 12px;
    color: {COLORS['text']};
}}
QPushButton:hover {{ border-color: {COLORS['accent_dim']}; }}
QPushButton:pressed {{ background-color: #23262e; }}
QPushButton#Primary {{
    background-color: {COLORS['accent_dim']};
    border-color: {COLORS['accent']};
    color: #17181c;
    font-weight: 600;
}}
QPushButton#Primary:hover {{ background-color: {COLORS['accent']}; }}
QPushButton#Flat {{
    background: transparent;
    border: none;
    color: {COLORS['text_dim']};
    padding: 2px 6px;
}}
QPushButton#Flat:hover {{ color: {COLORS['bad']}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background-color: {COLORS['bg_alt']};
    border: 1px solid {COLORS['border']};
    border-radius: 4px;
    padding: 3px 6px;
    selection-background-color: {COLORS['accent_dim']};
}}
QComboBox QAbstractItemView {{
    background-color: {COLORS['bg_alt']};
    border: 1px solid {COLORS['border']};
    selection-background-color: {COLORS['accent_dim']};
}}
QCheckBox {{ spacing: 6px; }}
QCheckBox::indicator {{
    width: 14px; height: 14px;
    border: 1px solid {COLORS['border']};
    border-radius: 3px;
    background: {COLORS['bg_alt']};
}}
QCheckBox::indicator:checked {{
    background: {COLORS['accent']};
    border-color: {COLORS['accent']};
}}
QScrollArea {{ border: none; }}
QScrollBar:vertical {{
    background: transparent; width: 9px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {COLORS['border']}; border-radius: 4px; min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: {COLORS['accent_dim']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QTableWidget {{
    background-color: {COLORS['bg']};
    gridline-color: {COLORS['border']};
    border: 1px solid {COLORS['border']};
    border-radius: 5px;
}}
QHeaderView::section {{
    background-color: {COLORS['bg_alt']};
    color: {COLORS['text_dim']};
    border: none;
    border-bottom: 1px solid {COLORS['border']};
    padding: 4px;
}}
QTabWidget::pane {{ border: 1px solid {COLORS['border']}; border-radius: 6px; }}
QTabBar::tab {{
    background: {COLORS['bg_alt']};
    border: 1px solid {COLORS['border']};
    padding: 6px 14px;
    margin-right: 2px;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
}}
QTabBar::tab:selected {{ border-bottom-color: {COLORS['accent']}; color: {COLORS['accent']}; }}
QToolTip {{
    background-color: {COLORS['bg_alt']};
    color: {COLORS['text']};
    border: 1px solid {COLORS['border']};
}}
"""


def rarity_color(rarity: str) -> str:
    return {
        "magic": COLORS["magic"],
        "rare": COLORS["rare"],
        "unique": COLORS["unique"],
        "currency": COLORS["currency"],
    }.get((rarity or "").lower(), COLORS["text"])
