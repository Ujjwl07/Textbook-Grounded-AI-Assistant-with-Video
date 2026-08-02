from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings
from app.models.schemas import UserPublic
from app.services.cache_manager import cache_manager


# Use pbkdf2_sha256 for stable cross-platform hashing without bcrypt backend issues.
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


class AuthService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def hash_password(self, password: str) -> str:
        return pwd_context.hash(password)

    def verify_password(self, plain_password: str, password_hash: str) -> bool:
        return pwd_context.verify(plain_password, password_hash)

    def create_access_token(self, user_id: str, expires_delta: Optional[timedelta] = None) -> str:
        expire = datetime.utcnow() + (
            expires_delta or timedelta(minutes=self.settings.access_token_expire_minutes)
        )
        payload = {"sub": user_id, "exp": expire, "type": "access"}
        return jwt.encode(payload, self.settings.jwt_secret_key, algorithm=self.settings.jwt_algorithm)

    async def register_user(self, name: str, email: str, password: str) -> dict:
        normalized_email = email.lower().strip()
        existing = await cache_manager.get_user_by_email(normalized_email)
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

        now = datetime.utcnow()
        user = {
            "id": str(uuid4()),
            "name": name.strip(),
            "email": normalized_email,
            "password_hash": self.hash_password(password),
            "created_at": now,
            "updated_at": now,
            "is_active": True,
        }
        await cache_manager.create_user(user)
        return user

    async def authenticate_user(self, email: str, password: str) -> dict:
        user = await cache_manager.get_user_by_email(email.lower().strip())
        if not user or not self.verify_password(password, user["password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not user.get("is_active", True):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")
        return user

    def to_public_user(self, user: dict) -> UserPublic:
        return UserPublic(
            id=user["id"],
            name=user["name"],
            email=user["email"],
            created_at=user["created_at"],
        )


auth_service = AuthService()


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        settings = get_settings()
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        user_id = payload.get("sub")
        token_type = payload.get("type")
        if not user_id or token_type != "access":
            raise credentials_exception
    except JWTError as exc:
        raise credentials_exception from exc

    user = await cache_manager.get_user_by_id(user_id)
    if not user:
        raise credentials_exception
    return user
