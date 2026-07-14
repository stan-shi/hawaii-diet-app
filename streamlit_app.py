"""
streamlit_app.py  --  Hawaii Diet Cart web UI.

Run locally:
    streamlit run streamlit_app.py

Deploy:
    Push to GitHub → share.streamlit.io → connect repo → deploy.
    Embed on your own page with an <iframe>.
"""
import math
import pandas as pd
import pulp
import streamlit as st
from profile_to_targets import profile_to_targets

# ── page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Hawaii Diet Cart",
    page_icon="🌺",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── UH Hilo brand styles ──────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Raleway:wght@400;600;700;800&family=Source+Sans+Pro:wght@300;400;600&display=swap');

/* base typography */
html, body, [class*="css"] {
    font-family: 'Source Sans Pro', sans-serif;
}
h1, h2, h3, h4, h5 {
    font-family: 'Raleway', sans-serif !important;
}

/* top chrome bar */
[data-testid="stHeader"] {
    background-color: #d52b1e;
}

/* sidebar */
[data-testid="stSidebar"] {
    border-right: 4px solid #d52b1e;
    background-color: #fafafa;
}
[data-testid="stSidebar"] h1 {
    color: #d52b1e !important;
    font-size: 1.4rem !important;
}
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {
    color: #a32015 !important;
}

/* primary button */
.stButton > button[kind="primary"] {
    background-color: #d52b1e !important;
    color: #ffffff !important;
    font-family: 'Raleway', sans-serif !important;
    font-weight: 700 !important;
    border: none !important;
    border-radius: 4px !important;
    letter-spacing: 0.03em !important;
}
.stButton > button[kind="primary"]:hover {
    background-color: #a32015 !important;
}

/* metric cards */
[data-testid="metric-container"] {
    border-top: 3px solid #d52b1e;
    border-radius: 4px;
    background: #ffffff;
    padding: 0.8rem 1rem !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
}
[data-testid="stMetricValue"] {
    color: #d52b1e !important;
    font-family: 'Raleway', sans-serif !important;
    font-weight: 700 !important;
}
[data-testid="stMetricLabel"] {
    color: #7c7c7c !important;
    font-size: 0.82rem !important;
}

/* expanders */
[data-testid="stExpander"] {
    border: 1px solid #eeeeee !important;
    border-left: 4px solid #d52b1e !important;
    border-radius: 4px !important;
    margin-bottom: 6px !important;
}

/* progress bars */
[data-testid="stProgressBar"] > div > div {
    background-color: #005b89 !important;
}

/* info boxes */
[data-testid="stAlert"][kind="info"],
div[data-baseweb="notification"] {
    border-left: 4px solid #005b89 !important;
    background-color: #e8f2f7 !important;
}

