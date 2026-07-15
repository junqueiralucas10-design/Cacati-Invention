"""Estimate the grocery cost of a plan, in Brazilian reais (R$).

Prices are approximate Carrefour Brasil reference values (src/data/prices_brl.json,
R$ per kg) — not a live feed. Each shopping-list quantity is converted to kilograms
(using the food's portion unit) and multiplied by its price. Items without a known
price are reported separately rather than silently dropped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .diet_builder import Food, _load_foods
from .shopping import build_shopping_list

_PRICE_FILE = Path(__file__).parent / "data" / "prices_brl.json"


def _load_prices(price_file: Path | None = None) -> dict[str, float]:
    raw = json.loads((price_file or _PRICE_FILE).read_text(encoding="utf-8"))
    return {k: float(v) for k, v in raw["per_kg"].items()}


def _food_index(foods: list[Food]) -> dict[str, Food]:
    """Map short name and full name (lowercased) to a Food."""
    idx: dict[str, Food] = {}
    for f in foods:
        idx[f.name.lower()] = f
        idx[f.short_name().lower()] = f
    return idx


@dataclass
class CostLine:
    item: str
    quantity: float
    unit: str
    cost_brl: float


def estimate_plan_cost(
    plan: dict,
    foods: list[Food] | None = None,
    prices: dict[str, float] | None = None,
) -> dict:
    """Estimate a plan's grocery cost from its consolidated shopping list.

    Returns {"total_brl", "lines": [CostLine...], "unpriced": [names]}.
    Works for daily and weekly plans (build_shopping_list aggregates both).
    """
    foods = foods if foods is not None else _load_foods()
    prices = prices if prices is not None else _load_prices()
    idx = _food_index(foods)

    lines: list[CostLine] = []
    unpriced: list[str] = []
    total = 0.0

    for item in build_shopping_list(plan):
        food = idx.get(item.item.lower())
        price_per_kg = prices.get(food.name) if food else None
        if food is None or price_per_kg is None:
            unpriced.append(item.item)
            continue
        grams = item.quantity if item.unit == "g" else item.quantity * food.unit_g
        cost = (grams / 1000.0) * price_per_kg
        total += cost
        lines.append(CostLine(item.item, item.quantity, item.unit, round(cost, 2)))

    return {"total_brl": round(total, 2), "lines": lines, "unpriced": unpriced}


def format_brl(value: float) -> str:
    """Format a number as Brazilian currency, e.g. 32.5 -> 'R$ 32,50'."""
    return "R$ " + f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
