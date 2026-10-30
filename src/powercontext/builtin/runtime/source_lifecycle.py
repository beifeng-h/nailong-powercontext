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

"""Durable evidence dependencies and replayable native availability changes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Column, MetaData, String, Table, Text, insert, select, update

from powercontext.artifacts import ArtifactRef, MemoryCitation
from powercontext.builtin.persistence.artifact_governance import ArtifactGovernanceRepository, ArtifactLifecycleState
from powercontext.builtin.persistence.schema import create_tables
from powercontext.builtin.runtime.models import GetMemoryEntryRequest
from powercontext.builtin.sources import validate_scope_id
from powercontext.limits import MAX_SCOPE_ID_LENGTH
from powercontext.sources import SourceRef

if TYPE_CHECKING:
    from powercontext.builtin.persistence.database import AsyncDatabase
    from powercontext.builtin.persistence.sources import SourceRepository
    from powercontext.builtin.runtime.application import BuiltinRuntime


class SourceLifecycleError(ValueError):
    """An unknown binding, conflicting event, or unavailable generation input."""


class SourceLifecycleEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    node_id: str
    revision: int = Field(gt=0)
    sequence: int = Field(gt=0)
    available: bool
    reason: str

    @field_validator("node_id", "reason")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("event identifiers and reasons must not be blank")  # noqa: TRY003
        return value


class _Node(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["source", "memory", "topic"]
    reference: dict[str, Any]
    parents: tuple[str, ...] = ()
    policy: Literal["all", "any"] = "all"
    revision: int = 1
    available: bool = True
    event: SourceLifecycleEvent | None = None


class _Graph(BaseModel):
    nodes: dict[str, _Node] = Field(default_factory=dict)


_GRAPHS = Table(
    "pc_source_lifecycle_graphs",
    MetaData(),
    Column("scope_id", String(MAX_SCOPE_ID_LENGTH), primary_key=True),
    Column("payload", Text, nullable=False),
)


class SourceLifecycleStore:
    """Scope-local graph state, separate from immutable evidence bodies."""

    def __init__(self, database: AsyncDatabase, sources: SourceRepository) -> None:
        self.database = database
        self.sources = sources

    async def initialize(self) -> None:
        async with self.database.transaction() as connection:
            await create_tables(connection, (_GRAPHS,))

    async def load(self, scope_id: str) -> _Graph:
        async with self.database.transaction() as connection:
            payload = await connection.scalar(select(_GRAPHS.c.payload).where(_GRAPHS.c.scope_id == scope_id))
        return _Graph() if payload is None else _Graph.model_validate_json(payload)

    async def save(self, scope_id: str, graph: _Graph) -> None:
        async with self.database.transaction() as connection:
            exists = await connection.scalar(select(_GRAPHS.c.scope_id).where(_GRAPHS.c.scope_id == scope_id))
            statement = (
                insert(_GRAPHS).values(scope_id=scope_id, payload=graph.model_dump_json())
                if exists is None
                else update(_GRAPHS).where(_GRAPHS.c.scope_id == scope_id).values(payload=graph.model_dump_json())
            )
            await connection.execute(statement)


def _availability(graph: _Graph) -> dict[str, bool]:
    result: dict[str, bool] = {}

    def visit(node_id: str) -> bool:
        if node_id not in result:
            node = graph.nodes[node_id]
            values = tuple(visit(parent) for parent in node.parents)
            result[node_id] = node.available if node.kind == "source" else (
                all(values) if node.policy == "all" else any(values)
            )
        return result[node_id]

    for node_id in graph.nodes:
        visit(node_id)
    return result


def _identifier(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise SourceLifecycleError("node identifiers must be nonblank strings")


class ScopedSourceLifecycle:
    """Register a DAG and reconcile its desired state with native artifacts."""

    def __init__(self, runtime: BuiltinRuntime, scope_id: str, store: SourceLifecycleStore) -> None:
        self._runtime = runtime
        self.scope_id = validate_scope_id(scope_id)
        self._store = store

    async def register_source(self, node_id: str, source_ref: SourceRef, *, revision: int) -> None:
        if type(revision) is not int or revision <= 0 or not isinstance(source_ref, SourceRef):
            raise SourceLifecycleError("source registration requires a reference and positive revision")
        async with self._store.database.transaction() as connection:
            source = await self._store.sources.get(connection, self.scope_id, source_ref)
        await self._store.sources.read_value(source.value)
        await self._register(node_id, _Node(kind="source", reference=source_ref.model_dump(), revision=revision))

    async def register_memory(
        self, node_id: str, citation: MemoryCitation, *, parents: tuple[str, ...], policy: str
    ) -> None:
        if not isinstance(citation, MemoryCitation):
            raise SourceLifecycleError("memory registration requires an exact citation")
        await self._runtime.memory.for_scope(self.scope_id).get(GetMemoryEntryRequest(citation=citation))
        await self._register_derived(node_id, "memory", citation.model_dump(mode="json"), parents, policy)

    async def register_topic(
        self, node_id: str, artifact_ref: ArtifactRef, *, parents: tuple[str, ...], policy: str
    ) -> None:
        if not isinstance(artifact_ref, ArtifactRef) or artifact_ref.family != "topic-memory":
            raise SourceLifecycleError("topic registration requires a topic-memory reference")
        await self._runtime.records.for_scope(self.scope_id).get_artifact_revision(
            "topic-memory", artifact_ref.artifact_id, artifact_ref.revision
        )
        await self._register_derived(node_id, "topic", artifact_ref.model_dump(mode="json"), parents, policy)

    async def _register_derived(self, node_id, kind, reference, parents, policy) -> None:
        if policy not in {"all", "any"} or not parents or len(set(parents)) != len(parents):
            raise SourceLifecycleError("derived nodes require distinct parents and an all/any policy")
        for parent in parents:
            _identifier(parent)
        await self._register(
            node_id, _Node(kind=kind, reference=reference, parents=tuple(sorted(parents)), policy=policy)
        )

    async def _register(self, node_id: str, node: _Node) -> None:
        _identifier(node_id)
        async with self._runtime._context(self.scope_id), self._runtime._locked(self.scope_id):
            graph = await self._store.load(self.scope_id)
            existing = graph.nodes.get(node_id)
            if existing is not None:
                # Events change availability but never the registered identity.
                binding = existing.model_copy(update={"available": True, "event": None})
                if binding != node:
                    raise SourceLifecycleError("node is already bound to different evidence")
            else:
                if node_id in node.parents or any(parent not in graph.nodes for parent in node.parents):
                    raise SourceLifecycleError("parents must already exist and cannot include the node itself")
                graph.nodes[node_id] = node
                await self._store.save(self.scope_id, graph)
            await self._synchronize(graph, "source dependency registration")

    async def apply(self, event: SourceLifecycleEvent) -> list[str]:
        if not isinstance(event, SourceLifecycleEvent):
            raise SourceLifecycleError("a validated lifecycle event is required")
        async with self._runtime._context(self.scope_id), self._runtime._locked(self.scope_id):
            graph = await self._store.load(self.scope_id)
            node = graph.nodes.get(event.node_id)
            if node is None or node.kind != "source" or node.revision != event.revision:
                raise SourceLifecycleError("event source or lifecycle revision does not match")
            previous = node.event
            if previous is not None and (
                event.sequence < previous.sequence or event.sequence == previous.sequence and event != previous
            ):
                raise SourceLifecycleError("event sequence conflicts with the accepted event")
            if previous != event:
                node.available = event.available
                node.event = event
                # Commit intent first. A failed native update is safely resumed by replay.
                await self._store.save(self.scope_id, graph)
            await self._synchronize(graph, event.reason)
            return sorted(node_id for node_id, active in _availability(graph).items() if active)

    async def resolve(self, node_id: str, *, purpose: str):
        async with self._runtime._context(self.scope_id):
            graph = await self._store.load(self.scope_id)
            node = graph.nodes.get(node_id)
            if node is None or purpose not in {"generation", "audit"}:
                raise SourceLifecycleError("unknown node or evidence purpose")
            if purpose == "generation" and not _availability(graph)[node_id]:
                raise SourceLifecycleError("evidence is unavailable for generation")
            model = {"source": SourceRef, "memory": MemoryCitation, "topic": ArtifactRef}[node.kind]
            return model.model_validate(node.reference)

    async def _synchronize(self, graph: _Graph, reason: str) -> None:
        available = _availability(graph)
        memories = [(node_id, node) for node_id, node in graph.nodes.items() if node.kind == "memory"]
        if memories:
            async with self._runtime._context(self.scope_id) as context:
                service = context.artifacts.memory
                current = await service.head(context.artifacts.memory_artifact_id)
                entries = {entry.entry_id: entry for entry in await service.entries(current)}
                states = {entry.entry_id: entry.state for entry in current.content.manifest.entries}
                changes: dict[bool, list[Any]] = {False: [], True: []}
                for node_id, node in memories:
                    citation = MemoryCitation.model_validate(node.reference)
                    entry = entries.get(citation.entry_id)
                    if entry is None or entry.entry_version_id != citation.entry_version_id:
                        raise SourceLifecycleError("registered memory body has changed")
                    if (states[entry.entry_id] == "active") != available[node_id]:
                        changes[available[node_id]].append(entry)
                if changes[False]:
                    current = await service.forget(current, entries=changes[False], reason=reason)
                if changes[True]:
                    await service.reactivate(current, entries=changes[True], reason=reason)
        governance = ArtifactGovernanceRepository()
        async with self._store.database.transaction() as connection:
            for node_id, node in graph.nodes.items():
                if node.kind != "topic":
                    continue
                reference = ArtifactRef.model_validate(node.reference)
                current = await governance.get(connection, self.scope_id, "topic-memory", reference.artifact_id)
                state = ArtifactLifecycleState.ACTIVE if available[node_id] else ArtifactLifecycleState.DEPRECATED
                if current.lifecycle_state != state:
                    await governance.transition(
                        connection, self.scope_id, "topic-memory", reference.artifact_id,
                        current.governance_generation, state, None,
                    )


class SourceLifecycleApplication:
    def __init__(self, runtime: BuiltinRuntime, store: SourceLifecycleStore | None) -> None:
        self._runtime = runtime
        self._store = store

    def for_scope(self, scope_id: str) -> ScopedSourceLifecycle:
        if self._store is None:
            raise SourceLifecycleError("source lifecycle storage is not configured")
        return ScopedSourceLifecycle(self._runtime, scope_id, self._store)


__all__ = ["SourceLifecycleError", "SourceLifecycleEvent"]
