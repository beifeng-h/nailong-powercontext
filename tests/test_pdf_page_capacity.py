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

"""Complete captured PDF pages retain their text beyond the ordinary Memory limit."""

from __future__ import annotations

import hashlib
import io
from typing import TYPE_CHECKING

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from powercontext.builtin.artifacts.memory import (
    InvalidMemoryCandidateError,
    InvalidMemoryEvidenceError,
    MemoryEntryInput,
)
from powercontext.builtin.artifacts.memory.canonical import entry_content_hash
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    GetMemoryEntryRequest,
    RememberMemoryRequest,
    SearchMemoryRequest,
    SubmitSourceObservation,
    open_builtin_contexts,
    open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeDraft
from powercontext.errors import SourceNotFoundError
from powercontext.sources import SourceDefinitionRegistry, manifest_for_definition, project_source_for_transport
from powercontext.sources.pdf_pages import (
    PDF_PAGE_SOURCE_DEFINITION,
    PDFDocumentInput,
    PDFPageInput,
    parse_pdf_document,
    search_pdf_pages,
)
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY
from selftest_support.source_acceptance import persist

if TYPE_CHECKING:
    from pathlib import Path


def _config(directory: Path) -> BuiltinConfig:
    return BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{directory / 'capacity.db'}"))


def _dense_pdf() -> bytes:
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    for rows in (150, 0, 5):
        page = writer.add_blank_page(width=612, height=792)
        if not rows:
            continue
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
        )
        lines = [b"BT /F1 5 Tf 5 TL 30 770 Td"]
        for number in range(1, rows + 1):
            text = (
                f"Row {number:03d} revenue receivables operating income cash generation inventories payable totals."
            )
            if number == 150:
                text += " tailcapacityanchor"
            lines.append(f"({text}) Tj T*".encode("ascii"))
        lines.append(b"ET")
        stream = DecodedStreamObject()
        stream.set_data(b"\n".join(lines))
        page[NameObject("/Contents")] = writer._add_object(stream.flate_encode())
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


async def _observation(page: PDFPageInput):
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    source = await registry.resolve(page)
    assert await registry.read(source) == page
    return project_source_for_transport(registry, source)


async def _submit_page(contexts, scope_id: str, page: PDFPageInput):
    observation = await _observation(page)
    await contexts.register_source_definition(manifest_for_definition(PDF_PAGE_SOURCE_DEFINITION))
    await contexts.submit_source_observation(SubmitSourceObservation(scope_id=scope_id, observation=observation))
    return observation


def _unicode_page() -> PDFPageInput:
    return PDFPageInput(
        document_id="unicode-page",
        document_sha256=hashlib.sha256(b"synthetic complete unicode page").hexdigest(),
        page_number=1,
        text="界" * 2731,
    )


async def test_dense_physical_pdf_page_survives_ingestion_reopen_and_projection_rebuild(tmp_path: Path) -> None:
    raw = _dense_pdf()
    pages = parse_pdf_document(PDFDocumentInput(document_id="dense-report", content=raw))
    assert [page.page_number for page in pages] == [1, 2, 3]
    assert len(pages[0].text.encode("utf-8")) > 8192
    assert pages[1].text == ""
    assert len(pages[2].text.encode("utf-8")) < 8192
    assert all(f"Row {number:03d}" in pages[0].text for number in range(1, 151))
    assert all(page.document_sha256 == hashlib.sha256(raw).hexdigest() for page in pages)
    observations = [await _observation(page) for page in pages]
    config, scope_id, stored = await persist(tmp_path, PDF_PAGE_SOURCE_DEFINITION, observations)
    assert len(stored) == 3
    expected = observations[0].projection(TEXT_EVIDENCE_PROJECTION_KEY)["content"].strip()

    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope_id)
        entries = (await memory.list()).entries
        assert len(entries) == 3
        record = next(entry for entry in entries if entry.entry.sources[0].source_id == observations[0].name)
        assert record.entry.text == expected
        assert record.entry.entry_content_hash == entry_content_hash(
            kind=record.entry.kind,
            text=expected,
            source_refs=tuple(reference.model_dump(mode="json") for reference in record.entry.sources),
            artifact_refs=tuple(reference.model_dump(mode="json") for reference in record.entry.artifacts),
        )
        hits = await memory.search(SearchMemoryRequest(query="tailcapacityanchor", mode="fts"))
        assert any(hit.entry_version_id == record.entry.entry_version_id for hit in hits.hits)
        assert record.citation in await search_pdf_pages(memory, "Find tailcapacityanchor", limit=3)
        assert await memory.get(GetMemoryEntryRequest(citation=record.citation)) == record

    async with open_builtin_contexts(config) as contexts:
        context = await contexts.get(scope_id)
        assert len(await context.sources.journal.entries()) == 3
        await context.artifacts.memory.rebuild_projections()

    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope_id)
        assert await memory.get(GetMemoryEntryRequest(citation=record.citation)) == record
        assert record.citation in await search_pdf_pages(memory, "Find tailcapacityanchor", limit=3)
        assert (await memory.list()).memory_ref == record.memory_ref


