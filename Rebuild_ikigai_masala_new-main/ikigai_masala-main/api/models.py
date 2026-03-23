"""
Pydantic models for API request/response validation.
"""

from datetime import datetime
from typing import Optional, Dict, Any, List, Set
from pydantic import BaseModel, Field, validator


class MenuPlanRequest(BaseModel):
    """Request model for menu planning endpoint."""

    client_name: str = Field(
        description='Client name (must exist in clients.json)'
    )

    start_date: Optional[str] = Field(
        default=None,
        description='Start date for planning (YYYY-MM-DD). Defaults to today.'
    )

    num_days: int = Field(
        default=5,
        ge=1,
        le=30,
        description='Number of days to plan (1-30)'
    )

    time_limit_seconds: int = Field(
        default=240,
        ge=10,
        le=600,
        description='Solver time limit in seconds (10-600)'
    )

    @validator('start_date')
    def validate_start_date(cls, v):
        if v is None:
            return datetime.now().strftime('%Y-%m-%d')
        try:
            datetime.strptime(v, '%Y-%m-%d')
            return v
        except ValueError:
            raise ValueError('start_date must be in YYYY-MM-DD format')

    class Config:
        json_schema_extra = {
            "example": {
                "client_name": "Rippling",
                "start_date": "2026-03-23",
                "num_days": 5,
                "time_limit_seconds": 240
            }
        }


class RegenerateRequest(BaseModel):
    """Request model for regeneration endpoint."""

    client_name: str = Field(description='Client name')

    base_plan: Dict[str, Dict[str, str]] = Field(
        description='Base plan: {date_iso: {slot_id: item_string}}'
    )

    replace_slots: Dict[str, List[str]] = Field(
        description='Slots to replace: {date_iso: [slot_ids]}'
    )

    start_date: Optional[str] = Field(default=None)
    num_days: int = Field(default=5)
    time_limit_seconds: int = Field(default=240)


class MenuSaveRequest(BaseModel):
    """Request model for saving a plan to history."""

    client_name: str
    week_plan: Dict[str, Dict[str, str]] = Field(
        description='Plan: {date_iso: {slot_id: item_string}}'
    )
    week_start: str = Field(description='Week start date YYYY-MM-DD')


class MenuPlanResponse(BaseModel):
    """Response model for menu planning endpoint."""

    success: bool = Field(description='Whether the solver found a solution')
    message: str = Field(description='Status message')
    solution: Optional[Dict[str, Any]] = Field(default=None, description='Menu plan solution')

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "Menu plan generated successfully",
                "solution": {
                    "2026-03-23": {
                        "theme": "Mix of South + North",
                        "items": {"rice": {"item": "jeera rice(Y)"}}
                    }
                }
            }
        }


class ErrorResponse(BaseModel):
    """Error response model."""

    success: bool = Field(default=False)
    error: str = Field(description='Error message')
    details: Optional[str] = Field(default=None)
