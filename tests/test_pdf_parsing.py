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


@pytest.mark.parametrize("compressed", [False, True], ids=["decoded", "flate"])
@pytest.mark.parametrize("nested", [False, True], ids=["direct-form", "nested-form"])
def test_malformed_form_syntax_fails_atomically(compressed: bool, nested: bool) -> None:
    writer = PdfWriter()
    _add_compressed_page(writer, zlib.compress(b"BT /F1 12 Tf (Earlier page 900) Tj ET"))
    _add_compressed_page(
        writer,
        zlib.compress(b"BT /F1 12 Tf (Before 123) Tj ET\nq /Fm1 Do Q\nBT /F1 12 Tf (After 456) Tj ET"),
    )
    page = writer.pages[-1]
    resources = page["/Resources"]
    form = EncodedStreamObject() if compressed else DecodedStreamObject()
    if compressed:
        form._data = zlib.compress(b"(Unterminated literal string")
        form[NameObject("/Filter")] = NameObject("/FlateDecode")
    else:
        form.set_data(b"(Unterminated literal string")
    form[NameObject("/Type")] = NameObject("/XObject")
    form[NameObject("/Subtype")] = NameObject("/Form")
    form[NameObject("/BBox")] = ArrayObject([NumberObject(value) for value in (0, 0, 100, 200)])
    form[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): resources["/Font"]})
    reference = writer._add_object(form)
    if nested:
        parent = DecodedStreamObject()
        parent.set_data(b"q /Nested Do Q")
        parent[NameObject("/Type")] = NameObject("/XObject")
        parent[NameObject("/Subtype")] = NameObject("/Form")
        parent[NameObject("/BBox")] = form["/BBox"]
        parent[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): resources["/Font"],
            NameObject("/XObject"): DictionaryObject({NameObject("/Nested"): reference}),
        })
        reference = writer._add_object(parent)
    resources[NameObject("/XObject")] = DictionaryObject({NameObject("/Fm1"): reference})
    with pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id="malformed-form-syntax", content=_document_bytes(writer)))


def test_fontless_malformed_content_syntax_fails_atomically() -> None:
    writer = PdfWriter()
    _add_compressed_page(writer, zlib.compress(b"BT /F1 12 Tf (Earlier page 900) Tj ET"))
    _add_compressed_page(writer, zlib.compress(b"(Unterminated literal string"))
    del writer.pages[-1]["/Resources"]
    with pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id="malformed-fontless-syntax", content=_document_bytes(writer)))


def test_valid_page_literal_can_span_multiple_content_streams() -> None:
    writer = PdfWriter()
    _add_compressed_page(writer, zlib.compress(b"q Q"))
    pieces = []
    for data in (b"BT /F1 12 Tf (Revenue", b" 123) Tj ET"):
        stream = DecodedStreamObject()
        stream.set_data(data)
        pieces.append(writer._add_object(stream))
    writer.pages[0][NameObject("/Contents")] = ArrayObject(pieces)
    pages = parse_pdf_document(PDFDocumentInput(document_id="split-page-content", content=_document_bytes(writer)))
    assert len(pages) == 1
    assert pages[0].text.split() == ["Revenue", "123"]


def test_valid_fontless_inline_image_remains_an_empty_physical_page() -> None:
    writer = PdfWriter()
    _add_compressed_page(writer, zlib.compress(b"BT /F1 12 Tf (Earlier page 900) Tj ET"))
    _add_compressed_page(writer, zlib.compress(b"q\nBI /W 1 /H 1 /CS /RGB /BPC 8 ID \xff\x00\x80\nEI\nQ"))
    del writer.pages[-1]["/Resources"]
    content = _document_bytes(writer)
    pages = parse_pdf_document(PDFDocumentInput(document_id="fontless-inline-image", content=content))
    assert [(page.page_number, page.text) for page in pages] == [(1, "Earlier page 900"), (2, "")]
    assert all(page.document_sha256 == hashlib.sha256(content).hexdigest() for page in pages)


