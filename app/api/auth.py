"""Authentication API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.database.database import get_db
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    MessageResponse,
    ProfileUpdateRequest,
    RegisterRequest,
    RegisterResponse,
    UserProfileResponse,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


def get_auth_service(db: Annotated[Session, Depends(get_db)]) -> AuthService:
    """Provide the authentication service."""
    return AuthService(db)


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    description="Create a secure user account with a bcrypt-hashed password.",
)
def register(
    payload: RegisterRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> RegisterResponse:
    """Register a new user account."""
    user = auth_service.register_user(payload)
    return RegisterResponse(message="Registration successful.", data=user)


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Login user",
    description="Authenticate a user with email and password, then return a JWT access token.",
)
def login(
    payload: LoginRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> LoginResponse:
    """Authenticate a user and return a bearer token."""
    login_data = auth_service.login_user(payload)
    return LoginResponse(message="Login successful.", data=login_data)


@router.get(
    "/me",
    response_model=UserProfileResponse,
    summary="Get current user",
    description="Return the profile for the user authenticated by the Bearer token.",
)
def read_current_user(
    current_user: Annotated[User, Depends(get_current_user)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> UserProfileResponse:
    """Return the authenticated user's profile."""
    profile = auth_service.get_profile(current_user)
    return UserProfileResponse(message="Authenticated user profile retrieved.", data=profile)


@router.put(
    "/profile",
    response_model=UserProfileResponse,
    summary="Update current user profile",
    description="Update the authenticated user's profile. Email updates are not allowed.",
)
def update_profile(
    payload: ProfileUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> UserProfileResponse:
    """Update the authenticated user's editable profile fields."""
    profile = auth_service.update_profile(current_user, payload)
    return UserProfileResponse(message="Profile updated successfully.", data=profile)


@router.put(
    "/change-password",
    response_model=MessageResponse,
    summary="Change current user password",
    description="Change the authenticated user's password after verifying the current password.",
)
def change_password(
    payload: ChangePasswordRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> MessageResponse:
    """Change the authenticated user's password."""
    auth_service.change_password(current_user, payload)
    return MessageResponse(message="Password changed successfully.")
