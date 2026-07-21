"""A Flask web UI for generating diet plans.

Reuses the same core as the CLI — profile math, planner, nutrition check, and
shopping list. The CLI intake (src/cli.py) is unchanged; this is an alternative
front end, not a replacement.

Run it:
    python -m src.webapp        # serves http://127.0.0.1:5000

The generator is injectable (`create_app(generate=...)`) so routes can be tested
without an API key.
"""

from __future__ import annotations

import os
import re
from typing import Callable

from flask import Flask, Response, redirect, render_template_string, request

from .diet_builder import build_personalized_plan, build_personalized_weekly_plan
from .diet_planner import generate_plan, generate_weekly_plan
from .intake import (
    IntakeError,
    parse_choice,
    parse_int_in_range,
    parse_list,
    parse_positive_float,
)
from .nutrition import verify_plan, verify_weekly_plan
from .pricing import (
    estimate_plan_cost,
    format_brl,
    load_prices,
    prices_from_csv,
    prices_to_csv,
    save_prices,
)
from .profile import UserProfile
from .shopping import build_shopping_list

# Choice data drives both the <select> rendering (label + description) and
# validation. Tuples are (value, label, description); value is the enum string
# the model/profile expects, label + description are what the user sees.
_SEX_CHOICES = [
    ("male", "Male", ""),
    ("female", "Female", ""),
]
_ACTIVITY_CHOICES = [
    ("sedentary", "Sedentary", "Little or no exercise."),
    ("light", "Lightly active", "Light exercise 1–3 days per week."),
    ("moderate", "Moderately active", "Moderate exercise 3–5 days per week."),
    ("active", "Very active", "Hard exercise 6–7 days per week."),
    ("very_active", "Extra active", "Very hard exercise or a physical job."),
]
_GOAL_CHOICES = [
    ("lose_weight", "Lose weight", "A moderate calorie deficit for steady, healthy fat loss (~0.5 kg/week)."),
    ("gain_muscle", "Gain muscle", "A calorie surplus with high protein to support lean muscle growth."),
    ("maintain", "Maintain", "Eat at maintenance to hold your current weight and composition."),
]
_LENGTH_CHOICES = [
    ("", "Single day", "One day to try it out."),
    ("3", "3 days", "A short run to plan ahead."),
    ("5", "5 days", "A work-week of meals."),
    ("7", "Full week", "Seven days, varied so it isn't repetitive."),
]
_MEALS_CHOICES = [
    ("3", "3 meals", "Breakfast, lunch, dinner."),
    ("4", "4 meals", "Three meals plus an afternoon snack."),
    ("5", "5 meals", "Three meals plus a morning and afternoon snack."),
    ("6", "6 meals", "Three meals plus three snacks through the day."),
]

# Validation option lists derive from the choices — single source of truth.
_SEX_OPTIONS = [c[0] for c in _SEX_CHOICES]
_ACTIVITY_OPTIONS = [c[0] for c in _ACTIVITY_CHOICES]
_GOAL_OPTIONS = [c[0] for c in _GOAL_CHOICES]

# A generate callable takes (profile, days|None) and returns a plan dict.
Generator = Callable[[UserProfile, "int | None"], dict]


