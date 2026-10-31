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

"""Explicit PDF replacement text survives complete physical-page parsing."""

from __future__ import annotations

import hashlib
import io

import pytest
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    FloatObject,
    NameObject,
    NumberObject,
    TextStringObject,
)

from powercontext.sources.pdf_pages import PDFDocumentInput, parse_pdf_document


def _writer() -> PdfWriter:
    writer = PdfWriter()
    mapping = DecodedStreamObject()
    mapping.set_data(b"1 beginbfchar\n<58> <0000>\nendbfchar")
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
        NameObject("/ToUnicode"): writer._add_object(mapping),
    })
    page = writer.add_blank_page(width=612, height=792)
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})
    })
    return writer


def _page_content(writer: PdfWriter, content: bytes, page_number: int = 0) -> None:
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 40 700 Td " + content + b" ET")
    writer.pages[page_number][NameObject("/Contents")] = writer._add_object(stream)


def _bytes(writer: PdfWriter) -> bytes:
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_explicit_replacement_restores_ligature_without_losing_surrounding_text() -> None:
    writer = _writer()
    _page_content(writer, b"(Sec) Tj /Span << /ActualText (ti) >> BDC (X) Tj EMC (on Revenue 123) Tj")
    content = _bytes(writer)
    pages = parse_pdf_document(PDFDocumentInput(document_id="marked-text", content=content))
    assert len(pages) == 1
    assert pages[0].text == "Section Revenue 123"
    assert pages[0].document_sha256 == hashlib.sha256(content).hexdigest()


@pytest.mark.parametrize("indirect_text", [False, True], ids=["direct-text", "indirect-text"])
def test_named_indirect_properties_preserve_unicode_replacement(indirect_text: bool) -> None:
    writer = _writer()
    text = TextStringObject("Revenue Ω 123")
    properties = DictionaryObject({NameObject("/ActualText"): writer._add_object(text) if indirect_text else text})
    writer.pages[0]["/Resources"][NameObject("/Properties")] = writer._add_object(
        DictionaryObject({NameObject("/Replacement"): writer._add_object(properties)})
    )
    _page_content(writer, b"/Span /Replacement BDC (X) Tj EMC")
    pages = parse_pdf_document(PDFDocumentInput(document_id="named-text", content=_bytes(writer)))
    assert pages[0].text == "Revenue Ω 123"


@pytest.mark.parametrize("show", [b"[(X) 120 (X)] TJ", b"(X) '", b'0 0 (X) "'])
def test_replacement_applies_to_each_supported_text_show_operator(show: bytes) -> None:
    writer = _writer()
    _page_content(writer, b"14 TL (Before ) Tj /Span << /ActualText (Tax 99) >> BDC " + show + b" EMC ( After) Tj")
    pages = parse_pdf_document(PDFDocumentInput(document_id="text-operators", content=_bytes(writer)))
    assert pages[0].text.split() == ["Before", "Tax", "99", "After"]


def test_form_named_properties_use_form_resources_and_restore_page_resources() -> None:
    writer = _writer()
    resources = writer.pages[0]["/Resources"]
    resources[NameObject("/Properties")] = DictionaryObject({
        NameObject("/Replacement"): DictionaryObject({
            NameObject("/ActualText"): TextStringObject("Parent replacement")
        })
    })
    form = DecodedStreamObject()
    form.set_data(b"BT /F1 12 Tf /Span /Replacement BDC (X) Tj EMC ET")
    form.update({
        NameObject("/Type"): NameObject("/XObject"),
        NameObject("/Subtype"): NameObject("/Form"),
        NameObject("/BBox"): ArrayObject([NumberObject(value) for value in (0, 0, 100, 100)]),
        NameObject("/Resources"): DictionaryObject({
            NameObject("/Font"): resources["/Font"],
            NameObject("/Properties"): DictionaryObject({
                NameObject("/Replacement"): DictionaryObject({
                    NameObject("/ActualText"): TextStringObject("Form replacement")
                })
            }),
        }),
    })
    resources[NameObject("/XObject")] = DictionaryObject({NameObject("/Fm"): writer._add_object(form)})
    _page_content(
        writer,
        b"/Span /Replacement BDC (X) Tj EMC ET /Fm Do BT /F1 12 Tf 40 660 Td /Span /Replacement BDC (X) Tj EMC",
    )
    pages = parse_pdf_document(PDFDocumentInput(document_id="form-properties", content=_bytes(writer)))
    assert pages[0].text.split() == ["Parent", "replacement", "Form", "replacement", "Parent", "replacement"]


