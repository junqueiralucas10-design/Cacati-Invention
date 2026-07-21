"""Tests for the R$ cost estimator. No API key needed."""

from src.diet_builder import build_personalized_plan, build_personalized_weekly_plan
from src.pricing import estimate_plan_cost, format_brl
from src.profile import UserProfile


def _profile(**kw) -> UserProfile:
    base = dict(age=30, sex="male", height_cm=178, weight_kg=82,
                activity_level="moderate", goal="gain_muscle")
    base.update(kw)
    return UserProfile(**base)


def test_format_brl():
    assert format_brl(32.5) == "R$ 32,50"
    assert format_brl(1234.5) == "R$ 1.234,50"
    assert format_brl(0) == "R$ 0,00"


def test_manual_price_calculation():
    # 400 g cooked white rice at R$2.50/kg = R$1.00; 200 g chicken at R$22/kg = R$4.40
    plan = {
        "meals": [
            {
                "name": "Lunch", "calories": 0, "protein_g": 0, "fat_g": 0, "carbs_g": 0,
                "ingredients": [
                    {"item": "arroz branco cozido", "quantity": 400, "unit": "g"},
                    {"item": "frango grelhado", "quantity": 200, "unit": "g"},
                ],
            }
        ]
    }
    cost = estimate_plan_cost(plan)
    assert cost["unpriced"] == []
    assert cost["total_brl"] == 5.40  # 1.00 + 4.40


def test_countable_item_uses_grams_per_unit():
    # 4 ovos * 50 g = 200 g at R$15/kg = R$3.00
    plan = {
        "meals": [
            {
                "name": "Breakfast", "calories": 0, "protein_g": 0, "fat_g": 0, "carbs_g": 0,
                "ingredients": [{"item": "ovos", "quantity": 4, "unit": ""}],
            }
        ]
    }
    cost = estimate_plan_cost(plan)
    assert cost["total_brl"] == 3.00


def test_unknown_item_is_reported_not_priced():
    plan = {
        "meals": [
            {
                "name": "Snack", "calories": 0, "protein_g": 0, "fat_g": 0, "carbs_g": 0,
                "ingredients": [{"item": "picanha importada", "quantity": 100, "unit": "g"}],
            }
        ]
    }
    cost = estimate_plan_cost(plan)
    assert cost["total_brl"] == 0.0
    assert "picanha importada" in cost["unpriced"]


def test_real_daily_plan_has_a_reasonable_cost():
    cost = estimate_plan_cost(build_personalized_plan(_profile()))
    # A day of whole foods should cost something modest but non-trivial.
    assert cost["unpriced"] == []
    assert 5 < cost["total_brl"] < 80


def test_weekly_costs_more_than_daily():
    daily = estimate_plan_cost(build_personalized_plan(_profile()))["total_brl"]
    weekly = estimate_plan_cost(build_personalized_weekly_plan(_profile(), days=7))["total_brl"]
    assert weekly > daily * 3  # a week clearly costs more than a single day


# --- price editing: save, CSV round-trip, and web routes ---------------------

import json
import shutil
from pathlib import Path

from src.pricing import load_prices, prices_from_csv, prices_to_csv, save_prices
from src.webapp import create_app

_REAL_PRICES = Path("src/data/prices_brl.json")


def _tmp_prices(tmp_path) -> Path:
    dst = tmp_path / "prices.json"
    shutil.copy(_REAL_PRICES, dst)
    return dst


def test_save_prices_persists_and_keeps_metadata(tmp_path):
    f = _tmp_prices(tmp_path)
    prices = load_prices(f)
    prices["banana"] = 9.99
    save_prices(prices, f)
    raw = json.loads(f.read_text(encoding="utf-8"))
    assert raw["per_kg"]["banana"] == 9.99
    assert raw["currency"] == "BRL"  # metadata preserved


def test_csv_round_trip(tmp_path):
    prices = load_prices(_tmp_prices(tmp_path))
    csv_text = prices_to_csv(prices)
    assert csv_text.startswith("food,price_brl_per_kg")
    parsed, skipped = prices_from_csv(csv_text, prices)
    assert skipped == []
    assert parsed == {k: round(v, 2) for k, v in prices.items()}


def test_csv_import_accepts_comma_decimals_and_skips_bad_lines():
    known = {"banana": 6.0, "ovos": 15.0}
    text = "food,price_brl_per_kg\nbanana,7,25\novos,abc\npicanha,50\n"
    parsed, skipped = prices_from_csv(text, known)
    assert parsed["banana"] == 7.25          # comma decimal accepted
    assert parsed["ovos"] == 15.0            # bad value skipped, old kept
    assert len(skipped) == 2                 # 'ovos,abc' and unknown 'picanha'


def test_prices_page_and_save_route(tmp_path):
    f = _tmp_prices(tmp_path)
    client = create_app(generate=lambda p, d: {}, price_file=f).test_client()

    page = client.get("/prices")
    assert page.status_code == 200
    assert "banana" in page.get_data(as_text=True)

    resp = client.post("/prices", data={"banana": "8,40"})
    assert resp.status_code == 200
    assert "Prices saved" in resp.get_data(as_text=True)
    assert load_prices(f)["banana"] == 8.40
    # the repo's real file is untouched
    assert load_prices(_REAL_PRICES)["banana"] != 8.40


def test_prices_csv_export_and_import_routes(tmp_path):
    f = _tmp_prices(tmp_path)
    client = create_app(generate=lambda p, d: {}, price_file=f).test_client()

    csv_resp = client.get("/prices.csv")
    assert csv_resp.status_code == 200
    assert csv_resp.mimetype == "text/csv"

    modified = csv_resp.get_data(as_text=True).replace(
        "banana,6.00", "banana,9.10"
    )
    import io
    resp = client.post(
        "/prices/import",
        data={"csv_file": (io.BytesIO(modified.encode("utf-8")), "prices.csv")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    assert load_prices(f)["banana"] == 9.10
