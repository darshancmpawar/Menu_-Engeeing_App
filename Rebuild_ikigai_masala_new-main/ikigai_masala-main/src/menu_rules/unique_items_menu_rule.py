"""
Unique items menu rule implementation.
"""

import logging
from typing import Dict, Any, List
from ortools.sat.python import cp_model
from .base_menu_rule import BaseMenuRule, MenuRuleType

logger = logging.getLogger(__name__)


class UniqueItemsMenuRule(BaseMenuRule):
    """
    Ensures items are not repeated within a planning session.

    Config format:
    {
        "name": "unique_items_session",
        "type": "unique_items",
        "scope": "session"
    }
    """

    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.UNIQUE_ITEMS
        self.scope = self.config.get('scope', 'session').lower()

    def validate_config(self) -> bool:
        """Validate the unique items rule configuration"""
        valid_scopes = {'session'}
        if self.scope not in valid_scopes:
            logger.warning("Unique items rule '%s' has invalid scope '%s'", self.name, self.scope)
            return False
        return True

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        """
        Apply unique items rule to the model.

        For the session scope, prevents selecting the same item on more than one day.
        """
        if 'daily_items' not in variables:
            return

        if self.scope != 'session':
            return

        # Collect all item IDs across the planning horizon
        all_item_ids: List[str] = []
        for day_vars in variables['daily_items'].values():
            all_item_ids.extend(day_vars.keys())

        # Enforce: each item can be selected at most once across all days
        unique_item_ids = set(all_item_ids)
        for item_id in unique_item_ids:
            item_usage = []
            for day_vars in variables['daily_items'].values():
                if item_id in day_vars:
                    item_usage.append(day_vars[item_id])

            if item_usage:
                model.Add(sum(item_usage) <= 1)

        logger.info("Applied unique items rule: %s", self.name)
