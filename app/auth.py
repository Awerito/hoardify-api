import asyncio
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseModel

from app.config import SecurityConfig

ADMIN_USERNAME = "admin"


class Token(BaseModel):
    access_token: str
    token_type: str


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


async def authenticate(username: str, password: str) -> bool:
    if username != ADMIN_USERNAME:
        return False
    return await asyncio.to_thread(
        bcrypt.checkpw,
        password.encode(),
        SecurityConfig.admin_password_hash.encode(),
    )


def create_access_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=SecurityConfig.access_token_duration_minutes
    )
    return jwt.encode(
        {"sub": subject, "exp": expire},
        SecurityConfig.secret_key,
        algorithm=SecurityConfig.algorithm,
    )


async def require_admin(token: str = Depends(oauth2_scheme)) -> None:
    try:
        payload = jwt.decode(
            token, SecurityConfig.secret_key, algorithms=[SecurityConfig.algorithm]
        )
    except JWTError:
        payload = {}
    if payload.get("sub") != ADMIN_USERNAME:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
