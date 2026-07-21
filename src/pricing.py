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


def load_prices(price_file: Path | None = None) -> dict[str, float]:
    """Public alias: food name -> R$/kg."""
    return _load_prices(price_file)


def save_prices(prices: dict[str, float], price_file: Path | None = None) -> None:
    """Persist updated per-kg prices, preserving the file's metadata fields."""
    path = price_file or _PRICE_FILE
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["per_kg"] = {k: round(float(v), 2) for k, v in prices.items()}
    path.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


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


def prices_to_csv(prices: dict[str, float]) -> str:
    """Render prices as 'food,price_brl_per_kg' CSV text (comma decimal ok on import)."""
    lines = ["food,price_brl_per_kg"]
    for name in sorted(prices):
        lines.append(f"{name},{prices[name]:.2f}")
    return "\n".join(lines) + "\n"


def prices_from_csv(text: str, known: dict[str, float]) -> tuple[dict[str, float], list[str]]:
    """Parse a CSV back into prices, keyed to known food names.

    Accepts '12.50' or '12,50'. Unknown food names and bad values are collected
    into a skipped list instead of failing the whole import. Foods absent from
    the CSV keep their current price.
    """
    updated = dict(known)
    skipped: list[str] = []
    for line_no, raw_line in enumerate(text.splitlines()):
        line = raw_line.strip().lstrip("﻿")
        if not line or line_no == 0 and line.lower().startswith("food"):
            continue
        # Split on the FIRST comma: our food names contain no commas, while the
        # value may use a comma decimal ("12,50").
        name, sep, value = line.partition(",")
        name = name.strip().strip('"')
        if not sep or name not in updated:
            skipped.append(raw_line.strip())
            continue
        try:
            price = float(value.strip().strip('"').replace(",", "."))
        except ValueError:
            skipped.append(raw_line.strip())
            continue
        if price <= 0:
            skipped.append(raw_line.strip())
            continue
        updated[name] = round(price, 2)
    return updated, skipped
