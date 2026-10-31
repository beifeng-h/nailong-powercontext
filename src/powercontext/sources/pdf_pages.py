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

"""Complete PDF physical pages as captured, revision-specific evidence."""

from __future__ import annotations

import hashlib
import io
import json
import zlib
from copy import copy
from typing import Any, Literal, cast

from pydantic import BaseModel, Field, field_validator
from pypdf import PdfReader
from pypdf._encryption import Encryption
from pypdf.filters import ZLIB_MAX_OUTPUT_LENGTH, decode_stream_data
from pypdf.generic import (
    ArrayObject,
    ContentStream,
    DictionaryObject,
    EncodedStreamObject,
    IndirectObject,
    NameObject,
    NullObject,
    PdfObject,
    StreamObject,
)

from powercontext.sources._pdf_search import search_pdf_pages
from powercontext.sources._pdf_text import extract_pdf_page_text
from powercontext.sources.definitions import AdapterSourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

_PDF_SOURCE_NAME = "pdf-page"
_PDF_WHITESPACE = b"\x00\t\n\f\r "


def _validate_document_id(value: str) -> str:
    if not value.strip():
        raise ValueError("document_id must not be empty or blank")  # noqa: TRY003
    return value


class PDFDocumentInput(BaseModel):
    """One complete PDF revision supplied as bytes."""

    document_id: str
    content: bytes

    _document_id = field_validator("document_id")(_validate_document_id)


class PDFPageInput(BaseModel):
    """Extractable text from one physical page of an exact PDF revision."""

    document_id: str
    document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_number: int = Field(ge=1)
    text: str

    _document_id = field_validator("document_id")(_validate_document_id)


def _resolved_pdf_value(value: object) -> object:
    return value.get_object() if isinstance(value, IndirectObject) else value


def _stream_filter_parameters(stream: StreamObject, count: int) -> tuple[PdfObject, ...]:
    parameters = _resolved_pdf_value(stream.get("/DecodeParms"))
    if parameters is None or isinstance(parameters, NullObject):
        return (NullObject(),) * count
    elif isinstance(parameters, ArrayObject):
        if len(parameters) != count:
            raise ValueError("PDF filter parameters do not match the filter chain")  # noqa: TRY003
        parameters = tuple(_resolved_pdf_value(value) for value in parameters)
    elif isinstance(parameters, DictionaryObject) and count == 1:
        parameters = (parameters,)
    else:
        raise ValueError("PDF Crypt filter parameters must be a matching dictionary or array")  # noqa: TRY003
    if any(not isinstance(value, (DictionaryObject, NullObject)) for value in parameters):
        raise ValueError("PDF filter parameters must contain dictionaries or null")  # noqa: TRY003
    return cast(tuple[PdfObject, ...], parameters)


def _crypt_filter_name(parameter: PdfObject) -> NameObject:
    if isinstance(parameter, NullObject):
        return NameObject("/Identity")
    if not isinstance(parameter, DictionaryObject):
        raise ValueError("PDF Crypt filter parameters must be a dictionary")  # noqa: TRY003
    kind = _resolved_pdf_value(parameter.get("/Type"))
    if kind is not None and not isinstance(kind, NullObject) and (
        not isinstance(kind, NameObject) or kind != "/CryptFilterDecodeParms"
    ):
        raise ValueError("PDF Crypt filter parameter type is invalid")  # noqa: TRY003
    name = _resolved_pdf_value(parameter.get("/Name"))
    if name is None or isinstance(name, NullObject):
        return NameObject("/Identity")
    if not isinstance(name, NameObject):
        raise ValueError("PDF Crypt filter name must be a name")  # noqa: TRY003
    return name


def _crypt_filter_info(
    stream: StreamObject,
) -> tuple[tuple[NameObject, ...], tuple[PdfObject, ...], frozenset[int], NameObject] | None:
    filters = _resolved_pdf_value(stream.get("/Filter", ()))
    values = tuple(filters) if isinstance(filters, ArrayObject) else (filters,)
    values = tuple(_resolved_pdf_value(value) for value in values)
    positions = frozenset(index for index, value in enumerate(values) if value == "/Crypt")
    if not positions:
        return None
    if positions != {0}:
        raise ValueError("PDF Crypt filter must occur once at the start of its chain")  # noqa: TRY003
    if any(not isinstance(value, NameObject) for value in values):
        raise ValueError("PDF stream filters must be names")  # noqa: TRY003
    parameters = _stream_filter_parameters(stream, len(values))
    name = _crypt_filter_name(parameters[0])
    return cast(tuple[NameObject, ...], values), tuple(parameters), positions, name


