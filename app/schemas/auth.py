"""Pydantic schemas for authentication workflows."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.models.constants import EMAIL_MAX_LENGTH, FULL_NAME_MAX_LENGTH

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128


class APIResponse(BaseModel):
    """Base response envelope."""

    success: bool
    message: str


class ErrorResponse(APIResponse):
    """Standard error response envelope."""

    success: bool = False


class RegisterRequest(BaseModel):
    """Request payload for user registration."""

    full_name: str = Field(..., min_length=1, max_length=FULL_NAME_MAX_LENGTH)
    email: EmailStr = Field(..., max_length=EMAIL_MAX_LENGTH)
    password: str = Field(..., min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
    confirm_password: str = Field(..., min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str) -> str:
        """Normalize whitespace around a user's full name."""
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("Full name cannot be empty.")
        return normalized_value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        """Normalize email casing for consistent lookup."""
        return value.lower()

    @model_validator(mode="after")
    def validate_password_confirmation(self) -> "RegisterRequest":
        """Ensure password confirmation matches the password."""
        if self.password != self.confirm_password:
            raise ValueError("Password and confirm password do not match.")
        return self


class LoginRequest(BaseModel):
    """Request payload for user login."""

    email: EmailStr = Field(..., max_length=EMAIL_MAX_LENGTH)
    password: str = Field(..., min_length=1, max_length=PASSWORD_MAX_LENGTH)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        """Normalize email casing for consistent lookup."""
        return value.lower()


class ProfileUpdateRequest(BaseModel):
    """Request payload for updating the authenticated user's profile."""

    full_name: str = Field(..., min_length=1, max_length=FULL_NAME_MAX_LENGTH)

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str) -> str:
        """Normalize whitespace around a user's full name."""
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("Full name cannot be empty.")
        return normalized_value


class ChangePasswordRequest(BaseModel):
    """Request payload for changing an authenticated user's password."""

    current_password: str = Field(..., min_length=1, max_length=PASSWORD_MAX_LENGTH)
    new_password: str = Field(..., min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
    confirm_password: str = Field(..., min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)

    @model_validator(mode="after")
    def validate_password_confirmation(self) -> "ChangePasswordRequest":
        """Ensure new password confirmation matches."""
        if self.new_password != self.confirm_password:
            raise ValueError("New password and confirm password do not match.")
        return self


class AuthUser(BaseModel):
    """Authenticated user data exposed in auth responses."""

    id: int
    full_name: str
    email: EmailStr

    model_config = ConfigDict(from_attributes=True)


class UserProfile(AuthUser):
    """Authenticated user profile response data."""

    is_active: bool
    created_at: datetime
    updated_at: datetime


class LoginData(BaseModel):
    """JWT login response data."""

    access_token: str
    token_type: str = "bearer"
    user: AuthUser


class RegisterResponse(APIResponse):
    """Registration response envelope."""

    success: bool = True
    data: AuthUser


class LoginResponse(APIResponse):
    """Login response envelope."""

    success: bool = True
    data: LoginData


class UserProfileResponse(APIResponse):
    """Authenticated profile response envelope."""

    success: bool = True
    data: UserProfile


class MessageResponse(APIResponse):
    """Response envelope for successful commands without data."""

    success: bool = True
    data: dict[str, Any] | None = None
