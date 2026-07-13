"""Command-line entry point: build a profile and print a generated plan.

Usage:
    python -m src.cli          # interactive: asks for your details
    python -m src.cli --demo   # skip prompts, use a built-in example profile
"""

from __future__ import annotations

import sys

from .diet_planner import generate_plan
from .intake import collect_profile
from .profile import UserProfile


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


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    profile = _demo_profile() if "--demo" in argv else collect_profile()

    macros = profile.target_macros()
    print(
        f"\nTargets — {profile.target_calories()} kcal | "
        f"{macros['protein_g']}g protein / {macros['fat_g']}g fat / {macros['carbs_g']}g carbs\n"
    )

    plan = generate_plan(profile)

    print(plan["summary"], "\n")
    for meal in plan["meals"]:
        print(f"• {meal['name']} — {meal['calories']} kcal")
        print(f"    {meal['description']}")
        print(
            f"    P {meal['protein_g']}g / F {meal['fat_g']}g / C {meal['carbs_g']}g\n"
        )
    print(plan["notes"])


if __name__ == "__main__":
    main()
