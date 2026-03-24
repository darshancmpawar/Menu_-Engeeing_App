"""
Streamlit frontend for Ikigai Masala Menu Planning.

Single entry point — auto-starts the Flask API backend in a background thread.

Run with:
    cd Rebuild_ikigai_masala_new-main/ikigai_masala-main
    streamlit run app.py
"""

import datetime as dt
import io
import csv
import logging
import threading
import time

import requests
import streamlit as st

from ui.api_client import MenuApiClient
from ui.formatters import (
    theme_label,
    display_label_for_slot_id,
    format_item_for_ui,
    slot_sort_key,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Auto-start Flask API backend
# ---------------------------------------------------------------------------
_BACKEND_PORT = 5000
_BACKEND_URL = f"http://localhost:{_BACKEND_PORT}"


def _start_flask_backend():
    """Start the Flask API server in a daemon thread."""
    from api.app import app as flask_app

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    flask_app.run(host="127.0.0.1", port=_BACKEND_PORT, debug=False, use_reloader=False)


def _ensure_backend_running():
    """Start backend if not already running, wait for it to be ready."""
    try:
        requests.get(f"{_BACKEND_URL}/api/v1/health", timeout=1)
        return True
    except (requests.ConnectionError, requests.Timeout):
        pass

    if "flask_started" not in st.session_state:
        t = threading.Thread(target=_start_flask_backend, daemon=True)
        t.start()
        st.session_state.flask_started = True

    for _ in range(20):
        try:
            requests.get(f"{_BACKEND_URL}/api/v1/health", timeout=1)
            return True
        except (requests.ConnectionError, requests.Timeout):
            time.sleep(0.5)

    return False


# ---------------------------------------------------------------------------
# Theme colors for day-type badges
# ---------------------------------------------------------------------------
_THEME_COLORS = {
    0: ("#e8f5e9", "#2e7d32", "Mix"),           # Monday - green
    1: ("#fff3e0", "#e65100", "Chinese"),        # Tuesday - orange
    2: ("#fce4ec", "#c62828", "Biryani"),        # Wednesday - red
    3: ("#e3f2fd", "#1565c0", "South"),          # Thursday - blue
    4: ("#f3e5f5", "#6a1b9a", "North"),          # Friday - purple
    5: ("#fff8e1", "#f57f17", "Weekend"),        # Saturday - amber
    6: ("#fff8e1", "#f57f17", "Weekend"),        # Sunday - amber
}

# ---------------------------------------------------------------------------
# Page config (must be first Streamlit command)
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Ikigai Masala - Menu Planner",
    page_icon="🍽️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Custom CSS
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    /* ---- Global ---- */
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 1rem;
    }

    /* ---- App header ---- */
    .app-header {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
        padding: 1.5rem 2rem;
        border-radius: 12px;
        margin-bottom: 1.5rem;
        display: flex;
        align-items: center;
        gap: 1rem;
    }
    .app-header h1 {
        color: #ffffff;
        margin: 0;
        font-size: 1.8rem;
        font-weight: 700;
        letter-spacing: -0.5px;
    }
    .app-header p {
        color: #94a3b8;
        margin: 0.25rem 0 0;
        font-size: 0.9rem;
    }

    /* ---- Sidebar ---- */
    [data-testid="stSidebar"] {
        background-color: #f8f9fc;
    }
    [data-testid="stSidebar"] .stMarkdown h2 {
        font-size: 1.1rem;
        color: #1a1a2e;
        border-bottom: 2px solid #e2e8f0;
        padding-bottom: 0.5rem;
        margin-bottom: 1rem;
    }

    /* ---- Status badge ---- */
    .status-badge {
        display: inline-block;
        padding: 0.2rem 0.7rem;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 600;
        letter-spacing: 0.3px;
    }

    /* ---- Theme day badge ---- */
    .theme-badge {
        display: inline-block;
        padding: 0.15rem 0.6rem;
        border-radius: 6px;
        font-size: 0.7rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }

    /* ---- Section cards ---- */
    .section-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 1.25rem 1.5rem;
        margin-bottom: 1rem;
    }
    .section-card h3 {
        margin: 0 0 0.75rem;
        font-size: 1.05rem;
        color: #1e293b;
    }

    /* ---- Menu table ---- */
    .menu-table {
        width: 100%;
        border-collapse: separate;
        border-spacing: 0;
        border-radius: 8px;
        overflow: hidden;
        border: 1px solid #e2e8f0;
        font-size: 0.85rem;
    }
    .menu-table thead th {
        background: #1a1a2e;
        color: #ffffff;
        padding: 0.6rem 0.75rem;
        text-align: center;
        font-weight: 600;
        font-size: 0.8rem;
        border-right: 1px solid #2a2a4e;
    }
    .menu-table thead th:last-child {
        border-right: none;
    }
    .menu-table thead th .day-name {
        display: block;
        font-size: 0.8rem;
    }
    .menu-table thead th .theme-badge {
        margin-top: 0.25rem;
    }
    .menu-table tbody td {
        padding: 0.5rem 0.75rem;
        border-bottom: 1px solid #f1f5f9;
        border-right: 1px solid #f1f5f9;
        vertical-align: middle;
    }
    .menu-table tbody td:last-child {
        border-right: none;
    }
    .menu-table tbody tr:last-child td {
        border-bottom: none;
    }
    .menu-table tbody tr:hover {
        background-color: #f8fafc;
    }
    .menu-table .slot-cell {
        font-weight: 600;
        color: #475569;
        background: #f8f9fc;
        white-space: nowrap;
        min-width: 110px;
    }
    .menu-table .item-cell {
        color: #334155;
    }
    .menu-table tbody tr:nth-child(even) {
        background-color: #fafbfd;
    }
    .menu-table tbody tr:nth-child(even):hover {
        background-color: #f1f5f9;
    }

    /* ---- Action buttons row ---- */
    .action-row {
        display: flex;
        gap: 0.5rem;
        margin: 0.75rem 0;
    }

    /* ---- Stat card ---- */
    .stat-card {
        background: #f8f9fc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 0.75rem 1rem;
        text-align: center;
    }
    .stat-card .stat-value {
        font-size: 1.5rem;
        font-weight: 700;
        color: #1a1a2e;
    }
    .stat-card .stat-label {
        font-size: 0.75rem;
        color: #64748b;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }

    /* ---- Changes log ---- */
    .log-entry {
        padding: 0.4rem 0.75rem;
        background: #f1f5f9;
        border-left: 3px solid #3b82f6;
        border-radius: 0 6px 6px 0;
        margin-bottom: 0.4rem;
        font-size: 0.82rem;
        color: #475569;
    }

    /* ---- Empty state ---- */
    .empty-state {
        text-align: center;
        padding: 3rem 2rem;
        color: #94a3b8;
    }
    .empty-state .icon {
        font-size: 3rem;
        margin-bottom: 0.75rem;
    }
    .empty-state h3 {
        color: #475569;
        margin: 0 0 0.5rem;
    }
    .empty-state p {
        font-size: 0.9rem;
    }

    /* ---- Hide default Streamlit title ---- */
    header[data-testid="stHeader"] {
        background: transparent;
    }

    /* ---- Regen section ---- */
    .regen-day-header {
        font-weight: 600;
        font-size: 0.85rem;
        color: #1e293b;
        margin-bottom: 0.3rem;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.markdown("""
<div class="app-header">
    <div>
        <h1>Ikigai Masala</h1>
        <p>AI-Powered Weekly Menu Planner</p>
    </div>
</div>
""", unsafe_allow_html=True)

# Start backend
backend_ok = _ensure_backend_running()
client = MenuApiClient(_BACKEND_URL)

# ---------------------------------------------------------------------------
# Session state defaults
# ---------------------------------------------------------------------------
if "plan" not in st.session_state:
    st.session_state.plan = None
if "plan_dates" not in st.session_state:
    st.session_state.plan_dates = []
if "client_name" not in st.session_state:
    st.session_state.client_name = None
if "changes_log" not in st.session_state:
    st.session_state.changes_log = []

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("## Settings")

    if not backend_ok:
        st.error("Backend API failed to start.")
        clients_list = []
    else:
        try:
            clients_list = client.list_clients()
        except (ConnectionError, OSError, ValueError):
            clients_list = []
            st.error("Cannot reach API.")

    selected_client = st.selectbox(
        "Client",
        clients_list if clients_list else ["(no clients)"],
        help="Choose the client to generate a menu for.",
    )
    start_date = st.date_input("Start Date", value=dt.date.today())
    num_days = st.slider("Days", min_value=1, max_value=30, value=5)
    time_limit = st.slider("Solver Time (sec)", min_value=10, max_value=600, value=240)

    st.markdown("---")

    generate_clicked = st.button(
        "Generate Menu Plan",
        type="primary",
        use_container_width=True,
    )

# ---------------------------------------------------------------------------
# Generate handler
# ---------------------------------------------------------------------------
if generate_clicked:
    if selected_client and selected_client != "(no clients)":
        with st.spinner(f"Generating plan for **{selected_client}**..."):
            try:
                result = client.plan(
                    client_name=selected_client,
                    start_date=start_date.isoformat(),
                    num_days=num_days,
                    time_limit_seconds=time_limit,
                )
                raw_solution = result.get("solution", {})
                flat_plan = {}
                for date_key, day_data in raw_solution.items():
                    items = day_data.get("items", {}) if isinstance(day_data, dict) else {}
                    flat_plan[date_key] = {
                        slot_id: slot_val.get("item", "") if isinstance(slot_val, dict) else str(slot_val)
                        for slot_id, slot_val in items.items()
                    }
                st.session_state.plan = flat_plan
                st.session_state.plan_dates = sorted(flat_plan.keys())
                st.session_state.client_name = selected_client
                st.session_state.changes_log = []
                st.toast("Menu plan generated!", icon="✅")
                st.rerun()
            except (ConnectionError, OSError, ValueError, RuntimeError) as e:
                st.error(f"Generation failed: {e}")
    else:
        st.warning("Select a valid client first.")

# ---------------------------------------------------------------------------
# Display plan
# ---------------------------------------------------------------------------
plan = st.session_state.plan
plan_dates = st.session_state.plan_dates

if plan and plan_dates:
    # ---- Stats row ----
    all_slots = set()
    for date_str in plan_dates:
        all_slots.update(plan.get(date_str, {}).keys())
    sorted_slots = sorted(all_slots, key=slot_sort_key)

    stat_cols = st.columns(4)
    with stat_cols[0]:
        st.markdown(f"""<div class="stat-card">
            <div class="stat-value">{st.session_state.client_name}</div>
            <div class="stat-label">Client</div>
        </div>""", unsafe_allow_html=True)
    with stat_cols[1]:
        st.markdown(f"""<div class="stat-card">
            <div class="stat-value">{len(plan_dates)}</div>
            <div class="stat-label">Days</div>
        </div>""", unsafe_allow_html=True)
    with stat_cols[2]:
        st.markdown(f"""<div class="stat-card">
            <div class="stat-value">{len(sorted_slots)}</div>
            <div class="stat-label">Slots / Day</div>
        </div>""", unsafe_allow_html=True)
    with stat_cols[3]:
        total_items = sum(
            1 for d in plan_dates for s in sorted_slots
            if plan.get(d, {}).get(s, "")
        )
        st.markdown(f"""<div class="stat-card">
            <div class="stat-value">{total_items}</div>
            <div class="stat-label">Total Items</div>
        </div>""", unsafe_allow_html=True)

    st.markdown("")

    # ---- Menu table (custom HTML) ----
    header_html = '<tr><th style="text-align:left;">Slot</th>'
    for d_str in plan_dates:
        d = dt.date.fromisoformat(d_str)
        day_name = d.strftime("%a %d %b")
        wd = d.weekday()
        bg, fg, label = _THEME_COLORS.get(wd, ("#f1f5f9", "#475569", ""))
        header_html += (
            f'<th><span class="day-name">{day_name}</span>'
            f'<br><span class="theme-badge" style="background:{bg};color:{fg};">'
            f'{label}</span></th>'
        )
    header_html += '</tr>'

    body_html = ''
    for slot_id in sorted_slots:
        slot_label = display_label_for_slot_id(slot_id)
        body_html += f'<tr><td class="slot-cell">{slot_label}</td>'
        for d_str in plan_dates:
            item = format_item_for_ui(plan.get(d_str, {}).get(slot_id, ""))
            body_html += f'<td class="item-cell">{item}</td>'
        body_html += '</tr>'

    st.markdown(
        f'<table class="menu-table"><thead>{header_html}</thead>'
        f'<tbody>{body_html}</tbody></table>',
        unsafe_allow_html=True,
    )

    st.markdown("")

    # ---- Action buttons ----
    act_cols = st.columns([1, 1, 1, 3])

    with act_cols[0]:
        if st.button("Save to History", use_container_width=True):
            try:
                client.save(
                    client_name=st.session_state.client_name,
                    week_plan=plan,
                    week_start=plan_dates[0],
                )
                st.toast("Plan saved to history!", icon="💾")
            except (ConnectionError, OSError, ValueError, RuntimeError) as e:
                st.error(f"Save failed: {e}")

    with act_cols[1]:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Slot"] + plan_dates)
        for slot_id in sorted_slots:
            row = [display_label_for_slot_id(slot_id)]
            for d_str in plan_dates:
                row.append(plan.get(d_str, {}).get(slot_id, ""))
            writer.writerow(row)
        st.download_button(
            "Download CSV",
            data=buf.getvalue(),
            file_name=f"menu_plan_{st.session_state.client_name}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    with act_cols[2]:
        if st.button("Clear Plan", use_container_width=True):
            st.session_state.plan = None
            st.session_state.plan_dates = []
            st.session_state.changes_log = []
            st.rerun()

    # ---- Regeneration ----
    st.markdown("")
    with st.expander("Regenerate Cells", expanded=False):
        st.caption("Select cells to replace with new items while keeping the rest locked.")

        regen_selections = {}
        cols = st.columns(min(len(plan_dates), 5))
        for i, d_str in enumerate(plan_dates):
            col = cols[i % len(cols)]
            d = dt.date.fromisoformat(d_str)
            with col:
                wd = d.weekday()
                bg, fg, label = _THEME_COLORS.get(wd, ("#f1f5f9", "#475569", ""))
                st.markdown(
                    f'<div class="regen-day-header">{d.strftime("%a %d %b")} '
                    f'<span class="theme-badge" style="background:{bg};color:{fg};">'
                    f'{label}</span></div>',
                    unsafe_allow_html=True,
                )
                day_slots = sorted(plan.get(d_str, {}).keys(), key=slot_sort_key)
                selected = st.multiselect(
                    f"Slots for {d_str}",
                    day_slots,
                    format_func=display_label_for_slot_id,
                    key=f"regen_{d_str}",
                    label_visibility="collapsed",
                )
                if selected:
                    regen_selections[d_str] = selected

        st.markdown("")
        if st.button("Regenerate Selected", type="primary"):
            if regen_selections:
                with st.spinner("Regenerating..."):
                    try:
                        result = client.regenerate(
                            client_name=st.session_state.client_name,
                            base_plan=plan,
                            replace_slots=regen_selections,
                            start_date=plan_dates[0],
                            num_days=len(plan_dates),
                            time_limit_seconds=time_limit,
                        )
                        raw_regen = result.get("solution", {})
                        flat_regen = {}
                        for date_key, day_data in raw_regen.items():
                            items = day_data.get("items", {}) if isinstance(day_data, dict) else {}
                            flat_regen[date_key] = {
                                slot_id: slot_val.get("item", "") if isinstance(slot_val, dict) else str(slot_val)
                                for slot_id, slot_val in items.items()
                            }
                        st.session_state.plan = flat_regen if flat_regen else st.session_state.plan
                        st.session_state.plan_dates = sorted(st.session_state.plan.keys())
                        n = sum(len(v) for v in regen_selections.values())
                        st.session_state.changes_log.append(
                            f"Regenerated {n} cell{'s' if n != 1 else ''}"
                        )
                        st.toast("Regeneration complete!", icon="🔄")
                        st.rerun()
                    except (ConnectionError, OSError, ValueError, RuntimeError) as e:
                        st.error(f"Regeneration failed: {e}")
            else:
                st.warning("Select at least one cell to regenerate.")

    # ---- Changes log ----
    if st.session_state.changes_log:
        with st.expander("Changes Log"):
            for entry in st.session_state.changes_log:
                st.markdown(f'<div class="log-entry">{entry}</div>', unsafe_allow_html=True)

else:
    # ---- Empty state ----
    st.markdown("""
    <div class="empty-state">
        <div class="icon">🍽️</div>
        <h3>No Menu Plan Yet</h3>
        <p>Select a client and click <strong>Generate Menu Plan</strong> in the sidebar to get started.</p>
    </div>
    """, unsafe_allow_html=True)
