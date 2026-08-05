"""Safe complete configuration available before API modules are imported."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.pdf_factory import build_pdf
from tests.postgres_test_support import acquire_test_schema_lock, get_test_database_url


os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("SUPABASE_URL", "https://project.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("WEB_ORIGIN", "https://web.example")


@pytest.fixture
def locked_test_database_url():
    """Serialize every test that upgrades/downgrades admission_coach_test."""
    database_url = get_test_database_url()
    lock = acquire_test_schema_lock(database_url)
    try:
        yield database_url
    finally:
        lock.release()


@pytest.fixture
def text_pdf_bytes() -> bytes:
    """Provide a deterministic one-page PDF with extractable text."""
    return build_pdf()


@pytest.fixture
def text_pdf_path(tmp_path: Path, text_pdf_bytes: bytes) -> Path:
    """Provide the shared valid upload fixture required by document API tests."""
    path = tmp_path / "text.pdf"
    path.write_bytes(text_pdf_bytes)
    return path
