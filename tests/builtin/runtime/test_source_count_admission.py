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

"""Source-count admission preserves each processor's committed progress."""

from __future__ import annotations

import asyncio
from functools import partial

from sqlalchemy import insert, update

from powercontext.builtin.persistence.cursors import SourceCursorRepository
from powercontext.builtin.persistence.processing_intents import ArtifactProcessingIntentRepository
from powercontext.builtin.persistence.tables import SOURCE_JOURNAL_HEADS_TABLE
from powercontext.builtin.runtime.artifact_processing import ArtifactProcessingBinding, ArtifactProcessingSupervisor
from powercontext.builtin.runtime.processing_contracts import ArtifactProcessingWorkerCompletion
from powercontext.builtin.runtime.processing_discovery import source_count_ready_scopes
from powercontext.builtin.sources import SourceCursor
from tests.builtin.runtime.test_processing_scheduler import _Launcher, _profile, _wait


async def test_count_selection_uses_independent_scope_and_family_cursors(tmp_path):
    async with _profile(tmp_path, "count-selection") as profile:
        async with profile.database.transaction() as connection:
            await connection.execute(
                insert(SOURCE_JOURNAL_HEADS_TABLE),
                [{"scope_id": "left", "position": 7}, {"scope_id": "right", "position": 7}],
            )
            cursors = SourceCursorRepository()
            for scope, binding, position in (
                ("left", "memory-binding", 5),
                ("right", "memory-binding", 3),
                ("left", "topic-binding", 6),
                ("right", "topic-binding", 6),
            ):
                await cursors.save(
                    connection, scope, binding, SourceCursor(sequence=position), expected_generation=None
                )
            scopes = ("left", "right", "no-input")
            assert await source_count_ready_scopes(
                connection, scopes, binding_name="memory-binding", threshold=3
            ) == frozenset({"right"})
            assert not await source_count_ready_scopes(
                connection, scopes, binding_name="topic-binding", threshold=2
            )
            assert await source_count_ready_scopes(
                connection, scopes, binding_name="new-family-binding", threshold=7
            ) == frozenset({"left", "right"})


async def test_count_invocations_recheck_after_one_window_and_explicit_requests_bypass(tmp_path):
    async with _profile(tmp_path, "count-window") as profile:
        binding = "memory-binding"
        scope = "scope"
        intents = ArtifactProcessingIntentRepository()
        cursors = SourceCursorRepository()
        async with profile.database.transaction() as connection:
            await connection.execute(insert(SOURCE_JOURNAL_HEADS_TABLE).values(scope_id=scope, position=3))
            await intents.mark_dirty(connection, scope, binding)

        async def process_window(work):
            async with profile.database.transaction() as connection:
                stored = await cursors.load(connection, scope, binding)
                sequence = 0 if stored is None else stored.cursor.sequence
                await cursors.save(
                    connection,
                    scope,
                    binding,
                    SourceCursor(sequence=sequence + 1),
                    expected_generation=None if stored is None else stored.generation,
                )
                await intents.acknowledge(connection, scope, binding, work.claimed_request_generation)
            return ArtifactProcessingWorkerCompletion()

        launcher = _Launcher(profile.database, on_work=process_window)
        registration = ArtifactProcessingBinding(
            binding,
            "memory",
            launcher,
            automatic_count_filter=partial(source_count_ready_scopes, binding_name=binding, threshold=3),
        )
        async with ArtifactProcessingSupervisor(
            database=profile.database,
            bindings=(registration,),
            lease_mode="single-process",
            oceanbase_tick_seconds=0.01,
        ) as supervisor:
            await _wait(lambda: supervisor.family_status["memory"]["completed"] == 1)
            await asyncio.sleep(0.08)
            assert len(launcher.assignments) == 1
            async with profile.database.transaction() as connection:
                await connection.execute(
                    update(SOURCE_JOURNAL_HEADS_TABLE)
                    .where(SOURCE_JOURNAL_HEADS_TABLE.c.scope_id == scope)
                    .values(position=4)
                )
                await intents.mark_dirty(connection, scope, binding)
            # No wake: journal writers that emit lineage still need count admission.
            await _wait(lambda: supervisor.family_status["memory"]["completed"] == 2)
            await asyncio.sleep(0.08)
            assert len(launcher.assignments) == 2
            async with profile.database.transaction() as connection:
                await intents.request(connection, scope, binding)
            supervisor.wake(binding)
            await _wait(lambda: supervisor.family_status["memory"]["completed"] == 3)
            await asyncio.sleep(0.08)
            assert len(launcher.assignments) == 3
