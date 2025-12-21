from typing import Annotated
from datetime import datetime, timedelta, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

from app.utils.logger import logger
from app.database import MongoDBConnectionManager
from app.config import SecurityConfig


class Token(BaseModel):
    access_token: str
    token_type: str


class User(BaseModel):
    username: str
    disabled: bool = False


class UserInDB(User):
    hashed_password: str


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


async def get_user(db: AsyncIOMotorDatabase, username: str) -> UserInDB | None:
    user = await db.users.find_one({"username": username})
    if not user:
        return None
    return UserInDB(**user)


async def authenticate_user(
    db: AsyncIOMotorDatabase, username: str, password: str
) -> UserInDB | None:
    user = await get_user(db, username)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=SecurityConfig.access_token_duration_minutes
        )
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode, SecurityConfig.secret_key, algorithm=SecurityConfig.algorithm
    )
    return encoded_jwt


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, SecurityConfig.secret_key, algorithms=[SecurityConfig.algorithm]
        )
        username: str = payload.get("sub", "")
        if username == "":
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    async with MongoDBConnectionManager() as db:
        user = await get_user(db, username=username)
    if user is None:
        raise credentials_exception

    return user


async def current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


async def create_admin_user(db: AsyncIOMotorDatabase) -> User | None:
    """Create admin user from ADMIN_PASSWORD_HASH env var on first run."""
    async with MongoDBConnectionManager() as db:
        user = await db.users.find_one({"username": "admin"})
        if user:
            return None

        if not SecurityConfig.admin_password_hash:
            logger.warning("ADMIN_PASSWORD_HASH not set, skipping admin user creation")
            return None

        admin_user = UserInDB(
            username="admin",
            hashed_password=SecurityConfig.admin_password_hash,
            disabled=False,
        )
        await db.users.insert_one(admin_user.model_dump())
        logger.info("Admin user created")

        return User(**admin_user.model_dump())
