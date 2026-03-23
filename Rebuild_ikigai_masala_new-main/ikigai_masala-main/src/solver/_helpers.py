"""
Shared utility functions for the solver package.

These helpers are used by menu_solver, solution_formatter, and regenerator.
"""

import datetime as dt
import re


def weekday_type(d: dt.date) -> str:
    """Return the theme type for a given date's weekday."""
    wd = d.strftime('%A').lower()
    return {
        'monday': 'mix', 'tuesday': 'chinese', 'wednesday': 'biryani',
        'thursday': 'south', 'friday': 'north',
    }.get(wd, 'holiday' if wd in ('saturday', 'sunday') else 'normal')


def theme_label(day_type: str) -> str:
    """Return a human-readable label for a day theme type."""
    return {
        'mix': 'Mix of South + North', 'chinese': 'Chinese',
        'biryani': 'Biryani', 'south': 'South Indian',
        'north': 'North Indian', 'holiday': 'Holiday', 'normal': 'Normal',
    }.get(day_type, day_type.capitalize())


def strip_color_suffix(s: str) -> str:
    """Remove trailing color suffix like '(R)' from an item string."""
    return re.sub(r'\([A-Z]\)\s*$', '', (s or '').strip()).strip()
