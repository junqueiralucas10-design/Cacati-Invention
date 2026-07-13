"""Rule-based personalized diet builder.

Turns a UserProfile's calorie/macro targets into a concrete day (or week) of
meals, chosen from the bundled food database and filtered by the person's
dietary restrictions and allergies. No API key required — this is the engine
that runs after the client fills in their details.

The output matches the shape produced by the AI planner (summary / meals /
notes, each meal with macros + ingredients), so it flows straight into the
nutrition check and shopping-list builder.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .nutrition import calories_from_macros
from .profile import UserProfile

_DATA_FILE = Path(__file__).parent / "data" / "foods.json"

_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# Map free-text tokens to a canonical allergen key.
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
    group: str          # protein | carb | veg | fruit | fat
    diet: str           # vegan | vegetarian | omnivore
    allergens: tuple[str, ...]
    calories: float
    protein_g: float
    fat_g: float
    carbs_g: float

    def short_name(self) -> str:
        """Display name without the ", cooked"/", raw" detail suffix."""
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
                calories=per["calories"],
                protein_g=per["protein_g"],
                fat_g=per["fat_g"],
                carbs_g=per["carbs_g"],
            )
        )
    return foods


def _parse_restrictions(tokens: list[str]):
    """Interpret restriction/allergy text into filtering rules."""
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
        # "no X" / "X-free" / "X free" -> exclude keyword X
        keyword = tok
        if keyword.startswith("no "):
            keyword = keyword[3:]
        keyword = keyword.replace("-free", "").replace(" free", "").strip()
        for word in keyword.split():
            if word in _ALLERGEN_WORDS:
                excluded_allergens.add(_ALLERGEN_WORDS[word])
        # Direct allergen words anywhere in the token
        for word in tok.split():
            if word in _ALLERGEN_WORDS:
                excluded_allergens.add(_ALLERGEN_WORDS[word])
        # Keep a name-exclusion keyword when it's a specific "no X"/"X-free" phrase
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


def _round5(x: float) -> int:
    return int(max(0, round(x / 5.0) * 5))


def _pick(pool: list[Food], idx: int) -> Food | None:
    return pool[idx % len(pool)] if pool else None


def _build_meal(name: str, cal_share: float, targets: dict, pools: dict, rot: int) -> dict:
    """Assemble one meal to hit its share of the day's calories + protein."""
    meal_cal = targets["calories"] * cal_share
    meal_protein = targets["protein_g"] * cal_share
    meal_fat = targets["fat_g"] * cal_share
    is_snack = name == "Snack"

    components: list[tuple[Food, int]] = []
    totals = {"protein_g": 0.0, "fat_g": 0.0, "carbs_g": 0.0}

    def add(food: Food | None, grams: int) -> None:
        if food is None or grams < 10:
            return
        components.append((food, grams))
        m = _macros_for(food, grams)
        for k in totals:
            totals[k] += m[k]

    # 1. Protein source sized to hit the meal's protein share.
    protein = _pick(pools["protein"], rot)
    if protein:
        grams_p = _round5(meal_protein / (protein.protein_g / 100)) if protein.protein_g else 100
        add(protein, min(max(grams_p, 40), 350))

    # 2. A vegetable (or a fruit for snacks) for volume + micros.
    if is_snack:
        add(_pick(pools["fruit"], rot), 120)
    else:
        add(_pick(pools["veg"], rot), 120)

    # 3. Fill the remaining calories with a carb source.
    cal_so_far = calories_from_macros(totals["protein_g"], totals["fat_g"], totals["carbs_g"])
    remaining = meal_cal - cal_so_far
    carb = _pick(pools["carb"], rot)
    if carb and remaining > 40:
        grams_c = _round5(remaining / (carb.calories / 100))
        add(carb, min(grams_c, 400))

    # 4. Top up fat toward the meal's fat share with a small fat source.
    fat_deficit = meal_fat - totals["fat_g"]
    fat = _pick(pools["fat"], rot)
    if fat and fat_deficit > 4 and fat.fat_g:
        grams_f = _round5(fat_deficit / (fat.fat_g / 100))
        add(fat, min(max(grams_f, 5), 40))

    protein_g = round(totals["protein_g"])
    fat_g = round(totals["fat_g"])
    carbs_g = round(totals["carbs_g"])
    calories = round(calories_from_macros(protein_g, fat_g, carbs_g))

    names = [f.short_name() for f, _ in components]
    description = _phrase(names) + "."
    ingredients = [{"item": f.short_name(), "quantity": g, "unit": "g"} for f, g in components]

    return {
        "name": name,
        "description": description,
        "calories": calories,
        "protein_g": protein_g,
        "fat_g": fat_g,
        "carbs_g": carbs_g,
        "ingredients": ingredients,
    }


