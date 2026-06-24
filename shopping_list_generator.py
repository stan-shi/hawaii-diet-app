"""
Hawaii Grocery Shopping List Generator
========================================
Generates a weekly shopping list from local Safeway & Foodland prices,
personalized to your weight, age, and exercise frequency.

Requirements:
    pip install pandas

Usage:
    python shopping_list_generator.py
"""

import os
import re
import math
import pandas as pd

# ── DATA FILE ─────────────────────────────────────────────────────────────────
DATA_FILE = "matched_foods.csv"

# ── ACTIVITY MAPPING (exercise days/week → TDEE multiplier) ──────────────────
def _exercise_to_activity(days: int) -> tuple:
    """Return (tdee_multiplier, protein_multiplier, label) from days/week."""
    if days == 0:
        return 1.2, 0.8, "Sedentary (no exercise)"
    elif days <= 2:
        return 1.375, 1.0, "Lightly Active (1–2 days/week)"
    elif days <= 4:
        return 1.55, 1.3, "Moderately Active (3–4 days/week)"
    elif days <= 6:
        return 1.725, 1.6, "Very Active (5–6 days/week)"
    else:
        return 1.9, 2.0, "Extra Active (7 days/week)"


# ── TDEE CALCULATION (Mifflin-St Jeor, median heights) ───────────────────────
_MEDIAN_HEIGHT_CM = {"male": 175.4, "female": 162.1}

def calculate_tdee(weight_kg: float, age: int, sex: str, activity_mult: float) -> float:
    h = _MEDIAN_HEIGHT_CM[sex]
    if sex == "male":
        bmr = 10 * weight_kg + 6.25 * h - 5 * age + 5
    else:
        bmr = 10 * weight_kg + 6.25 * h - 5 * age - 161
    return bmr * activity_mult


# ── 2025-2030 DIETARY GUIDELINES SERVINGS TABLE ───────────────────────────────
_DGA_SERVINGS = {
    1000: dict(protein=1.0,  dairy=2.0, vegetables=1.25, fruits=1.0, whole_grains=1.0,  healthy_fats=2.5),
    1200: dict(protein=1.5,  dairy=2.5, vegetables=1.75, fruits=1.0, whole_grains=1.5,  healthy_fats=2.5),
    1400: dict(protein=2.0,  dairy=2.5, vegetables=1.75, fruits=1.5, whole_grains=1.75, healthy_fats=2.5),
    1600: dict(protein=2.5,  dairy=3.0, vegetables=2.5,  fruits=1.5, whole_grains=1.75, healthy_fats=3.5),
    1800: dict(protein=2.5,  dairy=3.0, vegetables=3.0,  fruits=1.5, whole_grains=2.0,  healthy_fats=4.0),
    2000: dict(protein=3.0,  dairy=3.0, vegetables=3.0,  fruits=2.0, whole_grains=2.0,  healthy_fats=4.5),
    2200: dict(protein=3.5,  dairy=3.0, vegetables=3.5,  fruits=2.0, whole_grains=2.25, healthy_fats=4.5),
    2400: dict(protein=3.5,  dairy=3.0, vegetables=3.5,  fruits=2.0, whole_grains=2.75, healthy_fats=5.0),
    2600: dict(protein=3.5,  dairy=3.0, vegetables=4.25, fruits=2.0, whole_grains=3.0,  healthy_fats=5.5),
    2800: dict(protein=4.0,  dairy=3.0, vegetables=4.25, fruits=2.5, whole_grains=3.25, healthy_fats=6.0),
    3000: dict(protein=4.0,  dairy=3.0, vegetables=4.75, fruits=2.5, whole_grains=3.25, healthy_fats=7.0),
    3200: dict(protein=4.0,  dairy=3.0, vegetables=4.75, fruits=2.5, whole_grains=3.25, healthy_fats=8.0),
}

# Grams per one DGA serving
_DGA_SERVING_G = {
    "protein":      85.0,   # ~3 oz cooked meat
    "dairy":       200.0,   # ~1 cup milk / ¾ cup yogurt
    "vegetables":  150.0,   # 1 cup raw/cooked
    "fruits":      150.0,   # 1 cup raw
    "whole_grains": 80.0,   # ½ cup cooked oats/rice
    "healthy_fats":  5.0,   # 1 tsp oil/butter
}

