"""A small Flask web UI for generating diet plans.

Reuses the same core as the CLI — profile math, planner, nutrition check, and
shopping list. The CLI intake (src/cli.py) is unchanged; this is an alternative
front end, not a replacement.

Run it:
    python -m src.webapp        # serves http://127.0.0.1:5000

The generator is injectable (`create_app(generate=...)`) so routes can be tested
without an API key.
"""

from __future__ import annotations

from typing import Callable

from flask import Flask, render_template_string, request

from .diet_planner import generate_plan, generate_weekly_plan
from .intake import (
    IntakeError,
    parse_choice,
    parse_int_in_range,
    parse_list,
    parse_positive_float,
)
from .nutrition import verify_plan, verify_weekly_plan
from .profile import UserProfile
from .shopping import build_shopping_list

# Option lists mirrored from intake, used to render <select> fields.
_SEX_OPTIONS = ["male", "female"]
_ACTIVITY_OPTIONS = ["sedentary", "light", "moderate", "active", "very_active"]
_GOAL_OPTIONS = ["lose_weight", "gain_muscle", "maintain"]
_LENGTH_OPTIONS = [("", "Single day"), ("3", "3 days"), ("5", "5 days"), ("7", "7 days")]

# A generate callable takes (profile, days|None) and returns a plan dict.
Generator = Callable[[UserProfile, "int | None"], dict]


def _default_generate(profile: UserProfile, days: int | None) -> dict:
    if days is None:
        return generate_plan(profile)
    return generate_weekly_plan(profile, days=days)


def profile_from_form(form) -> UserProfile:
    """Parse and validate an HTML form into a UserProfile.

    Raises IntakeError with a human-readable message on the first bad field.
    """
    age = parse_int_in_range(form.get("age", ""), 13, 120)
    sex = parse_choice(form.get("sex", ""), _SEX_OPTIONS)
    height_cm = parse_positive_float(form.get("height_cm", ""))
    weight_kg = parse_positive_float(form.get("weight_kg", ""))
    activity = parse_choice(form.get("activity_level", ""), _ACTIVITY_OPTIONS)
    goal = parse_choice(form.get("goal", ""), _GOAL_OPTIONS)
    restrictions = parse_list(form.get("dietary_restrictions", ""))
    allergies = parse_list(form.get("allergies", ""))
    return UserProfile(
        age=age,
        sex=sex,  # type: ignore[arg-type]
        height_cm=height_cm,
        weight_kg=weight_kg,
        activity_level=activity,  # type: ignore[arg-type]
        goal=goal,  # type: ignore[arg-type]
        dietary_restrictions=restrictions,
        allergies=allergies,
    )


def _parse_days(form) -> int | None:
    raw = (form.get("plan_length") or "").strip()
    return int(raw) if raw.isdigit() else None


def create_app(generate: Generator | None = None) -> Flask:
    app = Flask(__name__)
    gen = generate or _default_generate

    @app.get("/")
    def index():
        return render_template_string(
            _PAGE,
            error=None,
            result=None,
            form={},
            sex_options=_SEX_OPTIONS,
            activity_options=_ACTIVITY_OPTIONS,
            goal_options=_GOAL_OPTIONS,
            length_options=_LENGTH_OPTIONS,
        )

    @app.post("/plan")
    def plan():
        form = request.form
        try:
            profile = profile_from_form(form)
        except IntakeError as exc:
            return (
                render_template_string(
                    _PAGE,
                    error=str(exc),
                    result=None,
                    form=form,
                    sex_options=_SEX_OPTIONS,
                    activity_options=_ACTIVITY_OPTIONS,
                    goal_options=_GOAL_OPTIONS,
                    length_options=_LENGTH_OPTIONS,
                ),
                400,
            )

        days = _parse_days(form)
        raw_plan = gen(profile, days)

        # Normalize daily vs weekly into a common "days" list for the template.
        if days is None:
            day_blocks = [{"day": None, "meals": raw_plan.get("meals", [])}]
            flags = verify_plan(raw_plan)
        else:
            day_blocks = raw_plan.get("days", [])
            flags = verify_weekly_plan(raw_plan)

        macros = profile.target_macros()
        result = {
            "summary": raw_plan.get("summary", ""),
            "notes": raw_plan.get("notes", ""),
            "day_blocks": day_blocks,
            "flags": [str(f) for f in flags],
            "shopping": [str(i) for i in build_shopping_list(raw_plan)],
            "targets": {
                "calories": profile.target_calories(),
                **macros,
            },
        }
        return render_template_string(
            _PAGE,
            error=None,
            result=result,
            form=form,
            sex_options=_SEX_OPTIONS,
            activity_options=_ACTIVITY_OPTIONS,
            goal_options=_GOAL_OPTIONS,
            length_options=_LENGTH_OPTIONS,
        )

    return app


