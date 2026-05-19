"""Admin-token verification dependency."""
from fastapi import Header, HTTPException, status

from app.config import get_app_config


async def require_admin(x_admin_token: str = Header(default="")) -> None:
    expected = get_app_config().admin_token
    if not expected or x_admin_token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid admin token")