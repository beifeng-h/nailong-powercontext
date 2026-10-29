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

from __future__ import annotations

import asyncio
import json

import pytest

from powercontext.sources import (
    TEXT_EVIDENCE_PROJECTION_KEY,
    SourceDefinitionRegistry,
    SourceMaterialization,
    TextEvidence,
)
from powercontext.sources.csv_rows import (
    CSV_ROW_SOURCE_DEFINITION,
    CSVDocumentInput,
    CSVRowInput,
    csv_row_source_id,
    parse_csv_document,
)


@pytest.mark.parametrize(
    ("document_id", "primary_key_value"),
    [("doc", "界" * 27 + "a" * 5), ("界" * 27 + "a" * 5, "doc")],
)
def test_identity_limit_applies_after_encoding_both_components(document_id: str, primary_key_value: str) -> None:
    assert len(csv_row_source_id(document_id, primary_key_value)) == 256
    rows = parse_csv_document(
        CSVDocumentInput(
            document_id=document_id,
            primary_key="id",
            content=f"id,note\n{primary_key_value},kept\n".encode(),
        )
    )
    assert rows[0].primary_key_value == primary_key_value

    with pytest.raises(ValueError):
        csv_row_source_id(document_id, primary_key_value + "a")
    with pytest.raises(ValueError):
        parse_csv_document(
            CSVDocumentInput(
                document_id=document_id,
                primary_key="id",
                content=f"id,note\n{primary_key_value}a,too-long\n".encode(),
            )
        )


def test_unicode_and_literal_percent_signs_have_unambiguous_identities() -> None:
    assert csv_row_source_id("文/档:%", "键:%/") == "csv:%E6%96%87%2F%E6%A1%A3%3A%25:%E9%94%AE%3A%25%2F"
    identities = {
        csv_row_source_id("文", "键"),
        csv_row_source_id("%E6%96%87", "键"),
        csv_row_source_id("文", "%E9%94%AE"),
        csv_row_source_id("a:b", "c"),
        csv_row_source_id("a", "b:c"),
    }
    assert len(identities) == 5


def test_direct_row_preserves_distinct_spaced_columns_and_whitespace_values() -> None:
    row = CSVRowInput(
        document_id="表格:1",
        primary_key=" id ",
        primary_key_value=" 001 ",
        columns=("id", " id ", "name", " name ", "note", "count"),
        values=("other", " 001 ", "数值", " 机场 ", "\t \r\n", "0001"),
    )
    registry = SourceDefinitionRegistry((CSV_ROW_SOURCE_DEFINITION,))
    source = asyncio.run(registry.resolve(row))
    evidence = TextEvidence.model_validate(registry.project(source, TEXT_EVIDENCE_PROJECTION_KEY))
    expected_row = {
        "id": "other",
        " id ": " 001 ",
        "name": "数值",
        " name ": " 机场 ",
        "note": "\t \r\n",
        "count": "0001",
    }

    assert source.materialization is SourceMaterialization.CAPTURED
    assert asyncio.run(registry.read(source)) == row
    assert evidence.content == json.dumps(expected_row, ensure_ascii=False, separators=(",", ":"))
    assert evidence.metadata == {
        "document_id": row.document_id,
        "primary_key": row.primary_key,
        "primary_key_value": row.primary_key_value,
        "columns": list(row.columns),
        "row": expected_row,
    }
    assert list(json.loads(evidence.content)) == list(row.columns)


def test_csv_strict_semantics_allow_literal_quotes_and_preserve_quoted_crlf() -> None:
    rows = parse_csv_document(
        CSVDocumentInput(
            document_id="quote-control",
            primary_key="id",
            content=b'id,note\r\n1,say "hello"\r\n2,"quoted\r\nlines"\r\n',
        )
    )
    assert tuple(row.values for row in rows) == (("1", 'say "hello"'), ("2", "quoted\r\nlines"))


@pytest.mark.parametrize("invalid_record", [b"2,extra,field\n", b'2,"closed"tail\n'])
def test_invalid_later_record_fails_at_the_parse_call(invalid_record: bytes) -> None:
    with pytest.raises(ValueError):
        parse_csv_document(
            CSVDocumentInput(
                document_id="atomic-control",
                primary_key="id",
                content=b"id,note\n1,valid-first-row\n" + invalid_record,
            )
        )


@pytest.mark.parametrize(
    ("columns", "values"),
    [
        (("id", "note"), ("1",)),
        (("id", "note"), ("1", "kept", "must-not-disappear")),
        (("id", "id"), ("1", "1")),
        (("id", "note"), ("different-key", "text")),
    ],
)
def test_invalid_direct_rows_are_rejected_before_registry_projection(
    columns: tuple[str, ...], values: tuple[str, ...],
) -> None:
    registry = SourceDefinitionRegistry((CSV_ROW_SOURCE_DEFINITION,))
    with pytest.raises(ValueError):
        row = CSVRowInput(
            document_id="direct-control",
            primary_key="id",
            primary_key_value="1",
            columns=columns,
            values=values,
        )
        source = asyncio.run(registry.resolve(row))
        registry.project(source, TEXT_EVIDENCE_PROJECTION_KEY)
