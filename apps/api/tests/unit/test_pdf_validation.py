from __future__ import annotations

from hashlib import sha256
from io import BytesIO

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.core.errors import ApiError
from app.services.pdf_validation import MAX_PDF_BYTES, validate_pdf


def _pdf_bytes(
    *,
    pages: int = 1,
    text: str | None = "Interview evidence",
    password: str | None = None,
) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(width=612, height=792)
        if text is not None:
            font = DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }
            )
            font_ref = writer._add_object(font)
            page[NameObject("/Resources")] = DictionaryObject(
                {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
            )
            stream = DecodedStreamObject()
            stream.set_data(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii"))
            page[NameObject("/Contents")] = writer._add_object(stream)
    if password is not None:
        writer.encrypt(password)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_accepts_small_text_pdf() -> None:
    content = _pdf_bytes()

    result = validate_pdf(content, "application/pdf")

    assert result.content == content
    assert result.page_count == 1
    assert result.sha256 == sha256(content).hexdigest()


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
        validate_pdf(_pdf_bytes(password="secret"), "application/pdf")

    assert error.value.code == "ENCRYPTED_PDF_UNSUPPORTED"


def test_rejects_parser_failure() -> None:
    with pytest.raises(ApiError) as error:
        validate_pdf(b"%PDF-fake", "application/pdf")

    assert error.value.code == "INVALID_PDF"


def test_rejects_pdf_over_page_limit_before_text_check() -> None:
    with pytest.raises(ApiError) as error:
        validate_pdf(_pdf_bytes(pages=31, text=None), "application/pdf")

    assert error.value.code == "PDF_TOO_LONG"


def test_rejects_pdf_without_extractable_text() -> None:
    with pytest.raises(ApiError) as error:
        validate_pdf(_pdf_bytes(text=None), "application/pdf")

    assert error.value.code == "SCANNED_PDF_UNSUPPORTED"
