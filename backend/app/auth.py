"""Verifying the Supabase access token a browser sends with each request.

The token is checked locally rather than by calling Supabase: it is a signed
JWT, so the signature, audience and expiry are all the proof needed, and a
network round trip per request would put Supabase's availability in the path of
every chat message.

Two signing schemes exist and a project uses one of them:

  HS256   the legacy shared secret. Fast, and the secret never leaves the
          server.
  RS256/ES256
          asymmetric keys, which Supabase is moving to. The public half is
          published as a JWKS, fetched once and cached - rotation is then a
          matter of the cache expiring rather than an edit to the config.

Both are supported because a project migrating between them would otherwise
reject every token mid-flight.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Final

import httpx
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from .config import get_settings

logger = logging.getLogger(__name__)

# Supabase issues access tokens with this audience for a signed-in user.
AUDIENCE: Final = "authenticated"

# `auto_error=False`: a missing header is handled here, so the reason can be
# specific rather than FastAPI's generic "Not authenticated".
_bearer = HTTPBearer(auto_error=False)

_jwks_client: PyJWKClient | None = None


@dataclass(frozen=True)
class AuthenticatedUser:
    """Who the request is from. Only what the app actually needs."""

    id: str
    email: str | None = None

    @property
    def is_anonymous(self) -> bool:
        """True for the development identity used when auth is not configured."""
        return self.id == ANONYMOUS_ID


# Used only when no Supabase project is configured. It is a fixed, obviously
# fake id so that anything it writes is recognisable as unattributed rather
# than quietly mixed in with a real person's history.
ANONYMOUS_ID: Final = "00000000-0000-0000-0000-000000000000"
ANONYMOUS = AuthenticatedUser(id=ANONYMOUS_ID)


class AuthError(HTTPException):
    """401 with a reason the client can act on."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


def _jwks() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        settings = get_settings()
        url = settings.supabase_jwks_url or (
            f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
        )
        # Cached, so rotation costs one fetch rather than one per request.
        _jwks_client = PyJWKClient(url, cache_keys=True, lifespan=3600)
    return _jwks_client


def decode_token(token: str) -> dict[str, Any]:
    """Verify a Supabase access token and return its claims.

    Raises `AuthError` for anything that is not a currently valid token signed
    by this project.
    """
    settings = get_settings()

    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise AuthError("That access token is malformed.") from exc

    algorithm = header.get("alg", "HS256")

    try:
        if algorithm == "HS256":
            if not settings.supabase_jwt_secret:
                raise AuthError("This server is not configured to verify HS256 tokens.")
            return jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience=AUDIENCE,
            )

        # Asymmetric: verify against the project's published public key.
        signing_key = _jwks().get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience=AUDIENCE,
        )
    except jwt.ExpiredSignatureError as exc:
        # Distinguished from a bad signature: the client can fix this one by
        # refreshing, and should not be told to sign in again.
        raise AuthError("Your session has expired. Please sign in again.") from exc
    except jwt.InvalidAudienceError as exc:
        raise AuthError("That token was not issued for this application.") from exc
    except (jwt.PyJWTError, httpx.HTTPError) as exc:
        logger.warning("Rejected an access token: %s", exc)
        raise AuthError("That access token is not valid.") from exc


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthenticatedUser:
    """FastAPI dependency: the signed-in user, or a 401.

    When no Supabase project is configured this returns the anonymous
    development identity instead of refusing every request - the app predates
    accounts and still has to run without them. The moment credentials are
    present, a valid token is required.
    """
    settings = get_settings()

    if not settings.auth_configured:
        if credentials is not None:
            # A token arrived at a server that cannot check it. Accepting it
            # unverified would be worse than refusing.
            logger.warning("Access token received but no Supabase project is configured")
        return ANONYMOUS

    if credentials is None or not credentials.credentials:
        raise AuthError("Sign in to continue.")

    claims = decode_token(credentials.credentials)

    subject = claims.get("sub")
    if not subject:
        raise AuthError("That access token identifies no user.")

    # Belt and braces: PyJWT already enforces `exp`, but a token with no expiry
    # at all would pass that check by having nothing to compare.
    if "exp" not in claims:
        raise AuthError("That access token never expires, which is not accepted.")
    if float(claims["exp"]) < time.time():
        raise AuthError("Your session has expired. Please sign in again.")

    request.state.user_id = subject
    return AuthenticatedUser(id=str(subject), email=claims.get("email"))
