"""Shared test fixtures.

`fake_claude` stands in for anthropic.Anthropic so the copy generator can be
tested without an API key or a network call. It records the kwargs it was
called with, which is how the prompt-building tests inspect the request.
"""

import json

import pytest


class _Block:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _FakeStream:
    def __init__(self, message) -> None:
        self._message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self._message


class _FakeMessages:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.kwargs: dict | None = None

    def stream(self, **kwargs):
        self.kwargs = kwargs
        message = type("Message", (), {"content": [_Block(json.dumps(self.payload))]})()
        return _FakeStream(message)


class FakeClient:
    """Minimal stand-in for anthropic.Anthropic's streaming surface."""

    def __init__(self, payload: dict) -> None:
        self.messages = _FakeMessages(payload)


@pytest.fixture
def fake_claude():
    """Factory: fake_claude(payload) -> a client whose stream returns payload."""
    return FakeClient
