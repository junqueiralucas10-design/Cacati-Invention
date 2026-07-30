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

Both planners **write the plan in Brazilian Portuguese** — meal names
("Café da manhã", "Almoço"), descriptions, weekday names, the summary and the
nutrition-check messages. The food-database tags (`breakfast`, `lunch`, `dinner`,
`snack`) stay in English because they're data keys in `foods.json`, not display
text; `_meal_slots` keeps the label and the tag separate so one can change
without affecting which foods are eligible for a meal. Restriction terms are
still accepted in both languages on the way in.

The Flask UI, the CLI and the interactive intake are all in Portuguese too —
labels, hints, validation errors and the mockups in the gallery. The one page
still in English is the price-settings screen (`/prices`).

Both AI-backed modules read `MODEL` from `src/__init__.py`, so the diet planner
and the promo generator can't drift onto different Claude models.

## Brand positioning

`src/brand.py` holds the product's voice, and it is the single source for it —
both the landing page and the social copy generator read from there, so the page
and the posts can't end up saying different things.

> **A mudança não vem de fora pra dentro, mas de dentro pra fora.**

That line is the spine of the whole thing, and it does real work beyond sounding
good: the app is a **tool, not a transformation**. It hands over the numbers, the
meals, the list and the cost — the outside part. The change is the user's. Which
is also what keeps the marketing honest for an app that builds meal plans and
promises nothing about results.

`MANIFESTO` expands the idea, `QUOTES` illustrates it, and `VOICE` is handed to
the copywriter model so every post inherits the same positioning.

### About the sports quotes

`brand.QUOTES` reads like champions talking, and the landing page says plainly
that it isn't:

> Retratos de arquétipos do esporte, escritos para ilustrar a ideia — não são
> citações de atletas reais.

**Those lines are original copy, attributed to archetypes ("Uma velocista, sobre
o pódio olímpico") rather than to people.** They are deliberately not quotations
from real medalists — inventing a quote and signing a real athlete's name to it
puts words in their mouth, and naming real champions on a commercial page reads
as an endorsement they never gave.

To ship real quotes, replace the entries with ones you have verified against a
primary source and have permission to use commercially. Nothing else changes —
the rendering, the prompt and the tests all work off the same data. Two tests
guard the current state: one fails if the disclosure note disappears from the
page, another fails if an attribution stops looking like an archetype.

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
  promo.py         # Social-media copy, generated from a real plan
  social.py        # Publishing adapters (Instagram / X / LinkedIn)
  promo_cli.py     # Generate and optionally publish the promo posts
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

## Social media promotion

`src/promo.py` writes the promo copy — Instagram, TikTok, X and LinkedIn, in
Brazilian Portuguese — and `src/social.py` publishes it.

The copy is **grounded in real app output**: `campaign_facts()` runs the
rule-based builder on a persona and feeds the prompt the actual numbers (calorie
and macro targets, the meals, the R$ grocery estimate), and the system prompt
forbids inventing features, results, or health promises. Posts are verified after
generation the same way plans are — anything over a platform's character limit is
flagged instead of being shipped.

```bash
# Generate and print everything. Nothing is published.
python -m src.promo_cli

# One platform, with your own link in the captions
python -m src.promo_cli --platform linkedin --url https://meusite.com

# Publish for real — asks for typed confirmation per post
python -m src.promo_cli --platform x --publish
python -m src.promo_cli --platform instagram --publish --image-url https://.../post.jpg
```

Publishing is a dry run by default: `publish()` records the requests it *would*
send unless you pass `dry_run=False`. Credentials come from environment
variables (see `.env.example`) and are sent in the body or an `Authorization`
header, never in the query string. HTTP uses `urllib` from the standard library —
no new dependency for three POST requests.

Two limits worth knowing before you wire up an account:

- **Instagram has no text-only post.** The Graph API always needs media, so
  `--image-url` is required and the URL must be publicly reachable by Meta.
- **TikTok posting stays manual.** Its Content Posting API needs an approved app
  and a video upload, so the CLI generates TikTok copy but won't post it.

## Status

Early stage — working scaffold. The calorie/macro math and the Claude-backed
plan generator are in place; a real input flow (web or richer CLI) and a food
database are the next steps.

> Not medical advice. Consult a professional for medical conditions.
