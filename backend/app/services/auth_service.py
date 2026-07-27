import uuid
from datetime import datetime, timedelta, timezone

from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_token
from app.models.refersh_token import RefreshToken

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN.EXPIRE_MINUTES
    )
    to_encode.update({"exp": expire})
    return jwt.encode(
        to_encode,
        settings.ACCESS_TOKEN.SECRET_KEY,
        algorithm=settings.ACCESS_TOKEN.ALGORITHM,
    )

def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.REFRESH_TOKEN.EXPIRE_MINUTES
    )
    to_encode.update({"exp": expire})
    return jwt.encode(
        to_encode,
        settings.REFRESH_TOKEN.SECRET_KEY,
        algorithm=settings.REFRESH_TOKEN.ALGORITHM,
    )

async def create_both_tokens(db: AsyncSession, user_id: uuid.UUID) -> dict[str, str]:
    access_token = create_access_token({"sub": str(user_id)})

    jti = str(uuid.uuid4())
    refresh_token = create_refresh_token({"sub": str(user_id), "jti": jti})

    hashed_refresh_token = hash_token(refresh_token)
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.REFRESH_TOKEN.EXPIRE_MINUTES
    )

    refresh_token_doc = RefreshToken(
        user_id=user_id,
        jti=jti,
        token_hash=hashed_refresh_token,
        expires_at=expires_at,
        revoked=False,
    )

    db.add(refresh_token_doc)
    await db.commit()

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
    }