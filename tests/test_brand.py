"""Tests for the brand positioning and its two consumers.

The point of src/brand.py is that the landing page and the social copy can't
drift apart. These tests fail if either surface stops carrying the positioning.
"""

from src import brand
from src.profile import UserProfile
from src.promo import campaign_facts, generate_posts
from src.webapp import create_app


def _profile() -> UserProfile:
    return UserProfile(age=30, sex="male", height_cm=178, weight_kg=82,
                       activity_level="moderate", goal="gain_muscle")


def test_positioning_is_the_phrase_we_agreed_on():
    assert brand.POSITIONING == "A mudança não vem de fora pra dentro, mas de dentro pra fora."


# --- the landing page carries it --------------------------------------------

def _page() -> str:
    client = create_app(generate=lambda p, d: {}).test_client()
    return client.get("/").get_data(as_text=True)


def test_landing_page_leads_with_the_positioning():
    body = _page()
    # Jinja escapes the apostrophe-free text as-is, so a plain substring works.
    assert brand.POSITIONING in body
    assert f"<h1>{brand.POSITIONING}</h1>" in body


def test_landing_page_renders_the_manifesto_and_every_quote():
    body = _page()
    for line in brand.MANIFESTO:
        assert line in body
    for quote in brand.QUOTES:
        assert quote.text in body
        assert quote.attribution in body


def test_landing_page_discloses_that_the_quotes_are_not_real_athletes():
    # If the quotes render, the disclosure must render with them. Deleting the
    # note would turn original copy into apparent testimony from real medalists.
    assert "não são" in _page()
    assert "citações de atletas reais" in _page()


def test_page_is_marked_as_brazilian_portuguese():
    assert '<html lang="pt-BR">' in _page()


# --- the social copy carries it ---------------------------------------------

def test_promo_prompt_carries_the_positioning_and_manifesto(fake_claude):
    client = fake_claude({"posts": []})
    generate_posts(campaign_facts(_profile(), app_url="https://example.test"), client=client)

    prompt = client.messages.kwargs["messages"][0]["content"]
    system = client.messages.kwargs["system"]

    assert brand.POSITIONING in prompt
    assert brand.POSITIONING in system  # via brand.VOICE
    for line in brand.MANIFESTO:
        assert line in prompt


def test_promo_prompt_forbids_naming_real_athletes(fake_claude):
    client = fake_claude({"posts": []})
    generate_posts(campaign_facts(_profile(), app_url="https://example.test"), client=client)

    prompt = client.messages.kwargs["messages"][0]["content"]
    # The quotes are handed over as tone reference, so the prompt must say
    # plainly that they aren't real people and that names are off limits.
    assert "NÃO citações de atletas reais" in prompt
    assert "nunca atribua fala a atleta real" in prompt


# --- the quotes themselves ---------------------------------------------------

def test_quotes_are_attributed_to_archetypes_not_to_named_people():
    # Every attribution starts with an indefinite article + discipline
    # ("Uma velocista, sobre...") rather than a person's name.
    for quote in brand.QUOTES:
        first = quote.attribution.split()[0]
        assert first in ("Um", "Uma"), f"{quote.attribution!r} parece nomear alguém"
        assert ", sobre " in quote.attribution
