"""Authentication business logic."""

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from fastapi import HTTPException, status

from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.auth import (
    AuthUser,
    ChangePasswordRequest,
    LoginData,
    LoginRequest,
    ProfileUpdateRequest,
    RegisterRequest,
    UserProfile,
)

logger = logging.getLogger(__name__)


class AuthService:
    """Service containing authentication workflows."""

    def __init__(self, db: Session) -> None:
        """Initialize the service with a database session."""
        self.db = db

    def register_user(self, payload: RegisterRequest) -> AuthUser:
        """Register a new user with a securely hashed password."""
        if self._get_user_by_email(payload.email) is not None:
            logger.info("Registration rejected because account already exists")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A user with this email already exists.",
            )

        user = User(
            full_name=payload.full_name,
            email=payload.email,
            hashed_password=hash_password(payload.password),
        )
        self.db.add(user)

        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            logger.warning("Registration failed due to unique constraint")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A user with this email already exists.",
            ) from exc

        self.db.refresh(user)
        logger.info("User registered successfully user_id=%s", user.id)
        return AuthUser.model_validate(user)

    def login_user(self, payload: LoginRequest) -> LoginData:
        """Authenticate a user and issue a JWT access token."""
        user = self._get_user_by_email(payload.email)
        if user is None or not verify_password(payload.password, user.hashed_password):
            logger.warning("Login failed due to invalid credentials")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not user.is_active:
            logger.warning("Login rejected for inactive user_id=%s", user.id)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive.",
            )

        access_token = create_access_token(subject=user.id)
        logger.info("Login successful user_id=%s", user.id)
        return LoginData(access_token=access_token, user=AuthUser.model_validate(user))

    def get_profile(self, user: User) -> UserProfile:
        """Return the authenticated user's profile."""
        return UserProfile.model_validate(user)

    def update_profile(self, user: User, payload: ProfileUpdateRequest) -> UserProfile:
        """Update editable profile fields for the authenticated user."""
        user.full_name = payload.full_name
        self.db.commit()
        self.db.refresh(user)
        logger.info("Profile updated user_id=%s", user.id)
        return UserProfile.model_validate(user)

    def change_password(self, user: User, payload: ChangePasswordRequest) -> None:
        """Change the authenticated user's password after verifying the current password."""
        if not verify_password(payload.current_password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect.",
            )

        user.hashed_password = hash_password(payload.new_password)
        self.db.commit()
        logger.info("Password changed user_id=%s", user.id)

    def _get_user_by_email(self, email: str) -> User | None:
        """Return a user by normalized email address."""
        return self.db.scalar(select(User).where(User.email == email.lower()))
