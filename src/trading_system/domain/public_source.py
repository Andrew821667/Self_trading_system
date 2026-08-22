from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class LegalUseStatus(StrEnum):
    """TZ 5.3 / 6.1. Enforced by ingestion, not decided per-document at use time."""

    ALLOWED = "allowed"
    ATTRIBUTION_REQUIRED = "attribution_required"
    METADATA_ONLY = "metadata_only"
    PROHIBITED = "prohibited"


class PublicSource(BaseModel):
    """TZ 5.3. Registered artifact for one fetched document/version.

    published_at is the source clock; first_seen_at is ours. They are
    comparable only after accounting for measured source lag (TZ 2.6).
    """

    model_config = ConfigDict(frozen=True)

    source_id: str
    source_type: str
    issuer_id: str | None = None
    url: str
    external_registry_id: str | None = None
    published_at: datetime | None = None
    first_seen_at: datetime
    content_hash: str
    storage_uri: str
    version: int
    legal_use_status: LegalUseStatus
