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

"""Captured CSV records with document-and-primary-key Source identities."""

from __future__ import annotations

import csv
import io
import json
from typing import Literal
from urllib.parse import quote

from pydantic import BaseModel, JsonValue, model_validator

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.definitions import AdapterSourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

_CSV_ROW_SOURCE_NAME = "csv-row"


def _validate_document_id(value: str) -> None:
    if not value or value != value.strip():
        raise ValueError("document_id must be non-empty without surrounding whitespace")  # noqa: TRY003


def _validate_primary_key(value: str) -> None:
    if not value:
        raise ValueError("primary_key must not be empty")  # noqa: TRY003


def _validate_columns(columns: tuple[str, ...]) -> None:
    if not columns or any(not column.strip() for column in columns):
        raise ValueError("CSV columns must be non-empty and not blank")  # noqa: TRY003
    if len(set(columns)) != len(columns):
        raise ValueError("CSV columns must be unique")  # noqa: TRY003


def csv_row_source_id(document_id: str, primary_key_value: str) -> str:
    """Return the bounded, delimiter-safe identity of one document record."""

    _validate_document_id(document_id)
    if not primary_key_value.strip():
        raise ValueError("primary_key_value must not be empty or blank")  # noqa: TRY003
    source_id = f"csv:{quote(document_id, safe='')}:{quote(primary_key_value, safe='')}"
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        raise ValueError("CSV row Source identity must not exceed 256 characters")  # noqa: TRY003
    return source_id


def _validate_row(
    document_id: str,
    primary_key: str,
    primary_key_value: str,
    columns: tuple[str, ...],
    values: tuple[str, ...],
) -> str:
    _validate_primary_key(primary_key)
    _validate_columns(columns)
    if len(values) != len(columns):
        raise ValueError("CSV row width must match its columns")  # noqa: TRY003
    try:
        key_index = columns.index(primary_key)
    except ValueError:
        raise ValueError("primary_key must exactly match a CSV column") from None  # noqa: TRY003
    if values[key_index] != primary_key_value:
        raise ValueError("primary_key_value must match the row's primary-key field")  # noqa: TRY003
    return csv_row_source_id(document_id, primary_key_value)


class CSVDocumentInput(BaseModel):
    """One complete offline CSV document and its identity declaration."""

    document_id: str
    primary_key: str
    content: bytes

    @model_validator(mode="after")
    def validate_document(self) -> CSVDocumentInput:
        _validate_document_id(self.document_id)
        _validate_primary_key(self.primary_key)
        return self


class CSVRowInput(BaseModel):
    """One complete record, retaining its original column order and values."""

    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]

    @model_validator(mode="after")
    def validate_row(self) -> CSVRowInput:
        _validate_row(self.document_id, self.primary_key, self.primary_key_value, self.columns, self.values)
        return self


class CSVRowSource(Source):
    """A captured CSV record that can be projected and durably transported."""

    definition_version: Literal["1"] = "1"
    materialization: Literal[SourceMaterialization.CAPTURED] = SourceMaterialization.CAPTURED
    source_id: str
    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]

    @model_validator(mode="after")
    def validate_row_identity(self) -> CSVRowSource:
        expected = _validate_row(self.document_id, self.primary_key, self.primary_key_value, self.columns, self.values)
        if self.name != expected or self.source_id != expected:
            raise ValueError("CSV row name and source_id must match its document and primary key")  # noqa: TRY003
        return self


def parse_csv_document(value: CSVDocumentInput) -> tuple[CSVRowInput, ...]:
    """Validate the complete CSV before returning any captured row inputs."""

    try:
        text = value.content.decode("utf-8-sig")
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        try:
            columns = tuple(next(reader))
        except StopIteration:
            raise ValueError("CSV document must contain a header") from None  # noqa: TRY003
        _validate_columns(columns)
        try:
            key_index = columns.index(value.primary_key)
        except ValueError:
            raise ValueError("primary_key must exactly match a CSV column") from None  # noqa: TRY003
        rows: list[CSVRowInput] = []
        seen: set[str] = set()
        for fields in reader:
            if not fields:
                continue
            if len(fields) != len(columns):
                raise ValueError("CSV row width must match its header")  # noqa: TRY003
            key_value = fields[key_index]
            if key_value in seen:
                raise ValueError("CSV primary-key values must be unique within the document")  # noqa: TRY003
            rows.append(
                CSVRowInput(
                    document_id=value.document_id,
                    primary_key=value.primary_key,
                    primary_key_value=key_value,
                    columns=columns,
                    values=tuple(fields),
                )
            )
            seen.add(key_value)
    except (UnicodeDecodeError, csv.Error) as error:
        raise ValueError("CSV document must contain valid UTF-8 and CSV records") from error  # noqa: TRY003
    return tuple(rows)


class _CSVRowSourceAdapter:
    input_class = CSVRowInput
    name = _CSV_ROW_SOURCE_NAME
    source_class = CSVRowSource

    async def resolve(self, value: CSVRowInput, /) -> CSVRowSource:
        source_id = csv_row_source_id(value.document_id, value.primary_key_value)
        return CSVRowSource(
            name=source_id,
            source_id=source_id,
            document_id=value.document_id,
            primary_key=value.primary_key,
            primary_key_value=value.primary_key_value,
            columns=value.columns,
            values=value.values,
        )

    async def read(self, source: CSVRowSource, /) -> CSVRowInput:
        return CSVRowInput(
            document_id=source.document_id,
            primary_key=source.primary_key,
            primary_key_value=source.primary_key_value,
            columns=source.columns,
            values=source.values,
        )


class _CSVRowTextEvidenceProjection:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = CSVRowSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: CSVRowSource, /) -> TextEvidence:
        row: dict[str, JsonValue] = dict(zip(source.columns, source.values, strict=True))
        return TextEvidence(
            source_type=_CSV_ROW_SOURCE_NAME,
            source_id=source.source_id,
            content=json.dumps(row, ensure_ascii=False, separators=(",", ":")),
            metadata={
                "document_id": source.document_id,
                "primary_key": source.primary_key,
                "primary_key_value": source.primary_key_value,
                "columns": list(source.columns),
                "row": row,
            },
        )


CSV_ROW_SOURCE_DEFINITION = AdapterSourceDefinition(
    _CSVRowSourceAdapter(),
    projections=(_CSVRowTextEvidenceProjection(),),
)

__all__ = [
    "CSV_ROW_SOURCE_DEFINITION",
    "CSVDocumentInput",
    "CSVRowInput",
    "CSVRowSource",
    "csv_row_source_id",
    "parse_csv_document",
]