/* dividers */
hr { border-color: #eeeeee; }

/* section headings in main area */
.main h2 { color: #a32015; border-bottom: 2px solid #eeeeee; padding-bottom: 4px; }
.main h3 { color: #005b89; }
</style>
""", unsafe_allow_html=True)

# ── constants ─────────────────────────────────────────────────────────────────
DAYS         = 7
MEALS        = ["breakfast", "lunch", "dinner"]
N_MEALS      = len(MEALS)
PER_FOOD_CAP = 5.0
MIN_SERVING  = 0.3
MEAL_CAL_MIN = 0.20
MEAL_CAL_MAX = 0.45

_NUTR_COLS = [
    "kcal","protein_g","total_fat_g","sat_fat_g","trans_fat_g",
    "cholesterol_mg","carb_g","fiber_g","sugars_g","added_sugars_g",
    "sodium_mg","potassium_mg","vitamin_d_mcg","calcium_mg","iron_mg",
]


# ── data loading (cached so CSV is read once) ─────────────────────────────────
@st.cache_data
def load_food_matrix():
    df = pd.read_csv("food_matrix.csv")
    df[_NUTR_COLS] = df[_NUTR_COLS].fillna(0.0)
    df = df.dropna(subset=["price", "net_weight_g", "kcal"]).reset_index(drop=True)
    df["unit_price"] = df["price"] / (df["net_weight_g"] / 100.0)
    idx = df.groupby("product_id")["unit_price"].idxmin()
    return df.loc[idx].reset_index(drop=True)


# ── solver ────────────────────────────────────────────────────────────────────
def _solve(df, band, floors, ceilings, max_days, min_foods):
    D = range(DAYS); M = range(N_MEALS); I = df.index
    prob = pulp.LpProblem("weekly_diet", pulp.LpMinimize)

    x = {(i, d, ml): pulp.LpVariable(f"x_{i}_{d}_{ml}", lowBound=0)
         for i in I for d in D for ml in M}
    z = {(i, d): pulp.LpVariable(f"z_{i}_{d}", cat="Binary")
         for i in I for d in D}

    prob += pulp.lpSum(df.loc[i, "unit_price"] * x[i, d, ml]
                       for i in I for d in D for ml in M)

    for i in I:
        for d in D:
            prob += pulp.lpSum(x[i, d, ml] for ml in M) <= PER_FOOD_CAP * z[i, d]
            prob += pulp.lpSum(x[i, d, ml] for ml in M) >= MIN_SERVING  * z[i, d]
        prob += pulp.lpSum(z[i, d] for d in D) <= max_days

    for d in D:
        cal_day = pulp.lpSum(df.loc[i, "kcal"] * x[i, d, ml]
                             for i in I for ml in M)
        prob += cal_day >= band[0]
        prob += cal_day <= band[1]
        prob += pulp.lpSum(z[i, d] for i in I) >= min_foods
        for n, hi in ceilings.items():
            prob += pulp.lpSum(df.loc[i, n] * x[i, d, ml]
                               for i in I for ml in M) <= hi
        for ml in M:
            cal_meal = pulp.lpSum(df.loc[i, "kcal"] * x[i, d, ml] for i in I)
            prob += cal_meal >= MEAL_CAL_MIN * cal_day
            prob += cal_meal <= MEAL_CAL_MAX * cal_day

    for n, lo in floors.items():
        prob += pulp.lpSum(df.loc[i, n] * x[i, d, ml]
                           for i in I for d in D for ml in M) >= lo * DAYS

    prob.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=120))
    return prob, x


# ── sidebar inputs ────────────────────────────────────────────────────────────
with st.sidebar:
    st.image("HILO/color/left.png", width=260)
    st.caption("Undergraduate Research Program · Spring 2026 · College of Business and Economics")
    st.divider()

    st.subheader("Your Profile")
    age      = st.number_input("Age (years)",       min_value=18, max_value=99,  value=33)
    sex      = st.selectbox("Sex", ["male", "female"])
    height   = st.number_input("Height (cm)",       min_value=100, max_value=250, value=178)
    weight   = st.number_input("Weight (kg)",       min_value=30,  max_value=250, value=86)
    activity = st.selectbox("Activity level", [
        "sedentary", "light", "moderate", "active", "very_active"
    ], index=2,
        format_func=lambda v: {
            "sedentary":  "Sedentary (desk job)",
            "light":      "Light (1–3 days/wk)",
            "moderate":   "Moderate (3–5 days/wk)",
            "active":     "Active (6–7 days/wk)",
            "very_active":"Very Active (2×/day)",
        }[v]
    )
    goal = st.selectbox("Goal", ["cut", "cut_slow", "maintain", "bulk"],
        format_func=lambda v: {
            "cut":      "Cut  (−500 kcal/day)",
            "cut_slow": "Cut slowly  (−250 kcal/day)",
            "maintain": "Maintain",
            "bulk":     "Bulk  (+250 kcal/day)",
        }[v]
    )
    protein_ratio = st.slider(
        "Protein (g per kg body weight)", min_value=0.5, max_value=2.5,
        value=0.8, step=0.1,
    )

    st.divider()
    st.subheader("Optimizer Parameters")
    min_foods = st.slider("Min distinct foods per day",  min_value=1, max_value=10, value=4)
    max_days  = st.slider("Max days a food may appear",  min_value=1, max_value=7,  value=6)

    st.divider()
    run = st.button("Generate 7-Day Plan", type="primary", width="stretch")


# ── main area ─────────────────────────────────────────────────────────────────
st.markdown("""
<div style="background:#d52b1e;padding:22px 28px 16px;border-radius:6px;margin-bottom:1.2rem;">
  <h1 style="color:#fff;font-family:'Raleway',sans-serif;font-size:1.9rem;margin:0;letter-spacing:-0.5px;">
    🌺 Hawaii Diet Cart
  </h1>
  <p style="color:rgba(255,255,255,0.88);font-family:'Source Sans Pro',sans-serif;
            margin:5px 0 0;font-size:0.95rem;">
    Optimised 7-day meal plan &nbsp;·&nbsp; Lowest cost, full nutrition
    &nbsp;·&nbsp; Prices from <strong style="color:#fff;">Target Hilo, HI</strong>
  </p>
</div>
""", unsafe_allow_html=True)

if not run:
    st.info("Set your profile in the sidebar, then click **Generate 7-Day Plan**.")
    st.stop()

df = load_food_matrix()
targets = profile_to_targets(
    age=age, sex=sex, height_cm=height, weight_kg=weight,
    activity=activity, protein_g_per_kg=protein_ratio, goal=goal,
)

with st.spinner("Solving… this usually takes 15–60 seconds."):
    prob, x = _solve(
        df,
        band      = targets["CALORIE_BAND"],
        floors    = targets["FLOORS"],
        ceilings  = targets["CEILINGS"],
        max_days  = max_days,
        min_foods = min_foods,
    )

status = pulp.LpStatus[prob.status]
if status != "Optimal":
    st.error(f"No feasible plan found (status: {status}). "
             "Try reducing Min foods/day or loosening Max days.")
    st.stop()

D = range(DAYS); M = range(N_MEALS); I = df.index

# ── goal / calorie banner ─────────────────────────────────────────────────────
gi = targets
c1, c2, c3, c4 = st.columns(4)
c1.metric("Goal",           goal)
c2.metric("TDEE",          f"{gi['_tdee']} kcal/day")
c3.metric("Daily target",  f"{gi['_target']} kcal/day")
c4.metric("Calorie band",  f"{gi['CALORIE_BAND'][0]}–{gi['CALORIE_BAND'][1]}")

st.divider()

# ── cost summary ──────────────────────────────────────────────────────────────
def wk(col):
    return sum(df.loc[i, col] * (pulp.value(x[i, d, ml]) or 0)
               for i in I for d in D for ml in M)

# build shopping list data (needed for checkout total)
shopping_rows = []
for i in sorted(I, key=lambda i: -sum(
        (pulp.value(x[i, d, ml]) or 0) for d in D for ml in M)):
    total_g = sum((pulp.value(x[i, d, ml]) or 0) * 100 for d in D for ml in M)
    if total_g < 1:
        continue
    pkg_g = float(df.loc[i, "net_weight_g"])
    price = float(df.loc[i, "price"])
    pkgs  = math.ceil(total_g / pkg_g)
    shopping_rows.append({
        "Item":          df.loc[i, "name"],
        "g / day":       round(total_g / DAYS),
        "Total need (g)":round(total_g),
        "Pkg size (g)":  round(pkg_g),
        "Pkgs":          pkgs,
        "Each ($)":      price,
        "Line cost ($)": round(pkgs * price, 2),
    })

checkout  = sum(r["Line cost ($)"] for r in shopping_rows)
amortized = pulp.value(prob.objective)

ca, cb = st.columns(2)
ca.metric("Checkout total",          f"${checkout:.2f}",
          help="Buy whole packages at the store")
cb.metric("Amortised weekly cost",   f"${amortized:.2f}",
          help="fraction of packages actually consumed")

st.divider()

# ── day-by-day plan ───────────────────────────────────────────────────────────
st.subheader("Meal Plan")
for d in D:
    cal_day = sum(df.loc[i, "kcal"] * (pulp.value(x[i, d, ml]) or 0)
                  for i in I for ml in M)
    with st.expander(f"Day {d+1}  —  {cal_day:.0f} kcal", expanded=(d == 0)):
        for ml, meal_name in enumerate(MEALS):
            items = [
                (df.loc[i, "name"], (pulp.value(x[i, d, ml]) or 0) * 100)
                for i in I
                if (pulp.value(x[i, d, ml]) or 0) * 100 > 1
            ]
            if not items:
                continue
            cal_meal = sum(df.loc[i, "kcal"] * (pulp.value(x[i, d, ml]) or 0)
                           for i in I)
            st.markdown(f"**{meal_name.capitalize()}** &nbsp;·&nbsp; "
                        f"{cal_meal:.0f} kcal &nbsp;({cal_meal/cal_day*100:.0f}% of day)")
            meal_df = pd.DataFrame(
                sorted(items, key=lambda t: -t[1]),
                columns=["Food", "Grams"],
            )
            meal_df["Grams"] = meal_df["Grams"].round(0).astype(int)
            st.dataframe(meal_df, hide_index=True)

st.divider()

# ── weekly nutrients ──────────────────────────────────────────────────────────
st.subheader("Weekly Nutrients")
floors   = targets["FLOORS"]
ceilings = targets["CEILINGS"]

nutr_rows = []
for n, lo in floors.items():
    val = wk(n)
    nutr_rows.append({"Nutrient": n.replace("_", " "), "Weekly total": round(val, 1),
                      "Target": f"≥ {lo*DAYS:.0f}", "% met": min(val / (lo*DAYS), 2.0),
                      "_ok": round(val, 1) >= lo * DAYS, "_floor": True})
for n, hi in ceilings.items():
    val = wk(n)
    nutr_rows.append({"Nutrient": n.replace("_", " "), "Weekly total": round(val, 1),
                      "Target": f"≤ {hi*DAYS:.0f}", "% met": min(val / (hi*DAYS), 2.0),
                      "_ok": round(val, 1) <= hi * DAYS, "_floor": False})

for row in nutr_rows:
    col_n, col_v, col_t, col_b, col_s = st.columns([2, 1.2, 1.2, 2.5, 0.8])
    col_n.write(row["Nutrient"])
    col_v.write(row["Weekly total"])
    col_t.write(row["Target"])
    pct = min(row["% met"], 1.0)
    col_b.progress(pct)
    col_s.write("✅" if row["_ok"] else "❌")

st.divider()

# ── shopping list ─────────────────────────────────────────────────────────────
st.subheader("Shopping List")
st.info(
    "💡 Prices are based on **Target Hilo, HI** (store #2682). "
    "If you find the same product cheaper at another store — Walmart, Costco, "
    "a local market — buy it there. The nutritional plan stays the same; "
    "your actual cost will only go down."
)
shop_df = pd.DataFrame(shopping_rows)
st.dataframe(shop_df, hide_index=True)
st.markdown(f"**Checkout total: ${checkout:.2f}**")
