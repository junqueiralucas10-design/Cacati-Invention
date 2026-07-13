# Cacati Invention

An AI project focused on generating personalized diet plans for people trying to
build muscle or lose weight in a healthy, sustainable way.

## What it does

Given a user's profile (goal, body stats, activity level, dietary restrictions),
the app estimates daily calorie and macro targets, then uses Claude to generate a
concrete one-day meal plan that hits those targets.

## Project layout

```
src/
  profile.py       # UserProfile + calorie/macro math (Mifflin-St Jeor, TDEE)
  intake.py        # Interactive prompts that build a UserProfile
  diet_planner.py  # Calls Claude to generate a structured meal plan
  nutrition.py     # Food lookup + plan verification (Atwater factors)
  data/foods.json  # Curated per-100g macro reference
  cli.py           # Command-line entry point
tests/             # Unit tests for the math, intake, and nutrition (no API key)
```

The generated plan is verified after generation: each meal's stated calories are
cross-checked against its macros (4/4/9 kcal), so inconsistent numbers get flagged
rather than trusted blindly. The food lookup uses a bundled dataset now, behind a
pluggable interface so a live source (e.g. USDA FoodData Central) can be added later.

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

## Status

Early stage — working scaffold. The calorie/macro math and the Claude-backed
plan generator are in place; a real input flow (web or richer CLI) and a food
database are the next steps.

> Not medical advice. Consult a professional for medical conditions.
