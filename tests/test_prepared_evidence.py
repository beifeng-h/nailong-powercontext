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

"""Literal multi-scope fragment identity and complete JSON/envelope byte budgets."""

from __future__ import annotations

import json

import pytest

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.runtime.models import PrepareContextRequest
from powercontext.builtin.runtime.prepared_context import PreparedContextBuilder, PreparedMemoryCandidates


def _candidates(scope: str, text: str) -> PreparedMemoryCandidates:
    reference = ArtifactRef(family="memory", artifact_id="same-id", revision=3)
    hit = MemoryHit(
        memory_ref=reference,
        entry_id="same-entry",
        entry_version_id="same-version",
        text=text,
        score=1,
        matched_by=("fts",),
    )
    return PreparedMemoryCandidates(scope_id=scope, memory_ref=reference, hits=(hit,))


def test_distant_evidence_returns_multiple_literal_ranges_without_filling_the_gap() -> None:
    text = "The cobalt sensor was calibrated at 37 degrees. "
    text += "Irrelevant administrative boilerplate. " * 90
    text += "The amber valve opens when the pressure reaches 19 units."
    result = PreparedContextBuilder().build_scopes_result(
        request=PrepareContextRequest(
            query="cobalt sensor amber valve pressure", max_bytes=1400, evidence_selection=True
        ),
        current_scope_id="one",
        memory_candidates=(_candidates("one", text),),
    )
    assert len(result.fragments) >= 2
    assert any("37" in fragment.text for fragment in result.fragments)
    assert any("19" in fragment.text for fragment in result.fragments)
    assert all(fragment.text == text[fragment.start : fragment.end] for fragment in result.fragments)
    assert result.context.content_bytes == len(result.context.content.encode("utf-8")) <= 1400
    items = json.loads(result.context.content.splitlines()[-2])["items"]
    assert len(items) == len(result.origins) == len(result.fragments)


def test_equal_text_in_different_scopes_keeps_distinct_addresses() -> None:
    text = "A cobalt sensor measures temperature."
    result = PreparedContextBuilder().build_scopes_result(
        request=PrepareContextRequest(query="cobalt sensor temperature", max_bytes=1600, evidence_selection=True),
        current_scope_id="one",
        memory_candidates=(_candidates("one", text), _candidates("two", text)),
    )
    assert {fragment.address.memory.scope_id for fragment in result.fragments} == {"one", "two"}
    for origin, fragment in zip(result.origins, result.fragments, strict=True):
        assert origin == fragment.address
        assert (fragment.start, fragment.end, fragment.text) == (0, len(text), text)


@pytest.mark.parametrize("budget", [512, 700, 1100])
def test_unicode_and_json_escaping_budget_includes_citations_and_policy(budget: int) -> None:
    text = '海洋 station says "temperature\\sensor" has increased.\n' * 20
    result = PreparedContextBuilder().build_scopes_result(
        request=PrepareContextRequest(query="海洋 station temperature sensor", max_bytes=budget, evidence_selection=True),
        current_scope_id="one",
        memory_candidates=(_candidates("one", text),),
    )
    assert result.context.content_bytes == len((result.context.content or "").encode("utf-8")) <= budget
    for fragment in result.fragments:
        assert fragment.text == text[fragment.start : fragment.end]
        assert type(fragment.start) is int and type(fragment.end) is int


def test_evidence_mode_is_default_off_and_preserves_ordinary_prepare() -> None:
    group = _candidates("one", "A cobalt sensor measures temperature.")
    builder = PreparedContextBuilder()
    baseline = builder.build_scopes_result(
        request=PrepareContextRequest(query="cobalt", max_bytes=1400),
        current_scope_id="one",
        memory_candidates=(group,),
    )
    explicit = builder.build_scopes_result(
        request=PrepareContextRequest(query="cobalt", max_bytes=1400, evidence_selection=False),
        current_scope_id="one",
        memory_candidates=(group,),
    )
    assert baseline == explicit
    assert baseline.context.content and not baseline.fragments
