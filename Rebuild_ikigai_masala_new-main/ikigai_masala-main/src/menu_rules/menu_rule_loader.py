"""
Menu rule loader from JSON configuration.
"""

import json
from pathlib import Path
from typing import List, Dict, Any

from .base_menu_rule import BaseMenuRule, MenuRuleType
from .cuisine_menu_rule import CuisineMenuRule
from .color_pairing_menu_rule import ColorPairingMenuRule
from .color_variety_menu_rule import ColorVarietyMenuRule
from .unique_items_menu_rule import UniqueItemsMenuRule
from .theme_day_menu_rule import ThemeDayMenuRule
from .coupling_menu_rule import CouplingMenuRule
from .curd_side_menu_rule import CurdSideMenuRule
from .premium_menu_rule import PremiumMenuRule
from .welcome_drink_color_menu_rule import WelcomeDrinkColorMenuRule
from .week_signature_cooldown_menu_rule import WeekSignatureCooldownMenuRule
from .theme_starter_preference_rule import ThemeStarterPreferenceRule
from .theme_fallback_penalty_rule import ThemeFallbackPenaltyRule


class MenuRuleLoader:
    """Loads menu rules from JSON configuration files."""

    RULE_CLASSES = {
        'cuisine': CuisineMenuRule,
        'color_pairing': ColorPairingMenuRule,
        'color_variety': ColorVarietyMenuRule,
        'unique_items': UniqueItemsMenuRule,
        'theme_day': ThemeDayMenuRule,
        'coupling': CouplingMenuRule,
        'curd_side': CurdSideMenuRule,
        'premium': PremiumMenuRule,
        'welcome_drink_color': WelcomeDrinkColorMenuRule,
        'week_signature_cooldown': WeekSignatureCooldownMenuRule,
        'theme_starter_preference': ThemeStarterPreferenceRule,
        'theme_fallback_penalty': ThemeFallbackPenaltyRule,
    }

    def __init__(self, config_path: str = None):
        self.config_path = Path(config_path) if config_path else None
        self.rules = []

    def load_from_file(self, config_path: str = None) -> List[BaseMenuRule]:
        if config_path:
            self.config_path = Path(config_path)
        if not self.config_path or not self.config_path.exists():
            raise FileNotFoundError(f"Menu rule config file not found: {self.config_path}")
        with open(self.config_path, 'r') as f:
            config_data = json.load(f)
        return self.load_from_dict(config_data)

    def load_from_dict(self, config_data: Dict[str, Any]) -> List[BaseMenuRule]:
        self.rules = []
        rules_list = config_data.get('rules', config_data.get('constraints', []))
        for rule_config in rules_list:
            try:
                rule = self._create_rule(rule_config)
                if rule and rule.validate_config():
                    self.rules.append(rule)
                else:
                    print(f"Warning: Invalid rule config: {rule_config.get('name')}")
            except Exception as e:
                print(f"Error creating rule: {e}")
        print(f"Loaded {len(self.rules)} menu rule(s)")
        return self.rules

    def _create_rule(self, rule_config: Dict[str, Any]) -> BaseMenuRule:
        rule_type = rule_config.get('type', '').lower()
        if rule_type not in self.RULE_CLASSES:
            raise ValueError(f"Unknown rule type: {rule_type}")
        return self.RULE_CLASSES[rule_type](rule_config)

    def get_rules_by_type(self, rule_type: str) -> List[BaseMenuRule]:
        return [r for r in self.rules if r.rule_type.value == rule_type]

    def get_enabled_rules(self) -> List[BaseMenuRule]:
        return list(self.rules)
