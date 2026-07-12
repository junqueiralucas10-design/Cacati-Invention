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
  diet_planner.py  # Calls Claude to generate a structured meal plan
  cli.py           # Simple command-line demo
tests/
  test_profile.py  # Unit tests for the math (no API key needed)
```

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

# Generate a plan for the demo profile (needs ANTHROPIC_API_KEY)
python -m src.cli
```

## Status

Early stage — working scaffold. The calorie/macro math and the Claude-backed
plan generator are in place; a real input flow (web or richer CLI) and a food
database are the next steps.

> Not medical advice. Consult a professional for medical conditions.
