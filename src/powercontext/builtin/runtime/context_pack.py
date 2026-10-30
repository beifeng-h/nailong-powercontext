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

"""Portable, checked context packs and prefix-reusing delta messages."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass

_PACK_SCHEMA = "powercontext.context-pack.v1"
_DELTA_SCHEMA = "powercontext.context-pack-delta.v1"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


class ContextPackError(ValueError):
    """A context pack or delta violates the interoperable wire contract."""


def _json_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _items(values: object) -> tuple[bytes, ...]:
    if not isinstance(values, tuple) or any(not isinstance(value, bytes) for value in values):
        raise ContextPackError("context chunks must be a tuple of bytes")  # noqa: TRY003
    for value in values:
        try:
            value.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ContextPackError("context chunks must contain valid UTF-8") from error  # noqa: TRY003
    return values


def _encoded(items: tuple[bytes, ...]) -> list[str]:
    return [base64.b64encode(item).decode("ascii") for item in items]


def _decoded(values: object) -> tuple[bytes, ...]:
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise ContextPackError("wire chunks must be a Base64 string array")  # noqa: TRY003
    chunks = []
    for value in values:
        try:
            chunk = base64.b64decode(value, validate=True)
        except ValueError as error:
            raise ContextPackError("invalid Base64 context chunk") from error  # noqa: TRY003
        if base64.b64encode(chunk).decode("ascii") != value:
            raise ContextPackError("non-canonical Base64 context chunk")  # noqa: TRY003
        chunks.append(chunk)
    return _items(tuple(chunks))


def _digest(value: object) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ContextPackError("invalid context digest")  # noqa: TRY003
    return value


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ContextPackError("duplicate context wire field")  # noqa: TRY003
        result[key] = value
    return result


def _payload(data: bytes, fields: set[str], schema: str) -> dict[str, object]:
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_object)
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContextPackError("context wire must be UTF-8 JSON") from error  # noqa: TRY003
    if not isinstance(value, dict) or set(value) != fields or value["schema"] != schema:
        raise ContextPackError("invalid context wire schema or fields")  # noqa: TRY003
    return value


@dataclass(frozen=True, slots=True)
class ContextPack:
    """A complete context, with an identity covering its exact ordered chunks."""

    items: tuple[bytes, ...]
    digest: str
    byte_count: int

    @classmethod
    def build(cls, items: tuple[bytes, ...]) -> ContextPack:
        chunks = _items(items)
        unsigned: dict[str, object] = {"schema": _PACK_SCHEMA, "items": _encoded(chunks)}
        digest = "sha256:" + hashlib.sha256(_json_bytes(unsigned)).hexdigest()
        payload = {**unsigned, "digest": digest, "byte_count": 0}
        while True:
            size = len(_json_bytes(payload))
            if payload["byte_count"] == size:
                return cls(chunks, digest, size)
            payload["byte_count"] = size

    @classmethod
    def from_content(cls, content: str, *, chunk_bytes: int = 512) -> ContextPack:
        if not isinstance(content, str) or type(chunk_bytes) is not int or chunk_bytes <= 0:
            raise ContextPackError("content must be text and chunk_bytes a positive integer")  # noqa: TRY003
        chunks = []
        current = bytearray()
        try:
            for character in content:
                encoded = character.encode("utf-8")
                if len(encoded) > chunk_bytes:
                    raise ContextPackError("chunk limit cannot contain a UTF-8 character")  # noqa: TRY003
                if len(current) + len(encoded) > chunk_bytes:
                    chunks.append(bytes(current))
                    current.clear()
                current.extend(encoded)
        except UnicodeEncodeError as error:
            raise ContextPackError("content must contain valid Unicode") from error  # noqa: TRY003
        if current:
            chunks.append(bytes(current))
        return cls.build(tuple(chunks))

    def _validate(self) -> None:
        expected = self.build(self.items)
        if (
            self.digest != expected.digest
            or type(self.byte_count) is not int
            or self.byte_count != expected.byte_count
        ):
            raise ContextPackError("context digest or byte count does not match its chunks")  # noqa: TRY003

    def to_bytes(self) -> bytes:
        self._validate()
        return _json_bytes(
            {
                "schema": _PACK_SCHEMA,
                "items": _encoded(self.items),
                "digest": self.digest,
                "byte_count": self.byte_count,
            }
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> ContextPack:
        value = _payload(data, {"schema", "items", "digest", "byte_count"}, _PACK_SCHEMA)
        byte_count = value["byte_count"]
        if type(byte_count) is not int:
            raise ContextPackError("byte_count must be an integer")  # noqa: TRY003
        pack = cls(_decoded(value["items"]), _digest(value["digest"]), byte_count)
        pack._validate()
        return pack


@dataclass(frozen=True, slots=True)
class ContextPackDelta:
    """A checked base identity, retained chunk prefix and complete replacement suffix."""

    base_digest: str
    target_digest: str
    prefix_items: int
    appended: tuple[bytes, ...]

    def __post_init__(self) -> None:
        _digest(self.base_digest)
        _digest(self.target_digest)
        if type(self.prefix_items) is not int or self.prefix_items < 0:
            raise ContextPackError("prefix_items must be a nonnegative integer")  # noqa: TRY003
        _items(self.appended)

    @classmethod
    def between(cls, base: ContextPack, target: ContextPack) -> ContextPackDelta:
        base._validate()
        target._validate()
        prefix = 0
        for old, new in zip(base.items, target.items):
            if old != new:
                break
            prefix += 1
        return cls(base.digest, target.digest, prefix, target.items[prefix:])

    @property
    def byte_count(self) -> int:
        return len(self.to_bytes())

    def to_bytes(self) -> bytes:
        return _json_bytes(
            {
                "schema": _DELTA_SCHEMA,
                "base_digest": self.base_digest,
                "target_digest": self.target_digest,
                "prefix_items": self.prefix_items,
                "appended": _encoded(self.appended),
            }
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> ContextPackDelta:
        value = _payload(
            data, {"schema", "base_digest", "target_digest", "prefix_items", "appended"}, _DELTA_SCHEMA
        )
        prefix_items = value["prefix_items"]
        if type(prefix_items) is not int:
            raise ContextPackError("prefix_items must be an integer")  # noqa: TRY003
        return cls(
            _digest(value["base_digest"]),
            _digest(value["target_digest"]),
            prefix_items,
            _decoded(value["appended"]),
        )


def apply_context_pack_delta(base: ContextPack, delta: ContextPackDelta) -> ContextPack:
    """Rebuild without sender state, rejecting a stale base or altered target."""
    base._validate()
    if delta.base_digest != base.digest or delta.prefix_items > len(base.items):
        raise ContextPackError("delta base or prefix does not match the supplied pack")  # noqa: TRY003
    target = ContextPack.build(base.items[: delta.prefix_items] + delta.appended)
    if target.digest != delta.target_digest:
        raise ContextPackError("delta reconstructed a different target")  # noqa: TRY003
    return target


__all__ = ["ContextPack", "ContextPackDelta", "ContextPackError", "apply_context_pack_delta"]
