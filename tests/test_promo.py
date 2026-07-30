"""Tests for the promo content generator. No API key needed.

The `fake_claude` fixture (tests/conftest.py) stands in for the Anthropic client.
"""

from src.promo import (
    PLATFORMS,
    campaign_facts,
    generate_posts,
    render_text,
    verify_posts,
)
from src.profile import UserProfile


def _profile(**kw) -> UserProfile:
    base = dict(age=30, sex="male", height_cm=178, weight_kg=82,
                activity_level="moderate", goal="gain_muscle")
    base.update(kw)
    return UserProfile(**base)


URL = "https://example.test/app"


# --- facts come from the app, not from the copywriter ------------------------

def test_facts_match_the_profile_targets():
    profile = _profile()
    facts = campaign_facts(profile, app_url=URL)

    assert facts["target_calories"] == profile.target_calories()
    assert facts["protein_g"] == profile.target_macros()["protein_g"]
    assert facts["app_url"] == URL


def test_facts_include_a_real_plan_and_a_cost():
    facts = campaign_facts(_profile(), app_url=URL)

    assert facts["meal_count"] >= 3
    assert len(facts["sample_meals"]) == facts["meal_count"]
    assert facts["daily_cost_brl"].startswith("R$ ")
    assert facts["daily_cost_brl"] != "R$ 0,00"  # a real day of food costs something


def test_facts_differ_when_the_goal_differs():
    gain = campaign_facts(_profile(goal="gain_muscle"), app_url=URL)
    lose = campaign_facts(_profile(goal="lose_weight"), app_url=URL)
    assert gain["target_calories"] > lose["target_calories"]


# --- rendering ---------------------------------------------------------------

def test_render_adds_hashes_without_doubling_them():
    text = render_text({"caption": "Olá", "hashtags": ["dieta", "#fitness"]})
    assert text == "Olá\n\n#dieta #fitness"


def test_render_without_hashtags_is_just_the_caption():
    assert render_text({"caption": "Olá", "hashtags": []}) == "Olá"


# --- verification: a post that can't be published must be flagged ------------

def test_over_limit_post_is_flagged_with_the_overage():
    post = {"platform": "x", "caption": "a" * 300, "hashtags": []}
    problems = verify_posts([post])
    assert len(problems) == 1
    assert "20 a mais" in problems[0]  # 300 - 280


def test_hashtags_count_against_the_limit():
    # 275 chars of caption fits alone, but not once "#dieta" is appended.
    post = {"platform": "x", "caption": "a" * 275, "hashtags": ["dieta"]}
    assert verify_posts([post]) != []
    assert verify_posts([{"platform": "x", "caption": "a" * 275, "hashtags": []}]) == []


def test_unknown_platform_is_flagged():
    assert "desconhecida" in verify_posts([{"platform": "orkut", "caption": "oi"}])[0]


# --- generation wiring (fake client, no network) -----------------------------

def test_generate_posts_parses_the_structured_response(fake_claude):
    payload = {"posts": [{"platform": "x", "hook": "h", "caption": "c",
                          "hashtags": ["dieta"], "cta": "Baixe", "alt_text": "prato"}]}
    client = fake_claude(payload)

    posts = generate_posts(campaign_facts(_profile(), app_url=URL), client=client)

    assert posts == payload["posts"]


def test_prompt_carries_the_real_numbers_and_the_platform_keys(fake_claude):
    client = fake_claude({"posts": []})
    facts = campaign_facts(_profile(), app_url=URL)

    generate_posts(facts, client=client)

    prompt = client.messages.kwargs["messages"][0]["content"]
    assert str(facts["target_calories"]) in prompt
    assert facts["daily_cost_brl"] in prompt
    assert URL in prompt
    for platform in PLATFORMS:
        assert platform.key in prompt


def test_generation_requests_validated_json(fake_claude):
    client = fake_claude({"posts": []})
    generate_posts(campaign_facts(_profile(), app_url=URL), client=client)

    fmt = client.messages.kwargs["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["schema"]["required"] == ["posts"]
