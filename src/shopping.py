"""Build a consolidated shopping list from a generated plan.

Ingredients are aggregated across every meal: entries with the same item name
and unit are combined and their quantities summed. Different units of the same
item (e.g. "100 g onion" and "1 piece onion") are kept as separate lines, since
they can't be summed reliably without a unit-conversion table.

Pure functions — no API calls, fully testable offline.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ShoppingItem:
    """One consolidated line on the shopping list."""

    item: str
    quantity: float
    unit: str

    def __str__(self) -> str:
        # Drop a trailing ".0" so whole numbers read cleanly.
        qty = int(self.quantity) if self.quantity == int(self.quantity) else self.quantity
        unit = f" {self.unit}" if self.unit else ""
        return f"{qty}{unit} {self.item}".strip()


def _iter_meals(plan: dict):
    """Yield every meal dict from either a daily or weekly plan."""
    if "days" in plan:  # weekly shape
        for day in plan.get("days", []):
            yield from day.get("meals", [])
    else:  # daily shape
        yield from plan.get("meals", [])


def build_shopping_list(plan: dict) -> list[ShoppingItem]:
    """Aggregate ingredients across a daily or weekly plan.

    Returns items sorted by name (then unit). Combines by case-insensitive item
    name plus normalized unit; the display name/unit is the first spelling seen.
    """
    # key -> [display_item, display_unit, total_quantity]
    combined: dict[tuple[str, str], list] = {}

    for meal in _iter_meals(plan):
        for ing in meal.get("ingredients", []):
            item = str(ing.get("item", "")).strip()
            unit = str(ing.get("unit", "")).strip()
            if not item:
                continue
            try:
                qty = float(ing.get("quantity", 0) or 0)
            except (TypeError, ValueError):
                qty = 0.0
            key = (item.lower(), unit.lower())
            if key in combined:
                combined[key][2] += qty
            else:
                combined[key] = [item, unit, qty]

    items = [ShoppingItem(item=d[0], quantity=d[2], unit=d[1]) for d in combined.values()]
    items.sort(key=lambda s: (s.item.lower(), s.unit.lower()))
    return items