def _default_generate(profile: UserProfile, days: int | None) -> dict:
    """Use the AI planner when an API key is set; otherwise (or if the API call
    fails) fall back to the rule-based builder so the form always produces a plan.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return generate_plan(profile) if days is None else generate_weekly_plan(profile, days=days)
        except Exception:
            pass  # fall through to the offline builder
    if days is None:
        return build_personalized_plan(profile)
    return build_personalized_weekly_plan(profile, days=days)


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
    meals_raw = (form.get("meals_per_day") or "").strip()
    meals_per_day = int(meals_raw) if meals_raw.isdigit() else None
    return UserProfile(
        age=age,
        sex=sex,  # type: ignore[arg-type]
        height_cm=height_cm,
        weight_kg=weight_kg,
        activity_level=activity,  # type: ignore[arg-type]
        goal=goal,  # type: ignore[arg-type]
        dietary_restrictions=restrictions,
        allergies=allergies,
        meals_per_day=meals_per_day,
    )


def _parse_days(form) -> int | None:
    raw = (form.get("plan_length") or "").strip()
    return int(raw) if raw.isdigit() else None


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}


def _collect_screenshots(static_folder: str | None) -> list[dict]:
    """List image files under <static>/screenshots for the gallery.

    Returns [] when the folder is missing or empty, so the section simply
    doesn't render until the user drops images in. Filenames become alt text
    (dashes/underscores -> spaces); sort order follows the filename, so a
    numeric prefix like "01-form.png" controls placement.
    """
    if not static_folder:
        return []
    folder = os.path.join(static_folder, "screenshots")
    if not os.path.isdir(folder):
        return []
    shots = []
    for fname in sorted(os.listdir(folder)):
        if os.path.splitext(fname)[1].lower() not in _IMAGE_EXTS:
            continue
        stem = os.path.splitext(fname)[0]
        # Drop a leading ordering prefix like "01-" or "02_" from the caption.
        label = re.sub(r"^\d+[-_ ]*", "", stem)
        alt = (label or stem).replace("-", " ").replace("_", " ").strip().title()
        shots.append({"src": f"/static/screenshots/{fname}", "alt": alt})
    return shots


def _context(**overrides) -> dict:
    """Shared template context (choice lists + defaults)."""
    ctx = {
        "error": None,
        "result": None,
        "form": {},
        "screenshots": [],
        "sex_choices": _SEX_CHOICES,
        "activity_choices": _ACTIVITY_CHOICES,
        "goal_choices": _GOAL_CHOICES,
        "length_choices": _LENGTH_CHOICES,
        "meals_choices": _MEALS_CHOICES,
    }
    ctx.update(overrides)
    return ctx


def create_app(generate: Generator | None = None, price_file=None) -> Flask:
    """price_file overrides the prices JSON path (used by tests to avoid
    writing the repo's real data file)."""
    app = Flask(__name__)
    gen = generate or _default_generate

    @app.get("/")
    def index():
        return render_template_string(
            _PAGE, **_context(screenshots=_collect_screenshots(app.static_folder))
        )

    @app.post("/plan")
    def plan():
        form = request.form
        shots = _collect_screenshots(app.static_folder)
        try:
            profile = profile_from_form(form)
        except IntakeError as exc:
            return (
                render_template_string(
                    _PAGE, **_context(error=str(exc), form=form, screenshots=shots)
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

        cost = estimate_plan_cost(raw_plan, prices=load_prices(price_file))
        span = days or 1  # number of days the shopping list covers
        macros = profile.target_macros()
        result = {
            "summary": raw_plan.get("summary", ""),
            "notes": raw_plan.get("notes", ""),
            "day_blocks": day_blocks,
            "flags": [str(f) for f in flags],
            "shopping": [str(i) for i in build_shopping_list(raw_plan)],
            "targets": {"calories": profile.target_calories(), **macros},
            "cost_total": format_brl(cost["total_brl"]),
            "cost_per_day": format_brl(round(cost["total_brl"] / span, 2)),
            "cost_span_days": span,
        }
        return render_template_string(
            _PAGE, **_context(result=result, form=form, screenshots=shots)
        )

    @app.get("/prices")
    def prices_page():
        return render_template_string(
            _PRICES_PAGE,
            prices=sorted(load_prices(price_file).items()),
            saved=False,
            skipped=[],
        )

    @app.post("/prices")
    def prices_save():
        current = load_prices(price_file)
        skipped: list[str] = []
        for name in current:
            raw = (request.form.get(name) or "").strip()
            if not raw:
                continue
            try:
                value = float(raw.replace(",", "."))
            except ValueError:
                skipped.append(f"{name}: '{raw}'")
                continue
            if value > 0:
                current[name] = round(value, 2)
            else:
                skipped.append(f"{name}: '{raw}'")
        save_prices(current, price_file)
        return render_template_string(
            _PRICES_PAGE, prices=sorted(current.items()), saved=True, skipped=skipped
        )

    @app.get("/prices.csv")
    def prices_csv():
        return Response(
            prices_to_csv(load_prices(price_file)),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=prices_brl.csv"},
        )

    @app.post("/prices/import")
    def prices_import():
        file = request.files.get("csv_file")
        if file is None or not file.filename:
            return redirect("/prices")
        text = file.read().decode("utf-8", errors="replace")
        updated, skipped = prices_from_csv(text, load_prices(price_file))
        save_prices(updated, price_file)
        return render_template_string(
            _PRICES_PAGE, prices=sorted(updated.items()), saved=True, skipped=skipped
        )

    return app


_PAGE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>NutriForge — AI meal plans for muscle & fat loss</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <!-- Non-blocking: enhances typography when online, falls back to serif/sans instantly otherwise. -->
  <link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=Manrope:wght@400;500;600;700;800&display=swap" rel="stylesheet" media="print" onload="this.media='all'">
  <noscript><link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=Manrope:wght@400;500;600;700;800&display=swap" rel="stylesheet"></noscript>
  <style>
    :root {
      --bg: #f4f6fb;
      --surface: #ffffff;
      --ink: #0b1437;
      --muted: #5a6480;
      --line: #e6e9f2;
      --brand: #ff6a1a;
      --brand-dark: #e2540e;
      --hero-1: #0a1130;
      --hero-2: #1a2b66;
      --lime: #c6f24e;
      --accent: #ff6a1a;
      --ok: #1c9d5b;
      --shadow: 0 12px 34px rgba(11, 20, 55, 0.10);
      --radius: 16px;
    }
    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body {
      margin: 0; background: var(--bg); color: var(--ink);
      font-family: "Manrope", system-ui, -apple-system, sans-serif;
      line-height: 1.55; -webkit-font-smoothing: antialiased;
    }
    h1, h2, h3 { font-family: "Fraunces", Georgia, serif; line-height: 1.1; letter-spacing: -0.01em; }
    a { color: inherit; }
    .wrap { max-width: 1080px; margin: 0 auto; padding: 0 20px; }

    /* Nav */
    nav {
      position: sticky; top: 0; z-index: 20; backdrop-filter: blur(8px);
      background: rgba(246,248,244,0.85); border-bottom: 1px solid var(--line);
    }
    .nav-inner { display: flex; align-items: center; justify-content: space-between; height: 66px; }
    .brand { display: flex; align-items: center; gap: 10px; font-weight: 800; font-size: 1.15rem; }
    .brand .dot { width: 26px; height: 26px; border-radius: 8px; background: linear-gradient(135deg, var(--brand), var(--hero-2)); display: inline-block; }
    .nav-links { display: flex; gap: 26px; align-items: center; font-weight: 600; font-size: 0.95rem; }
    .nav-links a { text-decoration: none; color: var(--muted); }
    .nav-links a:hover { color: var(--ink); }
    .btn {
      display: inline-block; border: 0; cursor: pointer; text-decoration: none;
      padding: 12px 22px; border-radius: 999px; font: inherit; font-weight: 700;
      background: var(--brand); color: #fff; transition: transform .06s ease, background .2s ease;
    }
    .btn:hover { background: var(--brand-dark); }
    .btn:active { transform: translateY(1px); }
    .btn.ghost { background: transparent; color: var(--ink); border: 1px solid var(--line); }
    .btn.big { padding: 16px 30px; font-size: 1.05rem; }

    /* Hero */
    .hero { background: radial-gradient(120% 120% at 80% 0%, var(--hero-2), var(--hero-1)); color: #e9ecff; padding: 76px 0 90px; }
    .hero .wrap { display: grid; grid-template-columns: 1.1fr 0.9fr; gap: 40px; align-items: center; }
    .eyebrow { display: inline-block; font-weight: 700; font-size: 0.82rem; letter-spacing: 0.08em; text-transform: uppercase; color: var(--lime); margin-bottom: 14px; }
    .hero h1 { font-size: clamp(2.3rem, 5vw, 3.6rem); font-weight: 600; color: #fff; margin: 0 0 16px; }
    .hero p.lead { font-size: 1.15rem; color: #b9c2e6; margin: 0 0 26px; max-width: 30ch; }
    .hero-cta { display: flex; gap: 14px; flex-wrap: wrap; }
    .btn.lime { background: var(--lime); color: #0a1130; }
    .btn.lime:hover { background: #b6e83f; }
    .stats { display: flex; gap: 28px; margin-top: 34px; }
    .stat b { font-family: "Fraunces", serif; font-size: 1.6rem; display: block; color: #fff; }
    .stat span { font-size: 0.85rem; color: #9aa4cf; }
    .hero-card { background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.15); border-radius: 20px; padding: 22px; }
    .hero-card h4 { margin: 0 0 12px; font-family: "Manrope"; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--lime); }
    .hc-row { display: flex; justify-content: space-between; padding: 10px 0; border-bottom: 1px dashed rgba(255,255,255,0.15); color: #e9ecff; }
    .hc-row:last-child { border-bottom: 0; }
    .hc-row span { color: #aab3d9; }

    /* Sections */
    section.pad { padding: 72px 0; }
    .section-head { text-align: center; max-width: 620px; margin: 0 auto 42px; }
    .section-head h2 { font-size: clamp(1.8rem, 3.5vw, 2.5rem); font-weight: 600; margin: 0 0 12px; }
    .section-head p { color: var(--muted); font-size: 1.08rem; margin: 0; }
    .grid3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 22px; }
    .card {
      background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius);
      box-shadow: var(--shadow); overflow: hidden;
    }
    .card-img { width: 100%; height: 190px; object-fit: cover; display: block; }
    .card-body { padding: 24px; }
    .card .ico { font-size: 1.8rem; }
    .card h3 { font-size: 1.25rem; margin: 0 0 8px; }
    .card p { color: var(--muted); margin: 0; }

    .steps { display: grid; grid-template-columns: repeat(3, 1fr); gap: 22px; counter-reset: step; }
    .step { position: relative; padding-left: 8px; }
    .step .n { width: 40px; height: 40px; border-radius: 50%; background: #ffefe2; color: var(--brand-dark); font-weight: 800; display: grid; place-items: center; font-family: "Fraunces", serif; }
    .step h3 { font-size: 1.15rem; margin: 14px 0 6px; }
    .step p { color: var(--muted); margin: 0; }

    /* Planner form */
    .planner { background: linear-gradient(180deg, #eef1f9, var(--bg)); }
    .form-card { background: var(--surface); border: 1px solid var(--line); border-radius: 22px; box-shadow: var(--shadow); padding: 34px; max-width: 720px; margin: 0 auto; }
    form { display: grid; gap: 18px; }
    .row { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
    label { display: grid; gap: 6px; font-weight: 700; font-size: 0.92rem; }
    input, select { padding: 12px 14px; font: inherit; border: 1px solid #d7ded4; border-radius: 12px; background: #fcfdfb; }
    input:focus, select:focus { outline: 2px solid rgba(255,106,26,0.35); border-color: var(--brand); }
    .hint { font-weight: 500; font-size: 0.85rem; color: var(--muted); min-height: 1.1em; }
    .error { background: #fdecec; color: #a12626; border: 1px solid #f6cccc; padding: 12px 14px; border-radius: 12px; font-weight: 600; }
    button[type=submit] { justify-self: start; }

    /* Results */
    .result-wrap { max-width: 760px; margin: 34px auto 0; }
    .targets-pill { display: inline-flex; gap: 10px; flex-wrap: wrap; background: #ffefe2; color: var(--brand-dark); border-radius: 999px; padding: 10px 18px; font-weight: 700; }
    .day-card { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 20px; margin: 16px 0; box-shadow: var(--shadow); }
    .day-card h3 { margin: 0 0 10px; }
    .meal { padding: 12px 0; border-bottom: 1px solid #f0f3ee; }
    .meal:last-child { border-bottom: 0; }
    .meal .macros { color: var(--muted); font-size: 0.9rem; }
    .pass { color: var(--ok); font-weight: 700; }
    .flagbox { background: #fff6ec; border: 1px solid #f6dcbf; border-radius: 12px; padding: 14px 16px; color: #8a5a1c; }
    .shop { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 20px; box-shadow: var(--shadow); }
    .shop ul, .flagbox ul { margin: 8px 0 0; padding-left: 20px; }
    .shop li, .flagbox li { margin: 3px 0; }
    .cost { background: #fff6ef; border: 1px solid #f6dcbf; border-radius: var(--radius); padding: 18px 20px; margin: 16px 0; text-align: center; }
    .cost-amount { font-family: "Fraunces", Georgia, serif; font-size: 2rem; font-weight: 600; color: var(--brand-dark); }
    .cost-sub { color: var(--muted); font-size: 0.9rem; margin-top: 4px; }

    /* Testimonial */
    .quote { text-align: center; max-width: 720px; margin: 0 auto; }
    .quote p { font-family: "Fraunces", serif; font-size: 1.5rem; font-weight: 500; line-height: 1.35; }
    .quote .who { color: var(--muted); font-family: "Manrope"; font-size: 0.95rem; font-weight: 600; }

    /* Footer */
    footer { background: var(--hero-1); color: #aab3d9; padding: 40px 0; margin-top: 20px; }
    footer .wrap { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 16px; align-items: center; }
    footer .disclaimer { font-size: 0.85rem; max-width: 46ch; }

    /* Screenshot gallery */
    .shots { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 22px; }
    .shot { margin: 0; }
    .shot img { width: 100%; height: auto; display: block; border-radius: 14px; border: 1px solid var(--line); box-shadow: var(--shadow); background: var(--surface); }
    .shot figcaption { margin-top: 10px; text-align: center; color: var(--muted); font-weight: 600; font-size: 0.92rem; }

    @media (max-width: 820px) {
      .hero .wrap { grid-template-columns: 1fr; }
      .grid3, .steps { grid-template-columns: 1fr; }
      .row { grid-template-columns: 1fr; }
      .nav-links { display: none; }
    }
  </style>
</head>
<body>
  <nav>
    <div class="wrap nav-inner">
      <div class="brand"><span class="dot"></span> NutriForge</div>
      <div class="nav-links">
        <a href="#features">Features</a>
        <a href="#how">How it works</a>
        {% if screenshots %}<a href="#screens">Screens</a>{% endif %}
        <a href="#pricing">Pricing</a>
        <a class="btn" href="#plan">Get your plan</a>
      </div>
    </div>
  </nav>

  <header class="hero">
    <div class="wrap">
      <div>
        <span class="eyebrow">AI-powered nutrition</span>
        <h1>Eat for your goal, without the guesswork.</h1>
        <p class="lead">Personalized meal plans that hit your exact calorie and macro targets — for building muscle or losing weight, the healthy way.</p>
        <div class="hero-cta">
          <a class="btn lime big" href="#plan">Build my plan — free</a>
          <a class="btn ghost big" href="#how" style="color:#e9ecff;border-color:rgba(255,255,255,0.3)">See how it works</a>
        </div>
        <div class="stats">
          <div class="stat"><b>3&nbsp;sec</b><span>to a full plan</span></div>
          <div class="stat"><b>100%</b><span>macro-matched</span></div>
          <div class="stat"><b>0</b><span>spreadsheets</span></div>
        </div>
      </div>
      <div class="hero-card">
        <h4>Sample daily target</h4>
        <div class="hc-row">Calories <span>2,600 kcal</span></div>
        <div class="hc-row">Protein <span>164 g</span></div>
        <div class="hc-row">Carbs <span>300 g</span></div>
        <div class="hc-row">Fat <span>72 g</span></div>
        <div class="hc-row">Shopping list <span>✓ included</span></div>
      </div>
    </div>
  </header>

  <section class="pad" id="features">
    <div class="wrap">
      <div class="section-head">
        <h2>Everything you need to eat with intent</h2>
        <p>Not just a menu — a plan grounded in real numbers, checked for accuracy, and ready to shop.</p>
      </div>
      <div class="grid3">
        <div class="card">
          <img class="card-img" src="/static/images/meals-spread.jpg" alt="Assorted healthy meals on a table" loading="lazy">
          <div class="card-body"><h3>🎯 Dialed-in targets</h3><p>We compute your calories and macros from your body stats, activity, and goal — then build meals to match.</p></div>
        </div>
        <div class="card">
          <img class="card-img" src="/static/images/poke-bowl.jpg" alt="Colorful poke bowl with vegetables" loading="lazy">
          <div class="card-body"><h3>✅ Verified numbers</h3><p>Every meal's calories are cross-checked against its macros, so the plan's math actually adds up.</p></div>
        </div>
        <div class="card">
          <img class="card-img" src="/static/images/meal-prep.jpg" alt="Meal-prep containers with grilled chicken" loading="lazy">
          <div class="card-body"><h3>🛒 Auto shopping list</h3><p>Ingredients from every meal are combined into one tidy list — ready for your next grocery run.</p></div>
        </div>
      </div>
    </div>
  </section>

  <section class="pad" id="how" style="background:#eef1f9">
    <div class="wrap">
      <div class="section-head"><h2>Three steps to your plan</h2><p>From your details to a full day (or week) of meals in seconds.</p></div>
      <div class="steps">
        <div class="step"><div class="n">1</div><h3>Tell us about you</h3><p>Age, body stats, activity, and whether you're cutting, bulking, or maintaining.</p></div>
        <div class="step"><div class="n">2</div><h3>We do the math</h3><p>Your targets are calculated and meals are generated to land right on them.</p></div>
        <div class="step"><div class="n">3</div><h3>Eat & shop</h3><p>Get your meals, a nutrition check, and a combined shopping list.</p></div>
      </div>
    </div>
  </section>

  {% if screenshots %}
  <section class="pad" id="screens">
    <div class="wrap">
      <div class="section-head">
        <h2>See it in action</h2>
        <p>Real plans, real numbers — straight from the app.</p>
      </div>
      <div class="shots">
        {% for s in screenshots %}
          <figure class="shot">
            <img src="{{ s.src }}" alt="{{ s.alt }}" loading="lazy">
            <figcaption>{{ s.alt }}</figcaption>
          </figure>
        {% endfor %}
      </div>
    </div>
  </section>
  {% endif %}

  <!-- The planner -->
  <section class="pad planner" id="plan">
    <div class="wrap">
      <div class="section-head">
        <h2>Build your plan</h2>
        <p>Free, no sign-up. Fill in your details and pick a plan length.</p>
      </div>

      <div class="form-card">
        {% if error %}<div class="error">⚠ {{ error }}</div>{% endif %}
        <form method="post" action="/plan">
          <div class="row">
            <label>Age
              <input name="age" type="number" min="13" max="120" value="{{ form.get('age', '') }}" required>
            </label>
            <label>Sex
              <select name="sex">
                {% for value, lbl, desc in sex_choices %}<option value="{{ value }}" {{ 'selected' if form.get('sex')==value else '' }}>{{ lbl }}</option>{% endfor %}
              </select>
            </label>
          </div>
          <div class="row">
            <label>Height (cm)
              <input name="height_cm" type="text" inputmode="decimal" value="{{ form.get('height_cm', '') }}" placeholder="e.g. 178" required>
            </label>
            <label>Weight (kg)
              <input name="weight_kg" type="text" inputmode="decimal" value="{{ form.get('weight_kg', '') }}" placeholder="e.g. 82" required>
            </label>
          </div>
          <label>Activity level
            <select name="activity_level" data-hint="activity-hint">
              {% for value, lbl, desc in activity_choices %}<option value="{{ value }}" data-desc="{{ desc }}" {{ 'selected' if form.get('activity_level')==value else '' }}>{{ lbl }} — {{ desc }}</option>{% endfor %}
            </select>
            <span class="hint" id="activity-hint"></span>
          </label>
          <label>Goal
            <select name="goal" data-hint="goal-hint">
              {% for value, lbl, desc in goal_choices %}<option value="{{ value }}" data-desc="{{ desc }}" {{ 'selected' if form.get('goal')==value else '' }}>{{ lbl }} — {{ desc }}</option>{% endfor %}
            </select>
            <span class="hint" id="goal-hint"></span>
          </label>
          <label>Dietary restrictions <span style="font-weight:500;color:var(--muted)">(comma-separated, optional)</span>
            <input name="dietary_restrictions" type="text" value="{{ form.get('dietary_restrictions', '') }}" placeholder="e.g. vegetarian, no nuts">
          </label>
          <label>Allergies <span style="font-weight:500;color:var(--muted)">(comma-separated, optional)</span>
            <input name="allergies" type="text" value="{{ form.get('allergies', '') }}" placeholder="e.g. shellfish">
          </label>
          <div class="row">
            <label>Meals per day
              <select name="meals_per_day" data-hint="meals-hint">
                {% for value, lbl, desc in meals_choices %}<option value="{{ value }}" data-desc="{{ desc }}" {{ 'selected' if (form.get('meals_per_day')==value or (not form.get('meals_per_day') and value=='4')) else '' }}>{{ lbl }}</option>{% endfor %}
              </select>
              <span class="hint" id="meals-hint"></span>
            </label>
            <label>Plan length
              <select name="plan_length" data-hint="length-hint">
                {% for value, lbl, desc in length_choices %}<option value="{{ value }}" data-desc="{{ desc }}" {{ 'selected' if form.get('plan_length')==value else '' }}>{{ lbl }} — {{ desc }}</option>{% endfor %}
              </select>
              <span class="hint" id="length-hint"></span>
            </label>
          </div>
          <button class="btn big" type="submit">Generate my plan</button>
        </form>
      </div>

      {% if result %}
        <div class="result-wrap">
          <h2 style="text-align:center">Your plan</h2>
          <div style="text-align:center;margin-bottom:16px">
            <span class="targets-pill">
              <span>{{ result.targets.calories }} kcal</span>·
              <span>{{ result.targets.protein_g }}g protein</span>·
              <span>{{ result.targets.fat_g }}g fat</span>·
              <span>{{ result.targets.carbs_g }}g carbs</span>
            </span>
          </div>
          <p style="text-align:center;color:var(--muted)">{{ result.summary }}</p>

          {% for block in result.day_blocks %}
            <div class="day-card">
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

          <p style="color:var(--muted)">{{ result.notes }}</p>

          {% if result.flags %}
            <div class="flagbox"><strong>⚠ Nutrition check flagged some meals:</strong>
              <ul>{% for f in result.flags %}<li>{{ f }}</li>{% endfor %}</ul>
            </div>
          {% else %}
            <p class="pass">✓ Nutrition check passed — stated calories match the macros.</p>
          {% endif %}

          {% if result.shopping %}
            <div class="shop"><strong>🛒 Shopping list</strong>
              <ul>{% for item in result.shopping %}<li>{{ item }}</li>{% endfor %}</ul>
            </div>
          {% endif %}

          <div class="cost">
            <div class="cost-amount">{{ result.cost_total }}</div>
            <div class="cost-sub">
              {% if result.cost_span_days > 1 %}for {{ result.cost_span_days }} days · ~{{ result.cost_per_day }}/day · {% endif %}
              estimated grocery cost — reference Carrefour Brasil prices, varies by region
              · <a href="/prices">edit prices</a>
            </div>
          </div>
        </div>
      {% endif %}
    </div>
  </section>

  <section class="pad" id="pricing">
    <div class="wrap quote">
      <p>“I stopped guessing my macros. NutriForge gave me a full week of meals and a shopping list in seconds — and I finally hit my protein every day.”</p>
      <div class="who">— Sample testimonial · early user</div>
    </div>
  </section>

  <footer>
    <div class="wrap">
      <div class="brand" style="color:#fff"><span class="dot"></span> NutriForge</div>
      <div class="disclaimer">Not medical advice. Plans are informational estimates — consult a professional for medical conditions.<br>Food photography via Pexels (free license).</div>
    </div>
  </footer>

  <script>
    // Reflect the selected option's description into the hint line below each select.
    function wireHint(select) {
      var id = select.getAttribute('data-hint');
      if (!id) return;
      var out = document.getElementById(id);
      function update() {
        var opt = select.options[select.selectedIndex];
        out.textContent = opt ? (opt.getAttribute('data-desc') || '') : '';
      }
      select.addEventListener('change', update);
      update();
    }
    document.querySelectorAll('select[data-hint]').forEach(wireHint);
  </script>
</body>
</html>
"""


_PRICES_PAGE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>NutriForge — Price settings</title>
  <style>
    :root { --bg:#f4f6fb; --surface:#fff; --ink:#0b1437; --muted:#5a6480; --line:#e6e9f2;
            --brand:#ff6a1a; --brand-dark:#e2540e; }
    * { box-sizing: border-box; }
    body { margin:0; background:var(--bg); color:var(--ink);
           font-family:"Manrope",system-ui,sans-serif; line-height:1.5; }
    .wrap { max-width:820px; margin:0 auto; padding:32px 20px 60px; }
    h1 { font-family:Georgia,serif; margin:0 0 6px; }
    .sub { color:var(--muted); margin:0 0 22px; }
    a.back { color:var(--brand-dark); font-weight:700; text-decoration:none; }
    .bar { display:flex; gap:12px; flex-wrap:wrap; align-items:center; margin:18px 0; }
    .btn { display:inline-block; border:0; cursor:pointer; text-decoration:none;
           padding:10px 18px; border-radius:999px; font:inherit; font-weight:700;
           background:var(--brand); color:#fff; }
    .btn.ghost { background:transparent; color:var(--ink); border:1px solid var(--line); }
    .ok { background:#e6f6ec; color:#166534; border:1px solid #bfe6cd;
          padding:10px 14px; border-radius:10px; font-weight:600; margin:12px 0; }
    .warn { background:#fff6ec; color:#8a5a1c; border:1px solid #f6dcbf;
            padding:10px 14px; border-radius:10px; margin:12px 0; font-size:0.92rem; }
    table { width:100%; border-collapse:collapse; background:var(--surface);
            border:1px solid var(--line); border-radius:12px; overflow:hidden; }
    th, td { text-align:left; padding:10px 14px; border-bottom:1px solid var(--line); }
    th { background:#eef1f9; font-size:0.85rem; text-transform:uppercase;
         letter-spacing:0.04em; color:var(--muted); }
    tr:last-child td { border-bottom:0; }
    input[type=text] { width:110px; padding:7px 10px; font:inherit;
                       border:1px solid #d7ded4; border-radius:8px; text-align:right; }
    .note { color:var(--muted); font-size:0.88rem; margin-top:16px; }
  </style>
</head>
<body>
  <div class="wrap">
    <a class="back" href="/">&larr; Back to the planner</a>
    <h1>Price settings</h1>
    <p class="sub">Reference grocery prices in <strong>R$ per kg</strong>, used for the plan cost estimate.
       Edit inline, or export/import a CSV to update them in a spreadsheet.</p>

    {% if saved %}<div class="ok">✓ Prices saved.</div>{% endif %}
    {% if skipped %}
      <div class="warn"><strong>Skipped (not saved):</strong>
        {% for s in skipped %}<div>{{ s }}</div>{% endfor %}
      </div>
    {% endif %}

    <div class="bar">
      <a class="btn ghost" href="/prices.csv">⬇ Export CSV</a>
      <form method="post" action="/prices/import" enctype="multipart/form-data" style="display:flex;gap:8px;align-items:center">
        <input type="file" name="csv_file" accept=".csv,text/csv" required>
        <button class="btn ghost" type="submit">⬆ Import CSV</button>
      </form>
    </div>

    <form method="post" action="/prices">
      <table>
        <tr><th>Food</th><th style="text-align:right">R$ / kg</th></tr>
        {% for name, price in prices %}
          <tr>
            <td>{{ name }}</td>
            <td style="text-align:right">
              <input type="text" inputmode="decimal" name="{{ name }}" value="{{ '%.2f' % price }}">
            </td>
          </tr>
        {% endfor %}
      </table>
      <div class="bar"><button class="btn" type="submit">Save prices</button></div>
    </form>

    <p class="note">Values are reference estimates (originally based on Carrefour Brasil) — update them to
       match your local store. Blank fields keep the current price; invalid or non-positive values are skipped.</p>
  </div>
</body>
</html>
"""


if __name__ == "__main__":
    create_app().run(debug=True)
