"""Tests for shopping-list aggregation. No API key needed."""

from src.shopping import ShoppingItem, build_shopping_list


def _daily_plan() -> dict:
    return {
        "meals": [
            {
                "name": "Breakfast",
                "ingredients": [
                    {"item": "Oats", "quantity": 80, "unit": "g"},
                    {"item": "Banana", "quantity": 1, "unit": "piece"},
                ],
            },
            {
                "name": "Lunch",
                "ingredients": [
                    {"item": "oats", "quantity": 20, "unit": "g"},  # same item, diff case
                    {"item": "Chicken breast", "quantity": 200, "unit": "g"},
                ],
            },
        ]
    }


def test_combines_same_item_and_unit():
    items = build_shopping_list(_daily_plan())
    by_name = {i.item.lower(): i for i in items}
    # 80g + 20g oats -> 100g on one line, display name from first spelling
    assert by_name["oats"].quantity == 100
    assert by_name["oats"].unit == "g"
    assert by_name["oats"].item == "Oats"


def test_keeps_all_distinct_items():
    items = build_shopping_list(_daily_plan())
    names = sorted(i.item.lower() for i in items)
    assert names == ["banana", "chicken breast", "oats"]


def test_different_units_stay_separate():
    plan = {
        "meals": [
            {"ingredients": [{"item": "Onion", "quantity": 100, "unit": "g"}]},
            {"ingredients": [{"item": "onion", "quantity": 1, "unit": "piece"}]},
        ]
    }
    items = build_shopping_list(plan)
    assert len(items) == 2  # g and piece not merged


def test_weekly_plan_aggregates_across_days():
    weekly = {
        "days": [
            {"day": "Mon", "meals": [{"ingredients": [{"item": "Eggs", "quantity": 2, "unit": "piece"}]}]},
            {"day": "Tue", "meals": [{"ingredients": [{"item": "eggs", "quantity": 3, "unit": "piece"}]}]},
        ]
    }
    items = build_shopping_list(weekly)
    assert len(items) == 1
    assert items[0].item == "Eggs"
    assert items[0].quantity == 5


def test_sorted_by_name():
    items = build_shopping_list(_daily_plan())
    assert [i.item.lower() for i in items] == sorted(i.item.lower() for i in items)


def test_str_formatting_drops_trailing_zero():
    assert str(ShoppingItem(item="Oats", quantity=100.0, unit="g")) == "100 g Oats"
    assert str(ShoppingItem(item="Banana", quantity=1, unit="piece")) == "1 piece Banana"


def test_handles_missing_ingredients_and_empty_plan():
    assert build_shopping_list({}) == []
    assert build_shopping_list({"meals": [{"name": "no ingredients"}]}) == []


def test_bad_quantity_is_ignored_gracefully():
    plan = {"meals": [{"ingredients": [{"item": "Salt", "quantity": "a pinch", "unit": ""}]}]}
    items = build_shopping_list(plan)
    assert len(items) == 1
    assert items[0].quantity == 0