# Single-page template: the form always shows; results render below it when present.
_PAGE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Cacati Invention — Diet Planner</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 760px; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }
    h1 { margin-bottom: 0.25rem; }
    .sub { color: #666; margin-top: 0; }
    form { display: grid; gap: 0.75rem; margin: 1.5rem 0; }
    label { display: grid; gap: 0.25rem; font-weight: 600; font-size: 0.9rem; }
    input, select { padding: 0.5rem; font-size: 1rem; border: 1px solid #ccc; border-radius: 6px; }
    button { padding: 0.6rem 1rem; font-size: 1rem; border: 0; border-radius: 6px; background: #2563eb; color: #fff; cursor: pointer; }
    .row { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem; }
    .error { background: #fee2e2; color: #991b1b; padding: 0.6rem 0.8rem; border-radius: 6px; }
    .card { border: 1px solid #e5e7eb; border-radius: 8px; padding: 1rem; margin: 0.75rem 0; }
    .meal { padding: 0.5rem 0; border-bottom: 1px solid #f0f0f0; }
    .macros { color: #555; font-size: 0.9rem; }
    .flag { color: #92400e; }
    .ok { color: #166534; }
    ul { margin: 0.25rem 0 0; }
    .targets { color: #444; }
  </style>
</head>
<body>
  <h1>Cacati Invention</h1>
  <p class="sub">Personalized diet plans for muscle gain or healthy weight loss.</p>

  {% if error %}<div class="error">⚠ {{ error }}</div>{% endif %}

  <form method="post" action="/plan">
    <div class="row">
      <label>Age
        <input name="age" type="number" min="13" max="120" value="{{ form.get('age', '') }}" required>
      </label>
      <label>Sex
        <select name="sex">
          {% for o in sex_options %}<option value="{{ o }}" {{ 'selected' if form.get('sex')==o else '' }}>{{ o }}</option>{% endfor %}
        </select>
      </label>
    </div>
    <div class="row">
      <label>Height (cm)
        <input name="height_cm" type="text" value="{{ form.get('height_cm', '') }}" required>
      </label>
      <label>Weight (kg)
        <input name="weight_kg" type="text" value="{{ form.get('weight_kg', '') }}" required>
      </label>
    </div>
    <div class="row">
      <label>Activity level
        <select name="activity_level">
          {% for o in activity_options %}<option value="{{ o }}" {{ 'selected' if form.get('activity_level')==o else '' }}>{{ o }}</option>{% endfor %}
        </select>
      </label>
      <label>Goal
        <select name="goal">
          {% for o in goal_options %}<option value="{{ o }}" {{ 'selected' if form.get('goal')==o else '' }}>{{ o }}</option>{% endfor %}
        </select>
      </label>
    </div>
    <label>Dietary restrictions (comma-separated)
      <input name="dietary_restrictions" type="text" value="{{ form.get('dietary_restrictions', '') }}" placeholder="e.g. vegetarian, no nuts">
    </label>
    <label>Allergies (comma-separated)
      <input name="allergies" type="text" value="{{ form.get('allergies', '') }}" placeholder="e.g. shellfish">
    </label>
    <label>Plan length
      <select name="plan_length">
        {% for value, text in length_options %}<option value="{{ value }}" {{ 'selected' if form.get('plan_length')==value else '' }}>{{ text }}</option>{% endfor %}
      </select>
    </label>
    <button type="submit">Generate plan</button>
  </form>

  {% if result %}
    <h2>Your plan</h2>
    <p class="targets">Targets — {{ result.targets.calories }} kcal |
      {{ result.targets.protein_g }}g protein / {{ result.targets.fat_g }}g fat / {{ result.targets.carbs_g }}g carbs</p>
    <p>{{ result.summary }}</p>

    {% for block in result.day_blocks %}
      <div class="card">
        {% if block.day %}<h3>{{ block.day }}</h3>{% endif %}
        {% for meal in block.meals %}
          <div class="meal">
            <strong>{{ meal.name }}</strong> — {{ meal.calories }} kcal<br>
            <span>{{ meal.description }}</span><br>
            <span class="macros">P {{ meal.protein_g }}g / F {{ meal.fat_g }}g / C {{ meal.carbs_g }}g</span>
          </div>
        {% endfor %}
      </div>
    {% endfor %}

    <p>{{ result.notes }}</p>

    {% if result.flags %}
      <div class="card flag">
        <strong>⚠ Nutrition check flagged some meals:</strong>
        <ul>{% for f in result.flags %}<li>{{ f }}</li>{% endfor %}</ul>
      </div>
    {% else %}
      <p class="ok">✓ Nutrition check passed — stated calories match the macros.</p>
    {% endif %}

    {% if result.shopping %}
      <div class="card">
        <strong>🛒 Shopping list</strong>
        <ul>{% for item in result.shopping %}<li>{{ item }}</li>{% endfor %}</ul>
      </div>
    {% endif %}
  {% endif %}
</body>
</html>
"""


if __name__ == "__main__":
    create_app().run(debug=True)