def get_dga_daily_grams(tdee: float) -> dict:
    """Interpolate DGA minimum servings and convert to grams per day."""
    levels = sorted(_DGA_SERVINGS.keys())
    tdee = max(levels[0], min(levels[-1], tdee))
    lo = max(l for l in levels if l <= tdee)
    hi = min(l for l in levels if l >= tdee)
    if lo == hi:
        servings = _DGA_SERVINGS[lo].copy()
    else:
        t = (tdee - lo) / (hi - lo)
        servings = {
            g: _DGA_SERVINGS[lo][g] + t * (_DGA_SERVINGS[hi][g] - _DGA_SERVINGS[lo][g])
            for g in _DGA_SERVINGS[lo]
        }
    return {grp: servings[grp] * _DGA_SERVING_G[grp] for grp in servings}


# ── FOOD GROUP CLASSIFIER ─────────────────────────────────────────────────────
_EXCLUDE_RE = re.compile(
    r"\b(broth|bouillon|stock|soup|sauce|seasoning|flavoring|"
    r"ramen|instant|mix|gravy|marinade|dressing|spread|dip|"
    r"creamer|powder|extract|concentrate)\b",
    re.I,
)

_CAT_MAP = {
    # Fruits
    "fresh fruits": "fruits",       "Fresh Fruits": "fruits",
    "fruit": "fruits",              "Fruit": "fruits",
    "dried fruit": "fruits",        "Dried Fruit": "fruits",
    # Vegetables
    "fresh vegetables": "vegetables", "Fresh Vegetables": "vegetables",
    "vegetables": "vegetables",       "Vegetables": "vegetables",
    # Dairy
    "milk & cream": "dairy",     "Milk & Cream": "dairy",
    "yogurt": "dairy",           "Yogurt": "dairy",
    "cheese": "dairy",           "Cheese": "dairy",
    "deli cheese": "dairy",      "Deli Cheese": "dairy",
    "sour cream": "dairy",       "Sour Cream": "dairy",
    # Healthy Fats
    "butter & margarine": "healthy_fats", "Butter & Margarine": "healthy_fats",
    "oil & spices": "healthy_fats",       "Oil & Spices": "healthy_fats",
    "nuts, seeds & trail mix": "healthy_fats", "Nuts, Seeds & Trail Mix": "healthy_fats",
    # Protein
    "meat": "protein",                         "Meat": "protein",
    "seafood": "protein",                      "Seafood": "protein",
    "meat-seafood": "protein",
    "meat, seafood & poultry": "protein",      "Meat, Seafood & Poultry": "protein",
    "deli meat": "protein",                    "Deli Meat": "protein",
    "tofu & meat alternatives": "protein",     "Tofu & Meat Alternatives": "protein",
    "meat alternatives": "protein",            "Meat Alternatives": "protein",
    "eggs & egg substitutes": "protein",       "Eggs & Egg Substitutes": "protein",
    # Whole Grains
    "rice, grains & dried beans": "whole_grains", "Rice, Grains & Dried Beans": "whole_grains",
    "grains-pasta-sides": "whole_grains",
    "packaged bread": "whole_grains",     "Packaged Bread": "whole_grains",
    "bread-bakery": "whole_grains",
    "artisan bread & pastries": "whole_grains", "Artisan Bread & Pastries": "whole_grains",
    "bagels & english muffins": "whole_grains", "Bagels & English Muffins": "whole_grains",
    "breakfast & cereal": "whole_grains",       "Breakfast & Cereal": "whole_grains",
    "tortillas & flatbreads": "whole_grains",   "Tortillas & Flatbreads": "whole_grains",
    "buns & rolls": "whole_grains",             "Buns & Rolls": "whole_grains",
    "bread & baked goods": "whole_grains",      "Bread & Baked Goods": "whole_grains",
}

