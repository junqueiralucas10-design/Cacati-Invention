"""Tests for the publishing adapters. No network, no credentials needed.

Every test injects a fake sender, so nothing is ever posted.
"""

import pytest

from src.social import PublishError, Request, publish

ENV = {
    "IG_USER_ID": "1784",
    "IG_ACCESS_TOKEN": "ig-secret",
    "X_ACCESS_TOKEN": "x-secret",
    "LINKEDIN_ACCESS_TOKEN": "li-secret",
    "LINKEDIN_AUTHOR_URN": "urn:li:person:ABC",
}


class _Recorder:
    """Captures requests and returns a canned Graph API container id."""

    def __init__(self):
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        return {"id": "container-1"}


# --- X -----------------------------------------------------------------------

def test_x_posts_the_text_with_a_bearer_token():
    send = _Recorder()
    publish("Olá", "x", dry_run=False, env=ENV, send=send)

    req = send.requests[0]
    assert req.url == "https://api.x.com/2/tweets"
    assert req.json_body == {"text": "Olá"}
    assert req.headers["Authorization"] == "Bearer x-secret"


# --- Instagram ---------------------------------------------------------------

def test_instagram_creates_a_container_then_publishes_it():
    send = _Recorder()
    publish("Legenda", "instagram", dry_run=False, env=ENV,
            image_url="https://cdn.test/a.jpg", send=send)

    create, publish_req = send.requests
    assert create.url.endswith("/1784/media")
    assert create.form["image_url"] == "https://cdn.test/a.jpg"
    assert create.form["caption"] == "Legenda"
    # The second call must use the id the first one returned.
    assert publish_req.url.endswith("/1784/media_publish")
    assert publish_req.form["creation_id"] == "container-1"


def test_instagram_requires_an_image():
    with pytest.raises(PublishError, match="image_url"):
        publish("Legenda", "instagram", dry_run=False, env=ENV, send=_Recorder())


def test_instagram_fails_loudly_if_no_container_id_comes_back():
    with pytest.raises(PublishError, match="container"):
        publish("Legenda", "instagram", dry_run=False, env=ENV,
                image_url="https://cdn.test/a.jpg", send=lambda req: {"error": "nope"})


# --- LinkedIn ----------------------------------------------------------------

def test_linkedin_uses_the_author_urn_and_ugc_shape():
    send = _Recorder()
    publish("Post", "linkedin", dry_run=False, env=ENV, send=send)

    req = send.requests[0]
    assert req.url == "https://api.linkedin.com/v2/ugcPosts"
    assert req.json_body["author"] == "urn:li:person:ABC"
    assert req.headers["X-Restli-Protocol-Version"] == "2.0.0"
    share = req.json_body["specificContent"]["com.linkedin.ugc.ShareContent"]
    assert share["shareCommentary"]["text"] == "Post"


# --- credentials and safety --------------------------------------------------

def test_missing_credential_names_the_variable():
    with pytest.raises(PublishError, match="X_ACCESS_TOKEN"):
        publish("Olá", "x", dry_run=False, env={}, send=_Recorder())


def test_secrets_never_land_in_the_url():
    send = _Recorder()
    publish("Legenda", "instagram", dry_run=False, env=ENV,
            image_url="https://cdn.test/a.jpg", send=send)
    for req in send.requests:
        assert "ig-secret" not in req.url


def test_redacted_masks_tokens():
    redacted = Request(
        url="https://api.x.com/2/tweets",
        headers={"Authorization": "Bearer x-secret"},
        json_body={"text": "oi"},
    ).redacted()
    assert redacted["headers"]["Authorization"] == "Bearer ***"

    form = Request(url="u", form={"access_token": "ig-secret", "caption": "oi"}).redacted()["form"]
    assert form == {"access_token": "***", "caption": "oi"}


def test_dry_run_sends_nothing_and_reports_the_requests():
    result = publish("Olá", "x", env=ENV)  # dry_run defaults to True

    assert result["dry_run"] is True
    assert result["requests"][0]["url"] == "https://api.x.com/2/tweets"
    assert result["requests"][0]["headers"]["Authorization"] == "Bearer ***"


def test_tiktok_is_rejected_rather_than_silently_skipped():
    with pytest.raises(PublishError, match="tiktok"):
        publish("Olá", "tiktok", dry_run=False, env=ENV, send=_Recorder())
