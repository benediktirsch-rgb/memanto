"""
Session Models for MEMANTO

Defines session-based authentication models for the new architecture.
Replaces tenant_id with Moorcheh API key-based identity.
"""

from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from memanto.app.utils.temporal_helpers import as_utc_aware, utc_now


class SessionStatus(str, Enum):
    """Session status enum"""

    ACTIVE = "active"
    EXPIRED = "expired"
    TERMINATED = "terminated"


class AgentPattern(str, Enum):
    """Agent pattern types for memory organization"""

    SUPPORT = "support"
    PROJECT = "project"
    TOOL = "tool"


class AgentProvider(str, Enum):
    """Model provider an avatar speaks through."""

    CLAUDE = "claude"
    OPENAI = "openai"
    OTHER = "other"


class AgentAvatar(BaseModel):
    """
    Persona shown for an agent in the CLI and web UI.

    An avatar gives an agent a face: a display name (``John``), the model
    provider behind it (``claude``) and an optional glyph/colour. Switching
    avatars means activating the agent that carries that avatar — memories
    stay in the agent's own namespace, so John and Madeleine never mix.
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=40,
        description="Display name of the persona (e.g. John, Madeleine)",
    )
    provider: AgentProvider = Field(
        default=AgentProvider.OTHER,
        description="Model provider behind the persona",
    )
    emoji: str | None = Field(
        default=None,
        max_length=8,
        description="Optional glyph shown in the UI; falls back to initials",
    )
    color: str | None = Field(
        default=None,
        pattern=r"^#[0-9a-fA-F]{6}$",
        description="Optional accent colour as #RRGGBB",
    )

    @field_validator("name", mode="before")
    @classmethod
    def _strip_name(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip()
        return v

    @field_validator("emoji", mode="before")
    @classmethod
    def _blank_emoji_is_none(cls, v: Any) -> Any:
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @property
    def initials(self) -> str:
        """Two-letter fallback glyph when no emoji is set."""
        parts = [p for p in self.name.split() if p]
        if not parts:
            return "?"
        if len(parts) == 1:
            return parts[0][:2].upper()
        return (parts[0][0] + parts[-1][0]).upper()


# Built-in personas. ``memanto agent create john --avatar john`` or
# ``memanto avatar set <agent> --preset madeleine`` copy one of these onto an
# agent; the copy can then be edited freely.
AVATAR_PRESETS: dict[str, AgentAvatar] = {
    "john": AgentAvatar(
        name="John", provider=AgentProvider.CLAUDE, emoji="🧭", color="#d97757"
    ),
    "madeleine": AgentAvatar(
        name="Madeleine", provider=AgentProvider.OPENAI, emoji="👩", color="#10a37f"
    ),
}


def get_avatar_preset(key: str) -> AgentAvatar | None:
    """Return a copy of a built-in avatar preset, or None if unknown."""
    preset = AVATAR_PRESETS.get(key.strip().lower())
    return preset.model_copy() if preset else None


class SessionCreate(BaseModel):
    """Request to create/activate a session"""

    agent_id: str = Field(..., description="Agent identifier")
    duration_hours: int | None = Field(
        default=None,
        description="Session duration in hours (default: from server config)",
    )


class SessionToken(BaseModel):
    """JWT token payload structure"""

    agent_id: str
    namespace: str
    session_id: str
    started_at: datetime
    expires_at: datetime


class Session(BaseModel):
    """Active session information"""

    session_id: str
    session_token: str
    agent_id: str
    namespace: str
    started_at: datetime
    expires_at: datetime
    pattern: AgentPattern | None = None
    status: SessionStatus = SessionStatus.ACTIVE
    metadata: dict[str, Any] | None = None

    def is_expired(self) -> bool:
        """Check if session is expired"""
        return utc_now() > as_utc_aware(self.expires_at)

    def is_active(self) -> bool:
        """Check if session is active"""
        return self.status == SessionStatus.ACTIVE and not self.is_expired()

    def time_remaining(self) -> timedelta:
        """Get time remaining in session"""
        return as_utc_aware(self.expires_at) - utc_now()


class SessionInfo(BaseModel):
    """Session information response"""

    session_id: str
    agent_id: str
    namespace: str
    started_at: datetime
    expires_at: datetime
    status: SessionStatus
    time_remaining_seconds: int
    pattern: AgentPattern | None = None
    avatar: AgentAvatar | None = None


class SessionSummary(BaseModel):
    """Summary of ended session"""

    session_id: str
    agent_id: str
    started_at: datetime
    ended_at: datetime
    duration_hours: float
    memories_created: int
    summary_memory_id: str | None = None


class AgentCreate(BaseModel):
    """Request to create a new agent"""

    agent_id: str = Field(
        ...,
        description="Unique agent identifier (alphanumeric, hyphens, underscores)",
        pattern=r"^[a-zA-Z0-9_-]+$",
    )
    pattern: AgentPattern = Field(
        default=AgentPattern.SUPPORT,
        description="Agent pattern for memory organization",
    )
    description: str | None = Field(
        None, description="Human-readable description of the agent"
    )
    avatar: AgentAvatar | None = Field(
        None, description="Optional persona shown for this agent"
    )


class AgentInfo(BaseModel):
    """Agent information"""

    agent_id: str
    namespace: str
    pattern: AgentPattern
    description: str | None = None
    avatar: AgentAvatar | None = None
    created_at: datetime
    last_session: datetime | None = None
    memory_count: int = 0
    session_count: int = 0
    status: str = "inactive"

    @field_validator("created_at", "last_session", mode="after")
    @classmethod
    def normalize_datetime(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return None
        return as_utc_aware(v)


class AgentList(BaseModel):
    """List of agents"""

    agents: list[AgentInfo]
    count: int
    warnings: list[str] = Field(default_factory=list)
