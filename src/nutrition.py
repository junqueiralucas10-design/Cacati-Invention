"""Nutrition data lookup and plan verification.

Two responsibilities:

1. `NutritionSource` — a pluggable food-lookup interface. `LocalNutritionDatabase`
   ships a small curated dataset (src/data/foods.json). A USDA FoodData Central
   source can be added later behind the same interface (needs an API key + network).
2. Verification — cross-check a generated plan's stated calories/macros against
   physics (Atwater factors) and, where possible, against the database, so numbers
   are validated rather than taken on faith from the model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

# Atwater energy factors (kcal per gram).
_KCAL_PER_G = {"protein_g": 4, "carbs_g": 4, "fat_g": 9}

_DATA_FILE = Path(__file__).parent / "data" / "foods.json"


@dataclass(frozen=True)
class FoodMacros:
    """Macros for a food, per 100 g."""

    name: str
    calories: float
    protein_g: float
    fat_g: float
    carbs_g: float


class NutritionSource(Protocol):
    """A source that can resolve a food name to its per-100g macros."""

    def lookup(self, name: str) -> FoodMacros | None:
        """Return macros for the closest matching food, or None if unknown."""
        ...


class LocalNutritionDatabase:
    """Food lookup backed by the bundled foods.json dataset."""

    def __init__(self, data_file: Path | None = None) -> None:
        raw = json.loads((data_file or _DATA_FILE).read_text(encoding="utf-8"))
        # Build a name/alias -> FoodMacros index for cheap matching.
        self._index: dict[str, FoodMacros] = {}
        for entry in raw["foods"]:
            per = entry["per_100g"]
            macros = FoodMacros(
                name=entry["name"],
                calories=per["calories"],
                protein_g=per["protein_g"],
                fat_g=per["fat_g"],
                carbs_g=per["carbs_g"],
            )
            keys = [entry["name"], *entry.get("aliases", [])]
            for key in keys:
                self._index[key.lower()] = macros

    def lookup(self, name: str) -> FoodMacros | None:
        """Match by exact name/alias first, then by substring overlap."""
        needle = name.strip().lower()
        if not needle:
            return None
        if needle in self._index:
            return self._index[needle]
        # Substring match: either the query contains a known key, or vice versa.
        for key, macros in self._index.items():
            if key in needle or needle in key:
                return macros
        return None

    def __len__(self) -> int:
        return len({id(m) for m in self._index.values()})


def calories_from_macros(protein_g: float, fat_g: float, carbs_g: float) -> float:
    """Compute calories from macros using Atwater factors."""
    return (
        protein_g * _KCAL_PER_G["protein_g"]
        + carbs_g * _KCAL_PER_G["carbs_g"]
        + fat_g * _KCAL_PER_G["fat_g"]
    )


@dataclass
class Discrepancy:
    """A flagged inconsistency between stated and computed values."""

    meal: str
    field: str          # e.g. "calories"
    stated: float
    computed: float

    @property
    def delta(self) -> float:
        return self.stated - self.computed

    def __str__(self) -> str:
        return (
            f"{self.meal}: {self.field} stated {self.stated:.0f} "
            f"vs computed {self.computed:.0f} (off by {self.delta:+.0f})"
        )


def _verify_meals(
    meals: list[dict], tolerance: float, label_prefix: str = ""
) -> list[Discrepancy]:
    """Flag meals whose stated calories don't match their macros."""
    discrepancies: list[Discrepancy] = []
    for meal in meals:
        computed = calories_from_macros(
            meal.get("protein_g", 0),
            meal.get("fat_g", 0),
            meal.get("carbs_g", 0),
        )
        stated = meal.get("calories", 0)
        # Avoid divide-by-zero; use the larger of the two as the denominator.
        denom = max(stated, computed, 1)
        if abs(stated - computed) / denom > tolerance:
            name = meal.get("name", "(unnamed)")
            discrepancies.append(
                Discrepancy(
                    meal=f"{label_prefix}{name}" if label_prefix else name,
                    field="calories",
                    stated=stated,
                    computed=computed,
                )
            )
    return discrepancies


def verify_plan(plan: dict, tolerance: float = 0.10) -> list[Discrepancy]:
    """Check each meal's stated calories against its macros.

    A meal is flagged when its stated calories differ from the Atwater-computed
    value by more than `tolerance` (a fraction, default 10%). This catches
    internally inconsistent model output without needing any external data.
    """
    return _verify_meals(plan.get("meals", []), tolerance)


def verify_weekly_plan(weekly: dict, tolerance: float = 0.10) -> list[Discrepancy]:
    """Like verify_plan, but for a multi-day plan.

    Expects {"days": [{"day", "meals": [...]}, ...]}. Flagged meals are labeled
    with their day, e.g. "Monday — Oatmeal".
    """
    discrepancies: list[Discrepancy] = []
    for day in weekly.get("days", []):
        prefix = f"{day.get('day', '?')} — "
        discrepancies.extend(_verify_meals(day.get("meals", []), tolerance, prefix))
    return discrepancies