async def test_complete_captured_page_can_exceed_utf8_byte_limit_with_fewer_characters(tmp_path: Path) -> None:
    page = _unicode_page()
    observation = await _observation(page)
    expected = observation.projection(TEXT_EVIDENCE_PROJECTION_KEY)["content"].strip()
    assert len(expected) < 8192 < len(expected.encode("utf-8"))
    config, scope_id, _stored = await persist(tmp_path, PDF_PAGE_SOURCE_DEFINITION, [observation])
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope_id)
        entries = (await memory.list()).entries
        assert len(entries) == 1
        assert entries[0].entry.text == expected
        assert await memory.get(GetMemoryEntryRequest(citation=entries[0].citation)) == entries[0]


async def test_ordinary_memory_keeps_8192_utf8_byte_limit_without_partial_writes(tmp_path: Path) -> None:
    boundary = "界" * 2730 + "ab"
    assert len(boundary.encode("utf-8")) == 8192
    async with open_builtin_runtime(_config(tmp_path)) as runtime:
        scope = await runtime.scopes.create(ScopeDraft(title="Ordinary", summary="Byte limit", idempotency_key="plain"))
        memory = runtime.memory.for_scope(scope.scope_id)
        written = await memory.remember(RememberMemoryRequest(entries=(MemoryEntryInput(kind="note", text=boundary),)))
        assert written.entry is not None
        with pytest.raises(InvalidMemoryCandidateError) as rejected:
            await memory.remember(
                RememberMemoryRequest(entries=(MemoryEntryInput(kind="note", text=boundary + "c"),))
            )
        assert rejected.value.canonical_code == "text-too-long"
        assert (await memory.list()).entries == (written.entry,)
        assert await memory.get(GetMemoryEntryRequest(citation=written.entry.citation)) == written.entry


async def test_long_memory_with_captured_source_must_equal_its_complete_projection(tmp_path: Path) -> None:
    async with open_builtin_contexts(_config(tmp_path)) as contexts:
        scope = await contexts.scopes.create(
            ScopeDraft(title="Captured", summary="Exact evidence", idempotency_key="exact")
        )
        observation = await _submit_page(contexts, scope.scope_id, _unicode_page())
        context = await contexts.get(scope.scope_id)
        text = observation.projection(TEXT_EVIDENCE_PROJECTION_KEY)["content"] + " unrelated addition"
        with pytest.raises(InvalidMemoryCandidateError) as rejected:
            await context.artifacts.memory.remember(
                memory=None,
                sources=(observation,),
                entries=(MemoryEntryInput(kind="source-evidence", text=text, sources=(observation,)),),
                mode="append",
            )
        assert rejected.value.canonical_code == "text-too-long"
        assert len(await context.sources.journal.entries()) == 1


async def test_long_memory_cannot_claim_a_captured_source_outside_allowed_evidence(tmp_path: Path) -> None:
    async with open_builtin_contexts(_config(tmp_path)) as contexts:
        scope = await contexts.scopes.create(
            ScopeDraft(title="Allowed", summary="Evidence set", idempotency_key="allowed")
        )
        long_source = await _submit_page(contexts, scope.scope_id, _unicode_page())
        short_page = _unicode_page().model_copy(update={"page_number": 2, "text": "Short page."})
        short_source = await _submit_page(contexts, scope.scope_id, short_page)
        context = await contexts.get(scope.scope_id)
        with pytest.raises(InvalidMemoryEvidenceError) as rejected:
            await context.artifacts.memory.remember(
                memory=None,
                sources=(short_source,),
                entries=(
                    MemoryEntryInput(
                        kind="source-evidence",
                        text=long_source.projection(TEXT_EVIDENCE_PROJECTION_KEY)["content"],
                        sources=(long_source,),
                    ),
                ),
                mode="append",
            )
        assert rejected.value.code == "source-outside"


async def test_unrecorded_source_projection_cannot_authorize_long_memory_text(tmp_path: Path) -> None:
    observation = await _observation(_unicode_page())
    async with open_builtin_contexts(_config(tmp_path)) as contexts:
        scope = await contexts.scopes.create(
            ScopeDraft(title="Unrecorded", summary="No capture", idempotency_key="missing")
        )
        await contexts.register_source_definition(manifest_for_definition(PDF_PAGE_SOURCE_DEFINITION))
        context = await contexts.get(scope.scope_id)
        with pytest.raises(SourceNotFoundError):
            await context.artifacts.memory.remember(
                memory=None,
                sources=(observation,),
                entries=(
                    MemoryEntryInput(
                        kind="source-evidence",
                        text=observation.projection(TEXT_EVIDENCE_PROJECTION_KEY)["content"],
                        sources=(observation,),
                    ),
                ),
                mode="append",
            )
        assert await context.sources.journal.entries() == ()
