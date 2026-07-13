"""Tests for nutrition lookup and plan verification. No API key needed."""

from src.nutrition import (
    LocalNutritionDatabase,
    calories_from_macros,
    verify_plan,
)


def test_calories_from_macros_atwater():
    # 30g protein, 10g fat, 20g carbs -> 30*4 + 20*4 + 10*9 = 290
    assert calories_from_macros(protein_g=30, fat_g=10, carbs_g=20) == 290


def test_local_db_exact_and_alias_lookup():
    db = LocalNutritionDatabase()
    exact = db.lookup("chicken breast, cooked")
    assert exact is not None and exact.protein_g == 31

    # alias resolves to the same food
    alias = db.lookup("chicken")
    assert alias is not None and alias.name == "chicken breast, cooked"


def test_local_db_substring_and_case_insensitive():
    db = LocalNutritionDatabase()
    m = db.lookup("Grilled CHICKEN with rice")  # contains a known key
    assert m is not None


def test_local_db_unknown_returns_none():
    db = LocalNutritionDatabase()
    assert db.lookup("dragonfruit smoothie") is None
    assert db.lookup("") is None


def test_verify_plan_passes_consistent_meal():
    plan = {
        "meals": [
            # 40*4 + 50*4 + 15*9 = 495 calories, stated 500 -> within 10%
            {"name": "Balanced bowl", "calories": 500, "protein_g": 40, "fat_g": 15, "carbs_g": 50},
        ]
    }
    assert verify_plan(plan) == []


def test_verify_plan_flags_inconsistent_meal():
    plan = {
        "meals": [
            # macros compute to ~290 kcal but stated 900 -> flagged
            {"name": "Suspicious meal", "calories": 900, "protein_g": 30, "fat_g": 10, "carbs_g": 20},
        ]
    }
    flagged = verify_plan(plan)
    assert len(flagged) == 1
    assert flagged[0].meal == "Suspicious meal"
    assert flagged[0].stated == 900
    assert flagged[0].computed == 290


def test_verify_plan_handles_empty_plan():
    assert verify_plan({}) == []
    assert verify_plan({"meals": []}) == []
