import logging
import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.models.users import User

logger = logging.getLogger(__name__)

credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
)


def verify_access_token(token: str) -> uuid.UUID:
    """Verify JWT access token from cookie and return user UUID."""
    try:
        payload = jwt.decode(
            token,
            settings.ACCESS_TOKEN.SECRET_KEY,
            algorithms=[settings.ACCESS_TOKEN.ALGORITHM],
        )

        user_id_str: str | None = payload.get("sub")
        if not user_id_str:
            raise credentials_exception

        return uuid.UUID(user_id_str)

    except (JWTError, ValueError) as exc:
        logger.warning("Access token verification failed: %r", exc)
        raise credentials_exception from exc


async def get_current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """FastAPI Dependency: extracts access_token from cookie and returns User."""
    token = request.cookies.get("access_token")
    if not token:
        logger.warning("access_token cookie missing")
        raise credentials_exception

    user_id = verify_access_token(token)

    user = await db.get(User, user_id)
    if not user:
        logger.warning("User %s not found in database", user_id)
        raise credentials_exception

    return user