@pytest.mark.parametrize(
    "content,expected",
    [
        (
            b"/Span << /ActualText (Alpha) >> BDC (X) Tj EMC ( ) Tj /Span << /ActualText (Beta) >> BDC (X) Tj EMC",
            "Alpha Beta",
        ),
        (
            b"/Span << /ActualText (Outer) >> BDC (X) Tj /Span << /ActualText (Inner) >> BDC (X) Tj EMC (X) Tj EMC",
            "Outer",
        ),
        (b"/Span << /ActualText (Once) >> BDC /Tag BMC (X) Tj EMC (X) Tj EMC", "Once"),
        (b"(Before) Tj /Span << /ActualText () >> BDC (X) Tj EMC (After) Tj", "BeforeAfter"),
        (b"/Span << /ActualText (Once) >> BDC [100] TJ (X) Tj EMC", "Once"),
        (b"/Span << /ActualText (Alpha) >> BDC (X) Tj EMC (X) Tj", "Alpha\x00"),
    ],
    ids=[
        "contextual-glyph",
        "nested-replacement",
        "nested-unmarked",
        "empty-replacement",
        "empty-array",
        "unmarked-glyph",
    ],
)
def test_marked_replacement_is_contextual_and_emitted_once(content: bytes, expected: str) -> None:
    writer = _writer()
    _page_content(writer, content)
    pages = parse_pdf_document(PDFDocumentInput(document_id="marked-context", content=_bytes(writer)))
    assert pages[0].text == expected


def test_replacement_state_and_named_resources_are_isolated_between_physical_pages() -> None:
    writer = _writer()
    fonts = writer.pages[0]["/Resources"]["/Font"]
    writer.add_blank_page(width=612, height=792)
    writer.add_blank_page(width=612, height=792)
    for page_number, replacement in ((0, "Alpha"), (2, "Beta")):
        writer.pages[page_number][NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): fonts,
            NameObject("/Properties"): DictionaryObject({
                NameObject("/Replacement"): DictionaryObject({NameObject("/ActualText"): TextStringObject(replacement)})
            }),
        })
        _page_content(writer, b"/Span /Replacement BDC (X) Tj EMC", page_number)
    content = _bytes(writer)
    pages = parse_pdf_document(PDFDocumentInput(document_id="marked-pages", content=content))
    assert [(page.page_number, page.text) for page in pages] == [(1, "Alpha"), (2, ""), (3, "Beta")]
    assert all(page.document_sha256 == hashlib.sha256(content).hexdigest() for page in pages)


def test_outer_replacement_covers_inner_form_text_without_duplicating_inner_replacement() -> None:
    writer = _writer()
    resources = writer.pages[0]["/Resources"]
    form = DecodedStreamObject()
    form.set_data(b"BT /F1 12 Tf /Span << /ActualText (Inner) >> BDC (X) Tj EMC ET")
    form.update({
        NameObject("/Type"): NameObject("/XObject"),
        NameObject("/Subtype"): NameObject("/Form"),
        NameObject("/BBox"): ArrayObject([NumberObject(value) for value in (0, 0, 100, 100)]),
        NameObject("/Resources"): resources,
    })
    resources[NameObject("/XObject")] = DictionaryObject({NameObject("/Fm"): writer._add_object(form)})
    _page_content(writer, b"/Span << /ActualText (Outer replacement) >> BDC ET /Fm Do BT EMC")
    pages = parse_pdf_document(PDFDocumentInput(document_id="outer-form", content=_bytes(writer)))
    assert pages[0].text.strip() == "Outer replacement"