def _remove_crypt_filter(stream: StreamObject) -> None:
    information = _crypt_filter_info(stream)
    if information is None:
        return
    filters, parameters, positions, _name = information
    remaining = tuple(index for index in range(len(filters)) if index not in positions)
    stream[NameObject("/Filter")] = ArrayObject([filters[index] for index in remaining])
    stream[NameObject("/DecodeParms")] = ArrayObject([parameters[index] for index in remaining])
    if isinstance(stream, EncodedStreamObject):
        stream.decoded_self = None


class _CryptAwareDecryption:
    """Select each stream's declared cipher while retaining the document string cipher."""

    def __init__(self, original: Encryption, filters: DictionaryObject | None) -> None:
        self._original = original
        self._filters = filters

    def __getattr__(self, name: str) -> Any:
        return getattr(self._original, name)

    def decrypt_object(self, value: PdfObject, idnum: int, generation: int, **kwargs: Any) -> PdfObject:
        information = _crypt_filter_info(value) if isinstance(value, StreamObject) else None
        if information is None:
            return self._original.decrypt_object(value, idnum, generation, **kwargs)
        name = information[3]
        if name == "/Identity":
            method = "/Identity"
        else:
            definition = _resolved_pdf_value(self._filters.get(name)) if self._filters is not None else None
            if not isinstance(definition, DictionaryObject):
                raise ValueError("PDF references an unknown Crypt filter")  # noqa: TRY003
            cipher = _resolved_pdf_value(definition.get("/CFM"))
            if not isinstance(cipher, NameObject) or cipher not in ("/V2", "/AESV2", "/AESV3"):
                raise ValueError("PDF contains an unsupported Crypt filter method")  # noqa: TRY003
            method = str(cipher)
        selected = copy(self._original)
        selected.StmF = method
        return selected.decrypt_object(value, idnum, generation, **kwargs)


class _CryptPdfReader(PdfReader):
    """Apply stream Crypt semantics within this Reader, before native decoding."""

    def get_object(self, indirect_reference: int | IndirectObject) -> PdfObject | None:
        original = getattr(self, "_encryption", None)
        if original is None or isinstance(original, _CryptAwareDecryption):
            value = super().get_object(indirect_reference)
        else:
            entry = self.trailer.get("/Encrypt")
            if isinstance(entry, IndirectObject):
                entry = super().get_object(entry)
            filters = entry.get("/CF") if isinstance(entry, DictionaryObject) else None
            if isinstance(filters, IndirectObject):
                filters = super().get_object(filters)
            self._encryption = cast(
                Encryption,
                _CryptAwareDecryption(original, filters if isinstance(filters, DictionaryObject) else None),
            )
            try:
                value = super().get_object(indirect_reference)
            finally:
                self._encryption = original
        if isinstance(value, StreamObject):
            information = _crypt_filter_info(value)
            if information is not None and information[3] != "/Identity" and original is None:
                raise ValueError("PDF named Crypt filter requires document encryption")  # noqa: TRY003
            _remove_crypt_filter(value)
        return value


