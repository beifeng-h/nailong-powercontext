# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Compressed page streams must be complete without rejecting empty pages."""

from __future__ import annotations

import hashlib
import io
import zlib
from base64 import a85encode

import pytest
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    EncodedStreamObject,
    NameObject,
    NumberObject,
)

from powercontext.sources.pdf_pages import PDFDocumentInput, parse_pdf_document


def _add_compressed_page(writer: PdfWriter, data: bytes, *, ascii85: bool = False) -> None:
    page = writer.add_blank_page(width=100, height=200)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    stream = EncodedStreamObject()
    stream._data = a85encode(data, adobe=True)[2:] if ascii85 else data
    stream[NameObject("/Filter")] = (
        ArrayObject([NameObject("/ASCII85Decode"), NameObject("/FlateDecode")])
        if ascii85
        else NameObject("/FlateDecode")
    )
    page[NameObject("/Contents")] = writer._add_object(stream)


def _document_bytes(writer: PdfWriter) -> bytes:
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.mark.parametrize("ascii85", [False, True], ids=["flate", "ascii85-flate"])
@pytest.mark.parametrize("font_resources", [False, True], ids=["fontless", "font-resources"])
@pytest.mark.parametrize(
    "data", [b"not-a-zlib-stream", zlib.compress(b"q Q")[:-2]], ids=["invalid-stream", "truncated-stream"]
)
def test_corrupt_later_page_fails_without_returning_earlier_pages(
    data: bytes, ascii85: bool, font_resources: bool
) -> None:
    writer = PdfWriter()
    _add_compressed_page(writer, zlib.compress(b"BT /F1 12 Tf (Revenue 123) Tj ET"))
    _add_compressed_page(writer, data, ascii85=ascii85)
    if not font_resources:
        del writer.pages[-1]["/Resources"]
    with pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id="corrupt-later-page", content=_document_bytes(writer)))


@pytest.mark.parametrize("encrypted", [False, True], ids=["plain", "empty-password"])
def test_blank_and_valid_compressed_empty_pages_keep_physical_order(encrypted: bool) -> None:
    writer = PdfWriter()
    _add_compressed_page(writer, zlib.compress(b"BT /F1 12 Tf (Revenue 123) Tj ET"), ascii85=True)
    writer.add_blank_page(width=100, height=200)
    _add_compressed_page(writer, zlib.compress(b"q Q"))
    _add_compressed_page(writer, zlib.compress(b""), ascii85=True)
    if encrypted:
        writer.encrypt(user_password="", owner_password="owner")
    content = _document_bytes(writer)
    pages = parse_pdf_document(PDFDocumentInput(document_id="complete-streams", content=content))
    assert [(page.page_number, page.text) for page in pages] == [(1, "Revenue 123"), (2, ""), (3, ""), (4, "")]
    assert all(page.document_sha256 == hashlib.sha256(content).hexdigest() for page in pages)


@pytest.mark.parametrize("encrypted", [False, True], ids=["plain", "empty-password"])
def test_valid_fontless_streams_and_blank_pages_are_readable(encrypted: bool) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=200)
    for data in (b"q Q", b""):
        _add_compressed_page(writer, zlib.compress(data), ascii85=True)
        del writer.pages[-1]["/Resources"]
    if encrypted:
        writer.encrypt(user_password="", owner_password="owner")
    content = _document_bytes(writer)
    pages = parse_pdf_document(PDFDocumentInput(document_id="fontless", content=content))
    assert [(page.page_number, page.text) for page in pages] == [(1, ""), (2, ""), (3, "")]
    assert all(page.document_sha256 == hashlib.sha256(content).hexdigest() for page in pages)


@pytest.mark.parametrize(
    "data, valid",
    [
        (zlib.compress(b"BT /F1 12 Tf (Revenue 123) Tj ET"), True),
        (b"not-a-zlib-stream", False),
        (zlib.compress(b"q Q")[:-2], False),
    ],
    ids=["readable-form", "invalid-form", "truncated-form"],
)
def test_form_streams_are_validated_without_duplicating_text(data: bytes, valid: bool) -> None:
    writer = PdfWriter()
    _add_compressed_page(writer, zlib.compress(b"q Q"))
    page = writer.pages[0]
    resources = page["/Resources"]
    form = EncodedStreamObject()
    form._data = data
    form[NameObject("/Filter")] = NameObject("/FlateDecode")
    form[NameObject("/Type")] = NameObject("/XObject")
    form[NameObject("/Subtype")] = NameObject("/Form")
    form[NameObject("/BBox")] = ArrayObject([NumberObject(value) for value in (0, 0, 100, 200)])
    form[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): resources["/Font"]})
    resources[NameObject("/XObject")] = DictionaryObject({NameObject("/Fm1"): writer._add_object(form)})
    stream = DecodedStreamObject()
    stream.set_data(b"q /Fm1 Do Q")
    page[NameObject("/Contents")] = writer._add_object(stream)
    value = PDFDocumentInput(document_id="form-stream", content=_document_bytes(writer))
    if not valid:
        with pytest.raises(ValueError):
            parse_pdf_document(value)
    else:
        pages = parse_pdf_document(value)
        assert len(pages) == 1
        assert pages[0].text.strip() == "Revenue 123"