_KEYWORD_RULES = [
    (["beef", "steak", "brisket", "chuck", "angus", "hamburger",
      "chicken", "poultry", "rotisserie", "turkey",
      "pork", "ham", "bacon", "sausage", "hot dog",
      "salmon", "tuna", "tilapia", "cod", "mahi", "halibut",
      "shrimp", "crab", "lobster", "clam", "oyster", "scallop", "sardine",
      "fish", "seafood", "egg", "tofu", "tempeh", "edamame",
      "almond", "walnut", "cashew", "peanut", "pecan", "pistachio",
      "macadamia", "hazelnut", "nut", "peanut butter", "almond butter",
      "sunflower seed", "chia seed", "flax seed",
      "kidney bean", "black bean", "pinto bean", "chickpea", "lentil",
      "garbanzo", "bean"], "protein"),
    (["milk", "cream", "buttermilk", "half and half",
      "cheese", "cheddar", "mozzarella", "parmesan", "brie", "gouda",
      "feta", "ricotta", "swiss", "colby",
      "yogurt", "kefir", "cottage cheese", "sour cream"], "dairy"),
    (["broccoli", "spinach", "kale", "lettuce", "carrot", "tomato",
      "potato", "onion", "garlic", "pepper", "cucumber", "zucchini",
      "cabbage", "cauliflower", "mushroom", "celery", "corn",
      "pea", "green bean", "asparagus", "sweet potato", "bok choy",
      "eggplant", "artichoke", "beet", "radish",
      "vegetable", "veggie", "salad mix", "stir fry"], "vegetables"),
    (["apple", "banana", "orange", "grape", "mango", "pear",
      "peach", "plum", "cherry", "strawberry", "blueberry",
      "raspberry", "watermelon", "pineapple", "kiwi", "avocado",
      "lemon", "lime", "grapefruit", "papaya", "guava",
      "dried fruit", "raisin", "cranberry", "apricot"], "fruits"),
    (["brown rice", "whole grain", "whole wheat", "oat", "oatmeal",
      "quinoa", "barley", "buckwheat", "farro",
      "whole grain bread", "whole wheat bread", "multigrain",
      "granola", "bran cereal", "shredded wheat"], "whole_grains"),
    (["olive oil", "canola oil", "avocado oil", "flaxseed oil",
      "butter", "ghee", "coconut oil"], "healthy_fats"),
]

def _classify_group(name: str, category: str):
    nl = name.lower()
    if _EXCLUDE_RE.search(nl):
        return None
    if category in _CAT_MAP:
        return _CAT_MAP[category]
    if category.lower() in _CAT_MAP:
        return _CAT_MAP[category.lower()]
    for keywords, group in _KEYWORD_RULES:
        for kw in keywords:
            if " " in kw:
                if kw in nl:
                    return group
            else:
                if re.search(rf"\b{re.escape(kw)}s?\b", nl):
                    return group
    return None


# ── JUNK FILTER ───────────────────────────────────────────────────────────────
_JUNK_KW = [
    "ice cube", "ice party", "party ice", "sparkling water", "distilled water",
    "purified water", "sweetener packet", "sugar packet", "chewing gum",
    "breath mint", "aluminum foil", "plastic wrap", "paper towel",
    "trash bag", "napkin", "detergent", "soap", "shampoo",
]
_COUNT_RE = re.compile(r"\(\d+\s*(count|ct|packets?|tabs?|capsules?)\)", re.I)

def _is_junk(name: str) -> bool:
    nl = name.lower()
    return any(kw in nl for kw in _JUNK_KW) or bool(_COUNT_RE.search(name))


# ── LOAD & CLASSIFY FOODS ─────────────────────────────────────────────────────
def load_foods(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)

    required = [
        "Product Name", "Price per Gram", "Min Price", "Weight_g",
        "Energy (kcal)", "Protein (g)", "Healthy Fats (g)",
        "Unhealthy Fats (g)", "Carbohydrate, by difference (g)",
        "Fiber, total dietary (g)",
    ]
    df = df.dropna(subset=required)
    df = df[(df["Price per Gram"] > 0) & (df["Price per Gram"] <= 1.0)]
    df = df[df["Energy (kcal)"] > 0]
    df = df[df["Weight_g"] > 0]
    df = df[~df["Product Name"].apply(_is_junk)]

    cat_col = "Category" if "Category" in df.columns else None
    df["food_group"] = df.apply(
        lambda r: _classify_group(
            str(r["Product Name"]),
            str(r[cat_col]) if cat_col else "",
        ),
        axis=1,
    )

    df = df.sort_values("Price per Gram").reset_index(drop=True)
    return df


# ── SHOPPING LIST BUILDER ─────────────────────────────────────────────────────
# How many distinct food items to include per group
_ITEMS_PER_GROUP = {
    "protein":      4,
    "vegetables":   5,
    "fruits":       3,
    "whole_grains": 2,
    "dairy":        2,
    "healthy_fats": 1,
}

_GROUP_LABELS = {
    "protein":      "Protein Foods",
    "dairy":        "Dairy",
    "vegetables":   "Vegetables",
    "fruits":       "Fruits",
    "whole_grains": "Whole Grains",
    "healthy_fats": "Healthy Fats",
}

