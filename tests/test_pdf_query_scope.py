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

"""Natural financial queries retain their evidence through real scoped Memory."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest
from selftest_support.source_acceptance import persist

from powercontext.artifacts import MemoryCitation
from powercontext.builtin.runtime import GetMemoryEntryRequest, open_builtin_runtime
from powercontext.sources import SourceDefinitionRegistry, project_source_for_transport
from powercontext.sources.pdf_pages import (
    PDF_PAGE_SOURCE_DEFINITION,
    PDFPageInput,
    search_pdf_pages,
)
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY

if TYPE_CHECKING:
    from pathlib import Path


def _page(document_id: str, number: int, text: str) -> PDFPageInput:
    return PDFPageInput(
        document_id=document_id,
        document_sha256=hashlib.sha256(f"synthetic complete revision {document_id}".encode()).hexdigest(),
        page_number=number,
        text=text,
    )


async def _persist_pages(tmp_path: Path, pages: tuple[PDFPageInput, ...]):
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    observations = [project_source_for_transport(registry, await registry.resolve(page)) for page in pages]
    return await persist(tmp_path, PDF_PAGE_SOURCE_DEFINITION, observations)


async def _retrieved_locations(memory, citations, stored) -> set[tuple[str, int]]:
    assert isinstance(citations, tuple) and len(citations) <= 20
    locations = set()
    for citation in citations:
        assert isinstance(citation, MemoryCitation)
        record = await memory.get(GetMemoryEntryRequest(citation=citation))
        assert record.citation == citation and len(record.entry.sources) == 1
        reference = record.entry.sources[0]
        assert reference.source_type == "pdf-page"
        projection = stored[reference.source_id].projection(TEXT_EVIDENCE_PROJECTION_KEY)
        assert projection["source_type"] == reference.source_type
        assert projection["source_id"] == reference.source_id
        assert record.entry.text == projection["content"].strip()
        metadata = projection["metadata"]
        assert set(metadata) == {"document_id", "document_sha256", "page_number"}
        location = (metadata["document_id"], metadata["page_number"])
        assert location not in locations
        locations.add(location)
    return locations


async def test_named_company_note_survives_other_companies_statement_coverage(
    tmp_path: Path,
) -> None:
    document_id = "HARBOR_2025_10K"
    pages = [
        _page(
            document_id,
            1,
            "Consolidated Statements of Income\nRevenue 450. Operating income 80.",
        ),
        _page(
            document_id,
            2,
            "Consolidated Statements of Cash Flows\nCash from operations 110.",
        ),
        _page(
            document_id,
            3,
            "Revenue recognition note\nOperating income includes contract revenue earned before customers pay. "
            "Cash flow increases when those receivables are collected. "
            + "Accounting policies describe inventory costing, insurance, leases and employee benefits. "
            * 12,
        ),
        *(
            _page(
                document_id,
                number,
                "The report describes personnel policies, insurance contracts and office leases.",
            )
            for number in range(4, 33)
        ),
    ]
    for index in range(6):
        other_id = f"OTHER{index}_2025_10K"
        for number in range(1, 5):
            heading = "Consolidated Statements of Income" if number % 2 else "Consolidated Statements of Cash Flows"
            pages.append(
                _page(
                    other_id,
                    number,
                    heading + "\n" + "Operating income and cash flow reconciliation. " * 6,
                )
            )
    config, scope_id, stored = await _persist_pages(tmp_path, tuple(pages))
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope_id)
        citations = await search_pdf_pages(
            memory,
            "For Harbor, explain why operating income differs from cash flow, using its income statement "
            "and cash flow statement.",
            limit=20,
        )
        locations = await _retrieved_locations(memory, citations, stored)
        assert (document_id, 3) in locations


async def test_operating_margin_keeps_income_statement_and_explicit_management_drivers(
    tmp_path: Path,
) -> None:
    document_id = "HARBOR_2025_10K"
    pages = (
        _page(
            document_id,
            1,
            "Consolidated Statements of Income\nNet sales 450. Earnings from operations 90. Net income 60.",
        ),
        _page(
            document_id,
            2,
            "Management discussion\nOperating margin improved because pricing gains exceeded higher freight costs.",
        ),
        *(
            _page(
                document_id,
                number,
                "Operating margin change reflects revenue and sales trends. " * 5,
            )
            for number in range(3, 25)
        ),
    )
    config, scope_id, stored = await _persist_pages(tmp_path, pages)
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope_id)
        citations = await search_pdf_pages(
            memory,
            "Explain Harbor's operating margin change and the effect of pricing and freight.",
            limit=20,
        )
        locations = await _retrieved_locations(memory, citations, stored)
        assert {(document_id, 1), (document_id, 2)}.issubset(locations)


async def test_capital_intensity_recalls_asset_investment_and_revenue_evidence(
    tmp_path: Path,
) -> None:
    document_id = "NIMBUS_2025_10K"
    pages = (
        _page(
            document_id,
            1,
            "Consolidated Balance Sheets\nProperty plant and equipment 900. Total assets 2000.",
        ),
        _page(
            document_id,
            2,
            "Consolidated Statements of Cash Flows\nPurchases of property plant and equipment 280.",
        ),
        _page(
            document_id,
            3,
            "Consolidated Statements of Income\nRevenue 4500. Net income 400.",
        ),
        *(
            _page(
                document_id,
                number,
                "Our business operates a capital-intensive production model. " * 4,
            )
            for number in range(4, 25)
        ),
    )
    config, scope_id, stored = await _persist_pages(tmp_path, pages)
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope_id)
        citations = await search_pdf_pages(
            memory,
            "Is Nimbus a capital-intensive business based on FY2025 data?",
            limit=20,
        )
        locations = await _retrieved_locations(memory, citations, stored)
        assert {(document_id, 1), (document_id, 2), (document_id, 3)}.issubset(locations)


@pytest.mark.parametrize(
    "document_id,mention",
    (("NORTHSTAR_2024Q2_10Q", "North Star"), ("3M_2024Q2_10Q", "3M")),
    ids=("spaced-company-quarter", "numeric-company-quarter"),
)
async def test_quarterly_company_identity_keeps_its_evidence(tmp_path: Path, document_id: str, mention: str) -> None:
    pages = (
        _page(document_id, 1, "Operating income 90. Revenue 450."),
        *(
            _page(
                "OTHER_2024Q2_10Q",
                number,
                "Operating income 400. Operating income includes product operating income. " * 4,
            )
            for number in range(1, 25)
        ),
    )
    config, scope_id, stored = await _persist_pages(tmp_path, pages)
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope_id)
        citations = await search_pdf_pages(memory, f"What was {mention}'s operating income in Q2 of FY2024?", limit=20)
        assert (document_id, 1) in await _retrieved_locations(memory, citations, stored)


@pytest.mark.parametrize(
    "question,rows,expected",
    (
        (
            "Give Harbor and Nimbus operating income in FY2025.",
            (
                ("HARBOR_2025_10K", "Harbor operating income 80."),
                ("NIMBUS_2025_10K", "Nimbus operating income 60."),
            ),
            {"HARBOR_2025_10K", "NIMBUS_2025_10K"},
        ),
        (
            "Compare Harbor, Nimbus and CS operating income in FY2025.",
            (
                ("HARBOR_2025_10K", "Harbor operating income 80."),
                ("NIMBUS_2025_10K", "Nimbus operating income 60."),
                ("CEDARSYSTEMS_2025_10K", "Cedar Systems operating income 40."),
            ),
            {"HARBOR_2025_10K", "NIMBUS_2025_10K", "CEDARSYSTEMS_2025_10K"},
        ),
        (
            "Give Harbor and CS operating income in FY2025.",
            (
                ("HARBOR_2025_10K", "Harbor operating income 80."),
                ("CEDARSYSTEMS_2025_10K", "Cedar Systems operating income 40."),
            ),
            {"HARBOR_2025_10K", "CEDARSYSTEMS_2025_10K"},
        ),
        (
            "Give Harbor's and CS's operating income in FY2025.",
            (
                ("HARBOR_2025_10K", "Harbor operating income 80."),
                ("CEDARSYSTEMS_2025_10K", "Cedar Systems operating income 40."),
            ),
            {"HARBOR_2025_10K", "CEDARSYSTEMS_2025_10K"},
        ),
        (
            "Give Harbor’s and CS’s operating income in FY2025.",  # noqa: RUF001 - Exercise curly possessives.
            (
                ("HARBOR_2025_10K", "Harbor operating income 80."),
                ("CEDARSYSTEMS_2025_10K", "Cedar Systems operating income 40."),
            ),
            {"HARBOR_2025_10K", "CEDARSYSTEMS_2025_10K"},
        ),
        (
            "Give Harbor's revenue and CS's operating income in FY2025.",
            (
                ("HARBOR_2025_10K", "Harbor revenue 450. Operating income 80."),
                ("CEDARSYSTEMS_2025_10K", "Cedar Systems operating income 40."),
            ),
            {"HARBOR_2025_10K", "CEDARSYSTEMS_2025_10K"},
        ),
        (
            "Give Harbor, CS operating income in FY2025.",
            (
                ("HARBOR_2025_10K", "Harbor operating income 80."),
                ("CEDARSYSTEMS_2025_10K", "Cedar Systems operating income 40."),
            ),
            {"HARBOR_2025_10K", "CEDARSYSTEMS_2025_10K"},
        ),
        (
            "Give operating income for Harbor/CS in FY2025.",
            (
                ("HARBOR_2025_10K", "Harbor operating income 80."),
                ("CEDARSYSTEMS_2025_10K", "Cedar Systems operating income 40."),
            ),
            {"HARBOR_2025_10K", "CEDARSYSTEMS_2025_10K"},
        ),
        (
            "Compare Harbor and Nimbus operating income in FY2025.",
            (
                ("report-a", "Harbor operating income 80."),
                ("report-b", "Nimbus operating income 60."),
            ),
            {"report-a", "report-b"},
        ),
    ),
    ids=(
        "multiple-without-compare",
        "unknown-company-alias",
        "one-known-and-unknown-alias-plain",
        "one-known-and-unknown-alias-ascii-possessive",
        "one-known-and-unknown-alias-curly-possessive",
        "metric-separated-unknown-alias",
        "comma-separated-unknown-alias",
        "slash-separated-unknown-alias",
        "opaque-document-ids",
    ),
)
async def test_multiple_company_queries_preserve_available_companies(
    tmp_path: Path, question: str, rows: tuple[tuple[str, str], ...], expected: set[str]
) -> None:
    pages = tuple(_page(document_id, 1, text) for document_id, text in rows)
    config, scope_id, stored = await _persist_pages(tmp_path, pages)
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope_id)
        citations = await search_pdf_pages(memory, question, limit=20)
        locations = await _retrieved_locations(memory, citations, stored)
        assert {(document_id, 1) for document_id in expected}.issubset(locations)


@pytest.mark.parametrize(
    "label,question",
    (
        ("OPERATING_INCOME", "What was operating income in FY2025?"),
        ("NET_REVENUE", "What was net revenue in FY2025?"),
        ("OPERATINGINCOME", "What was operating income in FY2025?"),
        ("NETREVENUE", "What was net revenue in FY2025?"),
    ),
    ids=("operating-income-label", "net-revenue-label", "joined-operating-income", "joined-net-revenue"),
)
async def test_financial_document_labels_do_not_hide_other_reports(tmp_path: Path, label: str, question: str) -> None:
    pages = (
        _page(f"{label}_2025_10K", 1, "Operating income 80. Net revenue 450."),
        _page("RIVER_2025_10K", 1, "Operating income 60. Net revenue 300."),
    )
    config, scope_id, stored = await _persist_pages(tmp_path, pages)
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope_id)
        citations = await search_pdf_pages(memory, question, limit=20)
        assert ("RIVER_2025_10K", 1) in await _retrieved_locations(memory, citations, stored)
