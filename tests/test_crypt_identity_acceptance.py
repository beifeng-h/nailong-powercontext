"""Public PDF-parser acceptance for independently written stream-crypt fixtures."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest

from powercontext.sources.pdf_pages import PDFDocumentInput, parse_pdf_document


def _build_fixture(**options):
    path = Path(__file__).with_name("crypt_identity_fixtures.py")
    spec = importlib.util.spec_from_file_location("independent_crypt_identity_fixtures", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_fixture(**options)


@pytest.mark.parametrize(
    "options",
    (
        {"global_identity": True, "blank": True},
        {"explicit_name": None},
        {},
        {"flate": True},
        {"explicit_name": ""},
    ),
    ids=("global-identity-blank", "implicit-aes-control", "explicit-identity", "identity-flate", "default-name"),
)
def test_legitimate_empty_password_stream_crypt_filters_preserve_complete_pages(options) -> None:
    fixture = _build_fixture(**options)
    content = fixture["content"]
    pages = parse_pdf_document(PDFDocumentInput(document_id="independent-crypt-fixture", content=content))
    assert isinstance(pages, tuple)
    assert [page.page_number for page in pages] == [1, 2]
    assert tuple(page.text.strip() for page in pages) == fixture["expected_texts"]
    assert all(page.document_id == "independent-crypt-fixture" for page in pages)
    assert all(page.document_sha256 == hashlib.sha256(content).hexdigest() for page in pages)
    assert len(fixture["dictionary_strings_verified_encrypted"]) == 2


@pytest.mark.parametrize(
    "options",
    (
        {"flate": True, "truncate_flate": True},
        {"user_password": "synthetic-user"},
        {"explicit_name": "/StdCF"},
    ),
    ids=("truncated-flate-after-identity", "nonempty-user-password", "nonidentity-crypt"),
)
def test_invalid_or_unsupported_crypt_document_fails_atomically(options) -> None:
    fixture = _build_fixture(**options)
    assert fixture["implicit_stream_really_encrypted"]
    with pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id="independent-crypt-fixture", content=fixture["content"]))
