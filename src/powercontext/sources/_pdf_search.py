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

"""Offline financial-page retrieval using exact, scope-owned Memory citations."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from powercontext.builtin.runtime.models import SearchMemoryRequest

if TYPE_CHECKING:
    from collections.abc import Sequence

    from powercontext.artifacts import MemoryCitation
    from powercontext.builtin.runtime.application import ScopedMemoryApplication
    from powercontext.builtin.runtime.models import MemoryEntryRecord


_WORDS = re.compile(r"[a-z]+|\d+", re.IGNORECASE)
_YEARS = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_STOP_WORDS = frozenset(
    "a an the and or for of to in on at by from with as is are was were be been being what which who how why when "
    "where do does did can could should would i we you it its our your this that these those please has have had "
    "any some all each than then if also about into during per based according question answer respond response "
    "assuming assume perspective investment analyst use using rely relying details shown show provided provide "
    "calculate calculated calculation define defined state directly explicitly quantity amount value figure "
    "million millions billion billions usd dollar dollars fiscal fy year years annual report reported reporting "
    "primarily respective respectively relevant information concerning tell give find determine".split()
)

# Vocabulary is shared across companies and reports; no question or document identity is encoded here.
_FINANCIAL_VOCABULARY = (
    (
        "geography geographies geographic geographical region country countries",
        "geographic geographical segment division international foreign region country",
        ("geographic information", "business segments", "reportable segments", "principal markets"),
    ),
    (
        "legal litigation lawsuit lawsuits battle proceeding proceedings contingency contingencies",
        "legal litigation lawsuit proceeding contingency claim dispute pending",
        ("legal proceedings", "legal matters", "litigation", "commitments contingencies"),
    ),
    (
        "restructuring restructure reorganization reorganize",
        "restructuring reorganization charge cost expense severance impairment",
        ("restructuring charges", "restructuring costs"),
    ),
    (
        "capex",
        "capital expenditure spending purchase property plant equipment",
        ("capital expenditures", "capital spending", "property plant equipment"),
    ),
    (
        "ebitda",
        "operating income depreciation amortization",
        ("operating income", "depreciation amortization", "cash flows"),
    ),
    (
        "revenue revenues sales turnover",
        "revenue revenues sales",
        ("net revenues", "net sales", "total revenues"),
    ),
    (
        "debt borrowing borrowings indebtedness",
        "debt borrowing indebtedness loan note maturity interest",
        ("long term debt", "short term debt", "credit facilities"),
    ),
    (
        "dividend dividends",
        "dividend cash share distribution shareholder",
        ("cash dividends", "dividends per share"),
    ),
    (
        "repurchase buyback",
        "repurchase share stock treasury",
        ("share repurchases", "treasury stock"),
    ),
    (
        "eps",
        "earnings income share diluted basic weighted average",
        ("earnings per share", "weighted average shares", "net income"),
    ),
    (
        "pension retirement benefit",
        "pension retirement benefit obligation plan expense",
        ("pension benefits", "retirement plans", "benefit obligations"),
    ),
)
_PHRASE_VOCABULARY = (
    (
        ("income statement", "profit loss", "p l"),
        "income earnings operation profit revenue sales",
        ("consolidated statements income", "statements operations", "statements earnings", "operating income"),
    ),
    (
        ("cash flow", "cashflow"),
        "cash flow operating investing financing",
        ("statements cash flows", "cash provided operating activities", "cash used investing activities"),
    ),
    (
        ("capital expenditure", "capital spending"),
        "capital expenditure spending purchase property plant equipment",
        ("capital expenditures", "capital spending", "property plant equipment"),
    ),
    (
        ("free cash flow",),
        "cash operating capital expenditure",
        ("cash provided operating activities", "capital expenditures"),
    ),
    (
        ("current ratio", "working capital", "quick ratio"),
        "current asset liability cash receivable inventory",
        ("current assets", "current liabilities", "balance sheets"),
    ),
    (
        ("gross margin", "gross profit"),
        "gross profit revenue sales cost",
        ("gross profit", "cost sales", "cost revenue", "net revenues"),
    ),
    (
        ("asset turnover", "return assets"),
        "income revenue sales total asset",
        ("total assets", "net income", "net revenues"),
    ),
)


def _stem(word: str) -> str:
    if len(word) > 5 and word.endswith("ies"):
        word = word[:-3] + "y"
    elif len(word) > 4 and word.endswith(("sses", "xes", "zes", "ches", "shes")):
        word = word[:-2]
    elif len(word) > 4 and word.endswith("s") and not word.endswith(("ss", "us")):
        word = word[:-1]
    if len(word) > 6 and word.endswith("ing"):
        word = word[:-3]
    elif len(word) > 5 and word.endswith("ed"):
        word = word[:-2]
    return word[:-1] if len(word) > 5 and word.endswith("e") else word


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(_stem(word) for word in _WORDS.findall(text.casefold()) if word not in _STOP_WORDS)


@dataclass(frozen=True)
class _Page:
    citation: MemoryCitation
    source_id: str
    document_id: str
    body: str
    counts: Counter[str]


def _pages(entries: Sequence[MemoryEntryRecord]) -> tuple[_Page, ...]:
    pages = []
    seen: set[str] = set()
    for record in entries:
        sources = record.entry.sources
        if len(sources) != 1 or sources[0].source_type != "pdf-page":
            continue
        source_id = sources[0].source_id
        if source_id in seen:
            continue
        seen.add(source_id)
        document_id, _separator, body = record.entry.text.partition("\n")
        counts = Counter(_tokens(body))
        if counts:
            pages.append(_Page(record.citation, source_id, document_id, body, counts))
    return tuple(pages)


def _query(question: str) -> tuple[dict[str, float], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    words = tuple(word for word in _WORDS.findall(question.casefold()) if word not in _STOP_WORDS)
    weights = {_stem(word): 0.15 if word.isdigit() else 1.0 for word in words}
    original = set(weights)
    phrases: set[str] = set()
    expanded_words: list[str] = []

    def expand(vocabulary: str, matches: tuple[str, ...]) -> None:
        for token in _tokens(vocabulary):
            weights[token] = max(weights.get(token, 0.0), 0.45)
        phrases.update(" ".join(_tokens(phrase)) for phrase in matches)
        expanded_words.extend(_WORDS.findall(vocabulary))

    for triggers, vocabulary, matches in _FINANCIAL_VOCABULARY:
        if original.intersection(_tokens(triggers)):
            expand(vocabulary, matches)
    normalized = " ".join(_tokens(question))
    for triggers, vocabulary, matches in _PHRASE_VOCABULARY:
        if any(f" {' '.join(_tokens(trigger))} " in f" {normalized} " for trigger in triggers):
            expand(vocabulary, matches)
    if re.search(r"\bd\s*&\s*a\b", question, re.IGNORECASE):
        expand("depreciation amortization", ("depreciation amortization",))
    if re.search(r"\bp\s*&\s*l\b", question, re.IGNORECASE):
        expand("income earnings profit revenue", ("statements income", "statements operations"))
    if "margin" in original:
        expand("revenue sales", ("net revenues", "net sales"))
    return weights, tuple(sorted(phrases)), tuple(dict.fromkeys(words)), tuple(dict.fromkeys(expanded_words))


def _document_terms(pages: tuple[_Page, ...]) -> set[str]:
    terms = set()
    for page in pages:
        terms.update(token for token in _tokens(page.document_id) if not token.isdigit() and len(token) > 1)
    return terms


def _named_company_pages(pages: tuple[_Page, ...], question: str) -> tuple[_Page, ...]:
    matched = set()
    for document_id in {page.document_id for page in pages}:
        company = re.split(r"(?<![a-z0-9])(?:19|20)\d{2}(?!\d)", document_id.casefold(), maxsplit=1)[0]
        company = re.sub(r"(?:10[\W_]*[kq]|20[\W_]*f|40[\W_]*f)[\W_]*$", "", company)
        words = re.findall(r"[a-z0-9]+", company)
        while words and words[-1] in {"inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "plc"}:
            words.pop()
        identity = "".join(words)
        if not identity:
            continue
        pattern = r"(?<![a-z0-9])" + r"[\W_]*".join(map(re.escape, identity)) + r"(?![a-z0-9])"
        if re.search(pattern, question.casefold()):
            matched.add(document_id)
    # A report's repeated financial vocabulary must not outweigh an explicit company identity.
    return tuple(page for page in pages if page.document_id in matched) if matched else pages


def _page_score(
    page: _Page,
    weights: dict[str, float],
    phrases: tuple[str, ...],
    idf: dict[str, float],
    document_terms: set[str],
    average_length: float,
) -> float:
    length_norm = 1.2 * (0.55 + 0.45 * page.counts.total() / average_length)
    score = 0.0
    for term, weight in weights.items():
        count = page.counts[term]
        if count:
            adjusted = weight * (0.12 if term in document_terms else 1.0)
            score += adjusted * idf[term] * count * 2.2 / (count + length_norm)
    normalized_body = " ".join(_tokens(page.body))
    heading = " ".join(_tokens(page.body[:1600]))
    for phrase in phrases:
        if phrase in normalized_body:
            phrase_weight = sum(idf.get(term, 0.0) for term in phrase.split()) / len(phrase.split())
            score += 0.45 * phrase_weight * (1.5 if phrase in heading else 1.0)
    return score


def _rank(
    pages: tuple[_Page, ...], question: str, weights: dict[str, float], phrases: tuple[str, ...]
) -> list[tuple[float, _Page]]:
    pages = _named_company_pages(pages, question)
    frequencies: Counter[str] = Counter()
    for page in pages:
        frequencies.update(page.counts.keys())
    idf = {term: math.log1p((len(pages) - count + 0.5) / (count + 0.5)) for term, count in frequencies.items()}
    document_terms = _document_terms(pages)
    topical = {term for term in weights if not term.isdigit() and term not in document_terms}
    if not topical:
        return []
    average_length = sum(page.counts.total() for page in pages) / len(pages)
    question_years = set(_YEARS.findall(question))
    ranked = []
    for page in pages:
        if not topical.intersection(page.counts):
            continue
        score = _page_score(page, weights, phrases, idf, document_terms, average_length)
        if question_years.intersection(_YEARS.findall(page.document_id)):
            score *= 1.05
        if score > 0:
            ranked.append((score, page))
    return sorted(ranked, key=lambda item: (-item[0], item[1].document_id, item[1].source_id))


def _select(ranked: list[tuple[float, _Page]], limit: int) -> tuple[MemoryCitation, ...]:
    candidates = ranked[: max(80, limit * 4)]
    selected: list[_Page] = []
    if not candidates:
        return ()
    maximum = candidates[0][0]
    while candidates and len(selected) < limit:
        def value(item: tuple[float, _Page]) -> float:
            score, page = item
            vocabulary = page.counts.keys()
            similarity = max(
                (
                    len(vocabulary & other.counts.keys()) / len(vocabulary | other.counts.keys())
                    for other in selected
                ),
                default=0.0,
            )
            return score / maximum - 0.12 * similarity

        choice = max(range(len(candidates)), key=lambda index: value(candidates[index]))
        selected.append(candidates.pop(choice)[1])
    return tuple(page.citation for page in selected)


async def search_pdf_pages(
    memory: ScopedMemoryApplication, question: str, limit: int = 10
) -> tuple[MemoryCitation, ...]:
    """Rank actual PDF page entries without models, external assets, or invented references.

    One scoped listing supplies the page corpus for offline ranking. Two bounded full-text
    searches add exact lexical evidence without letting a long question's admission floor
    hide relevant pages. Every returned citation belongs to a stored page entry.
    """

    if limit <= 0 or not question.strip():
        return ()
    weights, phrases, words, expanded_words = _query(question)
    if not weights:
        return ()
    pages = _pages((await memory.list()).entries)
    if not pages:
        return ()
    ranked = _rank(pages, question, weights, phrases)
    if not ranked:
        return ()
    queries = [" ".join(words[:12])]
    if expanded_words:
        queries.append(" ".join(expanded_words[:8]))
    signals: dict[tuple[str, str], float] = {}
    for query in dict.fromkeys(queries):
        if not query.strip():
            continue
        result = await memory.search(SearchMemoryRequest(query=query, mode="fts", limit=min(160, max(40, limit * 4))))
        for rank, hit in enumerate(result.hits, start=1):
            identity = (hit.entry_id, hit.entry_version_id)
            signals[identity] = signals.get(identity, 0.0) + 1.0 / (10 + rank)
    maximum_signal = max(signals.values(), default=1.0)
    maximum_score = ranked[0][0]
    ranked = [
        (
            score
            + 0.05 * maximum_score * signals.get((page.citation.entry_id, page.citation.entry_version_id), 0.0)
            / maximum_signal,
            page,
        )
        for score, page in ranked
    ]
    ranked.sort(key=lambda item: (-item[0], item[1].document_id, item[1].source_id))
    return _select(ranked, limit)


__all__ = ["search_pdf_pages"]
