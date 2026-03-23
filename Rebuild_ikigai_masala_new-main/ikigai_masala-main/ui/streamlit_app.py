"""
Streamlit frontend for Ikigai Masala Menu Planning.

Run with:
    streamlit run ui/streamlit_app.py
"""

import datetime as dt
import io
import csv

import streamlit as st

from ui.api_client import MenuApiClient
from ui.formatters import (
    theme_label,
    display_label_for_slot_id,
    format_item_for_ui,
    slot_sort_key,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
API_URL = st.sidebar.text_input("API URL", value="http://localhost:5000")
client = MenuApiClient(API_URL)

st.set_page_config(page_title="Ikigai Masala - Menu Planner", layout="wide")
st.title("Ikigai Masala - Menu Planner")

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

try:
    clients_list = client.list_clients()
except (ConnectionError, OSError, ValueError) as _api_err:
    clients_list = []
    st.sidebar.error("Cannot reach API. Is the Flask server running?")

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
                st.session_state.plan = result.get("solution", {})
                st.session_state.plan_dates = sorted(result.get("solution", {}).keys())
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
                    st.session_state.plan = result.get("solution", st.session_state.plan)
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
