"""Public parser contract for crypt-filter position and indirect parameters."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest

from powercontext.sources.pdf_pages import PDFDocumentInput, parse_pdf_document


def _build_fixture(**options):
    path = Path(__file__).with_name("crypt_identity_fixtures_v2.py")
    spec = importlib.util.spec_from_file_location("independent_crypt_identity_contract_fixtures", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_fixture(flate=True, **options)


@pytest.mark.parametrize(
    "options",
    (
        {"parameter_shape": "indirect-array"},
        {"parameter_shape": "indirect-dictionary"},
        {"null_crypt_parameters": True},
    ),
    ids=("indirect-array", "indirect-dictionary", "null-name-and-type"),
)
def test_legitimate_indirect_crypt_parameters_preserve_complete_pages(options) -> None:
    fixture = _build_fixture(**options)
    assert fixture["implicit_stream_really_encrypted"]
    assert fixture["explicit_stream_data_plain"]
    assert len(fixture["dictionary_strings_verified_encrypted"]) == 2
    content = fixture["content"]
    pages = parse_pdf_document(PDFDocumentInput(document_id="indirect-crypt-fixture", content=content))
    assert isinstance(pages, tuple)
    assert [page.page_number for page in pages] == [1, 2]
    assert tuple(page.text.strip() for page in pages) == fixture["expected_texts"]
    assert all(page.document_id == "indirect-crypt-fixture" for page in pages)
    assert all(page.document_sha256 == hashlib.sha256(content).hexdigest() for page in pages)


@pytest.mark.parametrize(
    "options",
    (
        {"crypt_placement": "after-flate"},
        {"crypt_placement": "duplicate"},
        {"parameter_shape": "missing-tail-null"},
    ),
    ids=("crypt-not-first", "crypt-duplicated", "missing-filter-parameter"),
)
def test_invalid_crypt_filter_structure_fails_atomically(options) -> None:
    fixture = _build_fixture(global_identity=True, **options)
    assert len(fixture["dictionary_strings_verified_encrypted"]) == 2
    with pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id="invalid-crypt-fixture", content=fixture["content"]))
