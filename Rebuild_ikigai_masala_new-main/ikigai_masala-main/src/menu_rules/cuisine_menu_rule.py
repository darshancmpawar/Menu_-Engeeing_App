"""
Cuisine-specific menu rule implementation - MVP Version
"""

import logging
from typing import Dict, Any, List
from ortools.sat.python import cp_model
from .base_menu_rule import BaseMenuRule, MenuRuleType

logger = logging.getLogger(__name__)


class CuisineMenuRule(BaseMenuRule):
    """
    Enforces cuisine-specific rules (MVP version).
    
    Example: "Italian cuisine must be served on Wednesday, Thursday, Friday"
    
    Config format:
    {
        "name": "italian_specific_days",
        "type": "cuisine",
        "cuisine_family": "italian",
        "days_of_week": ["wednesday", "thursday", "friday"],
    }
    """
    
    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.CUISINE
        
        # Support both old and new column names for backward compatibility
        self.cuisine_family = self.config.get('cuisine_family', 
                                              self.config.get('cuisine_type', ''))
        self.days_of_week = self.config.get('days_of_week', [])
        
    def validate_config(self) -> bool:
        """Validate the cuisine menu rule configuration"""
        if not self.cuisine_family:
            logger.warning("Cuisine rule '%s' has no cuisine_family", self.name)
            return False
        
        valid_days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        for day in self.days_of_week:
            if day.lower() not in valid_days:
                logger.warning("Invalid day '%s' in rule '%s'", day, self.name)
                return False
        
        return True
    
    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any], 
              menu_data: Any, context: Dict[str, Any]) -> None:
        """
        Apply cuisine menu rule to the model with smart fallback.
        
        If a specific cuisine has no items for a course type,
        the rule is relaxed for that course type only, and any cuisine
        items can be selected for that course.
        
        Args:
            model: OR-Tools CP-SAT model
            variables: Decision variables for menu items
            menu_data: DataFrame containing menu information
            context: Additional context including planning dates and meal structure
        """
        # Get items of this cuisine family
        cuisine_items = self._get_cuisine_items(menu_data)
        
        if not cuisine_items:
            logger.warning("No items found for cuisine '%s'", self.cuisine_family)
            return
        
        # Get meal structure from context (always provided)
        meal_structure = context['meal_structure']
        course_items_map = self._group_items_by_course(menu_data)
        
        # Get planning dates from context
        planning_dates = context.get('planning_dates', [])
        include_weekends = context.get('include_weekends', True)
        
        # Apply rules to specific days
        for date_info in planning_dates:
            day_name = date_info.get('day_name', '').lower()
            day_key = date_info.get('date')

            if not include_weekends and day_name in ['saturday', 'sunday']:
                continue
            
            # Only apply constraint on specified days
            if not (self.days_of_week and day_name in self.days_of_week):
                continue
            
            if day_key not in variables.get('daily_items', {}):
                continue
            
            day_vars = variables['daily_items'][day_key]
            
            # Smart per-course-type constraint application
            constraints_applied = 0
            relaxed_courses = []
            
            for course_req in meal_structure.course_requirements:
                course_type = course_req.course_type
                
                # Check if there are cuisine items for this course type
                cuisine_items_for_course = self._get_cuisine_items_for_course(
                    menu_data, course_type, cuisine_items, course_items_map
                )
                
                if not cuisine_items_for_course:
                    # No items available for this course type - RELAX the constraint
                    relaxed_courses.append(course_type)
                    logger.info("No %s items available for '%s' on %s — relaxing constraint", self.cuisine_family, course_type, day_name)
                    continue
                
                # Get variables for cuisine items of this course type on this day
                course_cuisine_vars = [
                    day_vars[item_id] for item_id in cuisine_items_for_course
                    if item_id in day_vars
                ]
                
                if course_cuisine_vars:
                    # Apply constraint: exactly 1 item from this course type must be this cuisine
                    model.Add(sum(course_cuisine_vars) == 1)
                    constraints_applied += 1
            
            if relaxed_courses:
                logger.info("Applied %s constraint to %d courses on %s (relaxed: %s)", self.cuisine_family, constraints_applied, day_name, ', '.join(relaxed_courses))
            else:
                logger.info("Applied %s constraint to all %d courses on %s", self.cuisine_family, constraints_applied, day_name)
        
        logger.info("Applied cuisine rule: %s", self.name)
    
    def _get_cuisine_items(self, menu_data: Any) -> List[str]:
        """
        Get menu items of the specified cuisine family.
        
        Args:
            menu_data: DataFrame or dict containing menu data
            
        Returns:
            List of item IDs
        """
        if hasattr(menu_data, 'loc'):  # DataFrame
            # Check for cuisine_family column (MVP), fallback to cuisine_type
            if 'cuisine_family' in menu_data.columns:
                return menu_data[
                    menu_data['cuisine_family'].str.contains(self.cuisine_family, case=False, na=False)
                ]['item_id'].tolist()
            elif 'cuisine_type' in menu_data.columns:
                return menu_data[
                    menu_data['cuisine_type'].str.contains(self.cuisine_family, case=False, na=False)
                ]['item_id'].tolist()
        
        return []
    
    def _group_items_by_course(self, menu_data: Any) -> Dict[str, List[str]]:
        """
        Group menu items by course type.
        
        Args:
            menu_data: DataFrame containing menu data
            
        Returns:
            Dictionary mapping course types to item IDs
        """
        course_items = {}
        
        if hasattr(menu_data, 'groupby'):  # DataFrame
            for course_type, group in menu_data.groupby('course_type'):
                course_items[course_type] = group['item_id'].tolist()
        
        return course_items
    
    def _get_cuisine_items_for_course(self, menu_data: Any, course_type: str, 
                                      cuisine_items: List[str], 
                                      course_items_map: Dict[str, List[str]]) -> List[str]:
        """
        Get cuisine items for a specific course type.
        
        Args:
            menu_data: DataFrame containing menu data
            course_type: The course type to filter by
            cuisine_items: List of item IDs for the cuisine
            course_items_map: Pre-computed mapping of course types to item IDs
            
        Returns:
            List of item IDs that match both cuisine and course type
        """
        if course_type not in course_items_map:
            return []
        
        # Get items that are both in the cuisine and in this course type
        course_items = set(course_items_map[course_type])
        cuisine_items_set = set(cuisine_items)
        
        return list(course_items.intersection(cuisine_items_set))
