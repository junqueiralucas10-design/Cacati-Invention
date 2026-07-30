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
from . import brand
from .profile import UserProfile
from .shopping import build_shopping_list

# Choice data drives both the <select> rendering (label + description) and
# validation. Tuples are (value, label, description); value is the enum string
# the model/profile expects, label + description are what the user sees.
_SEX_CHOICES = [
    ("male", "Masculino", ""),
    ("female", "Feminino", ""),
]
_ACTIVITY_CHOICES = [
    ("sedentary", "Sedentário", "Pouco ou nenhum exercício."),
    ("light", "Levemente ativo", "Exercício leve, 1 a 3 dias por semana."),
    ("moderate", "Moderadamente ativo", "Exercício moderado, 3 a 5 dias por semana."),
    ("active", "Muito ativo", "Exercício pesado, 6 a 7 dias por semana."),
    ("very_active", "Extremamente ativo", "Exercício muito pesado ou trabalho físico."),
]
_GOAL_CHOICES = [
    ("lose_weight", "Perder peso", "Déficit calórico moderado para perda de gordura constante e saudável (~0,5 kg/semana)."),
    ("gain_muscle", "Ganhar massa", "Superávit calórico com proteína alta para sustentar ganho de massa magra."),
    ("maintain", "Manter", "Comer na manutenção para segurar o peso e a composição atuais."),
]
_LENGTH_CHOICES = [
    ("", "Um dia", "Um dia para experimentar."),
    ("3", "3 dias", "Um período curto para se antecipar."),
    ("5", "5 dias", "Uma semana útil de refeições."),
    ("7", "Semana inteira", "Sete dias, variados para não ficar repetitivo."),
]
_MEALS_CHOICES = [
    ("3", "3 refeições", "Café da manhã, almoço e jantar."),
    ("4", "4 refeições", "As três principais mais um lanche da tarde."),
    ("5", "5 refeições", "As três principais mais lanches da manhã e da tarde."),
    ("6", "6 refeições", "As três principais mais três lanches ao longo do dia."),
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

    Only the first word is capitalized — title-casing every word is wrong in
    Portuguese ("Seu Plano Do Dia" instead of "Seu plano do dia").
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
        words = (label or stem).replace("-", " ").replace("_", " ").strip()
        alt = words[:1].upper() + words[1:]
        shots.append({"src": f"/static/screenshots/{fname}", "alt": alt})
    return shots


def _context(**overrides) -> dict:
    """Shared template context (choice lists + defaults)."""
    ctx = {
        "error": None,
        "result": None,
        "form": {},
        "screenshots": [],
        "brand": brand,
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
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ brand.NAME }} — dieta personalizada para ganhar massa ou perder peso</title>
  <meta name="description" content="{{ brand.POSITIONING }} Plano alimentar que bate suas metas de calorias e macros, com lista de compras e custo estimado em R$.">
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
    .manifesto { max-width: 700px; margin: 0 auto 44px; }
    .manifesto p { font-family: "Fraunces", serif; font-size: 1.22rem; line-height: 1.5; margin: 0 0 18px; }
    .manifesto p:first-child { font-size: 1.45rem; font-weight: 600; }
    .manifesto p:last-child { color: var(--brand-dark); font-weight: 600; margin-bottom: 0; }
    .quotes { display: grid; grid-template-columns: repeat(2, 1fr); gap: 20px; }
    .qcard { margin: 0; background: var(--surface); border: 1px solid var(--line);
             border-left: 4px solid var(--brand); border-radius: 14px; padding: 22px 24px; }
    .qcard blockquote { margin: 0 0 12px; font-family: "Fraunces", serif; font-size: 1.05rem;
                        line-height: 1.45; }
    .qcard figcaption { color: var(--muted); font-size: 0.9rem; font-weight: 600; }
    .quotes-note { text-align: center; color: var(--muted); font-size: 0.85rem; margin: 22px 0 0; }

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
      .grid3, .steps, .quotes { grid-template-columns: 1fr; }
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
        <a href="#manifesto">Manifesto</a>
        <a href="#features">Recursos</a>
        <a href="#how">Como funciona</a>
        {% if screenshots %}<a href="#screens">Telas</a>{% endif %}
        <a class="btn" href="#plan">Montar meu plano</a>
      </div>
    </div>
  </nav>

  <header class="hero">
    <div class="wrap">
      <div>
        <span class="eyebrow">Nutrição com inteligência artificial</span>
        <h1>{{ brand.POSITIONING }}</h1>
        <p class="lead">{{ brand.LEAD }}</p>
        <div class="hero-cta">
          <a class="btn lime big" href="#plan">Montar meu plano — grátis</a>
          <a class="btn ghost big" href="#manifesto" style="color:#e9ecff;border-color:rgba(255,255,255,0.3)">O que a gente acredita</a>
        </div>
        <div class="stats">
          <div class="stat"><b>3&nbsp;seg</b><span>para o plano pronto</span></div>
          <div class="stat"><b>100%</b><span>ajustado aos macros</span></div>
          <div class="stat"><b>0</b><span>planilhas</span></div>
        </div>
      </div>
      <div class="hero-card">
        <h4>Exemplo de meta diária</h4>
        <div class="hc-row">Calorias <span>2.600 kcal</span></div>
        <div class="hc-row">Proteína <span>164 g</span></div>
        <div class="hc-row">Carboidrato <span>300 g</span></div>
        <div class="hc-row">Gordura <span>72 g</span></div>
        <div class="hc-row">Lista de compras <span>✓ incluída</span></div>
      </div>
    </div>
  </header>

  <section class="pad" id="manifesto">
    <div class="wrap">
      <div class="section-head">
        <h2>De dentro pra fora</h2>
        <p>{{ brand.TAGLINE }}</p>
      </div>
      <div class="manifesto">
        {% for line in brand.MANIFESTO %}<p>{{ line }}</p>{% endfor %}
      </div>
      <div class="quotes">
        {% for q in brand.QUOTES %}
          <figure class="qcard">
            <blockquote>{{ q.text }}</blockquote>
            <figcaption>{{ q.attribution }}</figcaption>
          </figure>
        {% endfor %}
      </div>
      <p class="quotes-note">
        Retratos de arquétipos do esporte, escritos para ilustrar a ideia — não são
        citações de atletas reais.
      </p>
    </div>
  </section>

  <section class="pad" id="features">
    <div class="wrap">
      <div class="section-head">
        <h2>A parte de fora, resolvida</h2>
        <p>Não é um menu — é um plano com números reais, conferidos, e pronto para o mercado.</p>
      </div>
      <div class="grid3">
        <div class="card">
          <img class="card-img" src="/static/images/meals-spread.jpg" alt="Refeições saudáveis variadas sobre a mesa" loading="lazy">
          <div class="card-body"><h3>🎯 Metas no ponto</h3><p>Calculamos suas calorias e macros a partir do seu corpo, da sua rotina e do seu objetivo — e montamos as refeições em cima disso.</p></div>
        </div>
        <div class="card">
          <img class="card-img" src="/static/images/poke-bowl.jpg" alt="Poke bowl colorido com legumes" loading="lazy">
          <div class="card-body"><h3>✅ Números conferidos</h3><p>As calorias de cada refeição são checadas contra os macros, então a conta do plano realmente fecha.</p></div>
        </div>
        <div class="card">
          <img class="card-img" src="/static/images/meal-prep.jpg" alt="Potes de marmita com frango grelhado" loading="lazy">
          <div class="card-body"><h3>🛒 Lista de compras automática</h3><p>Os ingredientes de todas as refeições viram uma lista só — pronta para a próxima ida ao mercado.</p></div>
        </div>
      </div>
    </div>
  </section>

  <section class="pad" id="how" style="background:#eef1f9">
    <div class="wrap">
      <div class="section-head"><h2>Três passos até o seu plano</h2><p>Dos seus dados a um dia (ou uma semana) de refeições em segundos.</p></div>
      <div class="steps">
        <div class="step"><div class="n">1</div><h3>Conte sobre você</h3><p>Idade, medidas, rotina de atividade e se o objetivo é secar, ganhar massa ou manter.</p></div>
        <div class="step"><div class="n">2</div><h3>A gente faz a conta</h3><p>Suas metas são calculadas e as refeições montadas para cair exatamente nelas.</p></div>
        <div class="step"><div class="n">3</div><h3>Você faz acontecer</h3><p>Receba as refeições, a conferência e a lista de compras. O resto é você.</p></div>
      </div>
    </div>
  </section>

  {% if screenshots %}
  <section class="pad" id="screens">
    <div class="wrap">
      <div class="section-head">
        <h2>Veja funcionando</h2>
        <p>Planos reais, números reais — direto do app.</p>
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
        <h2>Monte seu plano</h2>
        <p>Grátis, sem cadastro. Preencha seus dados e escolha a duração.</p>
      </div>

      <div class="form-card">
        {% if error %}<div class="error">⚠ {{ error }}</div>{% endif %}
        <form method="post" action="/plan">
          <div class="row">
            <label>Idade
              <input name="age" type="number" min="13" max="120" value="{{ form.get('age', '') }}" required>
            </label>
            <label>Sexo
              <select name="sex">
                {% for value, lbl, desc in sex_choices %}<option value="{{ value }}" {{ 'selected' if form.get('sex')==value else '' }}>{{ lbl }}</option>{% endfor %}
              </select>
            </label>
          </div>
          <div class="row">
            <label>Altura (cm)
              <input name="height_cm" type="text" inputmode="decimal" value="{{ form.get('height_cm', '') }}" placeholder="ex.: 178" required>
            </label>
            <label>Peso (kg)
              <input name="weight_kg" type="text" inputmode="decimal" value="{{ form.get('weight_kg', '') }}" placeholder="ex.: 82" required>
            </label>
          </div>
          <label>Nível de atividade
            <select name="activity_level" data-hint="activity-hint">
              {% for value, lbl, desc in activity_choices %}<option value="{{ value }}" data-desc="{{ desc }}" {{ 'selected' if form.get('activity_level')==value else '' }}>{{ lbl }} — {{ desc }}</option>{% endfor %}
            </select>
            <span class="hint" id="activity-hint"></span>
          </label>
          <label>Objetivo
            <select name="goal" data-hint="goal-hint">
              {% for value, lbl, desc in goal_choices %}<option value="{{ value }}" data-desc="{{ desc }}" {{ 'selected' if form.get('goal')==value else '' }}>{{ lbl }} — {{ desc }}</option>{% endfor %}
            </select>
            <span class="hint" id="goal-hint"></span>
          </label>
          <label>Restrições alimentares <span style="font-weight:500;color:var(--muted)">(separadas por vírgula, opcional)</span>
            <input name="dietary_restrictions" type="text" value="{{ form.get('dietary_restrictions', '') }}" placeholder="ex.: vegetariano, sem lactose">
          </label>
          <label>Alergias <span style="font-weight:500;color:var(--muted)">(separadas por vírgula, opcional)</span>
            <input name="allergies" type="text" value="{{ form.get('allergies', '') }}" placeholder="ex.: frutos do mar">
          </label>
          <div class="row">
            <label>Refeições por dia
              <select name="meals_per_day" data-hint="meals-hint">
                {% for value, lbl, desc in meals_choices %}<option value="{{ value }}" data-desc="{{ desc }}" {{ 'selected' if (form.get('meals_per_day')==value or (not form.get('meals_per_day') and value=='4')) else '' }}>{{ lbl }}</option>{% endfor %}
              </select>
              <span class="hint" id="meals-hint"></span>
            </label>
            <label>Duração do plano
              <select name="plan_length" data-hint="length-hint">
                {% for value, lbl, desc in length_choices %}<option value="{{ value }}" data-desc="{{ desc }}" {{ 'selected' if form.get('plan_length')==value else '' }}>{{ lbl }} — {{ desc }}</option>{% endfor %}
              </select>
              <span class="hint" id="length-hint"></span>
            </label>
          </div>
          <button class="btn big" type="submit">Gerar meu plano</button>
        </form>
      </div>

      {% if result %}
        <div class="result-wrap">
          <h2 style="text-align:center">Seu plano</h2>
          <div style="text-align:center;margin-bottom:16px">
            <span class="targets-pill">
              <span>{{ result.targets.calories }} kcal</span>·
              <span>{{ result.targets.protein_g }}g de proteína</span>·
              <span>{{ result.targets.fat_g }}g de gordura</span>·
              <span>{{ result.targets.carbs_g }}g de carboidrato</span>
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
                  <span class="macros">P {{ meal.protein_g }}g / G {{ meal.fat_g }}g / C {{ meal.carbs_g }}g</span>
                </div>
              {% endfor %}
            </div>
          {% endfor %}

          <p style="color:var(--muted)">{{ result.notes }}</p>

          {% if result.flags %}
            <div class="flagbox"><strong>⚠ A conferência nutricional sinalizou refeições:</strong>
              <ul>{% for f in result.flags %}<li>{{ f }}</li>{% endfor %}</ul>
            </div>
          {% else %}
            <p class="pass">✓ Conferência nutricional ok — as calorias batem com os macros.</p>
          {% endif %}

          {% if result.shopping %}
            <div class="shop"><strong>🛒 Lista de compras</strong>
              <ul>{% for item in result.shopping %}<li>{{ item }}</li>{% endfor %}</ul>
            </div>
          {% endif %}

          <div class="cost">
            <div class="cost-amount">{{ result.cost_total }}</div>
            <div class="cost-sub">
              {% if result.cost_span_days > 1 %}para {{ result.cost_span_days }} dias · ~{{ result.cost_per_day }}/dia · {% endif %}
              custo estimado do mercado — preços de referência do Carrefour Brasil, varia por região
              · <a href="/prices">editar preços</a>
            </div>
          </div>
        </div>
      {% endif %}
    </div>
  </section>

  <section class="pad" id="closing">
    <div class="wrap quote">
      <p>{{ brand.POSITIONING }}</p>
      <div class="who">{{ brand.NAME }} — a gente resolve a parte de fora</div>
    </div>
  </section>

  <footer>
    <div class="wrap">
      <div class="brand" style="color:#fff"><span class="dot"></span> NutriForge</div>
      <div class="disclaimer">Não é conselho médico. Os planos são estimativas informativas — consulte um profissional em caso de condição de saúde.<br>Fotos de alimentos via Pexels (licença livre).</div>
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
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>NutriForge — Ajuste de preços</title>
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
