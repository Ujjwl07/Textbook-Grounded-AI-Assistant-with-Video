"""Authentication backed by Clerk.

Clerk owns sign-in and sign-up. The frontend sends Clerk's short-lived session
token as ``Authorization: Bearer <token>``; this module verifies it and maps the
Clerk user onto the app's own MongoDB user record (which holds quiz progress,
videos, etc.). The first time a Clerk user is seen, an existing record with the
same email is linked to them, so accounts from the old email/password login keep
their data. Otherwise a fresh record is created.

Clerk session tokens expire after about a minute, which is too short for a
``<video>`` element that keeps issuing range requests. For that one case the API
mints its own longer-lived, read-only "media" token (see ``create_media_token``).
"""

import logging
from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4

from clerk_backend_api import Clerk
from clerk_backend_api.security import VerifyTokenOptions, verify_token_async
from clerk_backend_api.security.types import TokenVerificationError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.core.config import get_settings
from app.models.schemas import UserPublic
from app.services.database import database

logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer(auto_error=False)

MEDIA_TOKEN_TYPE = "media"


def _credentials_exception(detail: str = "Could not validate credentials") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


class AuthService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._clerk: Optional[Clerk] = None

    @property
    def clerk(self) -> Clerk:
        if not self.settings.clerk_secret_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="CLERK_SECRET_KEY is not configured on the server",
            )
        if self._clerk is None:
            self._clerk = Clerk(bearer_auth=self.settings.clerk_secret_key)
        return self._clerk

    # ---- Clerk session tokens -------------------------------------------------

    async def verify_clerk_token(self, token: str) -> str:
        """Verify a Clerk session token and return the Clerk user id (``sub``)."""
        if not self.settings.clerk_secret_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="CLERK_SECRET_KEY is not configured on the server",
            )
        try:
            claims = await verify_token_async(
                token,
                VerifyTokenOptions(
                    secret_key=self.settings.clerk_secret_key,
                    authorized_parties=self.settings.cors_origins or None,
                ),
            )
        except TokenVerificationError as exc:
            logger.info("Rejected Clerk token: %s", exc)
            raise _credentials_exception() from exc
        clerk_user_id = claims.get("sub")
        if not clerk_user_id:
            raise _credentials_exception()
        return clerk_user_id

    async def get_or_create_user(self, clerk_user_id: str) -> dict:
        """Return the app's user record for a Clerk user, creating/linking it on first sight."""
        user = await database.get_user_by_clerk_id(clerk_user_id)
        if user:
            return user

        clerk_user = await self.clerk.users.get_async(user_id=clerk_user_id)
        email = self._primary_email(clerk_user)
        if not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Your Clerk account has no email address",
            )
        name = self._display_name(clerk_user, email)

        existing = await database.get_user_by_email(email)
        if existing:
            # Account from the old email/password login: keep its data, link it to Clerk.
            await database.update_user(existing["id"], {"clerk_id": clerk_user_id})
            logger.info("Linked existing user %s to Clerk user %s", existing["id"], clerk_user_id)
            return await database.get_user_by_clerk_id(clerk_user_id)

        now = datetime.utcnow()
        user = {
            "id": str(uuid4()),
            "clerk_id": clerk_user_id,
            "name": name,
            "email": email,
            "created_at": now,
            "updated_at": now,
            "is_active": True,
            # Student learning data
            "ability": 0.0,
            "topic_mastery": {},
            "response_history": [],
            "videos_watched": 0,
        }
        await database.create_user(user)
        logger.info("Created user %s for Clerk user %s", user["id"], clerk_user_id)
        return await database.get_user_by_clerk_id(clerk_user_id)

    @staticmethod
    def _primary_email(clerk_user) -> Optional[str]:
        addresses = clerk_user.email_addresses or []
        primary = next(
            (a for a in addresses if a.id == clerk_user.primary_email_address_id),
            addresses[0] if addresses else None,
        )
        return primary.email_address.lower().strip() if primary else None

    @staticmethod
    def _display_name(clerk_user, email: str) -> str:
        full = " ".join(p for p in (clerk_user.first_name, clerk_user.last_name) if p).strip()
        return full or clerk_user.username or email.split("@")[0]

    # ---- Media tokens (for <video src> streaming) -------------------------------

    def create_media_token(self, user_id: str, expires_delta: Optional[timedelta] = None) -> str:
        expire = datetime.utcnow() + (
            expires_delta or timedelta(minutes=self.settings.access_token_expire_minutes)
        )
        payload = {"sub": user_id, "exp": expire, "type": MEDIA_TOKEN_TYPE}
        return jwt.encode(payload, self.settings.jwt_secret_key, algorithm=self.settings.jwt_algorithm)

    async def user_from_media_token(self, token: str) -> Optional[dict]:
        """Return the user for a valid media token, or None if this isn't one."""
        try:
            payload = jwt.decode(
                token, self.settings.jwt_secret_key, algorithms=[self.settings.jwt_algorithm]
            )
        except JWTError:
            return None
        if payload.get("type") != MEDIA_TOKEN_TYPE or not payload.get("sub"):
            return None
        return await database.get_user_by_id(payload["sub"])

    # ---- Shared -------------------------------------------------------------------

    async def user_from_clerk_token(self, token: str) -> dict:
        clerk_user_id = await self.verify_clerk_token(token)
        user = await self.get_or_create_user(clerk_user_id)
        if not user.get("is_active", True):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")
        return user

    def to_public_user(self, user: dict) -> UserPublic:
        return UserPublic(
            id=user["id"],
            name=user["name"],
            email=user["email"],
            is_admin=user.get("is_admin", False),
            created_at=user["created_at"],
            streak_days=user.get("streak_days", 0),
        )


auth_service = AuthService()


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    """FastAPI dependency: the signed-in user, from a Clerk session token."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _credentials_exception("Not authenticated")
    return await auth_service.user_from_clerk_token(credentials.credentials)


async def get_user_from_token(token: str) -> dict:
    """For WebSockets and media streams, where the token arrives as a query param.

    Accepts either a Clerk session token or a media token from /auth/media-token.
    """
    user = await auth_service.user_from_media_token(token)
    if user:
        return user
    return await auth_service.user_from_clerk_token(token)
