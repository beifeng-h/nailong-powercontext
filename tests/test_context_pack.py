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

"""Wire corruption and Unicode boundaries of independently reconstructed packs."""

from __future__ import annotations

import json

import pytest

from powercontext.builtin.runtime.context_pack import (
    ContextPack,
    ContextPackDelta,
    ContextPackError,
    apply_context_pack_delta,
)


@pytest.mark.parametrize("text", ["", "alpha\n海洋😀 beta\r\n", "x" * 9999])
def test_serialized_pack_and_delta_rebuild_without_sender_state(text: str) -> None:
    base = ContextPack.from_content(text, chunk_bytes=17)
    target = ContextPack.from_content(text + " newer revision 海洋", chunk_bytes=17)
    delta = ContextPackDelta.between(base, target)
    restored = apply_context_pack_delta(
        ContextPack.from_bytes(base.to_bytes()), ContextPackDelta.from_bytes(delta.to_bytes())
    )
    assert restored == target
    assert b"".join(restored.items).decode("utf-8") == text + " newer revision 海洋"
    assert all(len(item) <= 17 and item.decode("utf-8") for item in target.items)
    assert base.byte_count == len(base.to_bytes())
    assert delta.byte_count == len(delta.to_bytes())


@pytest.mark.parametrize("change", ["extra", "count", "digest", "base64", "utf8", "duplicate-field"])
def test_pack_rejects_inconsistent_wire(change: str) -> None:
    pack = ContextPack.from_content("alpha")
    payload = json.loads(pack.to_bytes())
    if change == "extra":
        payload["unexpected"] = None
    elif change == "count":
        payload["byte_count"] = True
    elif change == "digest":
        payload["digest"] = "sha256:" + "0" * 64
    elif change == "base64":
        payload["items"] = ["YQ==="]
    elif change == "utf8":
        payload["items"] = ["/w=="]
    if change == "duplicate-field":
        wire = pack.to_bytes().replace(b'{"byte_count":', b'{"schema":"powercontext.context-pack.v1","byte_count":')
    else:
        wire = json.dumps(payload).encode("utf-8")
    with pytest.raises(ContextPackError):
        ContextPack.from_bytes(wire)


@pytest.mark.parametrize("prefix", [True, 1.5, -1, 999])
def test_delta_rejects_invalid_or_out_of_bounds_prefix(prefix: object) -> None:
    base = ContextPack.from_content("a")
    delta = ContextPackDelta.between(base, ContextPack.from_content("a new value"))
    payload = json.loads(delta.to_bytes())
    payload["prefix_items"] = prefix
    with pytest.raises(ContextPackError):
        decoded = ContextPackDelta.from_bytes(json.dumps(payload).encode())
        apply_context_pack_delta(base, decoded)


def test_identical_rounds_reuse_complete_prefix_and_account_for_real_wire() -> None:
    content = "Stable cited material. " * 300
    pack = ContextPack.from_content(content)
    delta = ContextPackDelta.between(pack, ContextPack.from_bytes(pack.to_bytes()))
    assert delta.prefix_items == len(pack.items)
    assert not delta.appended
    assert len(delta.to_bytes()) < len(content.encode("utf-8")) // 10
    assert apply_context_pack_delta(pack, delta) == pack


@pytest.mark.parametrize("chunk_bytes", [0, -1, True, 2.5, 2])
def test_invalid_or_insufficient_utf8_chunk_limit_fails(chunk_bytes: object) -> None:
    with pytest.raises(ContextPackError):
        ContextPack.from_content("海洋", chunk_bytes=chunk_bytes)