def _decode_page_content_streams(page: DictionaryObject, reader: PdfReader) -> tuple[EncodedStreamObject, ...]:
    # Text extraction skips fontless pages and can suppress Form decoding errors.
    # Read their content independently before deciding whether the page is empty.
    streams: list[EncodedStreamObject] = []
    seen: set[int] = set()

    def decode(value: object) -> None:
        if isinstance(value, IndirectObject):
            value = value.get_object()
        if value is None or isinstance(value, NullObject):
            return
        if isinstance(value, ArrayObject):
            for item in value:
                decode(item)
            return
        if not isinstance(value, StreamObject):
            raise ValueError("PDF page content must be a stream")  # noqa: TRY003
        if id(value) in seen:
            return
        seen.add(id(value))
        value.get_data()
        if isinstance(value, EncodedStreamObject):
            streams.append(value)
        if value.get("/Subtype") == "/Form":
            # Extraction can swallow Form syntax errors and return partial text.
            # A fresh ContentStream forces its lazy parser before extraction.
            _ = ContentStream(value, reader).operations
            visit_resources(value)

    def visit_resources(owner: DictionaryObject) -> None:
        resources = owner.get("/Resources")
        if isinstance(resources, IndirectObject):
            resources = resources.get_object()
        if not isinstance(resources, DictionaryObject):
            return
        objects = resources.get("/XObject")
        if isinstance(objects, IndirectObject):
            objects = objects.get_object()
        if not isinstance(objects, DictionaryObject):
            return
        for value in objects.values():
            if isinstance(value, IndirectObject):
                value = value.get_object()
            if isinstance(value, DictionaryObject) and value.get("/Subtype") == "/Form":
                decode(value)

    contents = page.get("/Contents")
    decode(contents)
    if contents is not None and not isinstance(_resolved_pdf_value(contents), NullObject):
        # A page's array is one logical stream; literals may span its segments.
        _ = ContentStream(contents, reader).operations
    visit_resources(page)
    return tuple(streams)


def _validate_run_length_stream(data: bytes) -> None:
    position = 0
    while position < len(data):
        length = data[position]
        position += 1
        if length == 128:
            return
        position += length + 1 if length < 128 else 1
        if position > len(data):
            raise ValueError("PDF contains a truncated run-length stream")  # noqa: TRY003
    raise ValueError("PDF run-length stream has no end marker")  # noqa: TRY003


def _validate_lzw_stream(data: bytes, early_change: int) -> None:
    # Track dictionary sizes and code widths without expanding decoded strings.
    if early_change not in (0, 1):
        raise ValueError("PDF LZW EarlyChange must be 0 or 1")  # noqa: TRY003
    width, table_size, has_previous = 9, 258, False
    position = 0
    while True:
        if position + width > len(data) * 8:
            raise ValueError("PDF LZW stream has no complete end code")  # noqa: TRY003
        byte_start, bit_offset = divmod(position, 8)
        byte_count = (bit_offset + width + 7) // 8
        value = int.from_bytes(data[byte_start:byte_start + byte_count], "big")
        code = (value >> (byte_count * 8 - bit_offset - width)) & ((1 << width) - 1)
        position += width
        if code == 257:
            return
        if code == 256:
            width, table_size, has_previous = 9, 258, False
            continue
        if code >= table_size and not (has_previous and code == table_size and table_size < 4096):
            raise ValueError("PDF LZW stream references an undefined code")  # noqa: TRY003
        if has_previous and table_size < 4096:
            table_size += 1
            if width < 12 and table_size + early_change == (1 << width):
                width += 1
        has_previous = True


def _validate_decoded_streams(reader: PdfReader, content_streams: tuple[EncodedStreamObject, ...]) -> None:
    # The pinned decoder can recover empty or partial data from a damaged stream,
    # even in strict mode. Validate streams actually decoded for page extraction.
    seen: set[int] = set()
    for stream in (*content_streams, *tuple(reader.resolved_objects.values())):
        if not isinstance(stream, EncodedStreamObject) or stream.decoded_self is None:
            continue
        if id(stream) in seen:
            continue
        seen.add(id(stream))
        filters = stream.get("/Filter", ())
        if isinstance(filters, IndirectObject):
            filters = filters.get_object()
        if not isinstance(filters, ArrayObject):
            filters = (filters,)
        parameters = stream.get("/DecodeParms", (NullObject(),) * len(filters))
        if isinstance(parameters, IndirectObject):
            parameters = parameters.get_object()
        if not isinstance(parameters, (list, tuple)):
            parameters = (parameters,)
        for index, filter_name in enumerate(filters):
            if filter_name not in (
                "/FlateDecode",
                "/Fl",
                "/ASCII85Decode",
                "/A85",
                "/ASCIIHexDecode",
                "/AHx",
                "/RunLengthDecode",
                "/RL",
                "/LZWDecode",
                "/LZW",
            ):
                continue
            data = stream._data
            if index:
                prefix = copy(stream)
                prefix[NameObject("/Filter")] = ArrayObject(filters[:index])
                prefix[NameObject("/DecodeParms")] = ArrayObject(parameters[:index])
                data = decode_stream_data(prefix)
            if filter_name in ("/FlateDecode", "/Fl"):
                decoder = zlib.decompressobj()
                decoder.decompress(data, max_length=ZLIB_MAX_OUTPUT_LENGTH)
                if not decoder.eof or decoder.unconsumed_tail:
                    raise ValueError("PDF contains an incomplete compressed stream")  # noqa: TRY003
            elif filter_name in ("/ASCII85Decode", "/A85"):
                tail = data.rstrip(_PDF_WHITESPACE)
                if not tail.endswith(b">") or not tail[:-1].rstrip(_PDF_WHITESPACE).endswith(b"~"):
                    raise ValueError("PDF ASCII85 stream has no end marker")  # noqa: TRY003
            elif filter_name in ("/ASCIIHexDecode", "/AHx"):
                if b">" not in data:
                    raise ValueError("PDF ASCIIHex stream has no end marker")  # noqa: TRY003
            elif filter_name in ("/RunLengthDecode", "/RL"):
                _validate_run_length_stream(data)
            else:
                parameter = parameters[index] if index < len(parameters) else NullObject()
                if isinstance(parameter, IndirectObject):
                    parameter = parameter.get_object()
                early_change = parameter.get("/EarlyChange", 1) if isinstance(parameter, DictionaryObject) else 1
                _validate_lzw_stream(data, early_change)


