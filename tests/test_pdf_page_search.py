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

import pytest

from powercontext.artifacts import MemoryCitation
from powercontext.builtin.runtime import GetMemoryEntryRequest, open_builtin_runtime
from powercontext.builtin.scope import ScopeDraft
from powercontext.sources import SourceDefinitionRegistry, project_source_for_transport
from powercontext.sources.pdf_pages import PDF_PAGE_SOURCE_DEFINITION, PDFPageInput, search_pdf_pages
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY
from selftest_support.source_acceptance import persist

if TYPE_CHECKING:
    from pathlib import Path


async def _persist_pages(tmp_path: Path, pages: tuple[PDFPageInput, ...]):
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    observations = [project_source_for_transport(registry, await registry.resolve(page)) for page in pages]
    config, scope_id, stored = await persist(tmp_path, PDF_PAGE_SOURCE_DEFINITION, observations)
    return config, scope_id, stored, pages


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
    return await _persist_pages(tmp_path, pages)


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


def _competing_company_pages(company: str) -> tuple[PDFPageInput, ...]:
    digest = hashlib.sha256(b"synthetic competing company reports").hexdigest()
    return (
        PDFPageInput(
            document_id=f"{company}_2023_10K",
            document_sha256=digest,
            page_number=1,
            text="Consolidated statements of income. Revenue 480. Cost of sales 300. "
            "Operating income 90. Net income 65.",
        ),
        *(
            PDFPageInput(
                document_id="BETA_2022_10K",
                document_sha256=digest,
                page_number=number,
                text="Operating income. " * 4,
            )
            for number in range(1, 22)
        ),
    )


async def _retrieved_documents(memory, citations, stored) -> tuple[str, ...]:
    documents = []
    for citation in citations:
        record = await memory.get(GetMemoryEntryRequest(citation=citation))
        assert record.citation == citation
        source = stored[record.entry.sources[0].source_id]
        documents.append(source.projection(TEXT_EVIDENCE_PROJECTION_KEY)["metadata"]["document_id"])
    return tuple(documents)


@pytest.mark.parametrize(
    "company, mention",
    (("ACME", "Acme"), ("3M", "3M"), ("Cedar_Industries", "Cedar Industries"), ("CEDARINDUSTRIES", "Cedar Industries")),
)
async def test_named_company_survives_other_reports_repeating_financial_terms(
    tmp_path: Path, company: str, mention: str
) -> None:
    config, scope_id, stored, _pages = await _persist_pages(tmp_path, _competing_company_pages(company))
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope_id)
        citations = await search_pdf_pages(memory, f"What is {mention}'s operating income for FY2022?", limit=20)
        documents = await _retrieved_documents(memory, citations, stored)
        assert documents
        assert set(documents) == {f"{company}_2023_10K"}


async def test_comparison_retains_multiple_named_companies(tmp_path: Path) -> None:
    pages = _competing_company_pages("ACME") + (_competing_company_pages("3M")[0],)
    config, scope_id, stored, _pages = await _persist_pages(tmp_path, pages)
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope_id)
        citations = await search_pdf_pages(memory, "Compare Acme and 3M operating income for FY2022.", limit=20)
        assert set(await _retrieved_documents(memory, citations, stored)) == {"ACME_2023_10K", "3M_2023_10K"}


async def test_unnamed_company_keeps_reports_available(tmp_path: Path) -> None:
    config, scope_id, stored, _pages = await _persist_pages(tmp_path, _competing_company_pages("ACME"))
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope_id)
        citations = await search_pdf_pages(memory, "Which reports show operating income?", limit=30)
        assert set(await _retrieved_documents(memory, citations, stored)) == {"ACME_2023_10K", "BETA_2022_10K"}


def _competing_statement_pages(income_heading: str, cash_flow_heading: str) -> tuple[PDFPageInput, ...]:
    digest = hashlib.sha256(b"synthetic statement coverage report").hexdigest()
    texts = (
        f"{income_heading}\n2022 Revenue 480 Cost of sales 300 Operating profit 90 Net income 65.",
        f"{cash_flow_heading}\n2022 Net cash provided by operating activities 140 "
        "Depreciation and amortization 25 Purchases of property plant and equipment 40.",
        *(
            "Management discussion: EBITDA capex operating income depreciation amortization cash flow "
            "income statement capital expenditure spending purchase property plant equipment."
            for _ in range(21)
        ),
        *(
            "Revenue sales cost gross profit net income earnings operating profit income 100. "
            "Business overview and accounting notes."
            for _ in range(30)
        ),
    )
    return tuple(
        PDFPageInput(
            document_id="CEDAR_INDUSTRIES_2022_10K",
            document_sha256=digest,
            page_number=number,
            text=text,
        )
        for number, text in enumerate(texts, start=1)
    )


