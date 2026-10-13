"""Verifying Supabase access tokens.

These are the checks that decide whose chat history someone can read, so they
are pinned against forged, expired and mis-addressed tokens rather than only
against a valid one.

Offline: tokens are signed here with a known secret, so nothing contacts
Supabase.
"""

from __future__ import annotations

import time

import jwt
import pytest
from fastapi import HTTPException

from app.auth import ANONYMOUS_ID, AUDIENCE, AuthenticatedUser, decode_token
from app.config import get_settings

SECRET = "test-signing-secret-not-a-real-one"
USER = "11111111-2222-3333-4444-555555555555"


@pytest.fixture(autouse=True)
def configured(monkeypatch: pytest.MonkeyPatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co")
    monkeypatch.setattr(settings, "supabase_jwt_secret", SECRET)
    yield


def token(**overrides: object) -> str:
    claims: dict[str, object] = {
        "sub": USER,
        "aud": AUDIENCE,
        "exp": int(time.time()) + 3600,
        "email": "student@example.com",
    }
    claims.update(overrides)
    return jwt.encode(claims, SECRET, algorithm="HS256")


def test_a_valid_token_identifies_the_user() -> None:
    claims = decode_token(token())
    assert claims["sub"] == USER
    assert claims["email"] == "student@example.com"


def test_a_token_signed_with_another_secret_is_refused() -> None:
    """The whole point. Anyone can mint a JWT; only this project can sign one."""
    forged = jwt.encode(
        {"sub": USER, "aud": AUDIENCE, "exp": int(time.time()) + 3600},
        "a-different-secret",
        algorithm="HS256",
    )
    with pytest.raises(HTTPException) as caught:
        decode_token(forged)
    assert caught.value.status_code == 401


def test_an_expired_token_is_refused() -> None:
    with pytest.raises(HTTPException) as caught:
        decode_token(token(exp=int(time.time()) - 60))
    assert "expired" in caught.value.detail.lower()


def test_a_token_for_another_audience_is_refused() -> None:
    """A token minted for a different Supabase service is still correctly
    signed, and must not be accepted here."""
    with pytest.raises(HTTPException) as caught:
        decode_token(token(aud="some-other-service"))
    assert caught.value.status_code == 401


def test_an_unsigned_token_is_refused() -> None:
    """`alg: none` is the oldest JWT attack there is."""
    unsigned = jwt.encode(
        {"sub": USER, "aud": AUDIENCE, "exp": int(time.time()) + 3600},
        key="",
        algorithm="none",
    )
    with pytest.raises(HTTPException):
        decode_token(unsigned)


@pytest.mark.parametrize("rubbish", ["", "not-a-token", "a.b.c", "Bearer x"])
def test_malformed_tokens_are_refused(rubbish: str) -> None:
    with pytest.raises(HTTPException):
        decode_token(rubbish)


def test_the_anonymous_identity_is_recognisable() -> None:
    """It is a fixed, obviously fake id so anything written under it is
    visibly unattributed rather than mixed into a real person's history."""
    assert AuthenticatedUser(id=ANONYMOUS_ID).is_anonymous
    assert not AuthenticatedUser(id=USER).is_anonymous


def test_auth_is_only_enforced_once_it_can_be() -> None:
    """With nothing configured the app runs as it did before accounts existed;
    a missing env var must not turn into a wall of 401s."""
    settings = get_settings()
    assert settings.auth_configured

    original = settings.supabase_url
    try:
        object.__setattr__(settings, "supabase_url", "")
        assert not settings.auth_configured
    finally:
        object.__setattr__(settings, "supabase_url", original)
