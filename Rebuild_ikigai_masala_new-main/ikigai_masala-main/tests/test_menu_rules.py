"""
Unit tests for individual menu rule implementations.

Tests validate_config, rule_type, config parsing, and basic properties.
CP-SAT constraint logic is tested indirectly via the integration test.
"""

import pytest
from src.menu_rules.coupling_menu_rule import CouplingMenuRule
from src.menu_rules.curd_side_menu_rule import CurdSideMenuRule
from src.menu_rules.premium_menu_rule import PremiumMenuRule
from src.menu_rules.theme_day_menu_rule import ThemeDayMenuRule
from src.menu_rules.welcome_drink_color_menu_rule import WelcomeDrinkColorMenuRule
from src.menu_rules.week_signature_cooldown_menu_rule import WeekSignatureCooldownMenuRule
from src.menu_rules.theme_starter_preference_rule import ThemeStarterPreferenceRule
from src.menu_rules.theme_fallback_penalty_rule import ThemeFallbackPenaltyRule
from src.menu_rules.unique_items_menu_rule import UniqueItemsMenuRule
from src.menu_rules.color_pairing_menu_rule import ColorPairingMenuRule
from src.menu_rules.color_variety_menu_rule import ColorVarietyMenuRule
from src.menu_rules.cuisine_menu_rule import CuisineMenuRule
from src.menu_rules.base_menu_rule import MenuRuleType


# --- CouplingMenuRule ---

class TestCouplingMenuRule:
    def test_validate(self):
        rule = CouplingMenuRule({"name": "coupling", "type": "coupling"})
        assert rule.validate_config()

    def test_rule_type(self):
        rule = CouplingMenuRule({"name": "coupling", "type": "coupling"})
        assert rule.rule_type == MenuRuleType.COUPLING

    def test_apply_no_context_is_safe(self):
        from ortools.sat.python import cp_model
        model = cp_model.CpModel()
        rule = CouplingMenuRule({"name": "coupling", "type": "coupling"})
        # apply with empty context should not crash
        rule.apply(model, {}, None, {})


# --- CurdSideMenuRule ---

class TestCurdSideMenuRule:
    def test_validate(self):
        rule = CurdSideMenuRule({"name": "curd", "type": "curd_side",
                                  "pulao_subcats": ["south_veg_pulao"]})
        assert rule.validate_config()

    def test_rule_type(self):
        rule = CurdSideMenuRule({"name": "curd", "type": "curd_side"})
        assert rule.rule_type == MenuRuleType.CURD_SIDE

    def test_pulao_subcats_default(self):
        rule = CurdSideMenuRule({"name": "curd", "type": "curd_side"})
        assert isinstance(rule.pulao_subcats, (list, set))

    def test_apply_no_context_is_safe(self):
        from ortools.sat.python import cp_model
        model = cp_model.CpModel()
        rule = CurdSideMenuRule({"name": "curd", "type": "curd_side"})
        rule.apply(model, {}, None, {})


# --- PremiumMenuRule ---

class TestPremiumMenuRule:
    def test_validate(self):
        rule = PremiumMenuRule({"name": "prem", "type": "premium",
                                "max_per_day": 1, "min_per_horizon": 1, "max_per_horizon": 2})
        assert rule.validate_config()

    def test_config_defaults(self):
        rule = PremiumMenuRule({"name": "prem", "type": "premium"})
        assert rule.max_per_day == 1
        assert rule.min_per_horizon == 1
        assert rule.max_per_horizon == 2

    def test_config_override(self):
        rule = PremiumMenuRule({"name": "prem", "type": "premium",
                                "max_per_day": 2, "max_per_horizon": 5})
        assert rule.max_per_day == 2
        assert rule.max_per_horizon == 5

    def test_rule_type(self):
        rule = PremiumMenuRule({"name": "prem", "type": "premium"})
        assert rule.rule_type == MenuRuleType.PREMIUM

    def test_apply_no_cfg_is_safe(self):
        from ortools.sat.python import cp_model
        model = cp_model.CpModel()
        rule = PremiumMenuRule({"name": "prem", "type": "premium"})
        rule.apply(model, {}, None, {})


# --- ThemeDayMenuRule ---

class TestThemeDayMenuRule:
    def test_validate(self):
        rule = ThemeDayMenuRule({"name": "theme", "type": "theme_day"})
        assert rule.validate_config()

    def test_rule_type(self):
        rule = ThemeDayMenuRule({"name": "theme", "type": "theme_day"})
        assert rule.rule_type == MenuRuleType.THEME_DAY


# --- WelcomeDrinkColorMenuRule ---

class TestWelcomeDrinkColorMenuRule:
    def test_validate(self):
        rule = WelcomeDrinkColorMenuRule({"name": "wd_color", "type": "welcome_drink_color"})
        assert rule.validate_config()

    def test_rule_type(self):
        rule = WelcomeDrinkColorMenuRule({"name": "wd_color", "type": "welcome_drink_color"})
        assert rule.rule_type == MenuRuleType.WELCOME_DRINK_COLOR


# --- WeekSignatureCooldownMenuRule ---

