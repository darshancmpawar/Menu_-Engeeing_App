"""
HTTP client for the Menu Planning Flask API.
"""

import requests
from typing import Dict, List, Optional, Any


class MenuApiClient:
    """Wrapper around the Flask API endpoints."""

    def __init__(self, base_url: str = "http://localhost:5000"):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()

    def health(self) -> Dict[str, Any]:
        resp = self.session.get(f"{self.base_url}/api/v1/health", timeout=5)
        resp.raise_for_status()
        return resp.json()

    def list_clients(self) -> List[str]:
        resp = self.session.get(f"{self.base_url}/api/v1/clients", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            raise RuntimeError(data.get("error", "Unknown error"))
        return data["clients"]

    def plan(
        self,
        client_name: str,
        start_date: str,
        num_days: int = 5,
        time_limit_seconds: int = 240,
    ) -> Dict[str, Any]:
        payload = {
            "client_name": client_name,
            "start_date": start_date,
            "num_days": num_days,
            "time_limit_seconds": time_limit_seconds,
        }
        resp = self.session.post(
            f"{self.base_url}/api/v1/plan", json=payload, timeout=time_limit_seconds + 30
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            raise RuntimeError(data.get("error", "Solver failed"))
        return data

    def regenerate(
        self,
        client_name: str,
        base_plan: Dict[str, Dict[str, str]],
        replace_slots: Dict[str, List[str]],
        start_date: Optional[str] = None,
        num_days: int = 5,
        time_limit_seconds: int = 240,
    ) -> Dict[str, Any]:
        payload = {
            "client_name": client_name,
            "base_plan": base_plan,
            "replace_slots": replace_slots,
            "num_days": num_days,
            "time_limit_seconds": time_limit_seconds,
        }
        if start_date:
            payload["start_date"] = start_date
        resp = self.session.post(
            f"{self.base_url}/api/v1/regenerate", json=payload, timeout=time_limit_seconds + 30
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            raise RuntimeError(data.get("error", "Regeneration failed"))
        return data

    def save(
        self,
        client_name: str,
        week_plan: Dict[str, Dict[str, str]],
        week_start: str,
    ) -> Dict[str, Any]:
        payload = {
            "client_name": client_name,
            "week_plan": week_plan,
            "week_start": week_start,
        }
        resp = self.session.post(
            f"{self.base_url}/api/v1/save", json=payload, timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            raise RuntimeError(data.get("error", "Save failed"))
        return data
