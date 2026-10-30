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

"""Native hybrid filtering with multiple current Memory heads and exact tags."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import Engine, event

from powercontext.builtin.artifacts.memory import EmbeddingProfile, MemoryEntryInput
from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.artifacts.memory.service import MemoryService
from powercontext.builtin.inference import EmbeddingResult
from powercontext.builtin.persistence.memory import RelationalMemoryBackend
from powercontext.builtin.persistence.seekdb import SeekDBConfig
from powercontext.builtin.runtime import BuiltinConfig, open_builtin_contexts
from powercontext.builtin.tags import MemoryEntryTagTarget, TagFilter

if TYPE_CHECKING:
    from pathlib import Path


class _Embedding:
    profile = EmbeddingProfile(
        profile_id="hybrid-filter-regression",
        model="offline",
        dimension=2,
        distance="l2",
        normalization="unit",
    )

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        return EmbeddingResult(vectors=tuple((1.0, 0.0) if "alpha" in text.lower() else (0.0, 1.0) for text in texts))


@contextmanager
def _candidate_statements() -> Iterator[list[tuple[str, object]]]:
    statements: list[tuple[str, object]] = []

    def record(_connection, _cursor, statement, parameters, _context, _executemany) -> None:
        if "AGAINST" in statement.upper() or "l2_distance" in statement.lower():
            statements.append((statement, parameters))

    event.listen(Engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(Engine, "before_cursor_execute", record)


def _identity(hit: MemoryHit) -> tuple[str, int, str, str]:
    return hit.memory_ref.artifact_id, hit.memory_ref.revision, hit.entry_id, hit.entry_version_id


@pytest.mark.asyncio
async def test_multiple_heads_and_tagged_candidates_use_both_native_indexes(tmp_path: Path) -> None:
    config = BuiltinConfig(database=SeekDBConfig(path=tmp_path / "hybrid-db"))
    embedding = _Embedding()
    async with open_builtin_contexts(config, embedding_model=embedding) as contexts:
        memory = MemoryService(
            backend=RelationalMemoryBackend(
                database=contexts.database,
                scope_id="selected-scope",
                artifacts=contexts.repositories.artifacts,
                index=contexts.index,
            ),
            embedding_model=embedding,
        )
        first = await memory.remember(
            memory=None, entries=(MemoryEntryInput(kind="fact", text="Alpha first selected report."),), mode="append"
        )
        second = await memory.remember(
            memory=None, entries=(MemoryEntryInput(kind="fact", text="Alpha second selected report."),), mode="append"
        )
        excluded = await memory.remember(
            memory=None, entries=(MemoryEntryInput(kind="fact", text="Alpha excluded artifact."),), mode="append"
        )
        other = (await contexts.get("other-scope")).artifacts.memory
        other_head = await other.remember(
            memory=None, entries=(MemoryEntryInput(kind="fact", text="Alpha other scope."),), mode="append"
        )
        assert first is not None and second is not None and excluded is not None and other_head is not None
        assert len({first.artifact_id, second.artifact_id, excluded.artifact_id}) == 3
        current_first = await memory.remember(
            memory=first, entries=(MemoryEntryInput(kind="fact", text="Beta later addition."),), mode="append"
        )
        assert current_first is not None
        requested = (current_first, second)
        with _candidate_statements() as statements:
            result = await memory.search("alpha", memories=requested, mode="hybrid", limit=10)
        assert len(statements) == 1
        selected_refs = (current_first.as_ref(), second.as_ref())
        assert result.hits
        assert all(hit.memory_ref in selected_refs for hit in result.hits)
        assert {hit.text for hit in result.hits} == {
            "Alpha first selected report.", "Alpha second selected report."
        }
        identities = tuple(_identity(hit) for hit in result.hits)
        repeated = await memory.search("alpha", memories=requested, mode="hybrid", limit=10)
        assert tuple(_identity(hit) for hit in repeated.hits) == identities
        assert len(identities) == len(set(identities))
        second_entry = (await memory.entries(second))[0]
        target = MemoryEntryTagTarget(artifact_id=second.artifact_id, entry_id=second_entry.entry_id)
        tags = await contexts.records.get_tags("selected-scope", target)
        await contexts.records.replace_tags("selected-scope", target, ("selected",), expected_etag=tags.etag)
        with _candidate_statements() as tagged_statements:
            tagged = await memory.search(
                "alpha", memories=requested, mode="hybrid", limit=1, tag_filter=TagFilter(tags=("selected",))
            )
        assert len(tagged_statements) == 1
        assert [(hit.memory_ref, hit.entry_id) for hit in tagged.hits] == [(second.as_ref(), second_entry.entry_id)]
        for statement, parameters in (statements[0], tagged_statements[0]):
            async with contexts.database.transaction() as connection:
                plan = "\n".join(
                    str(row[0])
                    for row in (await connection.exec_driver_sql("EXPLAIN " + statement, parameters)).all()
                )
            assert "TEXT RETRIEVAL SCAN" in plan
            assert "VECTOR INDEX" in plan