def build_shopping_list(
    df: pd.DataFrame,
    daily_grams: dict,
    weeks: int = 1,
) -> pd.DataFrame:
    """
    Select the cheapest foods per group and compute quantities for `weeks` weeks.
    Returns a DataFrame with one row per selected product.
    """
    rows = []

    # Extract the first meaningful food word (e.g. "banana" from "Bananas, Local")
    _noise = re.compile(
        r"\b(organic|local|fresh|raw|whole|bunch|bag|lb|oz|large|small|medium|"
        r"count|ct|prepacked|previously|frozen|cooked|canned|sliced|diced|"
        r"signature|safeway|foodland|select|o organics|brand)\b",
        re.I,
    )

    def _core_word(name: str) -> str:
        cleaned = _noise.sub(" ", name.lower())
        cleaned = re.sub(r"[^a-z\s]", " ", cleaned)
        words   = [w for w in cleaned.split() if len(w) >= 4]
        return words[0] if words else name.lower()[:8]

    for grp, n_items in _ITEMS_PER_GROUP.items():
        group_df = df[df["food_group"] == grp].drop_duplicates("Product Name").copy()
        if group_df.empty:
            continue

        # Deduplicate by core food word — keeps only cheapest per core ingredient
        group_df["_core"] = group_df["Product Name"].apply(_core_word)
        group_df = group_df.drop_duplicates("_core")

        selected = group_df.head(n_items)
        total_daily_g = daily_grams.get(grp, 0)
        grams_each = max(total_daily_g / len(selected), 50.0)  # min 50g/day per food

        for _, row in selected.iterrows():
            weekly_g     = grams_each * 7 * weeks
            pkg_g        = row["Weight_g"]
            n_packages   = math.ceil(weekly_g / pkg_g)
            pkg_price    = row["Min Price"]
            total_cost   = n_packages * pkg_price

            cal_per_day  = row["Energy (kcal)"] * grams_each / 100
            prot_per_day = row["Protein (g)"]   * grams_each / 100

            rows.append({
                "Food Group":         _GROUP_LABELS[grp],
                "Product":            row["Product Name"],
                "Store":              row.get("Store", ""),
                "Pkg Price ($)":      round(pkg_price, 2),
                "Pkg Size (g)":       round(pkg_g, 0),
                "Daily Serving (g)":  round(grams_each, 0),
                "Weekly Total (g)":   round(weekly_g, 0),
                "Pkgs to Buy":        n_packages,
                "Est. Cost ($)":      round(total_cost, 2),
                "Cal/Day":            round(cal_per_day, 0),
                "Protein/Day (g)":    round(prot_per_day, 1),
                # raw floats for totals
                "_cal_day":           cal_per_day,
                "_prot_day":          prot_per_day,
                "_cost_total":        total_cost,
                "_daily_cost":        row["Price per Gram"] * grams_each,
            })

    return pd.DataFrame(rows)


# ── USER INPUT ────────────────────────────────────────────────────────────────
def get_user_input() -> tuple:
    print("\n" + "=" * 58)
    print("       HAWAII GROCERY SHOPPING LIST GENERATOR")
    print("=" * 58)

    # Weight
    unit = input("\nWeight unit — enter 'lb' or 'kg' [default: lb]: ").strip().lower() or "lb"
    weight_raw = float(input(f"Your weight ({unit}): ").strip())
    weight_kg  = weight_raw * 0.453592 if unit == "lb" else weight_raw

    # Age
    age = int(input("Your age (years): ").strip())

    # Sex
    sex_raw = input("Sex — 'male' or 'female' [default: male]: ").strip().lower() or "male"
    sex = "male" if sex_raw.startswith("m") else "female"

    # Exercise frequency
    print("\nExercise frequency (days per week):")
    print("  0  = no exercise (sedentary)")
    print("  1-2 = light exercise (walks, casual gym)")
    print("  3-4 = moderate (regular workouts)")
    print("  5-6 = active (intense training)")
    print("  7   = extra active (physical job or athlete)")
    days = int(input("Days per week you exercise [0-7]: ").strip())
    days = max(0, min(7, days))

    # Shopping window
    weeks_raw = input("Generate list for how many weeks? [default: 1]: ").strip()
    weeks = int(weeks_raw) if weeks_raw else 1

    return weight_kg, age, sex, days, weeks