def _glyph_writer(glyph_name: str, *, unicode_text: str | None = None) -> PdfWriter:
    writer = PdfWriter()
    glyph = DecodedStreamObject()
    glyph.set_data(b"600 0 d0 250 0 100 600 re f 100 400 400 100 re f")
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type3"),
        NameObject("/FontBBox"): ArrayObject([NumberObject(value) for value in (0, 0, 600, 700)]),
        NameObject("/FontMatrix"): ArrayObject([FloatObject(value) for value in (0.001, 0, 0, 0.001, 0, 0)]),
        NameObject("/CharProcs"): DictionaryObject({NameObject(glyph_name): writer._add_object(glyph)}),
        NameObject("/Encoding"): DictionaryObject({
            NameObject("/BaseEncoding"): NameObject("/WinAnsiEncoding"),
            NameObject("/Differences"): ArrayObject([NumberObject(1), NameObject(glyph_name)]),
        }),
        NameObject("/FirstChar"): NumberObject(1),
        NameObject("/LastChar"): NumberObject(1),
        NameObject("/Widths"): ArrayObject([NumberObject(600)]),
        NameObject("/Resources"): DictionaryObject(),
    })
    if unicode_text is not None:
        mapping = DecodedStreamObject()
        hexadecimal = unicode_text.encode("utf-16-be").hex().encode("ascii")
        mapping.set_data(b"1 beginbfchar\n<01> <" + hexadecimal + b">\nendbfchar")
        font[NameObject("/ToUnicode")] = writer._add_object(mapping)
    page = writer.add_blank_page(width=612, height=792)
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)}),
    })
    return writer


@pytest.mark.parametrize(
    "glyph_name,expected",
    (("/t.ss04", "t"), ("/A.swash", "A"), ("/one.oldstyle", "1"), ("/ampersand.alt01", "&")),
)
def test_glyph_style_names_retain_their_base_character(glyph_name: str, expected: str) -> None:
    writer = _glyph_writer(glyph_name)
    _page_content(writer, b"<01> Tj")
    content = _bytes(writer)
    pages = parse_pdf_document(PDFDocumentInput(document_id="styled-glyph", content=content))
    assert pages[0].text == expected
    assert pages[0].document_sha256 == hashlib.sha256(content).hexdigest()


def test_explicit_unicode_map_keeps_its_own_glyph_meaning() -> None:
    writer = _glyph_writer("/A.swash", unicode_text="Ω")
    _page_content(writer, b"<01> Tj")
    pages = parse_pdf_document(PDFDocumentInput(document_id="explicit-glyph-map", content=_bytes(writer)))
    assert pages[0].text == "Ω"


def test_plain_literal_text_is_not_treated_as_a_glyph_name() -> None:
    writer = _writer()
    _page_content(writer, b"(The literal /t.ss04 stays.) Tj")
    pages = parse_pdf_document(PDFDocumentInput(document_id="literal-glyph-name", content=_bytes(writer)))
    assert pages[0].text == "The literal /t.ss04 stays."


def test_form_glyph_styles_keep_their_own_font_encoding() -> None:
    writer = _glyph_writer("/t.alt")
    form = DecodedStreamObject()
    form.set_data(b"BT /F1 12 Tf 40 600 Td <01> Tj ET")
    form.update({
        NameObject("/Type"): NameObject("/XObject"),
        NameObject("/Subtype"): NameObject("/Form"),
        NameObject("/BBox"): ArrayObject([NumberObject(value) for value in (0, 0, 612, 792)]),
        NameObject("/Resources"): writer.pages[0]["/Resources"],
    })
    writer.pages[0][NameObject("/Resources")] = DictionaryObject({
        NameObject("/XObject"): DictionaryObject({NameObject("/Fm"): writer._add_object(form)}),
    })
    page_stream = DecodedStreamObject()
    page_stream.set_data(b"/Fm Do")
    writer.pages[0][NameObject("/Contents")] = writer._add_object(page_stream)
    pages = parse_pdf_document(PDFDocumentInput(document_id="form-styled-glyph", content=_bytes(writer)))
    assert pages[0].text.strip() == "t"
