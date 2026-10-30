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

"""Related notes remain retrievable alongside tables from multiple stored reports."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest

from powercontext.artifacts import MemoryCitation
from powercontext.builtin.runtime import GetMemoryEntryRequest, open_builtin_runtime
from powercontext.sources import SourceDefinitionRegistry, project_source_for_transport
from powercontext.sources.pdf_pages import PDF_PAGE_SOURCE_DEFINITION, PDFPageInput, search_pdf_pages
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY
from selftest_support.source_acceptance import persist

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("facet_count", (2, 3), ids=("income-cash", "income-cash-balance"))
async def test_related_note_and_required_tables_survive_other_reports_coverage(
    tmp_path: Path, facet_count: int
) -> None:
    statements = (
        ("Consolidated Statements of Income", "Revenue 100. Operating income 20. Net income 12."),
        ("Consolidated Statements of Cash Flows", "Cash provided by operating activities 15. Noncash tax 2."),
        ("Consolidated Balance Sheets", "Total assets 200. Trade receivables 30. Total liabilities 80."),
    )[:facet_count]
    note = (
        "Zephyrgrant noncash adjustment reconciliation. Acme recognized the project grant in income before "
        "cash collection, causing a temporary difference between the income statement and cash flow statement "
        "amounts. The effect reverses when the grant receivable is collected."
    )
    if facet_count == 3:
        note += " The grant receivable remains an asset on the balance sheet until collection."
    question = (
        "For Acme, explain the Zephyrgrant noncash adjustment that reconciles the income statement "
        "and cash flow statement"
    )
    question += " and balance sheet." if facet_count == 3 else "."
    pages = []
    target_id = "report-1"
    note_number = 2 * facet_count + 1
    for index in range(1, 6):
        document_id = f"report-{index}"
        digest = hashlib.sha256(f"synthetic opaque report revision {index}".encode()).hexdigest()
        for number, (heading, body) in enumerate(
            ((heading + suffix, body) for heading, body in statements for suffix in ("", " (continued)")),
            start=1,
        ):
            pages.append(
                PDFPageInput(
                    document_id=document_id,
                    document_sha256=digest,
                    page_number=number,
                    text=f"{heading}\n{body}",
                )
            )
        if document_id == target_id:
            note_page = PDFPageInput(
                document_id=document_id,
                document_sha256=digest,
                page_number=note_number,
                text=note,
            )
            pages.append(note_page)

    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    observations = [project_source_for_transport(registry, await registry.resolve(page)) for page in pages]
    config, scope_id, stored = await persist(tmp_path, PDF_PAGE_SOURCE_DEFINITION, observations)
    expected_pages = {(page.document_id, page.document_sha256, page.page_number): page for page in pages}

    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope_id)
        citations = await search_pdf_pages(memory, question, limit=20)
        assert isinstance(citations, tuple) and len(citations) <= 20
        locations = set()
        target_numbers = set()
        for citation in citations:
            assert isinstance(citation, MemoryCitation)
            record = await memory.get(GetMemoryEntryRequest(citation=citation))
            assert record.citation == citation
            assert len(record.entry.sources) == 1
            reference = record.entry.sources[0]
            assert reference.source_type == "pdf-page"
            projection = stored[reference.source_id].projection(TEXT_EVIDENCE_PROJECTION_KEY)
            assert projection["source_type"] == reference.source_type
            assert projection["source_id"] == reference.source_id
            metadata = projection["metadata"]
            assert set(metadata) == {"document_id", "document_sha256", "page_number"}
            location = (metadata["document_id"], metadata["document_sha256"], metadata["page_number"])
            assert location not in locations
            locations.add(location)
            page = expected_pages[location]
            assert projection["content"] == f"{page.document_id}\n{page.text}"
            assert record.entry.text == projection["content"].strip()
            if page.document_id == target_id:
                target_numbers.add(page.page_number)
        assert note_number in target_numbers
        for index in range(facet_count):
            assert target_numbers.intersection({2 * index + 1, 2 * index + 2})
