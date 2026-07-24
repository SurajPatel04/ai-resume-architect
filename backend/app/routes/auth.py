from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.security import hash_password, hash_token, verify_password
from app.dependencies.auth import get_current_user
from app.models.refersh_token import RefreshToken
from app.models.users import User
from app.schemas.auth import SignInRequest, SignUpRequest, UserResponse
from app.services.auth_service import create_both_tokens

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def sign_up(
    body: SignUpRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Register a new user account."""
    statement = select(User).where(User.email == body.email)
    result = await db.execute(statement)
    existing_user = result.scalar_one_or_none()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists",
        )

    hashed_pwd = hash_password(body.password)
    user = User(
        first_name=body.first_name,
        last_name=body.last_name,
        email=body.email,
        password_hash=hashed_pwd,
    )

    db.add(user)
    await db.commit()
    await db.refresh(user)

    return user


@router.post("/signin", response_model=UserResponse)
async def sign_in(
    body: SignInRequest,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Authenticate user and set HttpOnly session cookies."""
    statement = select(User).where(User.email == body.email)
    result = await db.execute(statement)
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    tokens = await create_both_tokens(db, user.id)

    response.set_cookie(
        key="access_token",
        value=tokens["access_token"],
        httponly=True,
        samesite="lax",
        secure=False,
    )

    response.set_cookie(
        key="refresh_token",
        value=tokens["refresh_token"],
        httponly=True,
        samesite="lax",
        secure=False,
    )

    return user


@router.post("/logout")
async def log_out(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Log out user by revoking refresh token in DB and clearing session cookies."""
    refresh_token = request.cookies.get("refresh_token")
    if refresh_token:
        hashed_token = hash_token(refresh_token)
        statement = update(RefreshToken).where(
            RefreshToken.token_hash == hashed_token
        ).values(revoked=True)
        await db.execute(statement)
        await db.commit()

    response.delete_cookie(key="access_token")
    response.delete_cookie(key="refresh_token")
    return {"message": "Successfully logged out"}


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: Annotated[User, Depends(get_current_user)]):
    """Get profile of current authenticated user."""
    return current_user
