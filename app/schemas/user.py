"""Pydantic schemas for users."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.constants import EMAIL_MAX_LENGTH, FULL_NAME_MAX_LENGTH, PASSWORD_HASH_MAX_LENGTH


class UserBase(BaseModel):
    """Shared user fields."""

    full_name: str = Field(..., min_length=1, max_length=FULL_NAME_MAX_LENGTH)
    email: EmailStr = Field(..., max_length=EMAIL_MAX_LENGTH)
    is_active: bool = True


class UserCreate(UserBase):
    """Fields required to create a user record."""

    hashed_password: str = Field(..., min_length=1, max_length=PASSWORD_HASH_MAX_LENGTH, repr=False)


class UserUpdate(BaseModel):
    """Fields allowed when updating a user record."""

    full_name: str | None = Field(default=None, min_length=1, max_length=FULL_NAME_MAX_LENGTH)
    email: EmailStr | None = Field(default=None, max_length=EMAIL_MAX_LENGTH)
    hashed_password: str | None = Field(default=None, min_length=1, max_length=PASSWORD_HASH_MAX_LENGTH, repr=False)
    is_active: bool | None = None


class UserResponse(UserBase):
    """User response fields safe to expose through APIs."""

    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
