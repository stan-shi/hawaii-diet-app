"""
Hawaii Grocery Shopping List — Streamlit Web App
=================================================
Run locally:
    streamlit run shopping_list_app.py

Deploy free:
    1. Push this file + matched_foods.csv to a GitHub repo
    2. Go to share.streamlit.io → "New app" → pick your repo
    3. Set main file = shopping_list_app.py  →  Deploy
"""

import os
import streamlit as st
import pandas as pd

# Import all logic from the CLI script (no duplication)
from shopping_list_generator import (
    _exercise_to_activity,
    calculate_tdee,
    get_dga_daily_grams,
    load_foods,
    build_shopping_list,
    _GROUP_LABELS,
    DATA_FILE,
)

# ── PAGE CONFIG ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Hawaii Shopping List",
    page_icon="🛒",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── LOAD DATA (cached so it only reads CSV once) ──────────────────────────────
@st.cache_data
def get_food_df():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), DATA_FILE)
    return load_foods(path)

# ── SIDEBAR: user inputs ──────────────────────────────────────────────────────
with st.sidebar:
    st.title("🛒 Your Info")

    unit = st.radio("Weight unit", ["lb", "kg"], horizontal=True)
    if unit == "lb":
        weight_raw = st.number_input("Weight (lb)", min_value=88.0, max_value=440.0,
                                     value=154.0, step=1.0)
        weight_kg = weight_raw * 0.453592
    else:
        weight_kg = st.number_input("Weight (kg)", min_value=40.0, max_value=200.0,
                                    value=70.0, step=0.5)

    age = st.number_input("Age", min_value=10, max_value=100, value=30, step=1)

    sex = st.radio("Sex", ["Male", "Female"], horizontal=True).lower()

    exercise_days = st.slider(
        "Exercise days per week",
        min_value=0, max_value=7, value=3,
        help="0 = sedentary · 1-2 = light · 3-4 = moderate · 5-6 = active · 7 = extra active",
    )

    weeks = st.number_input("Weeks to shop for", min_value=1, max_value=8, value=1, step=1)

    st.divider()
    generate = st.button("Generate Shopping List", type="primary", use_container_width=True)

# ── MAIN AREA ─────────────────────────────────────────────────────────────────
st.title("🌺 Hawaii Grocery Shopping List")
st.caption("Budget-optimized weekly groceries from Safeway & Foodland · Based on 2025–2030 Dietary Guidelines")

# Always show the nutrition profile so it updates live as the user moves sliders
act_mult, prot_mult, act_label = _exercise_to_activity(exercise_days)
tdee        = calculate_tdee(weight_kg, age, sex, act_mult)
protein_min = weight_kg * prot_mult
protein_max = weight_kg * 2.5
daily_grams = get_dga_daily_grams(tdee)

c1, c2, c3 = st.columns(3)
c1.metric("Daily Calories (TDEE)", f"{tdee:.0f} kcal")
c2.metric("Protein Target", f"{protein_min:.0f}–{protein_max:.0f} g/day")
c3.metric("Activity Level", act_label)

with st.expander("Food group targets (DGA 2025–2030)"):
    tgt_rows = [
        {"Food Group": _GROUP_LABELS[g], "Daily Target (g)": f"{v:.0f}g",
         "Daily Target (servings)": f"{v / {'protein':85,'dairy':200,'vegetables':150,'fruits':150,'whole_grains':80,'healthy_fats':5}[g]:.1f}"}
        for g, v in daily_grams.items()
    ]
    st.dataframe(pd.DataFrame(tgt_rows), hide_index=True, use_container_width=True)

# ── Generate on button press ──────────────────────────────────────────────────
if generate:
    with st.spinner("Loading grocery data..."):
        try:
            df = get_food_df()
        except FileNotFoundError:
            st.error(f"Data file `{DATA_FILE}` not found. Make sure it is in the same folder as this script.")
            st.stop()

    with st.spinner("Building your shopping list..."):
        result = build_shopping_list(df, daily_grams, weeks=weeks)

    if result.empty:
        st.warning("No matching foods found. Check that matched_foods.csv has data.")
        st.stop()

    # ── Summary metrics ───────────────────────────────────────────────────────
    total_cart  = result["_cost_total"].sum()
    daily_cost  = result["_daily_cost"].sum()
    total_cal   = result["_cal_day"].sum()
    total_prot  = result["_prot_day"].sum()

    st.divider()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Cart Total",     f"${total_cart:.2f}")
    m2.metric("Daily Cost",     f"${daily_cost:.2f}")
    m3.metric("Monthly Est.",   f"${daily_cost * 30:.0f}")
    m4.metric("Est. Cal/Day",   f"{total_cal:.0f} kcal")

    # ── Shopping list by food group ───────────────────────────────────────────
    st.subheader(f"Your {'Weekly' if weeks == 1 else str(weeks)+'-Week'} Shopping List")

    GROUP_ORDER = ["Protein Foods", "Vegetables", "Fruits", "Whole Grains", "Dairy", "Healthy Fats"]
    GROUP_ICONS = {"Protein Foods": "🥩", "Vegetables": "🥦", "Fruits": "🍎",
                   "Whole Grains": "🌾", "Dairy": "🥛", "Healthy Fats": "🫒"}

    display_cols = [
        "Product", "Store", "Pkg Price ($)", "Pkg Size (g)",
        "Daily Serving (g)", "Pkgs to Buy", "Est. Cost ($)",
        "Cal/Day", "Protein/Day (g)",
    ]

    for grp_label in GROUP_ORDER:
        grp_df = result[result["Food Group"] == grp_label][display_cols]
        if grp_df.empty:
            continue
        icon = GROUP_ICONS.get(grp_label, "")
        st.markdown(f"#### {icon} {grp_label}")
        st.dataframe(grp_df, hide_index=True, use_container_width=True)

    # ── Cost by store ─────────────────────────────────────────────────────────
    store_costs = result.groupby("Store")["Est. Cost ($)"].sum().reset_index()
    store_costs.columns = ["Store", "Total ($)"]
    if len(store_costs) > 1:
        st.subheader("Cost by Store")
        st.dataframe(store_costs, hide_index=True)

    # ── Download button ───────────────────────────────────────────────────────
    export_cols = [c for c in result.columns if not c.startswith("_")]
    csv_bytes = result[export_cols].to_csv(index=False).encode()
    st.download_button(
        label="Download Shopping List (CSV)",
        data=csv_bytes,
        file_name="shopping_list.csv",
        mime="text/csv",
    )
