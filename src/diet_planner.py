"""Generate a personalized daily meal plan with Claude.

Uses the Anthropic Messages API with structured outputs so the response is a
validated JSON object, adaptive thinking for better nutritional reasoning, and
streaming so large plans don't hit request timeouts.
"""

from __future__ import annotations

import json

import anthropic

from .profile import UserProfile

MODEL = "claude-opus-4-8"

# JSON Schema the model is constrained to. Keeps the output parseable.
_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "meals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "calories": {"type": "integer"},
                    "protein_g": {"type": "integer"},
                    "fat_g": {"type": "integer"},
                    "carbs_g": {"type": "integer"},
                },
                "required": ["name", "description", "calories", "protein_g", "fat_g", "carbs_g"],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["summary", "meals", "notes"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You are a knowledgeable, safety-conscious nutrition assistant. You design "
    "practical one-day meal plans that hit the given calorie and macro targets. "
    "You are not a doctor: never give medical advice, and add a note reminding "
    "the user to consult a professional for medical conditions."
)


def _build_prompt(profile: UserProfile) -> str:
    macros = profile.target_macros()
    return (
        f"Create a one-day meal plan for this person.\n\n"
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
        f"- Carbs: {macros['carbs_g']} g\n\n"
        f"Provide 3-5 meals whose totals land close to these targets. Respect all "
        f"restrictions and allergies strictly."
    )


def generate_plan(profile: UserProfile, client: anthropic.Anthropic | None = None) -> dict:
    """Generate a meal plan for the profile and return it as a dict."""
    client = client or anthropic.Anthropic()

    with client.messages.stream(
        model=MODEL,
        max_tokens=8000,
        system=_SYSTEM,
        thinking={"type": "adaptive"},
        output_config={"format": {"type": "json_schema", "schema": _PLAN_SCHEMA}},
        messages=[{"role": "user", "content": _build_prompt(profile)}],
    ) as stream:
        message = stream.get_final_message()

    text = next(b.text for b in message.content if b.type == "text")
    return json.loads(text)
