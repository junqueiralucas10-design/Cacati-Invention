"""Tests for the Flask web UI. The generator is stubbed, so no API key is used."""

import pytest

from src.webapp import _collect_screenshots, create_app, profile_from_form


def test_collect_screenshots_missing_folder_returns_empty(tmp_path):
    assert _collect_screenshots(str(tmp_path)) == []  # no screenshots/ subdir
    assert _collect_screenshots(None) == []


def test_collect_screenshots_lists_images_with_captions(tmp_path):
    shots_dir = tmp_path / "screenshots"
    shots_dir.mkdir()
    (shots_dir / "02-weekly_plan.png").write_bytes(b"x")
    (shots_dir / "01-the-form.jpg").write_bytes(b"x")
    (shots_dir / "notes.txt").write_text("ignored")  # non-image skipped

    shots = _collect_screenshots(str(tmp_path))
    # Sorted by filename -> 01 before 02; captions are title-cased from the stem.
    assert [s["alt"] for s in shots] == ["01 The Form", "02 Weekly Plan"]
    assert shots[0]["src"] == "/static/screenshots/01-the-form.jpg"


class _Form(dict):
    """Minimal stand-in for a Flask MultiDict (only .get is used)."""


def _valid_form(**overrides) -> _Form:
    data = {
        "age": "30",
        "sex": "male",
        "height_cm": "178",
        "weight_kg": "82",
        "activity_level": "moderate",
        "goal": "gain_muscle",
        "dietary_restrictions": "vegetarian, no nuts",
        "allergies": "",
        "plan_length": "",
    }
    data.update(overrides)
    return _Form(data)


def test_profile_from_form_valid():
    p = profile_from_form(_valid_form())
    assert p.age == 30
    assert p.sex == "male"
    assert p.goal == "gain_muscle"
    assert p.dietary_restrictions == ["vegetarian", "no nuts"]


def test_profile_from_form_rejects_bad_age():
    from src.intake import IntakeError

    with pytest.raises(IntakeError):
        profile_from_form(_valid_form(age="abc"))


# --- Route tests with a stubbed generator ---------------------------------

_FAKE_DAILY = {
    "summary": "A balanced day.",
    "meals": [
        {
            "name": "Chicken & rice",
            "description": "Grilled chicken with brown rice.",
            "calories": 495,
            "protein_g": 40,
            "fat_g": 15,
            "carbs_g": 50,
            "ingredients": [
                {"item": "Chicken breast", "quantity": 200, "unit": "g"},
                {"item": "Brown rice", "quantity": 150, "unit": "g"},
            ],
        }
    ],
    "notes": "Consult a professional.",
}

_FAKE_WEEKLY = {
    "summary": "A varied week.",
    "days": [
        {
            "day": "Monday",
            "meals": [
                {
                    "name": "Oatmeal",
                    "description": "Oats and banana.",
                    "calories": 300,
                    "protein_g": 10,
                    "fat_g": 5,
                    "carbs_g": 55,
                    "ingredients": [{"item": "Oats", "quantity": 80, "unit": "g"}],
                }
            ],
        }
    ],
    "notes": "Consult a professional.",
}


def _client(plan):
    def fake_generate(profile, days):
        return plan
    return create_app(generate=fake_generate).test_client()


def test_index_renders_form():
    client = create_app(generate=lambda p, d: _FAKE_DAILY).test_client()
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Generate my plan" in body
    assert 'name="age"' in body
    # Friendly goal labels + descriptions are rendered (not raw enum values only).
    assert "Lose weight" in body
    assert "support lean muscle growth" in body


def test_post_daily_plan_renders_results_and_shopping():
    client = _client(_FAKE_DAILY)
    resp = client.post("/plan", data=_valid_form())
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Chicken &amp; rice" in body  # HTML-escaped
    assert "Shopping list" in body
    assert "200 g Chicken breast" in body
    assert "Nutrition check passed" in body  # 495 vs 490 computed -> within tolerance


def test_post_weekly_plan_shows_day_headings():
    client = _client(_FAKE_WEEKLY)
    resp = client.post("/plan", data=_valid_form(plan_length="7"))
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Monday" in body
    assert "80 g Oats" in body


def test_post_invalid_form_shows_error_and_400():
    client = create_app(generate=lambda p, d: _FAKE_DAILY).test_client()
    resp = client.post("/plan", data=_valid_form(age="abc"))
    assert resp.status_code == 400
    assert "whole number" in resp.get_data(as_text=True)
