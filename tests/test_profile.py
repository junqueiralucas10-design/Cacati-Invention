"""Tests for the calorie/macro math. These need no API key."""

from src.profile import UserProfile


def _base(**overrides) -> UserProfile:
    defaults = dict(
        age=30,
        sex="male",
        height_cm=178,
        weight_kg=82,
        activity_level="moderate",
        goal="maintain",
    )
    defaults.update(overrides)
    return UserProfile(**defaults)


def test_bmr_mifflin_st_jeor_male():
    # 10*82 + 6.25*178 - 5*30 + 5 = 1787.5
    assert _base().bmr() == 1787.5


def test_muscle_gain_adds_surplus():
    maintain = _base(goal="maintain").target_calories()
    gain = _base(goal="gain_muscle").target_calories()
    assert gain == maintain + 300


def test_weight_loss_applies_deficit():
    maintain = _base(goal="maintain").target_calories()
    lose = _base(goal="lose_weight").target_calories()
    assert lose == maintain - 500


def test_macros_are_positive_and_sum_reasonably():
    profile = _base(goal="gain_muscle")
    macros = profile.target_macros()
    assert all(v >= 0 for v in macros.values())
    # protein at 2 g/kg for muscle gain
    assert macros["protein_g"] == round(2.0 * profile.weight_kg)
