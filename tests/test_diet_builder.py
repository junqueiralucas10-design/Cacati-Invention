"""Tests for the rule-based personalized diet builder. No API key needed."""

import pytest

from src.diet_builder import (
    _filter_foods,
    _load_foods,
    build_personalized_plan,
    build_personalized_weekly_plan,
)
from src.nutrition import verify_plan, verify_weekly_plan
from src.profile import UserProfile


def _profile(**overrides) -> UserProfile:
    base = dict(
        age=30, sex="male", height_cm=178, weight_kg=82,
        activity_level="moderate", goal="gain_muscle",
        dietary_restrictions=[], allergies=[],
    )
    base.update(overrides)
    return UserProfile(**base)


def test_plan_has_expected_shape():
    plan = build_personalized_plan(_profile())
    assert plan["summary"] and plan["notes"]
    assert len(plan["meals"]) >= 3
    for meal in plan["meals"]:
        for key in ("name", "description", "calories", "protein_g", "fat_g", "carbs_g", "ingredients"):
            assert key in meal
        assert meal["ingredients"]  # every meal lists ingredients


def test_plan_passes_nutrition_check():
    # Calories are derived from the macros, so the plan is internally consistent.
    plan = build_personalized_plan(_profile())
    assert verify_plan(plan) == []


def test_daily_totals_are_near_targets():
    profile = _profile()
    plan = build_personalized_plan(profile)
    total_cal = sum(m["calories"] for m in plan["meals"])
    total_pro = sum(m["protein_g"] for m in plan["meals"])
    assert abs(total_cal - profile.target_calories()) / profile.target_calories() < 0.12
    assert total_pro >= profile.target_macros()["protein_g"] * 0.85


@pytest.mark.parametrize(
    "kw",
    [
        dict(goal="gain_muscle", activity_level="active"),
        dict(goal="lose_weight", activity_level="light"),
        dict(goal="maintain", sex="female", weight_kg=60, height_cm=165),
        dict(goal="gain_muscle", dietary_restrictions=["vegetarian"]),
        dict(goal="lose_weight", dietary_restrictions=["vegan"]),
    ],
)
def test_calorie_precision_across_profiles(kw):
    profile = _profile(**kw)
    plan = build_personalized_plan(profile)
    total = sum(m["calories"] for m in plan["meals"])
    target = profile.target_calories()
    # The rule-based engine should land within 12% of the calorie target.
    assert abs(total - target) / target < 0.12, (total, target)


def test_vegetarian_excludes_meat_and_fish():
    foods = _filter_foods(_load_foods(), _profile(dietary_restrictions=["vegetarian"]))
    names = [f.name.lower() for f in foods]
    assert not any("frango" in n or "carne" in n or "tilápia" in n for n in names)
    # ovos/laticínios still allowed for a vegetarian
    assert any("ovos" in n for n in names)


def test_vegan_excludes_animal_products():
    foods = _filter_foods(_load_foods(), _profile(dietary_restrictions=["vegan"]))
    diets = {f.diet for f in foods}
    assert diets == {"vegan"}


def test_nut_allergy_excludes_nuts():
    plan = build_personalized_plan(_profile(allergies=["nuts"]))
    text = " ".join(
        ing["item"].lower()
        for m in plan["meals"]
        for ing in m["ingredients"]
    )
    assert "amendoim" not in text and "castanha" not in text


def test_portuguese_restrictions_work():
    # Portuguese terms should filter just like the English ones.
    vegan = _filter_foods(_load_foods(), _profile(dietary_restrictions=["vegano"]))
    assert {f.diet for f in vegan} == {"vegan"}

    plan = build_personalized_plan(_profile(allergies=["sem lactose"]))
    text = " ".join(
        ing["item"].lower() for m in plan["meals"] for ing in m["ingredients"]
    )
    assert "leite" not in text and "queijo" not in text and "iogurte" not in text


def test_impossible_restrictions_raise():
    # vegan + soy allergy removes tofu/tempeh/soy milk/edamame; excluding the
    # remaining legumes by name leaves no protein source at all.
    with pytest.raises(ValueError):
        build_personalized_plan(
            _profile(
                dietary_restrictions=["vegan", "no beans", "no lentils", "no chickpeas"],
                allergies=["soy"],
            )
        )


def test_weekly_plan_shape_and_variety():
    weekly = build_personalized_weekly_plan(_profile(), days=3)
    assert len(weekly["days"]) == 3
    assert [d["day"] for d in weekly["days"]] == ["Monday", "Tuesday", "Wednesday"]
    assert verify_weekly_plan(weekly) == []
    # Rotation should make at least two days differ in their first meal's makeup.
    firsts = [d["meals"][0]["description"] for d in weekly["days"]]
    assert len(set(firsts)) >= 2


def test_weekly_rejects_bad_day_count():
    with pytest.raises(ValueError):
        build_personalized_weekly_plan(_profile(), days=9)


def _meal(plan, name):
    return next(m for m in plan["meals"] if m["name"] == name)


def test_breakfast_avoids_dinner_only_foods():
    plan = build_personalized_plan(_profile())
    breakfast_items = " ".join(i["item"].lower() for i in _meal(plan, "Breakfast")["ingredients"])
    for bad in ("tilápia", "brócolis", "frango", "carne", "arroz", "feijão"):
        assert bad not in breakfast_items


def test_dinner_avoids_breakfast_only_foods():
    plan = build_personalized_plan(_profile())
    dinner_items = " ".join(i["item"].lower() for i in _meal(plan, "Dinner")["ingredients"])
    for bad in ("aveia", "banana", "pão francês", "tapioca"):
        assert bad not in dinner_items


@pytest.mark.parametrize("n", [3, 4, 5, 6])
def test_meals_per_day_controls_meal_count(n):
    plan = build_personalized_plan(_profile(meals_per_day=n))
    assert len(plan["meals"]) == n


def test_meals_per_day_uses_natural_snack_names():
    names = [m["name"] for m in build_personalized_plan(_profile(meals_per_day=6))["meals"]]
    assert names == [
        "Breakfast", "Morning Snack", "Lunch", "Afternoon Snack", "Dinner", "Evening Snack"
    ]


def test_meals_per_day_out_of_range_is_clamped():
    assert len(build_personalized_plan(_profile(meals_per_day=99))["meals"]) == 6
    assert len(build_personalized_plan(_profile(meals_per_day=1))["meals"]) == 3


def test_more_meals_still_hits_calorie_target():
    profile = _profile(meals_per_day=6)
    plan = build_personalized_plan(profile)
    total = sum(m["calories"] for m in plan["meals"])
    assert abs(total - profile.target_calories()) / profile.target_calories() < 0.15


def test_portions_use_natural_units():
    # e.g. ovos are counted ("" unit), not given in grams.
    plan = build_personalized_plan(_profile())
    units = {i["unit"] for m in plan["meals"] for i in m["ingredients"]}
    # some countable/measured unit is used (ovos/banana "", azeite "colher de sopa", leite "copo")
    assert any(u in units for u in ("", "colher de sopa", "copo", "scoop"))

    ovos = [
        i for m in plan["meals"] for i in m["ingredients"] if i["item"].lower() == "ovos"
    ]
    if ovos:  # when eggs are chosen, they're a small whole count, not hundreds of grams
        assert ovos[0]["unit"] == ""
        assert 1 <= ovos[0]["quantity"] <= 4
