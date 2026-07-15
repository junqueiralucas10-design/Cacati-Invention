"""Tests for the R$ cost estimator. No API key needed."""

from src.diet_builder import build_personalized_plan, build_personalized_weekly_plan
from src.pricing import estimate_plan_cost, format_brl
from src.profile import UserProfile


def _profile(**kw) -> UserProfile:
    base = dict(age=30, sex="male", height_cm=178, weight_kg=82,
                activity_level="moderate", goal="gain_muscle")
    base.update(kw)
    return UserProfile(**base)


def test_format_brl():
    assert format_brl(32.5) == "R$ 32,50"
    assert format_brl(1234.5) == "R$ 1.234,50"
    assert format_brl(0) == "R$ 0,00"


def test_manual_price_calculation():
    # 400 g cooked white rice at R$2.50/kg = R$1.00; 200 g chicken at R$22/kg = R$4.40
    plan = {
        "meals": [
            {
                "name": "Lunch", "calories": 0, "protein_g": 0, "fat_g": 0, "carbs_g": 0,
                "ingredients": [
                    {"item": "arroz branco cozido", "quantity": 400, "unit": "g"},
                    {"item": "frango grelhado", "quantity": 200, "unit": "g"},
                ],
            }
        ]
    }
    cost = estimate_plan_cost(plan)
    assert cost["unpriced"] == []
    assert cost["total_brl"] == 5.40  # 1.00 + 4.40


def test_countable_item_uses_grams_per_unit():
    # 4 ovos * 50 g = 200 g at R$15/kg = R$3.00
    plan = {
        "meals": [
            {
                "name": "Breakfast", "calories": 0, "protein_g": 0, "fat_g": 0, "carbs_g": 0,
                "ingredients": [{"item": "ovos", "quantity": 4, "unit": ""}],
            }
        ]
    }
    cost = estimate_plan_cost(plan)
    assert cost["total_brl"] == 3.00


def test_unknown_item_is_reported_not_priced():
    plan = {
        "meals": [
            {
                "name": "Snack", "calories": 0, "protein_g": 0, "fat_g": 0, "carbs_g": 0,
                "ingredients": [{"item": "picanha importada", "quantity": 100, "unit": "g"}],
            }
        ]
    }
    cost = estimate_plan_cost(plan)
    assert cost["total_brl"] == 0.0
    assert "picanha importada" in cost["unpriced"]


def test_real_daily_plan_has_a_reasonable_cost():
    cost = estimate_plan_cost(build_personalized_plan(_profile()))
    # A day of whole foods should cost something modest but non-trivial.
    assert cost["unpriced"] == []
    assert 5 < cost["total_brl"] < 80


def test_weekly_costs_more_than_daily():
    daily = estimate_plan_cost(build_personalized_plan(_profile()))["total_brl"]
    weekly = estimate_plan_cost(build_personalized_weekly_plan(_profile(), days=7))["total_brl"]
    assert weekly > daily * 3  # a week clearly costs more than a single day