def parse_pdf_document(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]:
    """Extract every physical page before returning an atomically valid document."""

    try:
        if not value.content.rstrip(_PDF_WHITESPACE).endswith(b"%%EOF"):
            raise ValueError("PDF document has an incomplete end marker")  # noqa: TRY003
        reader = _CryptPdfReader(io.BytesIO(value.content), strict=True)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("PDF document requires a non-empty password")  # noqa: TRY003
        digest = hashlib.sha256(value.content).hexdigest()
        pages: list[PDFPageInput] = []
        content_streams: list[EncodedStreamObject] = []
        for number, page in enumerate(reader.pages, start=1):
            content_streams.extend(_decode_page_content_streams(page, reader))
            pages.append(
                PDFPageInput(
                    document_id=value.document_id,
                    document_sha256=digest,
                    page_number=number,
                    text=extract_pdf_page_text(page),
                )
            )
        _validate_decoded_streams(reader, tuple(content_streams))
        return tuple(pages)
    except Exception as error:  # noqa: BLE001 - malformed PDF objects raise varied parser exceptions.
        raise ValueError("PDF document must be readable in full") from error  # noqa: TRY003


def _pdf_page_source_id(value: PDFPageInput) -> str:
    identity = json.dumps(
        [value.document_id, value.document_sha256, value.page_number],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"pdf:{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"


class _PDFPageSource(Source):
    definition_version: Literal["1"] = "1"
    materialization: Literal[SourceMaterialization.CAPTURED] = SourceMaterialization.CAPTURED
    document_id: str
    document_sha256: str
    page_number: int
    text: str


class _PDFPageSourceAdapter:
    input_class = PDFPageInput
    name = _PDF_SOURCE_NAME
    source_class = _PDFPageSource

    async def resolve(self, value: PDFPageInput, /) -> _PDFPageSource:
        return _PDFPageSource(name=_pdf_page_source_id(value), **value.model_dump())

    async def read(self, source: _PDFPageSource, /) -> PDFPageInput:
        return PDFPageInput(
            document_id=source.document_id,
            document_sha256=source.document_sha256,
            page_number=source.page_number,
            text=source.text,
        )


class _PDFPageTextEvidenceProjection:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = _PDFPageSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: _PDFPageSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=_PDF_SOURCE_NAME,
            source_id=source.name,
            content=f"{source.document_id}\n{source.text}",
            metadata={
                "document_id": source.document_id,
                "document_sha256": source.document_sha256,
                "page_number": source.page_number,
            },
        )


PDF_PAGE_SOURCE_DEFINITION = AdapterSourceDefinition(
    _PDFPageSourceAdapter(),
    projections=(_PDFPageTextEvidenceProjection(),),
)

__all__ = [
    "PDF_PAGE_SOURCE_DEFINITION",
    "PDFDocumentInput",
    "PDFPageInput",
    "parse_pdf_document",
    "search_pdf_pages",
]
