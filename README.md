# Cacati Invention

An AI project focused on generating personalized diet plans for people trying to
build muscle or lose weight in a healthy, sustainable way.

## What it does

Given a user's profile (goal, body stats, activity level, dietary restrictions),
the app estimates daily calorie and macro targets, then builds a concrete meal
plan that hits those targets.

There are two planners behind the same interface:

- **Rule-based builder** (`src/diet_builder.py`) — constructs a personalized diet
  from the bundled food database, respecting the person's goal, dietary
  restrictions, and allergies. The database is built around foods common in
  **Brazil** (arroz, feijão, frango, ovos, tapioca, mandioca, frutas…), and
  restriction terms work in both English and Portuguese (e.g. `vegano`,
  `sem lactose`, `sem glúten`). **No API key required.**
- **AI planner** (`src/diet_planner.py`) — uses Claude for richer, more varied
  plans when an `ANTHROPIC_API_KEY` is configured.

The web UI uses the AI planner when a key is set and falls back to the rule-based
builder otherwise, so submitting the form always returns a plan.

## Project layout

```
src/
  profile.py       # UserProfile + calorie/macro math (Mifflin-St Jeor, TDEE)
  intake.py        # Interactive prompts that build a UserProfile
  diet_builder.py  # Rule-based personalized diet from the food DB (no API key)
  diet_planner.py  # Calls Claude to generate a structured meal plan
  nutrition.py     # Food lookup + plan verification (Atwater factors)
  shopping.py      # Consolidated shopping list from a plan
  data/foods.json  # Curated per-100g macros + group/diet/allergen tags
  webapp.py        # Flask web UI
  cli.py           # Command-line entry point
tests/             # Unit tests (no API key required)
```

The generated plan is verified after generation: each meal's stated calories are
cross-checked against its macros (4/4/9 kcal), so inconsistent numbers get flagged
rather than trusted blindly. The food lookup uses a bundled dataset now, behind a
pluggable interface so a live source (e.g. USDA FoodData Central) can be added later.

Every plan (daily or weekly) also produces a consolidated **shopping list** —
ingredients are aggregated across all meals, combining matching item+unit pairs
and summing quantities (`src/shopping.py`).

It also shows an **estimated grocery cost in R$** (`src/pricing.py`), computed
from the shopping-list quantities and reference Carrefour Brasil prices in
`src/data/prices_brl.json`. Those prices are editable estimates (not a live
feed) — update them to match your local store.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env      # then add your ANTHROPIC_API_KEY
```

Get an API key from https://console.anthropic.com/.

## Run

```bash
# Unit tests (no API key required)
python -m pytest

# Generate a one-day plan interactively (needs ANTHROPIC_API_KEY)
python -m src.cli

# Skip the prompts and use the built-in example profile
python -m src.cli --demo

# Generate a weekly plan (7 days, or pass a number 1-7)
python -m src.cli --week
python -m src.cli --demo --week 5
```

### Web UI

A browser front end offers the same features (the CLI intake still works too):

```bash
python -m src.webapp     # serves http://127.0.0.1:5000
```

Fill in the form, pick a plan length, and the page shows the plan, the nutrition
check, and the shopping list.

To add product screenshots to the landing page, drop image files into
`src/static/screenshots/` — they appear automatically in the "See it in action"
gallery (filename becomes the caption; a numeric prefix controls order). See
`src/static/screenshots/README.md`.

## Status

Early stage — working scaffold. The calorie/macro math and the Claude-backed
plan generator are in place; a real input flow (web or richer CLI) and a food
database are the next steps.

> Not medical advice. Consult a professional for medical conditions.