class TestWeekSignatureCooldownMenuRule:
    def test_validate(self):
        rule = WeekSignatureCooldownMenuRule({"name": "sig", "type": "week_signature_cooldown",
                                               "cooldown_days": 30})
        assert rule.validate_config()

    def test_cooldown_default(self):
        rule = WeekSignatureCooldownMenuRule({"name": "sig", "type": "week_signature_cooldown"})
        assert rule.cooldown_days == 30

    def test_rule_type(self):
        rule = WeekSignatureCooldownMenuRule({"name": "sig", "type": "week_signature_cooldown"})
        assert rule.rule_type == MenuRuleType.WEEK_SIGNATURE_COOLDOWN


# --- ThemeStarterPreferenceRule ---

class TestThemeStarterPreferenceRule:
    def test_validate(self):
        rule = ThemeStarterPreferenceRule({"name": "pref", "type": "theme_starter_preference",
                                            "bonus_weight": 1000000})
        assert rule.validate_config()

    def test_bonus_default(self):
        rule = ThemeStarterPreferenceRule({"name": "pref", "type": "theme_starter_preference"})
        assert rule.bonus_weight == 1000000

    def test_rule_type(self):
        rule = ThemeStarterPreferenceRule({"name": "pref", "type": "theme_starter_preference"})
        assert rule.rule_type == MenuRuleType.THEME_STARTER_PREFERENCE

    def test_apply_is_noop(self):
        """apply() should be a no-op since this rule only contributes to objective."""
        from ortools.sat.python import cp_model
        model = cp_model.CpModel()
        rule = ThemeStarterPreferenceRule({"name": "pref", "type": "theme_starter_preference"})
        rule.apply(model, {}, None, {})

    def test_get_objective_terms_empty_context(self):
        from ortools.sat.python import cp_model
        model = cp_model.CpModel()
        rule = ThemeStarterPreferenceRule({"name": "pref", "type": "theme_starter_preference"})
        terms = rule.get_objective_terms(model, {})
        assert terms == []


# --- ThemeFallbackPenaltyRule ---

class TestThemeFallbackPenaltyRule:
    def test_validate(self):
        rule = ThemeFallbackPenaltyRule({"name": "pen", "type": "theme_fallback_penalty",
                                          "penalty": 2000000})
        assert rule.validate_config()

    def test_penalty_default(self):
        rule = ThemeFallbackPenaltyRule({"name": "pen", "type": "theme_fallback_penalty"})
        assert rule.penalty == 2000000

    def test_rule_type(self):
        rule = ThemeFallbackPenaltyRule({"name": "pen", "type": "theme_fallback_penalty"})
        assert rule.rule_type == MenuRuleType.THEME_FALLBACK_PENALTY

    def test_get_objective_terms_empty_context(self):
        from ortools.sat.python import cp_model
        model = cp_model.CpModel()
        rule = ThemeFallbackPenaltyRule({"name": "pen", "type": "theme_fallback_penalty"})
        terms = rule.get_objective_terms(model, {})
        assert terms == []


# --- UniqueItemsMenuRule ---

class TestUniqueItemsMenuRule:
    def test_validate(self):
        rule = UniqueItemsMenuRule({"name": "unique", "type": "unique_items", "scope": "session"})
        assert rule.validate_config()

    def test_rule_type(self):
        rule = UniqueItemsMenuRule({"name": "unique", "type": "unique_items"})
        assert rule.rule_type == MenuRuleType.UNIQUE_ITEMS


# --- ColorPairingMenuRule ---

class TestColorPairingMenuRule:
    def test_validate(self):
        rule = ColorPairingMenuRule({"name": "color_pair", "type": "color_pairing",
                                      "course_type_a": "rice", "course_type_b": "veg_gravy"})
        assert rule.validate_config()

    def test_validate_fails_without_courses(self):
        rule = ColorPairingMenuRule({"name": "color_pair", "type": "color_pairing"})
        assert rule.validate_config() is False

    def test_rule_type(self):
        rule = ColorPairingMenuRule({"name": "color_pair", "type": "color_pairing",
                                      "course_type_a": "rice", "course_type_b": "veg_gravy"})
        assert rule.rule_type == MenuRuleType.COLOR_PAIRING


# --- ColorVarietyMenuRule ---

class TestColorVarietyMenuRule:
    def test_validate(self):
        rule = ColorVarietyMenuRule({"name": "color_var", "type": "color_variety",
                                      "min_distinct_colors": {"lunch": 3}})
        assert rule.validate_config()

    def test_validate_fails_without_mapping(self):
        rule = ColorVarietyMenuRule({"name": "color_var", "type": "color_variety"})
        assert rule.validate_config() is False

    def test_rule_type(self):
        rule = ColorVarietyMenuRule({"name": "color_var", "type": "color_variety",
                                      "min_distinct_colors": {"lunch": 3}})
        assert rule.rule_type == MenuRuleType.COLOR_VARIETY


# --- CuisineMenuRule ---

class TestCuisineMenuRule:
    def test_validate(self):
        rule = CuisineMenuRule({"name": "cuisine", "type": "cuisine",
                                 "cuisine_family": "italian",
                                 "days_of_week": ["monday", "tuesday"]})
        assert rule.validate_config()

    def test_validate_fails_without_family(self):
        rule = CuisineMenuRule({"name": "cuisine", "type": "cuisine"})
        assert rule.validate_config() is False

    def test_rule_type(self):
        rule = CuisineMenuRule({"name": "cuisine", "type": "cuisine",
                                 "cuisine_family": "italian",
                                 "days_of_week": ["monday"]})
        assert rule.rule_type == MenuRuleType.CUISINE
