"""Tests for weekly-plan verification and CLI arg parsing. No API key needed."""

import pytest

from src.cli import _parse_week_arg
from src.diet_planner import generate_weekly_plan
from src.nutrition import verify_weekly_plan


def test_parse_week_arg_absent():
    assert _parse_week_arg(["--demo"]) is None


def test_parse_week_arg_bare_defaults_to_7():
    assert _parse_week_arg(["--week"]) == 7
    assert _parse_week_arg(["--demo", "--week"]) == 7


def test_parse_week_arg_with_number():
    assert _parse_week_arg(["--week", "5"]) == 5
    assert _parse_week_arg(["--demo", "--week", "3"]) == 3


def test_generate_weekly_plan_rejects_bad_days():
    # Validation happens before any client call, so no API key is needed.
    with pytest.raises(ValueError):
        generate_weekly_plan(profile=None, days=0)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        generate_weekly_plan(profile=None, days=8)  # type: ignore[arg-type]


def _weekly_fixture() -> dict:
    return {
        "summary": "test week",
        "days": [
            {
                "day": "Monday",
                "meals": [
                    # consistent: 40*4 + 50*4 + 15*9 = 495, stated 500
                    {"name": "Oatmeal bowl", "calories": 500, "protein_g": 40, "fat_g": 15, "carbs_g": 50},
                ],
            },
            {
                "day": "Tuesday",
                "meals": [
                    # inconsistent: computes to 290, stated 900
                    {"name": "Mystery plate", "calories": 900, "protein_g": 30, "fat_g": 10, "carbs_g": 20},
                ],
            },
        ],
        "notes": "consult a professional",
    }


def test_verify_weekly_flags_only_bad_meal_with_day_label():
    flagged = verify_weekly_plan(_weekly_fixture())
    assert len(flagged) == 1
    assert flagged[0].meal == "Tuesday — Mystery plate"
    assert flagged[0].stated == 900
    assert flagged[0].computed == 290


def test_verify_weekly_handles_empty():
    assert verify_weekly_plan({}) == []
    assert verify_weekly_plan({"days": []}) == []
