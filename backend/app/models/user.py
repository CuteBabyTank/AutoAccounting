import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Boolean, ForeignKey, Enum as SAEnum, Integer, Float, LargeBinary
from sqlalchemy.orm import Mapped, deferred, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB
import enum

from app.database import Base


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    ENTERPRISE = "enterprise"
    MANAGER = "manager"
    EMPLOYEE = "employee"
    UNVERIFIED = "unverified"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)

    # Role-based access
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=UserRole.UNVERIFIED,
        server_default="unverified",
    )
    enterprise_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    organization_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    nickname: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Privacy policy accepted at sign-up (version = its effective date); NULL for accounts made before consent existed.
    privacy_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    privacy_policy_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Profile picture: a small square WebP (services/avatar_service). Deferred so the per-request user load skips it;
    # load it with `db.refresh(user, ["avatar"])`.
    avatar: Mapped[bytes | None] = deferred(mapped_column(LargeBinary, nullable=True), raiseload=True)

    # Usage caps
    usage_cap: Mapped[int | None] = mapped_column(Integer, nullable=True)
    global_usage_cap: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Billing
    page_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    special_page_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Tiered pricing config. When set, takes precedence over page_rate / special_page_rate.
    # Shape: [{"up_to": int|None, "rate": float}, ...] sorted by up_to ascending; trailing
    # null up_to = unbounded last tier. Tiers apply per document: each file walks
    # the ladder from page 1 independent of monthly history.
    page_rate_tiers: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    budget: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    employees = relationship("User", back_populates="enterprise", foreign_keys=[enterprise_id])
    enterprise = relationship("User", remote_side=[id], foreign_keys=[enterprise_id])
