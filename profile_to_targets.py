"""
profile_to_targets.py
Turn a person's stats into the daily targets the diet optimizer consumes:
CALORIE_BAND, FLOORS, CEILINGS.

Chain:
  BMR (Mifflin-St Jeor) -> TDEE (x activity) -> maintenance calorie band.
  Protein floor scales with body weight (g/kg).
  Other floors/ceilings come from US DRI / Dietary Guidelines, which vary by
  age and sex (iron and calcium especially).

These are POPULATION reference values for a budgeting tool, not personalized
medical or dietary advice; anyone with specific health needs should consult a
professional. Defaults target weight MAINTENANCE.
"""

ACTIVITY = {"sedentary":1.2, "light":1.375, "moderate":1.55,
            "active":1.725, "very_active":1.9}

def _bracket(age):
    return "19-50" if age <= 50 else ("51-70" if age <= 70 else "71+")

def bmr_mifflin(sex, kg, cm, age):
    base = 10*kg + 6.25*cm - 5*age
    return base + (5 if sex == "male" else -161)

GOAL_DELTA = {
    "cut":      -500,   # ~0.5 kg/week loss
    "cut_slow": -250,   # ~0.25 kg/week loss
    "maintain":    0,
    "bulk":      250,   # lean gain
}

def profile_to_targets(age, sex, height_cm, weight_kg, activity,
                       protein_g_per_kg=0.8, goal="maintain"):
    sex = sex.lower(); activity = activity.lower(); br = _bracket(age)
    tdee   = bmr_mifflin(sex, weight_kg, height_cm, age) * ACTIVITY[activity]
    target = tdee + GOAL_DELTA[goal]   # shift from maintenance

    # ---- floors that vary by sex/age (DRI) ----
    calcium = (1200 if (sex=="female" and br!="19-50") or
                       (sex=="male" and br=="71+") else 1000)
    iron = 18 if (sex=="female" and br=="19-50") else 8
    vit_d = 20 if br == "71+" else 15
    potassium = 3400 if sex == "male" else 2600
    fiber = round(14 * tdee/1000)                 # 14 g per 1000 kcal

    floors = {
        "protein_g":    round(protein_g_per_kg * weight_kg),
        "total_fat_g":  round(0.20 * target / 9),   # AMDR: >= 20% kcal from fat
        "fiber_g":      fiber,
        "vitamin_d_mcg": vit_d,
        "calcium_mg":   calcium,
        "iron_mg":      iron,
        "potassium_mg": potassium,
    }
    # ---- ceilings (Dietary Guidelines, % of calories) ----
    ceilings = {
        "sodium_mg":  2300,
        "sat_fat_g":  round(0.10 * tdee / 9),     # <10% kcal from sat fat
        "sugars_g":   round(0.10 * tdee / 4),     # proxy for added sugars
    }
    band = (round(target) - 75, round(target) + 75)
    return {"CALORIE_BAND": band, "FLOORS": floors, "CEILINGS": ceilings,
            "_tdee": round(tdee), "_target": round(target), "_goal": goal}

if __name__ == "__main__":
    for label, p in {
        "35M 178cm 80kg moderate": dict(age=35, sex="male",   height_cm=178, weight_kg=80, activity="moderate"),
        "30F 165cm 62kg light":    dict(age=30, sex="female", height_cm=165, weight_kg=62, activity="light"),
    }.items():
        t = profile_to_targets(**p)
        print(f"\n=== {label}  (TDEE {t['_tdee']} kcal) ===")
        print("CALORIE_BAND =", t["CALORIE_BAND"])
        print("FLOORS   =", t["FLOORS"])
        print("CEILINGS =", t["CEILINGS"])
