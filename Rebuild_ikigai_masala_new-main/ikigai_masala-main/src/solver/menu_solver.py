"""
Menu planning solver using Google OR-Tools CP-SAT.

Cell-based architecture: each (day, slot) pair has a pre-filtered candidate pool.
The solver creates one boolean variable per candidate per cell and selects exactly one.
"""

from __future__ import annotations

import datetime as dt
import random
import re
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Set, Tuple

import pandas as pd
from ortools.sat.python import cp_model

from ..menu_rules.base_menu_rule import BaseMenuRule
from ..preprocessor.pool_builder import (
    BASE_SLOT_NAMES, CONST_SLOTS, CONSTANT_ITEMS, EXEMPT_FROM_CUISINE,
    REPEATABLE_ITEM_BASES, THEME_FALLBACK_SLOTS, SLOT_SUFFIX_SEP,
    _base_slot, _slot_num, _expand_slots_in_order,
)
from ..preprocessor.column_mapper import _norm_str, _norm_color, _to_bool01, _is_nonveg_dry_row


# ---------------------------------------------------------------------------
# Config dataclass (runtime solver configuration)
# ---------------------------------------------------------------------------

@dataclass
class SolverConfig:
    days: int = 5
    start_date: dt.date = field(default_factory=dt.date.today)
    seed: int = 7
    time_limit_sec: int = 240
    max_attempts: int = 500000
    slot_counts: Optional[Dict[str, int]] = None
    color_col: str = 'item_color'
    color_slots: List[str] = field(default_factory=lambda: [
        'starter', 'rice', 'veg_gravy', 'veg_dry', 'nonveg_main', 'dal', 'dessert',
    ])
    min_distinct_colors_per_day: int = 4
    min_distinct_colors_per_day_chinese: int = 4
    min_distinct_colors_per_day_biryani: int = 4
    max_same_color_per_day: int = 2
    ignore_rice_gravy_color_diff_on_chinese_day: bool = True
    premium_flag_col: Optional[str] = None
    premium_min_per_horizon: int = 1
    premium_max_per_horizon: int = 2
    premium_max_per_day: int = 1
    rice_exclude_items: Set[str] = field(default_factory=lambda: {
        'steamed_rice', 'steamed rice', 'white_rice', 'white rice',
        'steam rice', 'plain rice', 'plain_rice',
    })
    cuisine_col: str = 'cuisine_family'
    cuisine_south_value: str = 'south_indian'
    cuisine_north_value: str = 'north_indian'
    f_chinese_rice: Optional[str] = 'is_chinese_fried_rice'
    f_chinese_nonveg: Optional[str] = 'is_chinese_chicken_gravy'
    f_chinese_veg_gravy: Optional[str] = 'is_chinese_veg_gravy'
    f_chinese_starter: Optional[str] = 'is_chinese_starter'
    f_nonveg_biryani: Optional[str] = 'is_nonveg_biryani'
    f_veg_biryani: Optional[str] = 'is_mixedveg_biryani'
    f_raita: Optional[str] = 'is_raita'
    prefer_theme_starter: bool = True
    theme_fallback_penalty: int = 2000000
    deterministic: bool = True


# ---------------------------------------------------------------------------
# Cell — the core abstraction
# ---------------------------------------------------------------------------

class _Cell:
    """A single (day, slot) decision point with a pre-filtered candidate pool."""
    __slots__ = ('d_idx', 'date', 'slot_id', 'base_slot',
                 'cand_df', 'theme_pref_flags', 'x_vars', 'cand_rows')

    def __init__(self, d_idx: int, date: dt.date, slot_id: str,
                 base_slot: str, cand_df: pd.DataFrame,
                 theme_pref_flags: List[bool]):
        self.d_idx = d_idx
        self.date = date
        self.slot_id = slot_id
        self.base_slot = base_slot
        self.cand_df = cand_df
        self.theme_pref_flags = list(theme_pref_flags)
        self.x_vars: List[cp_model.IntVar] = []
        self.cand_rows: List[pd.Series] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _weekday_type(d: dt.date) -> str:
    wd = d.strftime('%A').lower()
    return {
        'monday': 'mix', 'tuesday': 'chinese', 'wednesday': 'biryani',
        'thursday': 'south', 'friday': 'north',
    }.get(wd, 'holiday' if wd in ('saturday', 'sunday') else 'normal')


