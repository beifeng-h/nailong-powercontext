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

"""Query-directed literal evidence selection with complete rendered byte accounting."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from powercontext.artifacts import ArtifactAddress
from powercontext.builtin.runtime.prepared_text import TRUST_POLICY

if TYPE_CHECKING:
    from collections.abc import Sequence

    from powercontext.builtin.runtime.prepared_context import MemoryEntryAddress, PreparedMemoryCandidates

_WORDS = re.compile(r"[^\W_]+", re.UNICODE)
_BREAKS = re.compile(r"[.!?。！？]+(?=\s|$)|\n+")
_STOP_WORDS = frozenset(
    "a an the and or of to in on at by from with as is are was were be been being that this these those "
    "it its for into than then have has had can could would should which what where when how why "
    "we our they their you your study studies result results using used use based show shows shown".split()
)
_MAX_SEGMENT_BYTES = 384
_BEGIN_MARKER = "BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1"
_END_MARKER = "END_POWERCONTEXT_PREPARED_CONTEXT_V1"


@dataclass(frozen=True)
class PreparedMemoryFragment:
    """An unchanged half-open character interval in one exactly addressed Memory entry."""

    address: MemoryEntryAddress
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class _Document:
    address: MemoryEntryAddress
    text: str
    spans: tuple[tuple[int, int], ...]


def _stem(word: str) -> str:
    if len(word) > 5 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 5 and word.endswith("ing"):
        return word[:-3]
    if len(word) > 4 and word.endswith("ed"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us")):
        return word[:-1]
    return word


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(_stem(word) for word in _WORDS.findall(text.casefold()) if word not in _STOP_WORDS)


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _split_span(text: str, start: int, end: int) -> tuple[tuple[int, int], ...]:
    if len(text[start:end].encode("utf-8")) <= _MAX_SEGMENT_BYTES:
        return ((start, end),)
    spans = []
    position = start
    while position < end:
        stop = position
        used = 0
        while stop < end and used + len(text[stop].encode("utf-8")) <= _MAX_SEGMENT_BYTES:
            used += len(text[stop].encode("utf-8"))
            stop += 1
        if stop < end:
            boundary = next((index for index in range(stop, position, -1) if text[index - 1].isspace()), stop)
            if boundary > position:
                stop = boundary
        left, right = _trim(text, position, stop)
        if left < right:
            spans.append((left, right))
        position = stop
    return tuple(spans)


def _spans(text: str) -> tuple[tuple[int, int], ...]:
    result = []
    start = 0
    for stop in (*[match.end() for match in _BREAKS.finditer(text)], len(text)):
        left, right = _trim(text, start, stop)
        if left < right:
            result.extend(_split_span(text, left, right))
        start = stop
    return tuple(result)


def _documents(groups: Sequence[PreparedMemoryCandidates]) -> tuple[_Document, ...]:
    from powercontext.builtin.runtime.prepared_context import MemoryEntryAddress

    documents = []
    seen = set()
    for group in groups:
        for hit in group.hits:
            key = (
                group.scope_id,
                hit.memory_ref.family,
                hit.memory_ref.artifact_id,
                hit.memory_ref.revision,
                hit.entry_id,
                hit.entry_version_id,
            )
            if key in seen or not hit.text.strip():
                continue
            seen.add(key)
            address = MemoryEntryAddress(
                memory=ArtifactAddress(scope_id=group.scope_id, artifact=hit.memory_ref),
                entry_id=hit.entry_id,
                entry_version_id=hit.entry_version_id,
            )
            documents.append(_Document(address=address, text=hit.text, spans=_spans(hit.text)))
    return tuple(documents)


def _scores(documents: tuple[_Document, ...], query: str) -> dict[tuple[int, int], float]:
    tokens = {
        (number, index): _tokens(document.text[start:end])
        for number, document in enumerate(documents)
        for index, (start, end) in enumerate(document.spans)
    }
    frequencies = Counter(word for words in tokens.values() for word in set(words))
    query_words = _tokens(query)
    weights = {word: math.log1p((len(tokens) + 1) / (frequencies[word] + 1)) for word in query_words}
    pairs = set(zip(query_words, query_words[1:]))
    scores = {}
    for identity, words in tokens.items():
        counts = Counter(words)
        covered = {word for word in weights if word in counts}
        score = sum(weights[word] * 2 * counts[word] / (counts[word] + 1) for word in covered)
        score *= 1 + len(covered) / max(1, len(weights))
        score += sum(0.5 * weights[left] for left, right in pairs.intersection(zip(words, words[1:])))
        scores[identity] = score
    return scores


def _fragments(
    documents: tuple[_Document, ...], selected: dict[tuple[int, int], int]
) -> tuple[PreparedMemoryFragment, ...]:
    ordered = []
    for number, document in enumerate(documents):
        indices = sorted(index for doc, index in selected if doc == number)
        groups: list[list[int]] = []
        for index in indices:
            if groups and groups[-1][-1] + 1 == index:
                groups[-1].append(index)
            else:
                groups.append([index])
        for group in groups:
            start, end = document.spans[group[0]][0], document.spans[group[-1]][1]
            fragment = PreparedMemoryFragment(document.address, start, end, document.text[start:end])
            ordered.append((min(selected[(number, index)] for index in group), fragment))
    return tuple(fragment for _rank, fragment in sorted(ordered, key=lambda item: item[0]))


def _render(fragments: tuple[PreparedMemoryFragment, ...]) -> str:
    items = [
        {
            "citation": {
                "scope_id": fragment.address.memory.scope_id,
                "memory_ref": fragment.address.memory.artifact.model_dump(mode="json"),
                "entry_id": fragment.address.entry_id,
                "entry_version_id": fragment.address.entry_version_id,
            },
            "content": fragment.text,
            "start": fragment.start,
            "end": fragment.end,
        }
        for fragment in fragments
    ]
    encoded = json.dumps({"trust": "untrusted_history", "items": items}, ensure_ascii=False, separators=(",", ":"))
    encoded = encoded.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return "\n\n".join((TRUST_POLICY, f"{_BEGIN_MARKER}\n{encoded}\n{_END_MARKER}"))


def _fit_segment(
    documents: tuple[_Document, ...],
    scores: dict[tuple[int, int], float],
    selected: dict[tuple[int, int], int],
    identity: tuple[int, int],
    current_bytes: int,
    max_bytes: int,
) -> tuple[tuple[bool, float, float, int, int], str] | None:
    number, index = identity
    related = [other for other in selected if other[0] == number]
    neighbouring = any(abs(index - other[1]) == 1 for other in related)
    support = max((scores[other] for other in related), default=0.0)
    benefit = scores[identity] + (0.20 * support if neighbouring else 0.0)
    if benefit <= 0:
        return None
    trial = {**selected, identity: len(selected)}
    rendered = _render(_fragments(documents, trial))
    size = len(rendered.encode("utf-8"))
    if size > max_bytes:
        return None
    cost = max(1, size - current_bytes)
    priority = (scores[identity] > 0, benefit / math.sqrt(cost), benefit, -number, -index)
    return priority, rendered


def select_evidence(
    groups: Sequence[PreparedMemoryCandidates], query: str, max_bytes: int
) -> tuple[str | None, tuple[PreparedMemoryFragment, ...]]:
    """Choose sentence evidence, merging neighbours to avoid repeated citation overhead."""
    documents = _documents(groups)
    scores = _scores(documents, query)
    selected: dict[tuple[int, int], int] = {}
    content = ""
    remaining = set(scores)
    while remaining:
        choices = []
        current_bytes = len(content.encode("utf-8"))
        for identity in sorted(remaining):
            fitted = _fit_segment(documents, scores, selected, identity, current_bytes, max_bytes)
            if fitted is not None:
                priority, rendered = fitted
                choices.append((priority, identity, rendered))
        if not choices:
            break
        _priority, identity, content = max(choices, key=lambda choice: choice[0])
        selected[identity] = len(selected)
        remaining.remove(identity)
    return (content or None), _fragments(documents, selected)


__all__ = ["PreparedMemoryFragment", "select_evidence"]
