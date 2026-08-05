from __future__ import annotations

from hashlib import sha256
from io import BytesIO

import pytest

from app.core.errors import ApiError
from app.services import pdf_validation
from app.services.pdf_validation import MAX_PDF_BYTES, validate_pdf
from tests.pdf_factory import build_pdf


def test_accepts_small_text_pdf() -> None:
    content = build_pdf()

    result = validate_pdf(content, "application/pdf")

    assert result.content == content
    assert result.page_count == 1
    assert result.sha256 == sha256(content).hexdigest()


def test_accepts_pdf_at_exact_size_limit() -> None:
    content = build_pdf()
    content += b"\x00" * (MAX_PDF_BYTES - len(content))

    result = validate_pdf(content, "application/pdf")

    assert len(result.content) == MAX_PDF_BYTES


def test_accepts_pdf_at_exact_page_limit() -> None:
    result = validate_pdf(build_pdf(pages=30), "application/pdf")

    assert result.page_count == 30


@pytest.mark.parametrize("content_type", [None, "", "text/plain", "image/png"])
def test_rejects_invalid_content_type_before_inspecting_content(content_type: str | None) -> None:
    with pytest.raises(ApiError) as error:
        validate_pdf(b"not pdf", content_type)

    assert error.value.code == "INVALID_CONTENT_TYPE"


def test_rejects_oversized_content_before_signature_check() -> None:
    with pytest.raises(ApiError) as error:
        validate_pdf(b"x" * (MAX_PDF_BYTES + 1), "application/pdf")

    assert error.value.code == "FILE_TOO_LARGE"


def test_rejects_invalid_signature() -> None:
    with pytest.raises(ApiError) as error:
        validate_pdf(b"not pdf", "application/pdf")

    assert error.value.code == "INVALID_PDF_SIGNATURE"


def test_rejects_encrypted_pdf() -> None:
    with pytest.raises(ApiError) as error:
        validate_pdf(build_pdf(password="secret"), "application/pdf")

    assert error.value.code == "ENCRYPTED_PDF_UNSUPPORTED"


def test_rejects_parser_failure() -> None:
    with pytest.raises(ApiError) as error:
        validate_pdf(b"%PDF-fake", "application/pdf")

    assert error.value.code == "INVALID_PDF"


def test_rejects_pdf_over_page_limit_before_text_check() -> None:
    with pytest.raises(ApiError) as error:
        validate_pdf(build_pdf(pages=31, text=None), "application/pdf")

    assert error.value.code == "PDF_TOO_LONG"


def test_rejects_pdf_without_extractable_text() -> None:
    with pytest.raises(ApiError) as error:
        validate_pdf(build_pdf(text=None), "application/pdf")

    assert error.value.code == "SCANNED_PDF_UNSUPPORTED"


def test_maps_reader_constructor_exception_to_invalid_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(content: BytesIO):
        raise RuntimeError("unexpected parser failure")

    monkeypatch.setattr(pdf_validation, "PdfReader", explode)

    with pytest.raises(ApiError) as error:
        validate_pdf(b"%PDF-valid-enough-for-boundary", "application/pdf")

    assert error.value.code == "INVALID_PDF"


def test_maps_encryption_check_exception_to_invalid_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    class Reader:
        @property
        def is_encrypted(self) -> bool:
            raise RuntimeError("unexpected encryption failure")

    monkeypatch.setattr(pdf_validation, "PdfReader", lambda content: Reader())

    with pytest.raises(ApiError) as error:
        validate_pdf(b"%PDF-valid-enough-for-boundary", "application/pdf")

    assert error.value.code == "INVALID_PDF"


def test_maps_pages_exception_to_invalid_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    class Reader:
        is_encrypted = False

        @property
        def pages(self):
            raise RuntimeError("unexpected pages failure")

    monkeypatch.setattr(pdf_validation, "PdfReader", lambda content: Reader())

    with pytest.raises(ApiError) as error:
        validate_pdf(b"%PDF-valid-enough-for-boundary", "application/pdf")

    assert error.value.code == "INVALID_PDF"


def test_maps_text_extraction_exception_to_invalid_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    class Page:
        def extract_text(self) -> str:
            raise RuntimeError("unexpected text failure")

    class Reader:
        is_encrypted = False
        pages = [Page()]

    monkeypatch.setattr(pdf_validation, "PdfReader", lambda content: Reader())

    with pytest.raises(ApiError) as error:
        validate_pdf(b"%PDF-valid-enough-for-boundary", "application/pdf")

    assert error.value.code == "INVALID_PDF"
