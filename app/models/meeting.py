"""Meeting database model."""

from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, Enum, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.database import Base
from app.models.constants import FILE_EXTENSION_MAX_LENGTH, FILENAME_MAX_LENGTH, TITLE_MAX_LENGTH
from app.models.enums import ProcessingStatus
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.action_item import ActionItem
    from app.models.chat_history import ChatHistory
    from app.models.user import User


class Meeting(TimestampMixin, Base):
    """Uploaded meeting and its future AI-generated analysis."""

    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)

    title: Mapped[str] = mapped_column(String(TITLE_MAX_LENGTH), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(FILENAME_MAX_LENGTH), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(FILENAME_MAX_LENGTH), nullable=False)
    file_extension: Mapped[str] = mapped_column(String(FILE_EXTENSION_MAX_LENGTH), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    executive_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_points: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    key_decisions: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    participants: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    deadlines: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    risks: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    next_steps: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    processing_status: Mapped[ProcessingStatus] = mapped_column(
        Enum(ProcessingStatus, name="processing_status", validate_strings=True),
        default=ProcessingStatus.UPLOADED,
        index=True,
        nullable=False,
    )
    processing_progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    owner: Mapped["User"] = relationship("User", back_populates="meetings")
    action_items: Mapped[list["ActionItem"]] = relationship(
        "ActionItem",
        back_populates="meeting",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    chat_history: Mapped[list["ChatHistory"]] = relationship(
        "ChatHistory",
        back_populates="meeting",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
