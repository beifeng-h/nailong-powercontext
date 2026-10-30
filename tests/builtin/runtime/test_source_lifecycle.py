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

"""Lifecycle recovery keeps real Memory state and original citations aligned."""

from __future__ import annotations

import sqlite3

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.records import BaseValueNotFoundError
from powercontext.builtin.runtime import (
    BuiltinConfig,
    CaptureSource,
    GetMemoryEntryRequest,
    RememberMemoryRequest,
    SearchMemoryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.source_lifecycle import SourceLifecycleError, SourceLifecycleEvent
from powercontext.builtin.scope import ScopeDraft
from powercontext.sources import SourceRef


def _event(available: bool, sequence: int = 1) -> SourceLifecycleEvent:
    return SourceLifecycleEvent(
        node_id="root", revision=3, sequence=sequence, available=available, reason="controlled source availability"
    )


async def _register_scope(runtime, key: str):
    scope = await runtime.scopes.create(ScopeDraft(title=key, summary="Lifecycle recovery", idempotency_key=key))
    lifecycle = runtime.lifecycle.for_scope(scope.scope_id)
    receipt = await runtime.sources.for_scope(scope.scope_id).capture(
        CaptureSource(source_id="root", content=f"{key} original source", metadata={})
    )
    await lifecycle.register_source("root", receipt.source_ref, revision=3)
    citations = []
    for index in range(2):
        mutation = await runtime.memory.for_scope(scope.scope_id).remember(
            RememberMemoryRequest(entries=(MemoryEntryInput(kind="fact", text=f"{key} proof {index}"),))
        )
        citation = mutation.entry.citation
        await lifecycle.register_memory(f"memory-{index}", citation, parents=("root",), policy="all")
        citations.append(citation)
    return scope.scope_id, lifecycle, tuple(citations)


def test_event_rejects_numeric_coercion_and_blank_or_extra_fields() -> None:
    valid = {"node_id": "root", "revision": 3, "sequence": 1, "available": False, "reason": "withdraw"}
    invalid = [
        {field: value}
        for field in ("revision", "sequence")
        for value in (True, False, 0, -1, 1.0, "1")
    ]
    invalid += [{"available": value} for value in (0, 1, "true", "false", None)]
    invalid += [{field: value} for field in ("node_id", "reason") for value in ("", " \t\n", 1, None)]
    invalid.append({"extra": "unexpected"})
    for patch in invalid:
        with pytest.raises(ValidationError):
            SourceLifecycleEvent(**{**valid, **patch})
    assert SourceLifecycleEvent(**valid).model_dump() == valid


async def test_real_memory_write_failure_replays_after_restart_without_extra_revision(tmp_path) -> None:
    database = tmp_path / "lifecycle-retry.db"
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{database}"))
    withdrawal = _event(False)
    async with open_builtin_runtime(config) as runtime:
        scope, lifecycle, citations = await _register_scope(runtime, "retryproof")
        memory = runtime.memory.for_scope(scope)
        before = (await memory.list()).memory_ref
        with sqlite3.connect(database) as connection:
            connection.execute(
                "CREATE TRIGGER reject_lifecycle_memory BEFORE INSERT ON pc_artifacts "
                "WHEN NEW.family = 'memory' BEGIN SELECT RAISE(ABORT, 'controlled lifecycle failure'); END"
            )
        with pytest.raises(IntegrityError, match="controlled lifecycle failure"):
            await lifecycle.apply(withdrawal)
        assert (await memory.list()).memory_ref == before

    with sqlite3.connect(database) as connection:
        connection.execute("DROP TRIGGER reject_lifecycle_memory")
    async with open_builtin_runtime(config) as runtime:
        lifecycle = runtime.lifecycle.for_scope(scope)
        memory = runtime.memory.for_scope(scope)
        assert await lifecycle.apply(withdrawal) == []
        stopped = await memory.list(include_inactive=True)
        assert {row.state for row in stopped.entries} == {"inactive"}
        assert not (await memory.search(SearchMemoryRequest(query="retryproof", mode="fts"))).hits
        await lifecycle.apply(withdrawal)
        assert (await memory.list(include_inactive=True)).memory_ref == stopped.memory_ref
        for index, citation in enumerate(citations):
            assert await lifecycle.resolve(f"memory-{index}", purpose="audit") == citation
            original = await memory.get(GetMemoryEntryRequest(citation=citation))
            assert original.entry.text == f"retryproof proof {index}"
        assert await lifecycle.apply(_event(True, 2)) == ["memory-0", "memory-1", "root"]
        for index, citation in enumerate(citations):
            assert await lifecycle.resolve(f"memory-{index}", purpose="generation") == citation
        assert {row.entry.entry_version_id for row in (await memory.list()).entries} == {
            citation.entry_version_id for citation in citations
        }


async def test_identical_node_ids_and_event_sequences_remain_scope_local_after_restart(tmp_path) -> None:
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'lifecycle-scopes.db'}"))
    async with open_builtin_runtime(config) as runtime:
        left, left_lifecycle, left_citations = await _register_scope(runtime, "leftproof")
        right, right_lifecycle, right_citations = await _register_scope(runtime, "rightproof")
        await left_lifecycle.apply(_event(False))
        assert not (await runtime.memory.for_scope(left).list()).entries
        assert len((await runtime.memory.for_scope(right).list()).entries) == 2
        assert await right_lifecycle.resolve("memory-0", purpose="generation") == right_citations[0]
        with pytest.raises(SourceLifecycleError):
            await left_lifecycle.resolve("memory-0", purpose="generation")
        assert await left_lifecycle.resolve("memory-0", purpose="audit") == left_citations[0]

    async with open_builtin_runtime(config) as runtime:
        left_lifecycle = runtime.lifecycle.for_scope(left)
        right_lifecycle = runtime.lifecycle.for_scope(right)
        assert not (await runtime.memory.for_scope(left).list()).entries
        assert len((await runtime.memory.for_scope(right).list()).entries) == 2
        assert await right_lifecycle.apply(_event(False)) == []
        await left_lifecycle.apply(_event(True, 2))
        assert len((await runtime.memory.for_scope(left).list()).entries) == 2
        assert not (await runtime.memory.for_scope(right).list()).entries
        assert await left_lifecycle.resolve("memory-0", purpose="generation") == left_citations[0]


async def test_missing_references_fail_registration_without_leaving_bound_nodes() -> None:
    async with open_builtin_runtime(BuiltinConfig(database=SQLiteConfig())) as runtime:
        _scope, lifecycle, citations = await _register_scope(runtime, "referenceproof")
        with pytest.raises((LookupError, ValueError)):
            await lifecycle.register_source(
                "missing-source", SourceRef(source_type="content", source_id="absent"), revision=1
            )
        missing_memory = citations[0].model_copy(update={"entry_version_id": "absent-version"})
        with pytest.raises((LookupError, ValueError)):
            await lifecycle.register_memory("missing-memory", missing_memory, parents=("root",), policy="all")
        with pytest.raises((BaseValueNotFoundError, LookupError, ValueError)):
            await lifecycle.register_topic(
                "missing-topic",
                ArtifactRef(family="topic-memory", artifact_id="absent-topic", revision=1),
                parents=("root",),
                policy="all",
            )
        for node in ("missing-source", "missing-memory", "missing-topic"):
            with pytest.raises(SourceLifecycleError):
                await lifecycle.resolve(node, purpose="audit")
