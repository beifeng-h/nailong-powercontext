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

"""Synthetic page recall through persisted Runtime and exact public citations."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from powercontext.artifacts import MemoryCitation
from powercontext.builtin.runtime import GetMemoryEntryRequest, open_builtin_runtime
from powercontext.builtin.scope import ScopeDraft
from powercontext.sources import SourceDefinitionRegistry, project_source_for_transport
from powercontext.sources.pdf_pages import PDF_PAGE_SOURCE_DEFINITION, PDFPageInput, search_pdf_pages
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY
from selftest_support.source_acceptance import persist

if TYPE_CHECKING:
    from pathlib import Path


async def _persist_financial_pages(tmp_path: Path):
    digest = hashlib.sha256(b"synthetic financial report revision one").hexdigest()
    pages = tuple(
        PDFPageInput(document_id="Cedar_Industries_2025", document_sha256=digest, page_number=number, text=text)
        for number, text in enumerate(
            (
                "Consolidated statements of income\n"
                "Revenue 480. Cost of sales 300. Operating income 90. Net income 65.",
                "Consolidated statements of cash flows\n"
                "Net cash provided by operating activities 140. Depreciation and amortization 25.\n"
                "Capital expenditures for property, plant and equipment 40.",
                "Office cafeteria menus, bicycle parking and employee shuttle schedules.",
            ),
            start=1,
        )
    )
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    observations = [project_source_for_transport(registry, await registry.resolve(page)) for page in pages]
    config, scope_id, stored = await persist(tmp_path, PDF_PAGE_SOURCE_DEFINITION, observations)
    return config, scope_id, stored, pages


async def _read_page_numbers(memory, citations, stored, pages) -> tuple[int, ...]:
    numbers = []
    assert isinstance(citations, tuple)
    for citation in citations:
        assert isinstance(citation, MemoryCitation)
        record = await memory.get(GetMemoryEntryRequest(citation=citation))
        assert record.citation == citation
        assert len(record.entry.sources) == 1
        reference = record.entry.sources[0]
        assert reference.source_type == "pdf-page"
        source = stored[reference.source_id]
        evidence = source.projection(TEXT_EVIDENCE_PROJECTION_KEY)
        metadata = evidence["metadata"]
        page = pages[metadata["page_number"] - 1]
        assert metadata == {
            "document_id": page.document_id,
            "document_sha256": page.document_sha256,
            "page_number": page.page_number,
        }
        assert record.entry.text == f"{page.document_id}\n{page.text}".strip()
        assert record.entry.text == evidence["content"].strip()
        numbers.append(page.page_number)
    assert len(numbers) == len(set(numbers))
    return tuple(numbers)


async def test_financial_question_recalls_exact_persisted_pages_after_reopen(tmp_path: Path) -> None:
    config, scope_id, stored, pages = await _persist_financial_pages(tmp_path)
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope_id)
        citations = await search_pdf_pages(
            memory,
            "Which pages support EBITDA using operating income plus depreciation and amortization?",
            limit=10,
        )
        numbers = await _read_page_numbers(memory, citations, stored, pages)
        assert len(citations) <= 10
        assert {1, 2}.issubset(numbers)


async def test_page_search_honors_limit_and_empty_or_unrelated_questions(tmp_path: Path) -> None:
    config, scope_id, stored, pages = await _persist_financial_pages(tmp_path)
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope_id)
        question = "Where are depreciation and amortization in the cash flow statements?"
        citations = await search_pdf_pages(memory, question, limit=1)
        assert len(citations) == 1
        assert await _read_page_numbers(memory, citations, stored, pages) == (2,)
        assert await search_pdf_pages(memory, question, limit=0) == ()
        assert await search_pdf_pages(memory, "orbital mechanics and lunar geology", limit=10) == ()
        assert await search_pdf_pages(memory, "", limit=10) == ()
        assert await search_pdf_pages(memory, " \t\n", limit=10) == ()


async def test_empty_scope_does_not_recall_another_scopes_report(tmp_path: Path) -> None:
    config, scope_id, _stored, _pages = await _persist_financial_pages(tmp_path)
    async with open_builtin_runtime(config) as runtime:
        question = "What is the operating income?"
        populated = runtime.memory.for_scope(scope_id)
        assert await search_pdf_pages(populated, question, limit=1)
        scope = await runtime.scopes.create(
            ScopeDraft(title="Empty report scope", summary="Synthetic scope isolation", idempotency_key="empty-pdf")
        )
        assert scope.scope_id != scope_id
        assert await search_pdf_pages(runtime.memory.for_scope(scope.scope_id), question, limit=10) == ()
