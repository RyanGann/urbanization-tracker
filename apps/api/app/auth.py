from hmac import compare_digest
from typing import Annotated

from fastapi import Header, HTTPException, status

from app.config import get_settings


def require_reviewer_access(
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    token = get_settings().reviewer_api_token
    if not token:
        return

    scheme, _, credentials = (authorization or "").partition(" ")
    if scheme.lower() == "bearer" and compare_digest(credentials, token):
        return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Reviewer access required",
        headers={"WWW-Authenticate": "Bearer"},
    )
