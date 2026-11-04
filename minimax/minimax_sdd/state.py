"""Explicit PowerContext task state with file-backed SQLite and no models."""
from contextlib import asynccontextmanager
import importlib.metadata
import json
import os
from pathlib import Path

from .source_db import SourceError, require_text


def validate_state(state, task_id):
    if not isinstance(state, dict) or state.get("task_id") != task_id:
        raise SourceError("Task state does not match the selected task_id.")
    for key in ("completed", "pending"):
        if not isinstance(state.get(key), list) or not all(isinstance(x, str) for x in state[key]):
            raise SourceError("Task state must contain completed/pending string lists.")
    if not isinstance(state.get("verification"), dict):
        raise SourceError("Task state must contain a verification object.")
    return state


@asynccontextmanager
async def task_memory(directory, task_id):
    from powercontext.builtin.persistence.sqlite import SQLiteConfig
    from powercontext.builtin.runtime import BuiltinConfig, InferenceConfig, RuntimeConfig, open_builtin_runtime
    from powercontext.builtin.scope import ScopeDraft

    require_text(task_id, "task_id")
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    config = BuiltinConfig(
        database=SQLiteConfig(url="sqlite+aiosqlite:///" + (directory / "state.db").as_posix()),
        inference=InferenceConfig(),
        runtime=RuntimeConfig(dream_enabled=False),
    )
    async with open_builtin_runtime(config, scheduler_path=directory / "scheduler.db") as runtime:
        scope = await runtime.scopes.create(ScopeDraft(
            title="MiniMax SDD task", summary="Explicit progress and verification reuse",
            idempotency_key="minimax-sdd:" + task_id,
        ))
        yield runtime.memory.for_scope(scope.scope_id), scope.scope_id


async def remember(directory, task_id, state):
    from powercontext.builtin.artifacts.memory import MemoryEntryInput
    from powercontext.builtin.runtime import RememberMemoryRequest

    validate_state(state, task_id)
    async with task_memory(directory, task_id) as (memory, scope_id):
        before = await memory.list()
        written = await memory.remember(RememberMemoryRequest(entries=(
            MemoryEntryInput(kind="task_state", text=json.dumps(state, ensure_ascii=False)),
        )))
        if written.entry is None:
            raise SourceError("PowerContext did not return the written task memory.")
        return {"task_id": task_id, "pid": os.getpid(), "scope_id": scope_id,
                "empty_before_save": before.memory_ref is None and not before.entries,
                "citation": written.entry.citation.model_dump(mode="json"),
                "powercontext_version": importlib.metadata.version("powercontext")}


async def restore(directory, task_id):
    from powercontext.builtin.runtime import GetMemoryEntryRequest

    async with task_memory(directory, task_id) as (memory, scope_id):
        page = await memory.list()
        rows = [row for row in page.entries if row.entry.kind == "task_state" and row.state == "active"]
        if not rows:
            raise SourceError("No saved PowerContext task state exists; remember it first.")
        # Fixed SDK declares created_in_revision as a monotonic integer.
        latest = max(rows, key=lambda row: row.entry.created_in_revision)
        restored = await memory.get(GetMemoryEntryRequest(citation=latest.citation))
        state = validate_state(json.loads(restored.entry.text), task_id)
        return {"state": state, "citation": restored.citation.model_dump(mode="json"),
                "scope_id": scope_id, "pid": os.getpid(),
                "next_step": state["pending"][0] if state["pending"] else None,
                "powercontext_version": importlib.metadata.version("powercontext")}
