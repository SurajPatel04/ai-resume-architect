import logging
import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request, WebSocket, status
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


def verify_access_token_with_exp(token: str) -> tuple[uuid.UUID, float]:
    try:
        payload = jwt.decode(
            token,
            settings.ACCESS_TOKEN.SECRET_KEY,
            algorithms=[settings.ACCESS_TOKEN.ALGORITHM],
        )

        user_id_str: str | None = payload.get("sub")
        exp: float | None = payload.get("exp")
        
        if not user_id_str or exp is None:
            raise credentials_exception

        return uuid.UUID(user_id_str), float(exp)

    except (JWTError, ValueError) as exc:
        logger.warning("Access token verification failed: %r", exc)
        raise credentials_exception from exc


def verify_access_token(token: str) -> uuid.UUID:
    user_id, _ = verify_access_token_with_exp(token)
    return user_id


async def get_current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
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


async def get_current_user_ws(
    websocket: WebSocket,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> tuple[User, float] | tuple[None, None]:
    """Extracts access_token from cookie and authenticates WebSocket."""

    access_token = websocket.cookies.get("access_token")

    if not access_token:
        logger.warning("WebSocket auth: access_token cookie MISSING")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="access_token missing")
        return None, None

    try:
        user_id, exp = verify_access_token_with_exp(access_token)
    except Exception as e:
        logger.warning("WebSocket token verification failed: %r", e)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid token")
        return None, None

    user = await db.get(User, user_id)
    if not user:
        logger.warning("User %s not found in database", user_id)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="User not found")
        return None, None

    return user, exp