def _theme_label(day_type: str) -> str:
    return {
        'mix': 'Mix of South + North', 'chinese': 'Chinese',
        'biryani': 'Biryani', 'south': 'South Indian',
        'north': 'North Indian', 'holiday': 'Holiday', 'normal': 'Normal',
    }.get(day_type, day_type.capitalize())


def _color_initial(x) -> str:
    c = _norm_color(x)
    if c == 'unknown':
        return ''
    base = c.split('_')[-1]
    return base[:1].upper() if base else ''


def _fmt_item_with_color(row: pd.Series, color_col: str) -> str:
    item = str(row.get('item', ''))
    ini = _color_initial(row.get(color_col, 'unknown'))
    return f'{item}({ini})' if ini else item


def _strip_color_suffix(s: str) -> str:
    return re.sub(r'\([A-Z]\)\s*$', '', (s or '').strip()).strip()


def _min_distinct_for_day(cfg: SolverConfig, day_type: str) -> int:
    if day_type == 'chinese':
        return cfg.min_distinct_colors_per_day_chinese
    if day_type == 'biryani':
        return cfg.min_distinct_colors_per_day_biryani
    return cfg.min_distinct_colors_per_day


def _find_cells(cells: List[_Cell], di: int, base_slot: str) -> List[_Cell]:
    return [c for c in cells if c.d_idx == di and c.base_slot == base_slot]


def _link_any(model: cp_model.CpModel, lits: List, y) -> None:
    if not lits:
        model.Add(y == 0)
        return
    model.Add(sum(lits) >= y)
    for lit in lits:
        model.Add(lit <= y)


def _sample_with_priority(pool: pd.DataFrame, cap: int,
                          priority_mask: pd.Series,
                          rng: random.Random) -> pd.DataFrame:
    if len(pool) <= cap:
        return pool
    pm = priority_mask.reindex(pool.index).fillna(False).astype(bool)
    pri, oth = pool[pm], pool[~pm]
    if len(pri) >= cap:
        return pri.sample(cap, random_state=rng.randint(1, 10**9))
    if len(pri) == 0:
        return pool.sample(cap, random_state=rng.randint(1, 10**9))
    need = cap - len(pri)
    if len(oth) > need:
        oth = oth.sample(need, random_state=rng.randint(1, 10**9))
    return pd.concat([pri, oth], axis=0)


def _sample_cell_candidates(pool: pd.DataFrame, pref_mask: pd.Series,
                            cap: int, rng: random.Random) -> Tuple[pd.DataFrame, List[bool]]:
    pref2 = pref_mask.reindex(pool.index).fillna(False).astype(bool)
    if len(pool) > cap:
        if bool(pref2.any()):
            pool = _sample_with_priority(pool, cap, pref2, rng)
        else:
            pool = pool.sample(cap, random_state=rng.randint(1, 10**9))
    pref2 = pref2.reindex(pool.index).fillna(False).astype(bool)
    return pool.reset_index(drop=True), pref2.tolist()


# ---------------------------------------------------------------------------
# MenuSolver
# ---------------------------------------------------------------------------

