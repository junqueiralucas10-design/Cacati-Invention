"""Command-line entry point: build a profile and print a generated plan.

Usage:
    python -m src.cli               # interactive; one-day plan
    python -m src.cli --demo        # skip prompts, use a built-in example profile
    python -m src.cli --week        # generate a 7-day plan
    python -m src.cli --week 5      # generate a 5-day plan
    python -m src.cli --demo --week 3
"""

from __future__ import annotations

import sys

from .console import use_utf8_output
from .diet_planner import generate_plan, generate_weekly_plan
from .intake import collect_profile
from .nutrition import verify_plan, verify_weekly_plan
from .pricing import estimate_plan_cost, format_brl
from .profile import UserProfile
from .shopping import build_shopping_list


def _demo_profile() -> UserProfile:
    """A hardcoded example profile, used with --demo."""
    return UserProfile(
        age=30,
        sex="male",
        height_cm=178,
        weight_kg=82,
        activity_level="moderate",
        goal="gain_muscle",
        dietary_restrictions=[],
        allergies=[],
    )


def _parse_week_arg(argv: list[str]) -> int | None:
    """Return the number of days if --week is present, else None.

    `--week` alone means 7; `--week N` uses N.
    """
    if "--week" not in argv:
        return None
    i = argv.index("--week")
    if i + 1 < len(argv) and argv[i + 1].isdigit():
        return int(argv[i + 1])
    return 7


def _print_meal(meal: dict) -> None:
    print(f"• {meal['name']} — {meal['calories']} kcal")
    print(f"    {meal['description']}")
    print(f"    P {meal['protein_g']}g / G {meal['fat_g']}g / C {meal['carbs_g']}g\n")


def _print_flags(discrepancies: list) -> None:
    if discrepancies:
        print("\n⚠ A conferência nutricional sinalizou refeições (calorias declaradas vs calculadas):")
        for d in discrepancies:
            print(f"   - {d}")
    else:
        print("\n✓ Conferência nutricional ok — as calorias batem com os macros.")


def _print_shopping(plan: dict) -> None:
    items = build_shopping_list(plan)
    if not items:
        return
    print("\n🛒 Lista de compras:")
    for item in items:
        print(f"   - {item}")


def _print_cost(plan: dict, days: int | None) -> None:
    cost = estimate_plan_cost(plan)
    span = days or 1
    total = format_brl(cost["total_brl"])
    if span > 1:
        per_day = format_brl(round(cost["total_brl"] / span, 2))
        print(f"\n💰 Custo estimado: {total} para {span} dias (~{per_day}/dia)")
    else:
        print(f"\n💰 Custo estimado: {total} para o dia")
    print("   (preços de referência do Carrefour Brasil — varia por região)")


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    use_utf8_output()
    profile = _demo_profile() if "--demo" in argv else collect_profile()
    days = _parse_week_arg(argv)

    macros = profile.target_macros()
    print(
        f"\nMetas — {profile.target_calories()} kcal | "
        f"{macros['protein_g']}g de proteína / {macros['fat_g']}g de gordura / "
        f"{macros['carbs_g']}g de carboidrato\n"
    )

    if days is None:
        plan = generate_plan(profile)
        print(plan["summary"], "\n")
        for meal in plan["meals"]:
            _print_meal(meal)
        print(plan["notes"])
        _print_flags(verify_plan(plan))
        _print_shopping(plan)
        _print_cost(plan, days)
    else:
        plan = generate_weekly_plan(profile, days=days)
        print(plan["summary"], "\n")
        for day in plan["days"]:
            print(f"=== {day['day']} ===")
            for meal in day["meals"]:
                _print_meal(meal)
        print(plan["notes"])
        _print_flags(verify_weekly_plan(plan))
        _print_shopping(plan)
        _print_cost(plan, days)


if __name__ == "__main__":
    main()
