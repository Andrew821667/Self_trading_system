from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from trading_system.domain import LegalUseStatus, PublicSource


def make_source(**overrides: object) -> PublicSource:
    fields = dict(
        source_id="src-1",
        source_type="disclosure_center",
        url="https://e-disclosure.ru/example",
        first_seen_at=datetime(2026, 1, 1, tzinfo=UTC),
        content_hash="abc123",
        storage_uri="s3://documents/src-1/v1",
        version=1,
        legal_use_status=LegalUseStatus.ALLOWED,
    )
    fields.update(overrides)
    return PublicSource(**fields)


def test_round_trip() -> None:
    source = make_source()
    assert source.legal_use_status is LegalUseStatus.ALLOWED


def test_rejects_unknown_legal_use_status() -> None:
    with pytest.raises(ValidationError):
        make_source(legal_use_status="maybe_ok")