@pytest.mark.parametrize(
    "income_heading,cash_flow_heading",
    (
        ("Consolidated Statement of Income", "Consolidated Statement of Cash Flows"),
        ("Consolidated\nStatements of\nIncome", "Condensed Consolidated Statements\nof Cash Flows (continued)"),
        ("Consolidated Profit and Loss Statement", "Consolidated Cash-Flow Statement"),
    ),
)
async def test_explicit_statements_survive_keyword_heavy_discussion_pages(
    tmp_path: Path, income_heading: str, cash_flow_heading: str
) -> None:
    config, scope_id, stored, pages = await _persist_pages(
        tmp_path, _competing_statement_pages(income_heading, cash_flow_heading)
    )
    question = (
        "What is FY2022 EBITDA less capex for Cedar Industries? Use operating income plus depreciation "
        "and amortization from the cash flow statement and the income statement."
    )
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope_id)
        citations = await search_pdf_pages(memory, question, limit=20)
        numbers = await _read_page_numbers(memory, citations, stored, pages)
        assert len(citations) <= 20
        assert {1, 2}.issubset(numbers)
        limited = await search_pdf_pages(memory, question, limit=1)
        assert len(limited) == 1
        assert set(await _read_page_numbers(memory, limited, stored, pages)).issubset({1, 2})


async def test_explicit_balance_sheet_title_is_covered(tmp_path: Path) -> None:
    pages = _competing_statement_pages("Consolidated Balance Sheets", "Consolidated Statement of Cash Flows")
    config, scope_id, stored, pages = await _persist_pages(tmp_path, pages)
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope_id)
        citations = await search_pdf_pages(
            memory, "Use Cedar Industries' balance sheet and statement of cash flows for FY2022.", limit=2
        )
        assert set(await _read_page_numbers(memory, citations, stored, pages)) == {1, 2}


@pytest.mark.parametrize(
    "question",
    (
        "Use Cedar Industries' income and cash-flow statements to find operating profit and cash generation.",
        "What fraction of Cedar Industries' net sales is cash generated from operations after subtracting "
        "purchases of property, plant and equipment?",
        "For Cedar Industries, what percentage of operating income was cash provided by operating activities?",
    ),
)
async def test_shared_statement_names_and_financial_ratios_cover_each_source(tmp_path: Path, question: str) -> None:
    config, scope_id, stored, pages = await _persist_pages(
        tmp_path,
        _competing_statement_pages("Consolidated Statement of Income", "Consolidated Statement of Cash Flows"),
    )
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope_id)
        citations = await search_pdf_pages(memory, question, limit=20)
        assert {1, 2}.issubset(await _read_page_numbers(memory, citations, stored, pages))


@pytest.mark.parametrize(
    "question,disclosure",
    (
        (
            "Why does revenue attributed to geographic regions differ from final consumer demand?",
            "Revenue attributed to geographic regions differs from final consumer demand because customers "
            "export the products to consumers in other regions.",
        ),
        (
            "What percentage of Cedar Industries' revenue comes from Europe?",
            "Europe represented 30 percent of Cedar Industries' revenue. Geographic regional disclosures.",
        ),
        (
            "What percentage of Cedar Industries' revenue did the litigation settlement represent?",
            "The litigation settlement represented 4 percent of Cedar Industries' revenue. "
            "Legal proceedings disclosures.",
        ),
    ),
)
async def test_single_source_ratios_keep_specific_disclosures_ahead_of_statements(
    tmp_path: Path, question: str, disclosure: str
) -> None:
    pages = _competing_statement_pages("Consolidated Statement of Income", "Consolidated Statement of Cash Flows")
    operational_page = PDFPageInput(
        document_id=pages[0].document_id,
        document_sha256=pages[0].document_sha256,
        page_number=len(pages) + 1,
        text=disclosure,
    )
    config, scope_id, stored, pages = await _persist_pages(tmp_path, (*pages, operational_page))
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope_id)
        citations = await search_pdf_pages(memory, question, limit=1)
        assert await _read_page_numbers(memory, citations, stored, pages) == (operational_page.page_number,)
