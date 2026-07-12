"""User profile model and calorie/macro math for diet planning."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Goal = Literal["lose_weight", "gain_muscle", "maintain"]
Sex = Literal["male", "female"]
ActivityLevel = Literal[
    "sedentary",       # little or no exercise
    "light",           # 1-3 days/week
    "moderate",        # 3-5 days/week
    "active",          # 6-7 days/week
    "very_active",     # hard exercise / physical job
]

# Multipliers applied to BMR to estimate total daily energy expenditure (TDEE).
_ACTIVITY_FACTORS: dict[ActivityLevel, float] = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
    "very_active": 1.9,
}


@dataclass
class UserProfile:
    """A person's intake data for generating a diet plan."""

    age: int
    sex: Sex
    height_cm: float
    weight_kg: float
    activity_level: ActivityLevel
    goal: Goal
    dietary_restrictions: list[str] = field(default_factory=list)  # e.g. ["vegetarian", "no nuts"]
    allergies: list[str] = field(default_factory=list)

    def bmr(self) -> float:
        """Basal metabolic rate via the Mifflin-St Jeor equation (kcal/day)."""
        base = 10 * self.weight_kg + 6.25 * self.height_cm - 5 * self.age
        return base + (5 if self.sex == "male" else -161)

    def tdee(self) -> float:
        """Total daily energy expenditure (kcal/day)."""
        return self.bmr() * _ACTIVITY_FACTORS[self.activity_level]

    def target_calories(self) -> int:
        """Daily calorie target adjusted for the goal.

        A ~500 kcal deficit/surplus targets roughly 0.5 kg per week of change,
        a commonly recommended sustainable rate.
        """
        tdee = self.tdee()
        if self.goal == "lose_weight":
            tdee -= 500
        elif self.goal == "gain_muscle":
            tdee += 300
        return round(tdee)

    def target_macros(self) -> dict[str, int]:
        """Rough macro split (grams) for the goal.

        Protein is set per kg of bodyweight, fat as a share of calories, and
        carbs fill the remainder. These are starting points, not medical advice.
        """
        calories = self.target_calories()

        if self.goal == "gain_muscle":
            protein_g = round(2.0 * self.weight_kg)
            fat_ratio = 0.25
        elif self.goal == "lose_weight":
            protein_g = round(1.8 * self.weight_kg)
            fat_ratio = 0.30
        else:
            protein_g = round(1.6 * self.weight_kg)
            fat_ratio = 0.28

        fat_g = round((calories * fat_ratio) / 9)
        remaining = calories - (protein_g * 4) - (fat_g * 9)
        carbs_g = max(0, round(remaining / 4))

        return {"protein_g": protein_g, "fat_g": fat_g, "carbs_g": carbs_g}
