"""FastAPI dependency helpers shared by routers.

Centralizes two cross-cutting concerns:
  * fetching the :class:`AppContext` from app state, and
  * optional bearer-token authentication.
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request, status

from llmode.daemon.context import AppContext


def get_context(request: Request) -> AppContext:
    """Return the shared :class:`AppContext` attached during app startup."""
    return request.app.state.ctx


async def require_auth(
    ctx: AppContext = Depends(get_context),
    authorization: str | None = Header(default=None),
) -> None:
    """Enforce the bearer token when one is configured.

    Policy (REQUIREMENTS OQ-4): if ``settings.auth_token`` is unset we are in
    localhost-trusted mode and allow everything. When a token is set, every
    request must present ``Authorization: Bearer <token>``.
    """
    token = ctx.settings.auth_token
    if not token:
        return  # Auth disabled — localhost-trusted.
    expected = f"Bearer {token}"
    if authorization != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid bearer token.",
        )
