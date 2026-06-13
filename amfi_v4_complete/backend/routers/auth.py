"""AMFI v4 — JWT authentication router.

Provides:
  POST /auth/login   — exchange username+password for a JWT access token
  GET  /auth/me      — return the current authenticated user's info
  Dependency get_current_user — FastAPI dependency for protected routes

The login endpoint works regardless of AUTH_ENABLED so the frontend can always
reach it.  All *other* API routes are protected via the auth middleware in
main.py when AUTH_ENABLED=true.
"""
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from backend.utils.rate_limit import limiter
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database import get_db
from backend.models.models import User

router   = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()

# Bearer token scheme for protected endpoints (optional=True so routes that
# use Depends(maybe_user) don't break when no token is sent).
_oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 8   # 8-hour sessions by default


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class TokenOut(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    username:     str
    role:         str
    full_name:    Optional[str] = None


class UserOut(BaseModel):
    id:        int
    username:  str
    email:     Optional[str]
    full_name: Optional[str]
    role:      str
    is_active: bool


# ── JWT helpers ───────────────────────────────────────────────────────────────

def _create_token(data: dict, expires_delta: timedelta | None = None) -> str:
    payload = data.copy()
    expire  = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    payload["exp"] = expire
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def _verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


# ── Dependency: get current user (optional) ───────────────────────────────────

async def get_current_user(
    token: Optional[str] = Depends(_oauth2),
    db:    AsyncSession   = Depends(get_db),
) -> Optional[User]:
    """Resolve a Bearer token to a User row.  When auth is disabled, still tries
    to resolve the token if one is provided (so /auth/me works with a real token
    even when AUTH_ENABLED=false); falls back to a synthetic admin user."""
    if not settings.auth_enabled:
        # If a token was provided, try to resolve it to the real user
        if token:
            try:
                payload  = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
                username = payload.get("sub")
                if username:
                    r    = await db.execute(select(User).where(User.username == username))
                    user = r.scalar_one_or_none()
                    if user and user.is_active:
                        return user
            except Exception:
                pass
        # Fall back to a synthetic admin-equivalent
        return User(id=0, username="system", role="admin", is_active=True)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload  = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        username = payload.get("sub")
        if username is None:
            raise ValueError("missing sub")
    except (JWTError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    r    = await db.execute(select(User).where(User.username == username))
    user = r.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenOut, summary="Obtain JWT access token")
@limiter.limit("10/minute")
async def login(
    request: Request,
    form:    OAuth2PasswordRequestForm = Depends(),
    db:      AsyncSession              = Depends(get_db),
):
    r    = await db.execute(select(User).where(User.username == form.username))
    user = r.scalar_one_or_none()

    if not user or not _verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    token = _create_token({"sub": user.username, "role": user.role})
    return TokenOut(
        access_token=token,
        username=user.username,
        role=user.role,
        full_name=user.full_name,
    )


@router.get("/me", response_model=UserOut, summary="Current user profile")
async def me(current_user: User = Depends(get_current_user)):
    return UserOut(
        id        = current_user.id,
        username  = current_user.username,
        email     = getattr(current_user, "email", None),
        full_name = getattr(current_user, "full_name", None),
        role      = current_user.role,
        is_active = current_user.is_active,
    )


@router.get("/status", summary="Auth configuration status (public)")
async def auth_status():
    """Returns whether auth is enabled — used by the frontend on boot."""
    return {"auth_enabled": settings.auth_enabled}


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password:     str


@router.post("/change-password", summary="Change current user's password")
async def change_password(
    body:         ChangePasswordRequest,
    current_user: User         = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
):
    """Allow the logged-in user to change their own password.
    Requires the current password for verification."""
    if not _verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    if len(body.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="New password must be at least 8 characters",
        )

    # Re-fetch to get a mutable session-bound instance
    r    = await db.execute(select(User).where(User.id == current_user.id))
    user = r.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    user.hashed_password = bcrypt.hashpw(
        body.new_password.encode(), bcrypt.gensalt()
    ).decode()
    await db.commit()
    return {"message": "Password changed successfully"}
