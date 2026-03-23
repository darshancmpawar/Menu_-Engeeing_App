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

app = Flask(__name__)
CORS(app)

# Singletons loaded on startup
_client_loader = None
_pools = None
_df = None
_menu_rules = None


def _get_client_loader():
    global _client_loader
    if _client_loader is None:
        _client_loader = ClientConfigLoader(CLIENTS_CONFIG_PATH)
    return _client_loader


def _get_menu_data():
    global _pools, _df
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
        loader = MenuRuleLoader(MENU_RULES_CONFIG_PATH)
        _menu_rules = loader.load_from_file()
    return _menu_rules


@app.route('/api/v1/clients', methods=['GET'])
def list_clients():
    try:
        loader = _get_client_loader()
        return jsonify({'success': True, 'clients': loader.client_names})
    except Exception as e:
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

        if start_date_str:
            start_date = dt.date.fromisoformat(start_date_str)
        else:
            start_date = dt.date.today()

        # Load history
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

        cfg = SolverConfig(
            days=num_days,
            start_date=start_date,
            time_limit_sec=time_limit,
            slot_counts=client_cfg.slot_counts,
            premium_flag_col='is_premium_veg' if 'is_premium_veg' in df.columns and int(df['is_premium_veg'].sum()) > 0 else None,
        )

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

    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/v1/save', methods=['POST'])
def save_plan():
    try:
        data = request.get_json()
        client_name = data.get('client_name')
        week_plan_raw = data.get('week_plan', {})
        week_start_str = data.get('week_start')

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

    except Exception as e:
        traceback.print_exc()
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
    app.run(host=API_HOST, port=API_PORT, debug=DEBUG)