def _phrase(items: list[str]) -> str:
    items = [i.capitalize() for i in items]
    if not items:
        return "A simple mix"
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def _meal_plan_shares(calories: int) -> list[tuple[str, float]]:
    if calories >= 2200:
        return [("Breakfast", 0.28), ("Lunch", 0.32), ("Dinner", 0.30), ("Snack", 0.10)]
    return [("Breakfast", 0.33), ("Lunch", 0.34), ("Dinner", 0.33)]


_GOAL_WORD = {
    "lose_weight": "fat-loss",
    "gain_muscle": "muscle-building",
    "maintain": "maintenance",
}


def _build_day_meals(profile: UserProfile, pools: dict, rot: int) -> list[dict]:
    macros = profile.target_macros()
    targets = {"calories": profile.target_calories(), **macros}
    meals = []
    for i, (name, share) in enumerate(_meal_plan_shares(targets["calories"])):
        meals.append(_build_meal(name, share, targets, pools, rot + i))
    return meals


def _pools_for(profile: UserProfile, data_file: Path | None = None) -> dict:
    foods = _filter_foods(_load_foods(data_file), profile)
    pools = {g: [f for f in foods if f.group == g] for g in ("protein", "carb", "veg", "fruit", "fat")}
    if not pools["protein"]:
        raise ValueError(
            "No suitable protein sources for these restrictions — please relax them."
        )
    return pools


def _day_totals(meals: list[dict]) -> dict:
    keys = ("calories", "protein_g", "fat_g", "carbs_g")
    return {k: sum(m[k] for m in meals) for k in keys}


def _summary(profile: UserProfile, totals: dict) -> str:
    word = _GOAL_WORD.get(profile.goal, "balanced")
    return (
        f"A personalized {word} day at about {totals['calories']} kcal and "
        f"{totals['protein_g']} g protein, built from whole foods to match your targets."
    )


_NOTES = (
    "Built from our food database to match your calorie and macro targets. "
    "Portions are starting points — adjust to appetite. Not medical advice; "
    "consult a professional for medical conditions."
)


def build_personalized_plan(profile: UserProfile, data_file: Path | None = None) -> dict:
    """Build a single-day personalized plan (no API key needed)."""
    pools = _pools_for(profile, data_file)
    meals = _build_day_meals(profile, pools, rot=0)
    return {"summary": _summary(profile, _day_totals(meals)), "meals": meals, "notes": _NOTES}


def build_personalized_weekly_plan(
    profile: UserProfile, days: int = 7, data_file: Path | None = None
) -> dict:
    """Build a multi-day personalized plan, rotating foods for variety."""
    if not 1 <= days <= 7:
        raise ValueError("days must be between 1 and 7")
    pools = _pools_for(profile, data_file)
    day_blocks = []
    for d in range(days):
        meals = _build_day_meals(profile, pools, rot=d)  # rotate selection per day
        day_blocks.append({"day": _DAY_NAMES[d], "meals": meals})
    summary = (
        f"A personalized {_GOAL_WORD.get(profile.goal, 'balanced')} {days}-day plan, "
        "varied across days and matched to your targets."
    )
    return {"summary": summary, "days": day_blocks, "notes": _NOTES}
