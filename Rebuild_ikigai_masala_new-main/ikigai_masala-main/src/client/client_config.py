"""
Client configuration loader.

Reads clients.json and provides per-client slot lists, slot counts,
and menu category information.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

from src.preprocessor.pool_builder import (
    BASE_SLOT_NAMES as BASE_SLOTS,
    CONST_SLOTS,
    SLOT_SUFFIX_SEP,
)

ALL_SLOTS: List[str] = list(BASE_SLOTS) + list(CONST_SLOTS)


@dataclass
class ClientConfig:
    name: str
    menu_category: str
    active_slots: List[str] = field(default_factory=list)
    slot_counts: Dict[str, int] = field(default_factory=dict)


def _dedupe_preserve_order(values: List[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for v in values:
        if v not in seen:
            out.append(v)
            seen.add(v)
    return out


def _expand_slot_ids(base_slot: str, count: int) -> List[str]:
    n = int(count)
    if n <= 0:
        return []
    if n == 1:
        return [base_slot]
    return [f'{base_slot}{SLOT_SUFFIX_SEP}{i}' for i in range(1, n + 1)]


class ClientConfigLoader:
    """Loads and provides access to client configuration from a JSON file."""

    def __init__(self, config_path: str):
        self._path = Path(config_path)
        self._data: Dict = {}
        self._clients: Dict[str, Dict] = {}
        self._load()

    def _load(self):
        with open(self._path) as f:
            self._data = json.load(f)
        self._clients = {c['name']: c for c in self._data['clients']}

    @property
    def client_names(self) -> List[str]:
        return [c['name'] for c in self._data['clients']]

    @property
    def menu_categories(self) -> Dict[str, List[str]]:
        return self._data['menu_categories']

    @property
    def fallback_menu_category(self) -> str:
        return self._data.get('fallback_menu_category', 'menu_cat_3')

    @property
    def core_min_one_slots(self) -> List[str]:
        return self._data.get('core_min_one_slots', [])

    @property
    def constant_slots(self) -> List[str]:
        return self._data.get('constant_slots', CONST_SLOTS)

    def get_client(self, name: str) -> ClientConfig:
        """Return a fully-populated ClientConfig for the given client."""
        if name not in self._clients:
            raise ValueError(f"Unknown client: {name}")
        entry = self._clients[name]
        cat = entry['menu_category']
        slot_counts = self.get_slot_counts_for_client(name)

        base_to_show = self.get_slots_for_menu_category(cat)
        active: List[str] = []
        for slot in base_to_show:
            if slot in CONST_SLOTS:
                active.append(slot)
            else:
                active.extend(_expand_slot_ids(slot, slot_counts.get(slot, 1)))
        active = _dedupe_preserve_order(active)

        return ClientConfig(
            name=name,
            menu_category=cat,
            active_slots=active,
            slot_counts=slot_counts,
        )

    def get_client_menu_category(self, name: str) -> str:
        if name not in self._clients:
            return self.fallback_menu_category
        return self._clients[name]['menu_category']

    def get_slots_for_menu_category(self, category: str) -> List[str]:
        cats = self._data['menu_categories']
        slots = cats.get(category, cats.get(self.fallback_menu_category, []))
        return _dedupe_preserve_order(list(slots))

    def get_slot_counts_for_client(self, name: str) -> Dict[str, int]:
        counts = {s: 1 for s in BASE_SLOTS}
        overrides = self._data.get('slot_count_overrides', {}).get(name, {})
        for k, v in overrides.items():
            if k in counts:
                counts[k] = max(0, int(v))
        for must in self.core_min_one_slots:
            counts[must] = max(1, int(counts.get(must, 1)))
        return counts

    def get_slots_for_client(self, name: str) -> List[str]:
        return self.get_client(name).active_slots

    def validate(self):
        """Validate configuration consistency. Raises ValueError on problems."""
        names = self.client_names
        if len(set(names)) != len(names):
            dupes = [n for n in names if names.count(n) > 1]
            raise ValueError(f"Duplicate client names: {set(dupes)}")

        cats = self._data['menu_categories']
        for entry in self._data['clients']:
            cat = entry['menu_category']
            if cat not in cats:
                raise ValueError(f"Client '{entry['name']}' references unknown category: {cat}")

        all_slots_set = set(ALL_SLOTS)
        for cat_name, slots in cats.items():
            bad = [s for s in slots if s not in all_slots_set]
            if bad:
                raise ValueError(f"Category '{cat_name}' has unknown slot(s): {bad}")

        overrides = self._data.get('slot_count_overrides', {})
        for client, ovr in overrides.items():
            if client not in self._clients:
                raise ValueError(f"slot_count_overrides has unknown client: {client}")
            bad_keys = [k for k in ovr if k not in BASE_SLOTS]
            if bad_keys:
                raise ValueError(f"slot_count_overrides[{client}] has unknown slot(s): {bad_keys}")
