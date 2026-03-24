"""
Flask API Application for Menu Planning System.

Endpoints:
  POST /api/v1/plan — Generate a menu plan for a client
  POST /api/v1/regenerate — Regenerate selected cells
  POST /api/v1/save — Save plan to history
  GET  /api/v1/clients — List available clients
  GET  /api/v1/health — Health check
"""

import datetime as dt
import logging
import threading
import traceback
from pathlib import Path

from flask import Flask, request, jsonify
from flask_cors import CORS

from api.config import (
    DEFAULT_EXCEL_PATH, CLIENTS_CONFIG_PATH, MENU_RULES_CONFIG_PATH,
    HISTORY_LONG_PATH, HISTORY_WEEKS_PATH, API_HOST, API_PORT, DEBUG,
)
from src.preprocessor import ExcelReader, DataCleanser, ColumnMapper
from src.preprocessor.pool_builder import PoolBuilder, BASE_SLOT_NAMES, CONST_SLOTS, REPEATABLE_ITEM_BASES
from src.client import ClientConfigLoader
from src.history import HistoryManager
from src.menu_rules import MenuRuleLoader
from src.solver.menu_solver import MenuSolver, SolverConfig
from src.solver.solution_formatter import SolutionFormatter
from src.solver.regenerator import MenuRegenerator

logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Thread-safe lazy singletons
_init_lock = threading.Lock()
_client_loader = None
_pools = None
_df = None
_menu_rules = None


def _get_client_loader():
    global _client_loader
    if _client_loader is None:
        with _init_lock:
            if _client_loader is None:
                _client_loader = ClientConfigLoader(CLIENTS_CONFIG_PATH)
    return _client_loader


def _get_menu_data():
    global _pools, _df
    if _pools is None:
        with _init_lock:
            if _pools is None:
                reader = ExcelReader(DEFAULT_EXCEL_PATH)
                raw_df = reader.read()
                cleanser = DataCleanser(raw_df)
                _df = cleanser.clean()
                _pools = PoolBuilder.build_pools(_df)
    return _df, _pools


def _get_menu_rules():
    global _menu_rules
    if _menu_rules is None:
        with _init_lock:
            if _menu_rules is None:
                loader = MenuRuleLoader(MENU_RULES_CONFIG_PATH)
                _menu_rules = loader.load_from_file()
    return _menu_rules


def _build_history_context(df, client_name, start_date, num_days):
    """Shared helper to build history-based solver inputs."""
    hm = HistoryManager().load(HISTORY_LONG_PATH, HISTORY_WEEKS_PATH)
    hm = hm.filter_by_client(client_name)

    dates = [start_date + dt.timedelta(days=i) for i in range(num_days)]
    banned = hm.banned_items_by_date(dates, const_slots=CONST_SLOTS,
                                      repeatable_items=REPEATABLE_ITEM_BASES)
    ricebread_items = set(
        df.loc[df.get('is_rice_bread', 0) == 1, 'item'].tolist()
    ) if 'is_rice_bread' in df.columns else set()
    rb_ban = hm.ricebread_ban_by_date(dates, ricebread_items)
    recent_sigs = hm.recent_week_signatures(start_date)
    return banned, rb_ban, recent_sigs


def _build_solver_config(df, client_cfg, start_date, num_days, time_limit):
    """Shared helper to build SolverConfig."""
    return SolverConfig(
        days=num_days,
        start_date=start_date,
        time_limit_sec=time_limit,
        slot_counts=client_cfg.slot_counts,
        premium_flag_col='is_premium_veg' if 'is_premium_veg' in df.columns and int(df['is_premium_veg'].sum()) > 0 else None,
    )


@app.route('/api/v1/clients', methods=['GET'])
def list_clients():
    try:
        loader = _get_client_loader()
        return jsonify({'success': True, 'clients': loader.client_names})
    except (FileNotFoundError, ValueError, KeyError) as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/v1/plan', methods=['POST'])
