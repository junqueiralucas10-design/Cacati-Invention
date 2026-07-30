"""Publish a generated post to Instagram, X or LinkedIn.

Each network gets a small adapter that knows its endpoint and payload shape.
Adapters don't talk to the network themselves — they call an injected `send`,
so a dry run and a test are the same thing as a real publish with a different
sender. The dry-run sender is the default.

HTTP goes through urllib from the standard library: this is three POST requests,
not enough to justify a permanent dependency on requests/httpx.

Credentials come from environment variables and are sent in the request body or
an Authorization header — never in the query string, where they would end up in
proxy and server logs.

    Instagram   IG_USER_ID, IG_ACCESS_TOKEN          (Graph API, needs image_url)
    X           X_ACCESS_TOKEN                       (OAuth 2.0 user-context token)
    LinkedIn    LINKEDIN_ACCESS_TOKEN, LINKEDIN_AUTHOR_URN
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

_GRAPH_VERSION = "v21.0"


class PublishError(RuntimeError):
    """A publish attempt failed — missing credentials or an API rejection."""


@dataclass
class Request:
    """One outgoing HTTP POST."""

    url: str
    headers: dict[str, str] = field(default_factory=dict)
    json_body: dict | None = None
    form: dict[str, str] | None = None

    def redacted(self) -> dict:
        """The request with secrets masked, safe to print or log."""
        headers = {k: ("Bearer ***" if k.lower() == "authorization" else v) for k, v in self.headers.items()}
        form = {k: ("***" if "token" in k.lower() else v) for k, v in (self.form or {}).items()}
        return {"url": self.url, "headers": headers, "json": self.json_body, "form": form or None}


def send_http(request: Request) -> dict:
    """Actually POST the request and return the parsed JSON response."""
    if request.form is not None:
        data = urllib.parse.urlencode(request.form).encode("utf-8")
        headers = {"Content-Type": "application/x-www-form-urlencoded", **request.headers}
    else:
        data = json.dumps(request.json_body or {}).encode("utf-8")
        headers = {"Content-Type": "application/json", **request.headers}

    req = urllib.request.Request(request.url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        # These APIs put the actual reason in the body, not the status line.
        detail = exc.read().decode("utf-8", errors="replace")
        raise PublishError(f"HTTP {exc.code} de {request.url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise PublishError(f"falha de rede ao chamar {request.url}: {exc.reason}") from exc

    return json.loads(body) if body.strip() else {}


class DryRunSender:
    """Records requests instead of sending them."""

    def __init__(self) -> None:
        self.requests: list[Request] = []

    def __call__(self, request: Request) -> dict:
        self.requests.append(request)
        # Enough for the Instagram two-step to continue without a real container.
        return {"id": "dry-run"}


def _credential(env: dict[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise PublishError(f"variável de ambiente {name} não configurada")
    return value


def _publish_instagram(text: str, env: dict[str, str], image_url: str | None, send) -> dict:
    """Graph API: create a media container, then publish it.

    The Instagram API has no text-only post — a feed post always carries media,
    so `image_url` is required and must be publicly reachable by Meta's servers.
    """
    if not image_url:
        raise PublishError("Instagram exige image_url: a API não aceita post só de texto")

    user_id = _credential(env, "IG_USER_ID")
    token = _credential(env, "IG_ACCESS_TOKEN")
    base = f"https://graph.facebook.com/{_GRAPH_VERSION}/{user_id}"

    container = send(
        Request(url=f"{base}/media", form={"image_url": image_url, "caption": text, "access_token": token})
    )
    creation_id = container.get("id")
    if not creation_id:
        raise PublishError(f"Graph API não devolveu o id do container: {container}")

    return send(
        Request(url=f"{base}/media_publish", form={"creation_id": str(creation_id), "access_token": token})
    )


def _publish_x(text: str, env: dict[str, str], image_url: str | None, send) -> dict:
    """X API v2. The token must be a user-context OAuth 2.0 token — an app-only
    bearer token can read but cannot post."""
    token = _credential(env, "X_ACCESS_TOKEN")
    return send(
        Request(
            url="https://api.x.com/2/tweets",
            headers={"Authorization": f"Bearer {token}"},
            json_body={"text": text},
        )
    )


def _publish_linkedin(text: str, env: dict[str, str], image_url: str | None, send) -> dict:
    """LinkedIn UGC Posts API, text-only share on the author's own feed."""
    token = _credential(env, "LINKEDIN_ACCESS_TOKEN")
    author = _credential(env, "LINKEDIN_AUTHOR_URN")  # e.g. urn:li:person:XXXX
    return send(
        Request(
            url="https://api.linkedin.com/v2/ugcPosts",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Restli-Protocol-Version": "2.0.0",
            },
            json_body={
                "author": author,
                "lifecycleState": "PUBLISHED",
                "specificContent": {
                    "com.linkedin.ugc.ShareContent": {
                        "shareCommentary": {"text": text},
                        "shareMediaCategory": "NONE",
                    }
                },
                "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
            },
        )
    )


_ADAPTERS = {
    "instagram": _publish_instagram,
    "x": _publish_x,
    "linkedin": _publish_linkedin,
}

# TikTok has no public post-a-video endpoint for arbitrary apps; its Content
# Posting API requires an approved app and a video upload. Copy is generated for
# it (see promo.PLATFORMS) but posting stays manual.
PUBLISHABLE = tuple(_ADAPTERS)


def publish(
    text: str,
    platform: str,
    *,
    dry_run: bool = True,
    image_url: str | None = None,
    env: dict[str, str] | None = None,
    send=None,
) -> dict:
    """Publish `text` to `platform`.

    Defaults to a dry run: nothing leaves the machine unless `dry_run=False`.
    Returns {"platform", "dry_run", "requests": [redacted...], "response": {...}}.
    """
    adapter = _ADAPTERS.get(platform)
    if adapter is None:
        raise PublishError(
            f"publicação não suportada para {platform!r} (disponíveis: {', '.join(PUBLISHABLE)})"
        )

    if send is None:
        send = DryRunSender() if dry_run else send_http

    sent: list[Request] = []

    def recording_send(request: Request) -> dict:
        sent.append(request)
        return send(request)

    response = adapter(text, env if env is not None else dict(os.environ), image_url, recording_send)
    return {
        "platform": platform,
        "dry_run": dry_run,
        "requests": [r.redacted() for r in sent],
        "response": response,
    }
