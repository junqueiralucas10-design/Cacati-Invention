"""Rule-based personalized diet builder.

Turns a UserProfile's calorie/macro targets into a realistic day (or week) of
meals from the bundled food database. Foods are chosen to suit the meal (no
salmon or broccoli at breakfast), filtered by the person's dietary restrictions
and allergies, and portioned in natural units (2 eggs, 1 banana, 1 tbsp oil).
No API key required.

Output matches the AI planner's shape (summary / meals with macros + ingredients
/ notes), so it flows straight into the nutrition check and shopping list.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .nutrition import calories_from_macros
from .profile import UserProfile

_DATA_FILE = Path(__file__).parent / "data" / "foods.json"

_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

_ALLERGEN_WORDS = {
    "nut": "nuts", "nuts": "nuts", "peanut": "nuts", "peanuts": "nuts", "almond": "nuts",
    "dairy": "dairy", "milk": "dairy", "lactose": "dairy", "cheese": "dairy",
    "gluten": "gluten", "wheat": "gluten",
    "fish": "fish",
    "shellfish": "shellfish",
    "egg": "eggs", "eggs": "eggs",
    "soy": "soy",
}


@dataclass(frozen=True)
class Food:
    name: str
    aliases: tuple[str, ...]
    group: str                      # protein | carb | veg | fruit | fat
    diet: str                       # vegan | vegetarian | omnivore
    allergens: tuple[str, ...]
    meals: tuple[str, ...]          # which meal types this suits
    unit: str                       # "" = whole items, "g", "slice", "tbsp", "cup", "scoop"
    unit_g: float                   # grams per unit (1 for "g")
    min_g: float
    max_g: float
    calories: float
    protein_g: float
    fat_g: float
    carbs_g: float

    def short_name(self) -> str:
        return self.name.split(",")[0]


def _load_foods(data_file: Path | None = None) -> list[Food]:
    raw = json.loads((data_file or _DATA_FILE).read_text(encoding="utf-8"))
    foods = []
    for e in raw["foods"]:
        per = e["per_100g"]
        foods.append(
            Food(
                name=e["name"],
                aliases=tuple(e.get("aliases", [])),
                group=e.get("group", ""),
                diet=e.get("diet", "omnivore"),
                allergens=tuple(e.get("allergens", [])),
                meals=tuple(e.get("meals", [])),
                unit=e.get("unit", "g"),
                unit_g=e.get("unit_g", 1),
                min_g=e.get("min_g", 50),
                max_g=e.get("max_g", 300),
                calories=per["calories"],
                protein_g=per["protein_g"],
                fat_g=per["fat_g"],
                carbs_g=per["carbs_g"],
            )
        )
    return foods


def _parse_restrictions(tokens: list[str]):
    low = [t.strip().lower() for t in tokens if t.strip()]
    joined = " ".join(low)

    if "vegan" in joined:
        allowed_diets = {"vegan"}
    elif "vegetarian" in joined:
        allowed_diets = {"vegan", "vegetarian"}
    elif "pescatarian" in joined:
        allowed_diets = {"vegan", "vegetarian"}
    else:
        allowed_diets = {"vegan", "vegetarian", "omnivore"}
    pescatarian = "pescatarian" in joined

    excluded_allergens: set[str] = set()
    name_excludes: set[str] = set()
    for tok in low:
        keyword = tok
        if keyword.startswith("no "):
            keyword = keyword[3:]
        keyword = keyword.replace("-free", "").replace(" free", "").strip()
        for word in keyword.split():
            if word in _ALLERGEN_WORDS:
                excluded_allergens.add(_ALLERGEN_WORDS[word])
        for word in tok.split():
            if word in _ALLERGEN_WORDS:
                excluded_allergens.add(_ALLERGEN_WORDS[word])
        if (tok.startswith("no ") or "free" in tok) and len(keyword) >= 3:
            if keyword not in ("vegan", "vegetarian", "pescatarian", "gluten", "dairy"):
                name_excludes.add(keyword)

    return allowed_diets, excluded_allergens, name_excludes, pescatarian


def _filter_foods(foods: list[Food], profile: UserProfile) -> list[Food]:
    allowed_diets, excluded_allergens, name_excludes, pescatarian = _parse_restrictions(
        profile.dietary_restrictions + profile.allergies
    )

    def ok(f: Food) -> bool:
        diet_ok = f.diet in allowed_diets or (
            pescatarian and f.diet == "omnivore" and "fish" in f.allergens
        )
        if not diet_ok:
            return False
        if any(a in excluded_allergens for a in f.allergens):
            return False
        haystack = " ".join((f.name, *f.aliases)).lower()
        if any(kw in haystack for kw in name_excludes):
            return False
        return True

    return [f for f in foods if ok(f)]


def _macros_for(food: Food, grams: float) -> dict:
    factor = grams / 100.0
    return {
        "protein_g": food.protein_g * factor,
        "fat_g": food.fat_g * factor,
        "carbs_g": food.carbs_g * factor,
    }


def _portion(food: Food, grams: float) -> tuple[int, str, float]:
    """Convert a desired gram amount into a natural (quantity, unit, actual_g)."""
    grams = max(food.min_g, min(grams, food.max_g))
    if food.unit == "g":
        q = int(round(grams / 5.0) * 5)
        q = max(q, 5)
        return q, "g", float(q)
    # Countable / measured units (eggs, slices, tbsp, cups, scoops).
    max_count = max(1, round(food.max_g / food.unit_g))
    count = min(max(1, round(grams / food.unit_g)), max_count)
    return count, food.unit, float(count * food.unit_g)


def _pick(pool: list[Food], idx: int) -> Food | None:
    return pool[idx % len(pool)] if pool else None


def _pool(foods: list[Food], group: str, meal_key: str) -> list[Food]:
    return [f for f in foods if f.group == group and meal_key in f.meals]


def _phrase(items: list[str]) -> str:
    items = [i[:1].upper() + i[1:] for i in items]
    if not items:
        return "A simple mix"
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def _build_meal(name: str, cal_share: float, targets: dict, foods: list[Food], rot: int) -> dict:
    meal_key = name.lower()
    meal_cal = targets["calories"] * cal_share
    meal_protein = targets["protein_g"] * cal_share
    meal_fat = targets["fat_g"] * cal_share

    comps: list[tuple[Food, int, str, float]] = []
    totals = {"protein_g": 0.0, "fat_g": 0.0, "carbs_g": 0.0}
    used_ids: set[int] = set()

    def add(food: Food | None, grams: float) -> None:
        if food is None:
            return
        q, u, g = _portion(food, grams)
        if g < 5:
            return
        comps.append((food, q, u, g))
        used_ids.add(id(food))
        m = _macros_for(food, g)
        for k in totals:
            totals[k] += m[k]

    proteins = _pool(foods, "protein", meal_key)
    carbs = _pool(foods, "carb", meal_key)
    vegs = _pool(foods, "veg", meal_key)
    fruits = _pool(foods, "fruit", meal_key)
    fats = _pool(foods, "fat", meal_key)

    # 1. Primary protein, sized to the meal's protein share.
    p1 = _pick(proteins, rot)
    if p1:
        need = meal_protein / (p1.protein_g / 100) if p1.protein_g else p1.min_g
        add(p1, need)

    # 2. Secondary protein when the primary can't cover it (natural except at snack).
    if meal_key != "snack" and len(proteins) > 1:
        deficit = meal_protein - totals["protein_g"]
        if deficit > 12:
            for k in range(1, len(proteins) + 1):
                cand = proteins[(rot + k) % len(proteins)]
                if id(cand) not in used_ids:
                    need = deficit / (cand.protein_g / 100) if cand.protein_g else cand.min_g
                    add(cand, need)
                    break

    # 3. A vegetable (lunch/dinner) or fruit (breakfast/snack).
    if meal_key in ("lunch", "dinner"):
        add(_pick(vegs, rot), 120)
    else:
        fr = _pick(fruits, rot)
        if fr:
            add(fr, fr.min_g)

    # 4. Fill remaining calories with a carb source.
    cal_so_far = calories_from_macros(totals["protein_g"], totals["fat_g"], totals["carbs_g"])
    c1 = _pick(carbs, rot)
    if c1 and meal_cal - cal_so_far > 50:
        add(c1, (meal_cal - cal_so_far) / (c1.calories / 100))

    # 5. Top up fat toward the meal's fat share.
    ft = _pick(fats, rot)
    fat_deficit = meal_fat - totals["fat_g"]
    if ft and fat_deficit > 4 and ft.fat_g:
        add(ft, fat_deficit / (ft.fat_g / 100))

    protein_g = round(totals["protein_g"])
    fat_g = round(totals["fat_g"])
    carbs_g = round(totals["carbs_g"])
    calories = round(calories_from_macros(protein_g, fat_g, carbs_g))

    names = [f.short_name() for f, _, _, _ in comps]
    ingredients = [{"item": f.short_name(), "quantity": q, "unit": u} for f, q, u, _ in comps]

    return {
        "name": name,
        "description": _phrase(names) + ".",
        "calories": calories,
        "protein_g": protein_g,
        "fat_g": fat_g,
        "carbs_g": carbs_g,
        "ingredients": ingredients,
    }


def _meal_plan_shares(calories: int) -> list[tuple[str, float]]:
    if calories >= 2200:
        return [("Breakfast", 0.28), ("Lunch", 0.32), ("Dinner", 0.30), ("Snack", 0.10)]
    return [("Breakfast", 0.33), ("Lunch", 0.34), ("Dinner", 0.33)]


_GOAL_WORD = {
    "lose_weight": "fat-loss",
    "gain_muscle": "muscle-building",
    "maintain": "maintenance",
}

_NOTES = (
    "Built from our food database to match your calorie and macro targets. "
    "Portions are starting points — adjust to appetite. Not medical advice; "
    "consult a professional for medical conditions."
)


def _build_day_meals(profile: UserProfile, foods: list[Food], rot: int) -> list[dict]:
    targets = {"calories": profile.target_calories(), **profile.target_macros()}
    return [
        _build_meal(name, share, targets, foods, rot + i)
        for i, (name, share) in enumerate(_meal_plan_shares(targets["calories"]))
    ]


def _filtered_or_raise(profile: UserProfile, data_file: Path | None) -> list[Food]:
    foods = _filter_foods(_load_foods(data_file), profile)
    if not any(f.group == "protein" for f in foods):
        raise ValueError(
            "No suitable protein sources for these restrictions — please relax them."
        )
    return foods


def _day_totals(meals: list[dict]) -> dict:
    keys = ("calories", "protein_g", "fat_g", "carbs_g")
    return {k: sum(m[k] for m in meals) for k in keys}


def _summary(profile: UserProfile, totals: dict) -> str:
    word = _GOAL_WORD.get(profile.goal, "balanced")
    return (
        f"A personalized {word} day at about {totals['calories']} kcal and "
        f"{totals['protein_g']} g protein, built from whole foods to match your targets."
    )


def build_personalized_plan(profile: UserProfile, data_file: Path | None = None) -> dict:
    """Build a single-day personalized plan (no API key needed)."""
    foods = _filtered_or_raise(profile, data_file)
    meals = _build_day_meals(profile, foods, rot=0)
    return {"summary": _summary(profile, _day_totals(meals)), "meals": meals, "notes": _NOTES}


def build_personalized_weekly_plan(
    profile: UserProfile, days: int = 7, data_file: Path | None = None
) -> dict:
    """Build a multi-day personalized plan, rotating foods for variety."""
    if not 1 <= days <= 7:
        raise ValueError("days must be between 1 and 7")
    foods = _filtered_or_raise(profile, data_file)
    day_blocks = [
        {"day": _DAY_NAMES[d], "meals": _build_day_meals(profile, foods, rot=d)}
        for d in range(days)
    ]
    summary = (
        f"A personalized {_GOAL_WORD.get(profile.goal, 'balanced')} {days}-day plan, "
        "varied across days and matched to your targets."
    )
    return {"summary": summary, "days": day_blocks, "notes": _NOTES}
