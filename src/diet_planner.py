"""Generate personalized meal plans (single-day or weekly) with Claude.

Uses the Anthropic Messages API with structured outputs so responses are
validated JSON, adaptive thinking for better nutritional reasoning, and
streaming so large plans don't hit request timeouts.
"""

from __future__ import annotations

import json

import anthropic

from .profile import UserProfile

MODEL = "claude-opus-4-8"

# A single ingredient line, used to build a consolidated shopping list.
_INGREDIENT_SCHEMA = {
    "type": "object",
    "properties": {
        "item": {"type": "string"},
        "quantity": {"type": "number"},
        "unit": {"type": "string"},  # e.g. "g", "ml", "cup", "piece"
    },
    "required": ["item", "quantity", "unit"],
    "additionalProperties": False,
}

# A single meal — reused by both the daily and weekly schemas.
_MEAL_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "calories": {"type": "integer"},
        "protein_g": {"type": "integer"},
        "fat_g": {"type": "integer"},
        "carbs_g": {"type": "integer"},
        "ingredients": {"type": "array", "items": _INGREDIENT_SCHEMA},
    },
    "required": [
        "name",
        "description",
        "calories",
        "protein_g",
        "fat_g",
        "carbs_g",
        "ingredients",
    ],
    "additionalProperties": False,
}

_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "meals": {"type": "array", "items": _MEAL_SCHEMA},
        "notes": {"type": "string"},
    },
    "required": ["summary", "meals", "notes"],
    "additionalProperties": False,
}

_WEEKLY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "days": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "day": {"type": "string"},
                    "meals": {"type": "array", "items": _MEAL_SCHEMA},
                },
                "required": ["day", "meals"],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["summary", "days", "notes"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You are a knowledgeable, safety-conscious nutrition assistant. You design "
    "practical meal plans that hit the given calorie and macro targets. "
    "You are not a doctor: never give medical advice, and add a note reminding "
    "the user to consult a professional for medical conditions."
)


def _profile_block(profile: UserProfile) -> str:
    """The shared profile + daily-targets description used in every prompt."""
    macros = profile.target_macros()
    return (
        f"- Age: {profile.age}\n"
        f"- Sex: {profile.sex}\n"
        f"- Height: {profile.height_cm} cm\n"
        f"- Weight: {profile.weight_kg} kg\n"
        f"- Activity level: {profile.activity_level}\n"
        f"- Goal: {profile.goal}\n"
        f"- Dietary restrictions: {', '.join(profile.dietary_restrictions) or 'none'}\n"
        f"- Allergies: {', '.join(profile.allergies) or 'none'}\n\n"
        f"Daily targets:\n"
        f"- Calories: {profile.target_calories()} kcal\n"
        f"- Protein: {macros['protein_g']} g\n"
        f"- Fat: {macros['fat_g']} g\n"
        f"- Carbs: {macros['carbs_g']} g\n"
    )


def _meals_phrase(profile: UserProfile) -> str:
    """How many meals to request — honor the person's preference when given."""
    if profile.meals_per_day:
        n = max(3, min(6, profile.meals_per_day))
        return f"exactly {n} meals (including any snacks)"
    return "3-5 meals"


def _build_prompt(profile: UserProfile) -> str:
    return (
        "Create a one-day meal plan for this person.\n\n"
        f"{_profile_block(profile)}\n"
        f"Provide {_meals_phrase(profile)} whose totals land close to these targets. "
        "For each meal list its ingredients with a quantity and unit (e.g. grams, ml, "
        "cups, pieces) so a shopping list can be built. Respect all restrictions and "
        "allergies strictly."
    )


def _build_weekly_prompt(profile: UserProfile, days: int) -> str:
    return (
        f"Create a {days}-day meal plan for this person.\n\n"
        f"{_profile_block(profile)}\n"
        f"Provide {days} days, each with {_meals_phrase(profile)} whose daily totals land "
        "close to the targets above. Vary the meals across days so the week isn't "
        "repetitive. For each meal list its ingredients with a quantity and unit (e.g. "
        "grams, ml, cups, pieces) so a shopping list can be built. "
        "Respect all restrictions and allergies strictly."
    )


def _generate(schema: dict, prompt: str, client: anthropic.Anthropic, max_tokens: int) -> dict:
    """Run one structured, streamed request and return the parsed JSON."""
    with client.messages.stream(
        model=MODEL,
        max_tokens=max_tokens,
        system=_SYSTEM,
        thinking={"type": "adaptive"},
        output_config={"format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        message = stream.get_final_message()

    text = next(b.text for b in message.content if b.type == "text")
    return json.loads(text)


def generate_plan(profile: UserProfile, client: anthropic.Anthropic | None = None) -> dict:
    """Generate a single-day meal plan and return it as a dict."""
    client = client or anthropic.Anthropic()
    return _generate(_PLAN_SCHEMA, _build_prompt(profile), client, max_tokens=8000)


def generate_weekly_plan(
    profile: UserProfile,
    days: int = 7,
    client: anthropic.Anthropic | None = None,
) -> dict:
    """Generate a multi-day meal plan with variety across days.

    `days` must be 1-7. The result has the shape:
    {"summary", "days": [{"day", "meals": [...]}, ...], "notes"}.
    """
    if not 1 <= days <= 7:
        raise ValueError("days must be between 1 and 7")
    client = client or anthropic.Anthropic()
    # More output room: roughly one day's worth of tokens per day, capped for streaming.
    max_tokens = min(4000 + days * 4000, 32000)
    return _generate(_WEEKLY_SCHEMA, _build_weekly_prompt(profile, days), client, max_tokens)
