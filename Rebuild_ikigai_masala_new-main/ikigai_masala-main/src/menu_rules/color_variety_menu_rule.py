"""
Color variety menu rule implementation.
"""

import logging
from typing import Dict, Any, List
import re
from ortools.sat.python import cp_model
from .base_menu_rule import BaseMenuRule, MenuRuleType

logger = logging.getLogger(__name__)


class ColorVarietyMenuRule(BaseMenuRule):
    """
    Ensures a minimum number of distinct colors in a session/day.

    Config format:
    {
        "name": "daily_color_variety",
        "type": "color_variety",
        "min_distinct_colors": {
            "breakfast": 2,
            "lunch": 3,
            "dinner": 3,
            "snack": 1
        }
    }
    """

    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.COLOR_VARIETY

        self.min_distinct_colors = self.config.get('min_distinct_colors', None)

    def validate_config(self) -> bool:
        """Validate the color variety rule configuration"""
        if not isinstance(self.min_distinct_colors, dict):
            logger.warning("Color variety rule '%s' missing min_distinct_colors mapping", self.name)
            return False
        if not self.min_distinct_colors:
            logger.warning("Color variety rule '%s' has empty min_distinct_colors mapping", self.name)
            return False
        for meal_type, value in self.min_distinct_colors.items():
            try:
                if int(value) <= 0:
                    logger.warning("Color variety rule '%s' has invalid min_distinct_colors for meal_type '%s'", self.name, meal_type)
                    return False
            except (TypeError, ValueError):
                logger.warning("Color variety rule '%s' has invalid min_distinct_colors for meal_type '%s'", self.name, meal_type)
                return False
        return True

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        """
        Apply color variety rule to the model.

        For each day, ensures at least `min_distinct_colors` different
        item_color values are selected across the meal.
        """
        if not hasattr(menu_data, 'columns') or 'item_color' not in menu_data.columns:
            logger.warning("Menu data missing 'item_color' for rule '%s'", self.name)
            return

        if 'daily_items' not in variables:
            return

        color_map = self._group_items_by_color(menu_data)
        if not color_map:
            logger.warning("No items found for color variety rule '%s'", self.name)
            return

        min_distinct_colors = self._resolve_min_distinct_colors(context)
        if min_distinct_colors <= 0:
            logger.warning("Color variety rule '%s' missing min_distinct_colors", self.name)
            return

        planning_dates = context.get('planning_dates', [])

        for date_info in planning_dates:
            day_key = date_info.get('date')
            if day_key not in variables['daily_items']:
                continue

            day_vars = variables['daily_items'][day_key]
            color_used_vars = []

            for color, item_ids in color_map.items():
                color_item_vars = [day_vars[item_id] for item_id in item_ids if item_id in day_vars]
                if not color_item_vars:
                    continue

                color_safe = self._sanitize_label(str(color))
                used_var = model.NewBoolVar(f"color_used_{color_safe}_day_{day_key}")

                # Link: used_var == 1 iff any item of this color is selected on this day
                model.Add(sum(color_item_vars) >= used_var)
                model.Add(sum(color_item_vars) <= len(color_item_vars) * used_var)

                color_used_vars.append(used_var)

            if color_used_vars:
                model.Add(sum(color_used_vars) >= min_distinct_colors)

        logger.info("Applied color variety rule: %s", self.name)

    def _group_items_by_color(self, menu_data: Any) -> Dict[str, List[str]]:
        """
        Group items by item_color across all course types.
        """
        color_map: Dict[str, List[str]] = {}

        if hasattr(menu_data, 'loc'):
            for color, group in menu_data.groupby('item_color'):
                color_map[color] = group['item_id'].tolist()

        return color_map

    def _sanitize_label(self, value: str) -> str:
        """
        Sanitize label for use in variable names.
        """
        return re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_") or "unknown"

    def _resolve_min_distinct_colors(self, context: Dict[str, Any]) -> int:
        """
        Resolve the min distinct color requirement for the current meal type.
        """
        meal_type = context.get('meal_type')
        if not meal_type or not isinstance(self.min_distinct_colors, dict):
            return 0
        if meal_type not in self.min_distinct_colors:
            return 0
        try:
            return int(self.min_distinct_colors[meal_type])
        except (TypeError, ValueError):
            return 0
