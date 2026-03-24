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
    # Quick check — is it already up?
    try:
        requests.get(f"{_BACKEND_URL}/api/v1/health", timeout=1)
        return True
    except (requests.ConnectionError, requests.Timeout):
        pass

    # Start in background thread (only once per process)
    if "flask_started" not in st.session_state:
        t = threading.Thread(target=_start_flask_backend, daemon=True)
        t.start()
        st.session_state.flask_started = True

    # Wait up to 10 seconds for it to come up
    for _ in range(20):
        try:
            requests.get(f"{_BACKEND_URL}/api/v1/health", timeout=1)
            return True
        except (requests.ConnectionError, requests.Timeout):
            time.sleep(0.5)

    return False


# ---------------------------------------------------------------------------
# Page config (must be first Streamlit command)
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Ikigai Masala - Menu Planner", layout="wide")
st.title("Ikigai Masala - Menu Planner")

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
# Sidebar: client & parameters
# ---------------------------------------------------------------------------
st.sidebar.header("Planning Parameters")

if not backend_ok:
    st.sidebar.error("Backend API failed to start. Check logs.")
    clients_list = []
else:
    try:
        clients_list = client.list_clients()
    except (ConnectionError, OSError, ValueError) as _api_err:
        clients_list = []
        st.sidebar.error("Cannot reach API.")

selected_client = st.sidebar.selectbox("Client", clients_list if clients_list else ["(no clients)"])
start_date = st.sidebar.date_input("Start Date", value=dt.date.today())
num_days = st.sidebar.slider("Days", min_value=1, max_value=30, value=5)
time_limit = st.sidebar.slider("Solver Time Limit (sec)", min_value=10, max_value=600, value=240)

# ---------------------------------------------------------------------------
# Generate button
# ---------------------------------------------------------------------------
if st.sidebar.button("Generate Menu Plan", type="primary"):
    if selected_client and selected_client != "(no clients)":
        with st.spinner(f"Generating plan for {selected_client}..."):
            try:
                result = client.plan(
                    client_name=selected_client,
                    start_date=start_date.isoformat(),
                    num_days=num_days,
                    time_limit_seconds=time_limit,
                )
                raw_solution = result.get("solution", {})
                # Flatten: extract "items" sub-dict and item strings
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
                st.success(result.get("message", "Plan generated"))
            except (ConnectionError, OSError, ValueError, RuntimeError) as e:
                st.error(f"Generation failed: {e}")
    else:
        st.sidebar.warning("Select a valid client first.")

# ---------------------------------------------------------------------------
# Display plan as table
# ---------------------------------------------------------------------------
plan = st.session_state.plan
plan_dates = st.session_state.plan_dates

if plan and plan_dates:
    st.subheader("Menu Plan")

    # Collect all slot IDs across dates
    all_slots = set()
    for date_str in plan_dates:
        all_slots.update(plan.get(date_str, {}).keys())
    sorted_slots = sorted(all_slots, key=slot_sort_key)

    # Build header row with theme labels
    header_labels = []
    for d_str in plan_dates:
        d = dt.date.fromisoformat(d_str)
        day_name = d.strftime("%a %d-%b")
        t_label = theme_label(d.weekday())
        header_labels.append(f"{day_name}\n{t_label}" if t_label else day_name)

    # Build table data
    table_data = []
    for slot_id in sorted_slots:
        row = {"Slot": display_label_for_slot_id(slot_id)}
        for i, d_str in enumerate(plan_dates):
            item = plan.get(d_str, {}).get(slot_id, "")
            row[header_labels[i]] = format_item_for_ui(item)
        table_data.append(row)

    st.dataframe(table_data, use_container_width=True, hide_index=True)

    # ---------------------------------------------------------------------------
    # Regeneration: select cells to replace
    # ---------------------------------------------------------------------------
    st.subheader("Regenerate Cells")
    st.write("Select (date, slot) cells to regenerate:")

    regen_selections = {}
    cols = st.columns(min(len(plan_dates), 5))
    for i, d_str in enumerate(plan_dates):
        col = cols[i % len(cols)]
        with col:
            st.write(f"**{d_str}**")
            day_slots = sorted(plan.get(d_str, {}).keys(), key=slot_sort_key)
            selected = st.multiselect(
                f"Slots for {d_str}",
                day_slots,
                format_func=display_label_for_slot_id,
                key=f"regen_{d_str}",
            )
            if selected:
                regen_selections[d_str] = selected

    if st.button("Regenerate Selected"):
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
                    st.session_state.changes_log.append(
                        f"Regenerated {sum(len(v) for v in regen_selections.values())} cells"
                    )
                    st.success("Regeneration complete")
                    st.rerun()
                except (ConnectionError, OSError, ValueError, RuntimeError) as e:
                    st.error(f"Regeneration failed: {e}")
        else:
            st.warning("Select at least one cell to regenerate.")

    # ---------------------------------------------------------------------------
    # Action buttons: Save / Download / Clear
    # ---------------------------------------------------------------------------
    st.subheader("Actions")
    action_cols = st.columns(3)

    with action_cols[0]:
        if st.button("Save to History"):
            try:
                client.save(
                    client_name=st.session_state.client_name,
                    week_plan=plan,
                    week_start=plan_dates[0],
                )
                st.success("Plan saved to history!")
            except (ConnectionError, OSError, ValueError, RuntimeError) as e:
                st.error(f"Save failed: {e}")

    with action_cols[1]:
        # CSV download
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
        )

    with action_cols[2]:
        if st.button("Clear Plan"):
            st.session_state.plan = None
            st.session_state.plan_dates = []
            st.session_state.changes_log = []
            st.rerun()

    # ---------------------------------------------------------------------------
    # Changes log
    # ---------------------------------------------------------------------------
    if st.session_state.changes_log:
        with st.expander("Changes Log"):
            for entry in st.session_state.changes_log:
                st.write(f"- {entry}")

else:
    st.info("Generate a menu plan to get started. Select a client and click 'Generate Menu Plan' in the sidebar.")
