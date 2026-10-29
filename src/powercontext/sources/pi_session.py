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

"""Captured Pi branch evidence and lifecycle-owned incremental collection."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, Field, JsonValue

from powercontext.sources.connectors import (
    ConnectorRunCompletion,
    ConnectorRunSession,
    ConnectorRunStatus,
    ConnectorSubmissionStatus,
)
from powercontext.sources.definitions import AdapterSourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

_PI_SOURCE_NAME = "pi-event"


class PiSessionInput(BaseModel):
    """A complete Pi version-three archive and an optional selected leaf."""

    content: bytes
    leaf_id: str | None = None


class PiEventInput(BaseModel):
    """One visible event, including the complete original archive record."""

    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


def _required_string(record: dict[str, JsonValue], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Pi {field} must be a non-empty string")  # noqa: TRY003
    return value


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Pi archives cannot contain non-JSON numeric constant {value}")  # noqa: TRY003


def _load_records(content: bytes) -> list[dict[str, JsonValue]]:
    records = []
    for line in content.decode("utf-8-sig").split("\n"):
        if not line.strip():
            continue
        record = json.loads(line, parse_constant=_reject_json_constant)
        if not isinstance(record, dict):
            raise ValueError("Pi archive records must be JSON objects")  # noqa: TRY003
        records.append(cast("dict[str, JsonValue]", record))
    return records


def _add_node(record: dict[str, JsonValue], nodes: dict[str, dict[str, JsonValue]]) -> str:
    event_id = _required_string(record, "id")
    _required_string(record, "type")
    if event_id in nodes:
        raise ValueError("Pi event IDs must be unique within the session")  # noqa: TRY003
    if "parentId" not in record:
        raise ValueError("Pi events must declare parentId")  # noqa: TRY003
    parent_id = record["parentId"]
    if parent_id is not None and (not isinstance(parent_id, str) or parent_id not in nodes):
        raise ValueError("Pi event parentId must reference an earlier node or be null")  # noqa: TRY003
    nodes[event_id] = record
    return event_id


def _parse_archive(value: PiSessionInput) -> tuple[str, dict[str, dict[str, JsonValue]], str | None]:
    records = _load_records(value.content)
    if not records:
        raise ValueError("Pi archive must contain a session header")  # noqa: TRY003
    header = records[0]
    if header.get("type") != "session" or header.get("version") != 3:
        raise ValueError("Pi archive must start with a version-three session header")  # noqa: TRY003
    session_id = _required_string(header, "id")
    nodes: dict[str, dict[str, JsonValue]] = {}
    last_id = None
    for record in records[1:]:
        last_id = _add_node(record, nodes)
    leaf_id = last_id if value.leaf_id is None else value.leaf_id
    if leaf_id is not None and leaf_id not in nodes:
        raise ValueError("Pi selected leaf is absent from the archive")  # noqa: TRY003
    return session_id, nodes, leaf_id


def _block_text(block: JsonValue) -> str | None:
    if not isinstance(block, dict):
        return None
    if block.get("type") == "text":
        text = block.get("text")
        return text if isinstance(text, str) else None
    if block.get("type") == "toolCall":
        name = _required_string(block, "name")
        call_id = _required_string(block, "id")
        arguments = json.dumps(block.get("arguments", {}), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return f"[tool_call {name} {call_id}] {arguments}"
    return None


def _message_text(content: JsonValue) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = (_block_text(block) for block in content)
    return "\n".join(part for part in parts if part is not None)


def _message_body(message: dict[str, JsonValue]) -> tuple[str, str] | None:
    role = _required_string(message, "role")
    if role == "bashExecution":
        command = message.get("command", "")
        output = message.get("output", "")
        if not isinstance(command, str) or not isinstance(output, str):
            raise ValueError("Pi bash command and output must be strings")  # noqa: TRY003
        return role, f"$ {command}\n{output}"
    body = _message_text(message.get("content"))
    if not body:
        return None
    if role == "toolResult":
        name = _required_string(message, "toolName")
        call_id = _required_string(message, "toolCallId")
        body = f"[tool_result {name} {call_id}] {body}"
    return role, body


def _visible_event(session_id: str, record: dict[str, JsonValue]) -> PiEventInput | None:
    event_type = _required_string(record, "type")
    if event_type == "message":
        message = record.get("message")
        rendered = _message_body(message) if isinstance(message, dict) else None
    elif event_type in {"compaction", "branch_summary"}:
        summary = record.get("summary")
        rendered = (event_type, summary) if isinstance(summary, str) and summary else None
    elif event_type == "custom_message":
        body = _message_text(record.get("content"))
        rendered = ("custom", body) if body else None
    else:
        rendered = None
    if rendered is None:
        return None
    role, body = rendered
    return PiEventInput(
        session_id=session_id,
        event_id=_required_string(record, "id"),
        parent_id=cast("str | None", record["parentId"]),
        event_type=event_type,
        role=role,
        content=f"{role}: {body}",
        record=record,
    )


def _branch_events(
    session_id: str,
    nodes: dict[str, dict[str, JsonValue]],
    leaf_id: str | None,
) -> tuple[PiEventInput, ...]:
    branch = []
    while leaf_id is not None:
        record = nodes[leaf_id]
        branch.append(record)
        leaf_id = cast("str | None", record["parentId"])
    events = (_visible_event(session_id, record) for record in reversed(branch))
    return tuple(event for event in events if event is not None)


def parse_pi_session(value: PiSessionInput) -> tuple[PiEventInput, ...]:
    """Validate an entire archive, then preserve its selected root-to-leaf evidence."""

    return _branch_events(*_parse_archive(value))


def _event_source_id(session_id: str, event_id: str) -> str:
    identity = json.dumps([session_id, event_id], ensure_ascii=False, separators=(",", ":"))
    return f"pi:{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"


class _PiEventSource(Source):
    definition_version: Literal["1"] = "1"
    materialization: Literal[SourceMaterialization.CAPTURED] = SourceMaterialization.CAPTURED
    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


class _PiEventSourceAdapter:
    input_class = PiEventInput
    name = _PI_SOURCE_NAME
    source_class = _PiEventSource

    async def resolve(self, value: PiEventInput, /) -> _PiEventSource:
        return _PiEventSource(name=_event_source_id(value.session_id, value.event_id), **value.model_dump())

    async def read(self, source: _PiEventSource, /) -> PiEventInput:
        return PiEventInput(
            session_id=source.session_id,
            event_id=source.event_id,
            parent_id=source.parent_id,
            event_type=source.event_type,
            role=source.role,
            content=source.content,
            record=source.record,
        )


class _PiEventTextEvidenceProjection:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = _PiEventSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: _PiEventSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=_PI_SOURCE_NAME,
            source_id=source.name,
            content=source.content,
            metadata={
                "session_id": source.session_id,
                "event_id": source.event_id,
                "parent_id": source.parent_id,
                "event_type": source.event_type,
                "role": source.role,
            },
        )


PI_EVENT_SOURCE_DEFINITION = AdapterSourceDefinition(
    _PiEventSourceAdapter(),
    projections=(_PiEventTextEvidenceProjection(),),
)


class _PiCheckpoint(BaseModel):
    version: Literal[1] = 1
    imported: dict[str, str] = Field(default_factory=dict)


def _record_hash(record: dict[str, JsonValue]) -> str:
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class PiSessionConnector:
    """Collect new branch events; let ConnectorLifecycle commit durable progress."""

    name = "pi-session-history"
    version = "1"
    source_definitions = frozenset({_PI_SOURCE_NAME})

    def __init__(self, path: str | Path, leaf_id: str | None = None) -> None:
        self.path = Path(path)
        self.leaf_id = leaf_id

    async def run(self, session: ConnectorRunSession, /) -> ConnectorRunCompletion:
        archive = _parse_archive(PiSessionInput(content=self.path.read_bytes(), leaf_id=self.leaf_id))
        events = _branch_events(*archive)
        session_id, nodes, _ = archive
        previous = _PiCheckpoint() if session.checkpoint is None else _PiCheckpoint.model_validate(session.checkpoint)
        imported = dict(previous.imported)
        current_hashes = {
            _event_source_id(session_id, event_id): _record_hash(record) for event_id, record in nodes.items()
        }
        for identity, record_hash in current_hashes.items():
            if identity in imported and imported[identity] != record_hash:
                raise ValueError("An imported Pi event record has changed")  # noqa: TRY003
        for event in events:
            identity = _event_source_id(event.session_id, event.event_id)
            if identity in imported:
                continue
            outcome = await session.submit(identity, _PI_SOURCE_NAME, event)
            if outcome.status is not ConnectorSubmissionStatus.ACCEPTED:
                return ConnectorRunCompletion(status=ConnectorRunStatus.INCOMPLETE, checkpoint=session.checkpoint)
            imported[identity] = current_hashes[identity]
        checkpoint = _PiCheckpoint(imported=imported).model_dump(mode="json")
        return ConnectorRunCompletion(status=ConnectorRunStatus.COMPLETE, checkpoint=checkpoint)


__all__ = [
    "PI_EVENT_SOURCE_DEFINITION",
    "PiEventInput",
    "PiSessionConnector",
    "PiSessionInput",
    "parse_pi_session",
]
