"""
Color pairing menu rule implementation.
"""

import logging
from typing import Dict, Any, List
from ortools.sat.python import cp_model
from .base_menu_rule import BaseMenuRule, MenuRuleType

logger = logging.getLogger(__name__)


class ColorPairingMenuRule(BaseMenuRule):
    """
    Ensures two course types are not the same color in the same session/day.

    Config format:
    {
        "name": "starter_main_color_mismatch",
        "type": "color_pairing",
        "course_type_a": "starter",
        "course_type_b": "main",
    }
    """

    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.COLOR_PAIRING

        self.course_type_a = self.config.get('course_type_a', '')
        self.course_type_b = self.config.get('course_type_b', '')

    def validate_config(self) -> bool:
        """Validate the color pairing rule configuration"""
        if not self.course_type_a or not self.course_type_b:
            logger.warning("Color pairing rule '%s' missing course types", self.name)
            return False
        if self.course_type_a == self.course_type_b:
            logger.warning("Color pairing rule '%s' has identical course types", self.name)
            return False
        return True

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        """
        Apply color pairing rule to the model.

        For each day, prevents selecting items with the same item_color
        for the configured pair of course types.
        """
        if not hasattr(menu_data, 'columns') or 'item_color' not in menu_data.columns:
            logger.warning("Menu data missing 'item_color' for rule '%s'", self.name)
            return

        if 'daily_items' not in variables:
            return

        color_map_a = self._group_items_by_color(menu_data, self.course_type_a)
        color_map_b = self._group_items_by_color(menu_data, self.course_type_b)

        if not color_map_a or not color_map_b:
            logger.warning("No items found for color pairing rule '%s'", self.name)
            return

        planning_dates = context.get('planning_dates', [])

        for date_info in planning_dates:
            day_key = date_info.get('date')
            if day_key not in variables['daily_items']:
                continue

            day_vars = variables['daily_items'][day_key]

            for color, items_a in color_map_a.items():
                items_b = color_map_b.get(color, [])
                if not items_b:
                    continue

                vars_a = [day_vars[item_id] for item_id in items_a if item_id in day_vars]
                vars_b = [day_vars[item_id] for item_id in items_b if item_id in day_vars]

                if vars_a and vars_b:
                    # Prevent same color across the two courses on the same day
                    model.Add(sum(vars_a) + sum(vars_b) <= 1)

        logger.info("Applied color pairing rule: %s", self.name)

    def _group_items_by_color(self, menu_data: Any, course_type: str) -> Dict[str, List[str]]:
        """
        Group items by item_color for a specific course type.
        """
        color_map: Dict[str, List[str]] = {}

        if hasattr(menu_data, 'loc'):
            filtered = menu_data[menu_data['course_type'] == course_type]
            for color, group in filtered.groupby('item_color'):
                color_map[color] = group['item_id'].tolist()

        return color_map