# ── PRINT HELPERS ─────────────────────────────────────────────────────────────
def print_section(title: str):
    print(f"\n{'─' * 58}")
    print(f"  {title}")
    print(f"{'─' * 58}")


def print_shopping_list(result: pd.DataFrame, weeks: int):
    group_order = [
        "Protein Foods", "Vegetables", "Fruits",
        "Whole Grains", "Dairy", "Healthy Fats",
    ]
    for grp_label in group_order:
        rows = result[result["Food Group"] == grp_label]
        if rows.empty:
            continue
        print(f"\n  ▸ {grp_label.upper()}")
        print(f"  {'Product':<46} {'Store':<10} {'Serving':<10} {'Pkgs':<6} {'Cost':>8}")
        print(f"  {'─'*46} {'─'*10} {'─'*10} {'─'*6} {'─'*8}")
        for _, r in rows.iterrows():
            name = str(r["Product"])[:46]
            print(
                f"  {name:<46} {str(r['Store']):<10} "
                f"{str(r['Daily Serving (g)'])+'g/day':<10} "
                f"×{r['Pkgs to Buy']:<5} "
                f"${r['Est. Cost ($)']:>7.2f}"
            )


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    weight_kg, age, sex, exercise_days, weeks = get_user_input()

    # Activity params
    act_mult, prot_mult, act_label = _exercise_to_activity(exercise_days)

    # TDEE and targets
    tdee        = calculate_tdee(weight_kg, age, sex, act_mult)
    protein_min = weight_kg * prot_mult
    protein_max = weight_kg * 2.5
    daily_grams = get_dga_daily_grams(tdee)

    # Load food data
    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_path  = os.path.join(script_dir, DATA_FILE)
    if not os.path.exists(data_path):
        print(f"\nERROR: Data file not found: {data_path}")
        print("Please ensure matched_foods.csv is in the same folder as this script.")
        return

    print("\nLoading grocery data...")
    df = load_foods(data_path)
    print(f"  {len(df)} products loaded from Safeway & Foodland.")

    # Build shopping list
    result = build_shopping_list(df, daily_grams, weeks)

    # ── Print nutrition profile ───────────────────────────────────────────────
    print_section("YOUR NUTRITION PROFILE")
    print(f"  Activity Level  : {act_label}")
    print(f"  Daily Calories  : {tdee:.0f} kcal")
    print(f"  Protein Target  : {protein_min:.0f}–{protein_max:.0f} g/day")
    print()
    print("  DGA Food Group Targets (grams per day):")
    for grp, grams in daily_grams.items():
        print(f"    {_GROUP_LABELS[grp]:<16}: {grams:.0f}g")

    # ── Print shopping list ───────────────────────────────────────────────────
    period = "1 Week" if weeks == 1 else f"{weeks} Weeks"
    print_section(f"SHOPPING LIST — {period.upper()}")
    print_shopping_list(result, weeks)

    # ── Cost & nutrition summary ──────────────────────────────────────────────
    total_cost    = result["_cost_total"].sum()
    total_cal     = result["_cal_day"].sum()
    total_prot    = result["_prot_day"].sum()
    daily_cost    = result["_daily_cost"].sum()

    print_section("SUMMARY")
    print(f"  {'Shopping cart total':<28}: ${total_cost:.2f}")
    print(f"  {'Daily food cost':<28}: ${daily_cost:.2f}")
    print(f"  {'Monthly estimate':<28}: ${daily_cost * 30:.2f}")
    print()
    print(f"  {'Estimated daily calories':<28}: {total_cal:.0f} kcal  (target: {tdee:.0f})")
    print(f"  {'Estimated daily protein':<28}: {total_prot:.1f}g  (target: ≥{protein_min:.0f}g)")

    # Store breakdown
    store_costs = (
        result.groupby("Store")["Est. Cost ($)"].sum()
        .sort_values(ascending=False)
    )
    if len(store_costs) > 1:
        print()
        print("  Cost by store:")
        for store, cost in store_costs.items():
            print(f"    {store:<12}: ${cost:.2f}")

    # ── Save CSV ──────────────────────────────────────────────────────────────
    out_path = os.path.join(script_dir, "shopping_list.csv")
    export_cols = [c for c in result.columns if not c.startswith("_")]
    result[export_cols].to_csv(out_path, index=False)
    print(f"\n  Shopping list saved to: shopping_list.csv")
    print("=" * 58 + "\n")


if __name__ == "__main__":
    main()
