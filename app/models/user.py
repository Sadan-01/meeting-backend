"""User database model."""

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.database import Base
from app.models.constants import EMAIL_MAX_LENGTH, FULL_NAME_MAX_LENGTH, PASSWORD_HASH_MAX_LENGTH
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.meeting import Meeting


class User(TimestampMixin, Base):
    """Application user that owns meetings."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    full_name: Mapped[str] = mapped_column(String(FULL_NAME_MAX_LENGTH), nullable=False)
    email: Mapped[str] = mapped_column(String(EMAIL_MAX_LENGTH), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(PASSWORD_HASH_MAX_LENGTH), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    meetings: Mapped[list["Meeting"]] = relationship(
        "Meeting",
        back_populates="owner",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