class MenuSolver:
    """
    Cell-based CP-SAT menu planner.

    Each (day, slot) cell has a pre-filtered candidate pool. The solver
    picks exactly one candidate per cell subject to hard constraints.
    """

    # Default candidate caps per base slot
    CAP_BY_SLOT_BASE: Dict[str, int] = {
        'rice': 1600, 'healthy_rice': 1200, 'veg_gravy': 1400,
        'nonveg_main': 1400, 'curd_side': 1400, 'veg_dry': 1100,
        'bread': 1100, 'starter': 1200, 'soup': 900, 'salad': 900,
        'dal': 1000, 'dessert': 1000, 'welcome_drink': 1000,
        'sambar': 900, 'rasam': 900,
    }
    CAP_DEFAULT_BASE = 900

    def __init__(
        self,
        pools: Dict[str, pd.DataFrame],
        solver_config: SolverConfig,
        menu_rules: Optional[List[BaseMenuRule]] = None,
        banned_by_date: Optional[Dict[dt.date, Set[str]]] = None,
        ricebread_ban_day: Optional[Dict[dt.date, bool]] = None,
        recent_sigs: Optional[Set[str]] = None,
    ):
        self.pools = pools
        self.cfg = solver_config
        self.menu_rules = menu_rules or []
        self.banned_by_date = banned_by_date or {}
        self.ricebread_ban_day = ricebread_ban_day or {}
        self.recent_sigs = recent_sigs or set()

    def solve(self, locked=None, forbidden=None, similarity=None) -> Tuple[Dict, List[dt.date]]:
        """
        Solve the menu plan with multi-restart strategy.

        Returns:
            (week_plan, dates) where week_plan maps date -> {slot_id: item_string}
        """
        dates = [self.cfg.start_date + dt.timedelta(days=i) for i in range(self.cfg.days)]
        expanded_slots = _expand_slots_in_order(
            BASE_SLOT_NAMES, self.cfg.slot_counts or {s: 1 for s in BASE_SLOT_NAMES}
        )

        cap_multipliers = [1, 2]
        restarts_per_multiplier = 4
        base_seed = int(self.cfg.seed)
        total_time = float(self.cfg.time_limit_sec)
        per_attempt_time = max(20.0, total_time / (len(cap_multipliers) * restarts_per_multiplier))
        last_err = None
        orig_seed, orig_time = self.cfg.seed, self.cfg.time_limit_sec

        try:
            for mult in cap_multipliers:
                cap_default = self.CAP_DEFAULT_BASE * mult
                cap_by_slot = {k: v * mult for k, v in self.CAP_BY_SLOT_BASE.items()}

                for r in range(restarts_per_multiplier):
                    attempt_seed = base_seed + mult * 1000 + r * 17
                    rng = random.Random(attempt_seed)
                    self.cfg.seed = attempt_seed
                    self.cfg.time_limit_sec = int(per_attempt_time)

                    try:
                        cells = self._build_cells(
                            dates, expanded_slots, cap_default, cap_by_slot, rng
                        )
                        chosen_rows = self._solve_cpsat(
                            dates, cells, locked=locked, similarity=similarity,
                            forbidden=forbidden,
                        )
                        week_plan = self._rows_to_week_plan(
                            chosen_rows, dates, expanded_slots
                        )
                        return week_plan, dates
                    except Exception as e:
                        last_err = e
                        continue

            raise RuntimeError(
                'No feasible plan found after CP-SAT restarts. '
                'Likely causes: tight history cooldown, rice-bread gap, '
                'insufficient deep-fried starters, tight Chinese/Biryani pools, '
                'or color/premium constraints.'
            ) from last_err
        finally:
            self.cfg.seed, self.cfg.time_limit_sec = orig_seed, orig_time

    # ----- Cell building -----

    def _build_cells(
        self, dates: List[dt.date], expanded_slots: List[str],
        cap_default: int, cap_by_slot: Dict[str, int], rng: random.Random,
    ) -> List[_Cell]:
        cells: List[_Cell] = []
        base_slots = list(dict.fromkeys(_base_slot(s) for s in expanded_slots))

        # Pre-build per (day_idx, base_slot) pool cache
        cache = self._build_day_base_pool_cache(dates, base_slots)

        for di, d in enumerate(dates):
            for slot_id in expanded_slots:
                base = _base_slot(slot_id)
                pool2, pref_mask, day_type = cache[di, base]

                # Nonveg dry preference for slot 2+
                if base == 'nonveg_main' and (_slot_num(slot_id) or 1) >= 2:
                    pool2 = self._apply_nonveg_dry_preference(
                        pool2, day_type, self.banned_by_date.get(d, set())
                    )

                if len(pool2) == 0:
                    extra = ''
                    if base == 'bread' and self.ricebread_ban_day.get(d, False):
                        extra = ' (rice-bread banned by gap rule)'
                    raise RuntimeError(
                        f'Empty pool after filters: {d.isoformat()} '
                        f'slot={slot_id} day_type={day_type}{extra}'
                    )

                cap = cap_by_slot.get(base, cap_default)
                sampled, theme_flags = _sample_cell_candidates(pool2, pref_mask, cap, rng)
                cells.append(_Cell(di, d, slot_id, base, sampled, theme_flags))

        return cells

    def _build_day_base_pool_cache(
        self, dates: List[dt.date], base_slots: List[str],
    ) -> Dict:
        cache = {}
        for di, d in enumerate(dates):
            day_type = _weekday_type(d)
            banned = self.banned_by_date.get(d, set())
            for base in base_slots:
                pool2 = self.pools[base].copy()

                # Exclude steamed rice etc. from flavor rice/healthy_rice
                if base in ('rice', 'healthy_rice') and len(pool2) > 0:
                    pool2 = pool2[~pool2['item'].isin(self.cfg.rice_exclude_items)]

                # Rice-bread ban
                if base == 'bread' and self.ricebread_ban_day.get(d, False):
                    if 'is_rice_bread' in pool2.columns:
                        pool2 = pool2[pool2['is_rice_bread'] == 0]

                # Banned items removal
                if banned:
                    pool2 = pool2[~pool2['item'].isin(banned)]

                # Theme preference mask (for sampling priority)
                pref_mask = pd.Series(False, index=pool2.index)

                cache[di, base] = (pool2, pref_mask, day_type)
        return cache

    def _apply_nonveg_dry_preference(
        self, pool: pd.DataFrame, day_type: str, banned: Set[str],
    ) -> pd.DataFrame:
        """For nonveg_main slot 2+: prefer dry items, fallback to gravy."""
        if day_type in ('biryani', 'chinese'):
            alt_pool = self.pools['nonveg_main'].copy()
            if self.cfg.f_chinese_nonveg and self.cfg.f_chinese_nonveg in alt_pool.columns:
                alt_pool = alt_pool[alt_pool[self.cfg.f_chinese_nonveg].map(_to_bool01) == 0]
            bflag = self.cfg.f_nonveg_biryani
            if bflag and bflag in alt_pool.columns:
                alt_pool = alt_pool[alt_pool[bflag].map(_to_bool01) == 0]
            if banned:
                alt_pool = alt_pool[~alt_pool['item'].isin(banned)]
            if len(alt_pool) > 0:
                pool = alt_pool

        dry_pool = pool[pool.apply(_is_nonveg_dry_row, axis=1)]
        if len(dry_pool) > 0:
            return dry_pool
        if 'is_nonveg_gravy' in pool.columns:
            gravy_pool = pool[pool['is_nonveg_gravy'].map(_to_bool01) == 1]
            if len(gravy_pool) > 0:
                return gravy_pool
        return pool

    # ----- CP-SAT model -----

    def _solve_cpsat(
        self, dates: List[dt.date], cells: List[_Cell],
        locked=None, similarity=None, forbidden=None,
    ) -> Dict:
        rng = random.Random(self.cfg.seed)
        model = cp_model.CpModel()
        day_types = [_weekday_type(d) for d in dates]

        known_colors, known_welcome_colors = self._collect_known_colors(cells)
        build_result = self._build_decision_variables(
            model, cells, day_types, locked=locked, forbidden=forbidden,
        )
        (item_to_vars, day_color_vars, day_rice_color_vars,
         day_gravy_color_vars, day_premium_vars, day_welcome_color_vars,
         monday_south_lits, monday_north_lits, theme_fallback_bools) = build_result

        # Build rule context
        context = {
            'cells': cells,
            'dates': dates,
            'day_types': day_types,
            'item_to_vars': item_to_vars,
            'day_color_vars': day_color_vars,
            'day_rice_color_vars': day_rice_color_vars,
            'day_gravy_color_vars': day_gravy_color_vars,
            'day_premium_vars': day_premium_vars,
            'day_welcome_color_vars': day_welcome_color_vars,
            'monday_south_lits': monday_south_lits,
            'monday_north_lits': monday_north_lits,
            'theme_fallback_bools': theme_fallback_bools,
            'known_colors': known_colors,
            'known_welcome_colors': known_welcome_colors,
            'cfg': self.cfg,
            'recent_sigs': self.recent_sigs,
            'find_cells_fn': _find_cells,
            'link_any_fn': _link_any,
        }

        # Apply built-in constraints
        self._add_item_uniqueness(model, item_to_vars)
        self._add_color_constraints(model, dates, day_types, known_colors,
                                    day_color_vars, day_rice_color_vars,
                                    day_gravy_color_vars)

        # Apply user-defined rules
        for rule in self.menu_rules:
            try:
                rule.apply(model, {}, None, context)
            except Exception as e:
                print(f"Warning: rule {rule.name} failed: {e}")

        # Build objective
        self._build_objective(model, cells, rng, similarity,
                              theme_fallback_bools, context)

        # Solve
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(self.cfg.time_limit_sec)
        solver.parameters.random_seed = int(self.cfg.seed)
        solver.parameters.num_search_workers = 1 if self.cfg.deterministic else 8
        solver.parameters.cp_model_presolve = True

        status = solver.Solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            if status == cp_model.INFEASIBLE:
                raise RuntimeError('No feasible plan found (INFEASIBLE).')
            if status == cp_model.UNKNOWN:
                raise RuntimeError('No feasible plan found (TIME LIMIT).')
            if status == cp_model.MODEL_INVALID:
                raise RuntimeError('CP-SAT model invalid.')
            raise RuntimeError(f'CP-SAT failed with status={status}.')

        return self._extract_solution_rows(solver, cells, dates)

    def _collect_known_colors(self, cells: List[_Cell]) -> Tuple[List[str], List[str]]:
        known_colors: Set[str] = set()
        known_welcome: Set[str] = set()
        for cell in cells:
            if cell.base_slot in self.cfg.color_slots:
                for c in cell.cand_df[self.cfg.color_col].tolist():
                    col = _norm_color(c)
                    if col != 'unknown':
                        known_colors.add(col)
            if cell.base_slot == 'welcome_drink':
                for c in cell.cand_df[self.cfg.color_col].tolist():
                    col = _norm_color(c)
                    if col != 'unknown':
                        known_welcome.add(col)
        return sorted(known_colors), sorted(known_welcome)

    def _build_decision_variables(
        self, model: cp_model.CpModel, cells: List[_Cell],
        day_types: List[str], locked=None, forbidden=None,
    ):
        item_to_vars: Dict[str, List] = {}
        day_color_vars: Dict[Tuple, List] = {}
        day_rice_color_vars: Dict[Tuple, List] = {}
        day_gravy_color_vars: Dict[Tuple, List] = {}
        day_premium_vars: Dict[int, List] = {}
        day_welcome_color_vars: Dict[Tuple, List] = {}
        monday_south_lits: List = []
        monday_north_lits: List = []
        theme_fallback_bools: List = []

        for cell in cells:
            di = cell.d_idx
            slot_id = cell.slot_id
            base = cell.base_slot
            x_vars: List = []
            cand_rows: List = []

            for j in range(len(cell.cand_df)):
                row = cell.cand_df.iloc[j]
                item_base = _norm_str(row.get('item', ''))
                var = model.NewBoolVar(f'x_d{di}_{slot_id}_{j}')
                x_vars.append(var)
                cand_rows.append(row)

                item_to_vars.setdefault(item_base, []).append(var)

                # Premium tracking
                if self.cfg.premium_flag_col and int(row.get(self.cfg.premium_flag_col, 0)) == 1:
                    day_premium_vars.setdefault(di, []).append(var)

                # Color tracking
                if base in self.cfg.color_slots:
                    col = _norm_color(row.get(self.cfg.color_col, 'unknown'))
                    if col != 'unknown':
                        day_color_vars.setdefault((di, col), []).append(var)
                        if base == 'rice':
                            day_rice_color_vars.setdefault((di, col), []).append(var)
                        elif base == 'veg_gravy':
                            day_gravy_color_vars.setdefault((di, col), []).append(var)

                if base == 'welcome_drink':
                    col = _norm_color(row.get(self.cfg.color_col, 'unknown'))
                    if col != 'unknown':
                        day_welcome_color_vars.setdefault((di, col), []).append(var)

                # Monday mix tracking
                if day_types[di] == 'mix' and base not in EXEMPT_FROM_CUISINE:
                    cf = _norm_str(row.get(self.cfg.cuisine_col, ''))
                    if cf == self.cfg.cuisine_south_value:
                        monday_south_lits.append(var)
                    elif cf == self.cfg.cuisine_north_value:
                        monday_north_lits.append(var)

                # Locked/forbidden
                if locked and (cell.date, slot_id) in locked:
                    if item_base != _norm_str(locked[cell.date, slot_id]):
                        model.Add(var == 0)
                if forbidden and (cell.date, slot_id) in forbidden:
                    if item_base in forbidden[cell.date, slot_id]:
                        model.Add(var == 0)

            # Exactly one candidate per cell
            model.Add(sum(x_vars) == 1)
            cell.x_vars = x_vars
            cell.cand_rows = cand_rows

            # Theme fallback tracking
            if cell.base_slot in THEME_FALLBACK_SLOTS:
                pref_flags = [bool(v) for v in cell.theme_pref_flags]
                if pref_flags and any(pref_flags) and not all(pref_flags):
                    fallback_lits = [v for v, pf in zip(x_vars, pref_flags) if not pf]
                    if fallback_lits:
                        fb = model.NewBoolVar(f'theme_fallback_{di}_{slot_id}')
                        _link_any(model, fallback_lits, fb)
                        theme_fallback_bools.append(fb)

        return (item_to_vars, day_color_vars, day_rice_color_vars,
                day_gravy_color_vars, day_premium_vars, day_welcome_color_vars,
                monday_south_lits, monday_north_lits, theme_fallback_bools)

    # ----- Built-in constraints -----

    def _add_item_uniqueness(self, model, item_to_vars):
        repeatable = set(REPEATABLE_ITEM_BASES)
        for item_base, vars_ in item_to_vars.items():
            if item_base not in repeatable:
                model.Add(sum(vars_) <= 1)

    def _add_color_constraints(self, model, dates, day_types, known_colors,
                               day_color_vars, day_rice_color_vars,
                               day_gravy_color_vars):
        cfg = self.cfg
        for di, _ in enumerate(dates):
            day_type = day_types[di]
            min_dist = _min_distinct_for_day(cfg, day_type)

            for col in known_colors:
                lits = day_color_vars.get((di, col), [])
                if lits:
                    model.Add(sum(lits) <= cfg.max_same_color_per_day)

            y_vars = []
            for col in known_colors:
                lits = day_color_vars.get((di, col), [])
                if not lits:
                    continue
                y = model.NewBoolVar(f'y_color_{di}_{col}')
                _link_any(model, lits, y)
                y_vars.append(y)
            if y_vars:
                model.Add(sum(y_vars) >= min_dist)

            if not (cfg.ignore_rice_gravy_color_diff_on_chinese_day and day_type == 'chinese'):
                for col in known_colors:
                    r_lits = day_rice_color_vars.get((di, col), [])
                    g_lits = day_gravy_color_vars.get((di, col), [])
                    if r_lits and g_lits:
                        model.Add(sum(r_lits) + sum(g_lits) <= 1)

    # ----- Objective -----

    def _build_objective(self, model, cells, rng, similarity,
                         theme_fallback_bools, context):
        obj_terms = []

        if similarity:
            for cell in cells:
                for var, row in zip(cell.x_vars, cell.cand_rows):
                    sc = int(similarity.get(
                        (cell.date, cell.slot_id, _norm_str(row.get('item', ''))), 0
                    ))
                    if sc:
                        obj_terms.append(var * sc)
            for cell in cells:
                for var in cell.x_vars:
                    obj_terms.append(var * rng.randint(0, 3))
        else:
            for cell in cells:
                for var in cell.x_vars:
                    obj_terms.append(var * rng.randint(0, 1000))

        # Collect objective terms from rules
        for rule in self.menu_rules:
            try:
                terms = rule.get_objective_terms(model, context)
                obj_terms.extend(terms)
            except Exception:
                pass

        if theme_fallback_bools:
            obj_terms.append(sum(theme_fallback_bools) * (-abs(int(self.cfg.theme_fallback_penalty))))

        if obj_terms:
            model.Maximize(sum(obj_terms))

    # ----- Solution extraction -----

    def _extract_solution_rows(self, solver, cells, dates):
        chosen = {d: {} for d in dates}
        for cell in cells:
            pick_idx = next(
                (j for j, var in enumerate(cell.x_vars) if solver.Value(var) == 1),
                None,
            )
            if pick_idx is None:
                raise RuntimeError('Solver solution missing selection in a cell.')
            chosen[cell.date][cell.slot_id] = cell.cand_rows[pick_idx]
        return chosen

    def _rows_to_week_plan(self, chosen_rows, dates, expanded_slots):
        week_plan = {}
        for d in dates:
            day_out = {}
            for slot_id in expanded_slots:
                if slot_id in chosen_rows[d]:
                    day_out[slot_id] = _fmt_item_with_color(
                        chosen_rows[d][slot_id], self.cfg.color_col
                    )
            day_out.update(CONSTANT_ITEMS)
            week_plan[d] = day_out
        return week_plan
