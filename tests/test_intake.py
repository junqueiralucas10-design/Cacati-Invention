"""Tests for the profile intake flow. No API key needed."""

import pytest

from src.intake import (
    IntakeError,
    collect_profile,
    parse_choice,
    parse_int_in_range,
    parse_list,
    parse_positive_float,
)


def test_parse_int_in_range_ok():
    assert parse_int_in_range("30", 13, 120) == 30


def test_parse_strips_leading_bom_and_zero_width():
    # A BOM or zero-width space (from piped input / copy-paste) must not break parsing.
    assert parse_int_in_range("\ufeff30", 13, 120) == 30
    assert parse_positive_float("\u200b82.5") == 82.5


@pytest.mark.parametrize("raw", ["abc", "3.5", ""])
def test_parse_int_in_range_rejects_non_int(raw):
    with pytest.raises(IntakeError):
        parse_int_in_range(raw, 13, 120)


@pytest.mark.parametrize("raw", ["12", "121"])
def test_parse_int_in_range_rejects_out_of_range(raw):
    with pytest.raises(IntakeError):
        parse_int_in_range(raw, 13, 120)


def test_parse_positive_float_accepts_comma_decimal():
    assert parse_positive_float("82,5") == 82.5


@pytest.mark.parametrize("raw", ["0", "-1", "abc"])
def test_parse_positive_float_rejects(raw):
    with pytest.raises(IntakeError):
        parse_positive_float(raw)


def test_parse_choice_by_number_and_name():
    opts = ["lose_weight", "gain_muscle", "maintain"]
    assert parse_choice("2", opts) == "gain_muscle"
    assert parse_choice("maintain", opts) == "maintain"
    assert parse_choice("MAINTAIN", opts) == "maintain"


@pytest.mark.parametrize("raw", ["0", "4", "bulk"])
def test_parse_choice_rejects_bad(raw):
    with pytest.raises(IntakeError):
        parse_choice(raw, ["lose_weight", "gain_muscle", "maintain"])


def test_parse_list():
    assert parse_list("vegetarian, no nuts ,dairy") == ["vegetarian", "no nuts", "dairy"]
    assert parse_list("   ") == []


def test_collect_profile_scripted():
    """Drive collect_profile with canned answers and assert the built profile."""
    answers = iter(
        [
            "28",            # age
            "1",             # sex -> male
            "180",           # height
            "75",            # weight
            "moderate",      # activity (by name)
            "2",             # goal -> gain_muscle
            "vegetarian",    # restrictions
            "",              # allergies (none)
        ]
    )
    profile = collect_profile(input_fn=lambda _: next(answers), output_fn=lambda _: None)

    assert profile.age == 28
    assert profile.sex == "male"
    assert profile.height_cm == 180
    assert profile.weight_kg == 75
    assert profile.activity_level == "moderate"
    assert profile.goal == "gain_muscle"
    assert profile.dietary_restrictions == ["vegetarian"]
    assert profile.allergies == []


def test_collect_profile_reprompts_on_bad_input():
    """A bad answer should be rejected, then the retry accepted."""
    answers = iter(
        [
            "abc", "30",     # age: bad then good
            "male",          # sex
            "178", "82",     # height, weight
            "moderate",      # activity
            "maintain",      # goal
            "", "",          # restrictions, allergies
        ]
    )
    profile = collect_profile(input_fn=lambda _: next(answers), output_fn=lambda _: None)
    assert profile.age == 30
    assert profile.goal == "maintain"
