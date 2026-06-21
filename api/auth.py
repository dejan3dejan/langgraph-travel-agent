"""JWT authentication utilities."""

import os
from datetime import UTC, datetime, timedelta

import bcrypt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from core.database import User, get_db

load_dotenv()

_DEV_SECRET_DEFAULT = "dev-secret-change-in-production"


def _resolve_secret_key(secret: str | None, environment: str) -> str:
    """Return the JWT secret, refusing the dev default in production.

    A missing or default secret signs tokens with a publicly known key, so anyone
    could forge them. Fail loud at startup in production rather than booting insecure;
    the default stays convenient for local development.
    """
    if environment.lower() == "production" and (not secret or secret == _DEV_SECRET_DEFAULT):
        raise RuntimeError(
            "JWT_SECRET_KEY must be set to a strong value when ENVIRONMENT=production. "
            'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
        )
    return secret or _DEV_SECRET_DEFAULT


SECRET_KEY = _resolve_secret_key(os.getenv("JWT_SECRET_KEY"), os.getenv("ENVIRONMENT", "development"))
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/users/login", auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: str) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode({"sub": user_id, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


async def get_current_user(token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User | None:
    """Extract user from JWT. Returns None if no token (allows anonymous access)."""
    if not token:
        return None

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if not user_id:
            return None
    except JWTError:
        return None

    user = db.query(User).filter(User.id == user_id).first()
    if user and not user.is_active:
        return None
    return user


async def require_user(user: User | None = Depends(get_current_user)) -> User:
    """Require authenticated user. Raises 401 if not logged in."""
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