@pytest.mark.parametrize("encrypted", [False, True], ids=["plain", "empty-password"])
@pytest.mark.parametrize("marker", [b"%", b"%%", b"%%E", b"%%EO"])
def test_truncated_file_end_marker_fails_atomically(marker: bytes, encrypted: bool) -> None:
    writer = PdfWriter()
    _add_compressed_page(writer, zlib.compress(b"BT /F1 12 Tf (Revenue 123) Tj ET"))
    writer.add_blank_page(width=100, height=200)
    if encrypted:
        writer.encrypt(user_password="", owner_password="owner")
    content = _document_bytes(writer)
    complete, separator, _suffix = content.rpartition(b"%%EOF")
    assert separator
    with pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id="truncated-footer", content=complete + marker))


@pytest.mark.parametrize("suffix", [b"", b"\n", b"\r\n", b" \x00\t\r\n\f"])
def test_complete_file_end_marker_preserves_text_and_blank_page(suffix: bytes) -> None:
    writer = PdfWriter()
    _add_compressed_page(writer, zlib.compress(b"BT /F1 12 Tf (Revenue 123) Tj ET"))
    writer.add_blank_page(width=100, height=200)
    content = _document_bytes(writer).rstrip(b"\x00\t\n\f\r ") + suffix
    pages = parse_pdf_document(PDFDocumentInput(document_id="complete-footer", content=content))
    assert [(page.page_number, page.text) for page in pages] == [(1, "Revenue 123"), (2, "")]
    assert all(page.document_sha256 == hashlib.sha256(content).hexdigest() for page in pages)


def _literal_lzw(data: bytes, *, terminated: bool) -> bytes:
    codes = [256, *data, *([257] if terminated else [])]
    bits = "".join(f"{code:09b}" for code in codes)
    bits += "0" * (-len(bits) % 8)
    return int(bits, 2).to_bytes(len(bits) // 8, "big")


@pytest.mark.parametrize("filter_name", ["/ASCII85Decode", "/ASCIIHexDecode", "/RunLengthDecode", "/LZWDecode"])
@pytest.mark.parametrize("terminated", [False, True], ids=["missing-eod", "complete"])
@pytest.mark.parametrize("wrapped", [False, True], ids=["single-filter", "asciihex-chain"])
def test_content_filter_end_markers_are_required_without_rejecting_complete_streams(
    filter_name: str, terminated: bool, wrapped: bool
) -> None:
    payload = b"BT /F1 12 Tf (Revenue 123) Tj ET"
    if filter_name == "/ASCII85Decode":
        data = a85encode(payload, adobe=True)[2:]
        if not terminated:
            data = data[:-2]
    elif filter_name == "/ASCIIHexDecode":
        data = payload.hex().encode() + (b">" if terminated else b"")
    elif filter_name == "/RunLengthDecode":
        data = bytes([len(payload) - 1]) + payload + (b"\x80" if terminated else b"")
    else:
        data = _literal_lzw(payload, terminated=terminated)
    writer = PdfWriter()
    _add_compressed_page(writer, zlib.compress(b"BT /F1 12 Tf (First page) Tj ET"))
    _add_compressed_page(writer, data.hex().encode() + b">" if wrapped else data)
    stream = writer.pages[-1]["/Contents"]
    stream[NameObject("/Filter")] = (
        ArrayObject([NameObject("/ASCIIHexDecode"), NameObject(filter_name)]) if wrapped else NameObject(filter_name)
    )
    value = PDFDocumentInput(document_id="encoded-content", content=_document_bytes(writer))
    if not terminated:
        with pytest.raises(ValueError):
            parse_pdf_document(value)
    else:
        pages = parse_pdf_document(value)
        assert [(page.page_number, page.text) for page in pages] == [(1, "First page"), (2, "Revenue 123")]
