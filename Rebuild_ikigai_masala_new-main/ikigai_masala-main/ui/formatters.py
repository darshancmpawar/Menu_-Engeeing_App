"""
UI formatting utilities for menu plan display.
"""

import re
from typing import Dict, Optional

from src.preprocessor.pool_builder import DISPLAY_SLOT_NAME, CONST_SLOTS, CONSTANT_ITEMS


# Day-of-week theme labels (Monday=0)
THEME_LABELS = {
    0: "Mix of South + North",
    1: "Chinese / Indo-Chinese",
    2: "Biryani Day",
    3: "South Indian",
    4: "North Indian",
    5: "Weekend Special",
    6: "Weekend Special",
}


def theme_label(weekday: int) -> str:
    return THEME_LABELS.get(weekday, "")


def display_label_for_slot_id(slot_id: str) -> str:
    return DISPLAY_SLOT_NAME.get(slot_id, slot_id.replace("_", " ").title())


def format_item_for_ui(item_str: str) -> str:
    if not item_str:
        return ""
    return item_str.strip()


def pretty_text(item_str: str) -> str:
    if not item_str:
        return ""
    # Strip color suffix like (R), (G), etc.
    cleaned = re.sub(r'\s*\([A-Z]\)\s*$', '', item_str)
    return cleaned.strip().title()


def color_suffix(item_str: str) -> Optional[str]:
    m = re.search(r'\(([A-Z])\)\s*$', item_str)
    return m.group(1) if m else None


def slot_sort_key(slot_id: str) -> int:
    """Return sort index for display ordering."""
    from src.preprocessor.pool_builder import BASE_SLOT_NAMES
    base = slot_id.split("__")[0] if "__" in slot_id else slot_id
    try:
        return BASE_SLOT_NAMES.index(base)
    except ValueError:
        return 999
