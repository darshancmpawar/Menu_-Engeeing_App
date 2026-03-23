"""
Ikigai Masala - Menu Planning System
CLI entry point using cell-based solver pipeline.
"""

import argparse
import datetime as dt
import traceback
from pathlib import Path

from src.preprocessor import ExcelReader, DataCleanser, ColumnMapper
from src.preprocessor.pool_builder import PoolBuilder, BASE_SLOT_NAMES, CONST_SLOTS, REPEATABLE_ITEM_BASES
from src.client import ClientConfigLoader
from src.history import HistoryManager
from src.menu_rules import MenuRuleLoader
from src.solver.menu_solver import MenuSolver, SolverConfig
from src.solver.solution_formatter import SolutionFormatter


def main():
    parser = argparse.ArgumentParser(
        description="Ikigai Masala - Menu Planning System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --client Rippling --days 5
  python main.py --client Rippling --start-date 2026-03-23 --days 7
  python main.py --client Stripe --time-limit 120 --output-csv plan.csv
        """,
    )

    parser.add_argument('--client', required=True, help='Client name (must exist in clients.json)')
    parser.add_argument('--excel', default='data/raw/menu_items.xlsx', help='Path to Ontology Excel')
    parser.add_argument('--clients-config', default='data/configs/clients.json', help='Path to clients JSON')
    parser.add_argument('--rules-config', default='data/configs/indian_menu_rules.json', help='Path to menu rules JSON')
    parser.add_argument('--start-date', default=None, help='Start date YYYY-MM-DD (default: today)')
    parser.add_argument('--days', type=int, default=5, help='Number of days to plan')
    parser.add_argument('--time-limit', type=int, default=240, help='Solver time limit in seconds')
    parser.add_argument('--history-long', default='data/history_long.csv', help='Path to long history CSV')
    parser.add_argument('--history-weeks', default='data/history_weeks.csv', help='Path to week history CSV')
    parser.add_argument('--output-csv', default=None, help='Export solution to CSV')
    parser.add_argument('--output-xlsx', default=None, help='Export solution to Excel')

    args = parser.parse_args()

    try:
        # 1. Read and clean ontology
        print(f"Reading menu data from {args.excel}...")
        reader = ExcelReader(args.excel)
        raw_df = reader.read()
        cleanser = DataCleanser(raw_df)
        df = cleanser.clean()
        print(f"  {len(df)} items after cleaning")

        # 2. Build pools
        print("Building slot pools...")
        pools = PoolBuilder.build_pools(df)
        print(f"  {len(pools)} pools built")

        # 3. Load client config
        print(f"Loading client config for '{args.client}'...")
        loader = ClientConfigLoader(args.clients_config)
        client_cfg = loader.get_client(args.client)
        print(f"  Menu category: {client_cfg.menu_category}")
        print(f"  Active slots: {len(client_cfg.active_slots)}")

        # 4. Load menu rules
        print("Loading menu rules...")
        rule_loader = MenuRuleLoader(args.rules_config)
        rules = rule_loader.load_from_file()

        # 5. Parse start date
        if args.start_date:
            start_date = dt.date.fromisoformat(args.start_date)
        else:
            start_date = dt.date.today()

        # 6. Load history
        print("Loading history...")
        hm = HistoryManager()
        history_long = Path(args.history_long)
        history_weeks = Path(args.history_weeks)
        if history_long.exists() or history_weeks.exists():
            hm = hm.load(str(history_long), str(history_weeks))
            hm = hm.filter_by_client(args.client)

        dates = [start_date + dt.timedelta(days=i) for i in range(args.days)]
        banned = hm.banned_items_by_date(dates, const_slots=CONST_SLOTS,
                                          repeatable_items=REPEATABLE_ITEM_BASES)
        ricebread_items = set(
            df.loc[df.get('is_rice_bread', 0) == 1, 'item'].tolist()
        ) if 'is_rice_bread' in df.columns else set()
        rb_ban = hm.ricebread_ban_by_date(dates, ricebread_items)
        recent_sigs = hm.recent_week_signatures(start_date)

        # 7. Configure solver
        premium_col = None
        if 'is_premium_veg' in df.columns and int(df['is_premium_veg'].sum()) > 0:
            premium_col = 'is_premium_veg'

        cfg = SolverConfig(
            days=args.days,
            start_date=start_date,
            time_limit_sec=args.time_limit,
            slot_counts=client_cfg.slot_counts,
            premium_flag_col=premium_col,
        )

        # 8. Solve
        print(f"\nSolving menu plan for {args.client} ({args.days} days from {start_date})...")
        solver = MenuSolver(
            pools=pools,
            solver_config=cfg,
            menu_rules=rules,
            banned_by_date=banned,
            ricebread_ban_day=rb_ban,
            recent_sigs=recent_sigs,
        )

        week_plan, plan_dates = solver.solve()

        # 9. Format output
        formatter = SolutionFormatter(week_plan, plan_dates)
        formatter.print_summary()

        if args.output_csv:
            formatter.to_csv(args.output_csv)
            print(f"\nCSV saved to {args.output_csv}")

        if args.output_xlsx:
            formatter.to_excel(args.output_xlsx)
            print(f"\nExcel saved to {args.output_xlsx}")

        print("\nMenu planning completed successfully!")
        return 0

    except Exception as e:
        print(f"\nError: {e}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