def plan_menu():
    try:
        data = request.get_json()
        client_name = data.get('client_name')
        start_date_str = data.get('start_date')
        num_days = int(data.get('num_days', 5))
        time_limit = int(data.get('time_limit_seconds', 240))

        if not client_name:
            return jsonify({'success': False, 'error': 'client_name is required'}), 400

        loader = _get_client_loader()
        client_cfg = loader.get_client(client_name)

        df, pools = _get_menu_data()
        rules = _get_menu_rules()

        start_date = dt.date.fromisoformat(start_date_str) if start_date_str else dt.date.today()

        banned, rb_ban, recent_sigs = _build_history_context(df, client_name, start_date, num_days)
        cfg = _build_solver_config(df, client_cfg, start_date, num_days, time_limit)

        solver = MenuSolver(
            pools=pools,
            solver_config=cfg,
            menu_rules=rules,
            banned_by_date=banned,
            ricebread_ban_day=rb_ban,
            recent_sigs=recent_sigs,
        )

        week_plan, plan_dates = solver.solve()

        formatter = SolutionFormatter(week_plan, plan_dates)
        return jsonify({
            'success': True,
            'message': f'Menu plan generated for {client_name}',
            'solution': formatter.to_dict(),
        })

    except (ValueError, KeyError) as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except RuntimeError as e:
        logger.warning("Solver failed: %s", e)
        return jsonify({'success': False, 'error': str(e)}), 500
    except (FileNotFoundError, OSError) as e:
        logger.error("Data loading error: %s", e, exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/v1/regenerate', methods=['POST'])
def regenerate_cells():
    try:
        data = request.get_json()
        client_name = data.get('client_name')
        base_plan_raw = data.get('base_plan', {})
        replace_slots_raw = data.get('replace_slots', {})
        start_date_str = data.get('start_date')
        num_days = int(data.get('num_days', 5))
        time_limit = int(data.get('time_limit_seconds', 240))

        if not client_name:
            return jsonify({'success': False, 'error': 'client_name is required'}), 400
        if not base_plan_raw:
            return jsonify({'success': False, 'error': 'base_plan is required'}), 400
        if not replace_slots_raw:
            return jsonify({'success': False, 'error': 'replace_slots is required'}), 400

        loader = _get_client_loader()
        client_cfg = loader.get_client(client_name)

        df, pools = _get_menu_data()
        rules = _get_menu_rules()

        start_date = dt.date.fromisoformat(start_date_str) if start_date_str else dt.date.today()

        banned, rb_ban, recent_sigs = _build_history_context(df, client_name, start_date, num_days)
        cfg = _build_solver_config(df, client_cfg, start_date, num_days, time_limit)

        # Convert string date keys to date objects
        base_plan = {}
        for d_str, slots in base_plan_raw.items():
            # slots may be nested dicts from to_dict() — extract item strings
            day_items = {}
            for slot_id, val in slots.items():
                if isinstance(val, dict):
                    day_items[slot_id] = val.get('item', val.get('item_base', ''))
                else:
                    day_items[slot_id] = str(val)
            base_plan[dt.date.fromisoformat(d_str)] = day_items

        replace_mask = {}
        for d_str, slot_list in replace_slots_raw.items():
            replace_mask[dt.date.fromisoformat(d_str)] = set(slot_list)

        regen = MenuRegenerator(
            pools=pools,
            df=df,
            solver_config=cfg,
            menu_rules=rules,
            banned_by_date=banned,
            ricebread_ban_day=rb_ban,
            recent_sigs=recent_sigs,
        )

        week_plan, plan_dates = regen.regenerate(base_plan, replace_mask)

        formatter = SolutionFormatter(week_plan, plan_dates)
        return jsonify({
            'success': True,
            'message': f'Regenerated {sum(len(v) for v in replace_mask.values())} cells for {client_name}',
            'solution': formatter.to_dict(),
        })

    except (ValueError, KeyError) as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except RuntimeError as e:
        logger.warning("Regeneration failed: %s", e)
        return jsonify({'success': False, 'error': str(e)}), 500
    except (FileNotFoundError, OSError) as e:
        logger.error("Data loading error: %s", e, exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/v1/save', methods=['POST'])
def save_plan():
    try:
        data = request.get_json()
        client_name = data.get('client_name')
        week_plan_raw = data.get('week_plan', {})
        week_start_str = data.get('week_start')

        if not client_name:
            return jsonify({'success': False, 'error': 'client_name is required'}), 400
        if not week_plan_raw:
            return jsonify({'success': False, 'error': 'week_plan is required'}), 400
        if not week_start_str:
            return jsonify({'success': False, 'error': 'week_start is required'}), 400

        # Convert string date keys to date objects
        week_plan = {}
        for d_str, slots in week_plan_raw.items():
            week_plan[dt.date.fromisoformat(d_str)] = slots

        dates = sorted(week_plan.keys())
        week_start = dt.date.fromisoformat(week_start_str)

        sig = HistoryManager.compute_week_signature(week_plan, dates, const_slots=CONST_SLOTS)

        hm = HistoryManager()
        hm.save(week_plan, dates, client_name, week_start, sig,
                HISTORY_LONG_PATH, HISTORY_WEEKS_PATH)

        return jsonify({'success': True, 'message': 'Plan saved to history'})

    except (ValueError, KeyError) as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except (FileNotFoundError, OSError) as e:
        logger.error("Save failed: %s", e, exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/v1/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy'})


@app.route('/')
def root():
    return jsonify({
        'name': 'Ikigai Masala Menu Planning API',
        'version': '2.0',
        'docs': '/api/v1/clients',
    })


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    app.run(host=API_HOST, port=API_PORT, debug=DEBUG)
