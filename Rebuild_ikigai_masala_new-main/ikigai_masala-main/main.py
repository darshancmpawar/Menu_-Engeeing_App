"""
Ikigai Masala - Menu Planning System
CLI entry point using cell-based solver pipeline.
"""

import argparse
import datetime as dt
import logging
import traceback
from pathlib import Path

from src.preprocessor import ExcelReader, DataCleanser
from src.preprocessor.pool_builder import PoolBuilder, BASE_SLOT_NAMES, CONST_SLOTS, REPEATABLE_ITEM_BASES
from src.client import ClientConfigLoader
from src.history import HistoryManager
from src.menu_rules import MenuRuleLoader
from src.solver.menu_solver import MenuSolver, SolverConfig
from src.solver.solution_formatter import SolutionFormatter

logger = logging.getLogger(__name__)


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
        logger.info("Reading menu data from %s...", args.excel)
        reader = ExcelReader(args.excel)
        raw_df = reader.read()
        cleanser = DataCleanser(raw_df)
        df = cleanser.clean()
        logger.info("  %d items after cleaning", len(df))

        # 2. Build pools
        logger.info("Building slot pools...")
        pools = PoolBuilder.build_pools(df)
        logger.info("  %d pools built", len(pools))

        # 3. Load client config
        logger.info("Loading client config for '%s'...", args.client)
        loader = ClientConfigLoader(args.clients_config)
        client_cfg = loader.get_client(args.client)
        logger.info("  Menu category: %s", client_cfg.menu_category)
        logger.info("  Active slots: %d", len(client_cfg.active_slots))

        # 4. Load menu rules
        logger.info("Loading menu rules...")
        rule_loader = MenuRuleLoader(args.rules_config)
        rules = rule_loader.load_from_file()

        # 5. Parse start date
        if args.start_date:
            start_date = dt.date.fromisoformat(args.start_date)
        else:
            start_date = dt.date.today()

        # 6. Load history
        logger.info("Loading history...")
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
        logger.info("Solving menu plan for %s (%d days from %s)...", args.client, args.days, start_date)
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
            logger.info("CSV saved to %s", args.output_csv)

        if args.output_xlsx:
            formatter.to_excel(args.output_xlsx)
            logger.info("Excel saved to %s", args.output_xlsx)

        logger.info("Menu planning completed successfully!")
        return 0

    except (RuntimeError, ValueError, FileNotFoundError, OSError) as e:
        logger.error("Error: %s", e, exc_info=True)
        return 1


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    exit(main())
