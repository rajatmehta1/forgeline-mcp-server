"""Blanket MCP Server — Data models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field

class PolicyCategory(str, Enum):
    SECURITY = "security"
    QUALITY = "quality"
    COMPLIANCE = "compliance"
    ARCHITECTURE = "architecture"
    CUSTOM = "custom"

class PolicySeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class EventType(str, Enum):
    POLICY_INJECTION = "policy_injection"
    POLICY_SKIPPED = "policy_skipped"
    NO_MATCH = "no_match"

class Policy(BaseModel):
    id: UUID
    name: str
    slug: str
    description: str | None = None
    category: PolicyCategory
    severity: PolicySeverity
    prompt_injection_text: str

class Policy(BaseModel):
    id: UUID
    name: str
    slug: str
    description: str | None = None
    category: PolicyCategory
    severity: PolicySeverity
    prompt_injection_text: str
    tags: list[str] = Field(default_factory=list)
    applies_to_languages: list[str] = Field(default_factory=list)
    applies_to_frameworks: list[str] = Field(default_factory=list)
    is_template: bool = False


class PolicyContext(BaseModel):
    """Input context for policy matching."""

    project_slug: str | None = None
    language: str | None = None
    framework: str | None = None
    categories: list[PolicyCategory] | None = None
    severities: list[PolicySeverity] | None = None
    tags: list[str] | None = None


class EnforcementResult(BaseModel):
    """Result of a policy enforcement run."""

    policies_applied: list[Policy]
    policies_count: int
    injection_text: str
    event_type: EventType
    processing_ms: int


class AuthContext(BaseModel):
    """Resolved authentication context."""

    org_id: UUID
    api_key_id: UUID
    org_name: str
    org_plan: str
