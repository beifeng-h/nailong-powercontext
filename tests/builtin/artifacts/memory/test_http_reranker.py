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

"""HTTP error propagation and strict JSON score identities."""

from __future__ import annotations

import httpx
import pytest

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory.http_reranker import HTTPMemoryReranker
from powercontext.builtin.artifacts.memory.models import MemoryHit


def _hit() -> MemoryHit:
    return MemoryHit(
        memory_ref=ArtifactRef(family="memory", artifact_id="report", revision=1),
        entry_id="entry", entry_version_id="version", text="original evidence", score=1, matched_by=("fts",),
    )


@pytest.mark.parametrize(
    "score", [{"rank": True, "score": 0.5}, {"rank": 1.0, "score": 0.5},
              {"rank": 1, "score": True}, {"rank": 1, "score": "0.5"}],
)
async def test_service_cannot_coerce_rank_or_score_types(score) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"scores": [score]}))
    ) as client:
        with pytest.raises(ValueError):
            await HTTPMemoryReranker("https://reranker.invalid", client=client).rerank("q", (_hit(),), 1)


async def test_non_success_response_preserves_status_exception_before_schema_parsing() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, content=b"not a score response"))
    ) as client:
        with pytest.raises(httpx.HTTPStatusError) as caught:
            await HTTPMemoryReranker("https://reranker.invalid", client=client).rerank("q", (_hit(),), 1)
        assert caught.value.response.status_code == 503
        assert not client.is_closed


async def test_invalid_json_fails_instead_of_using_coarse_ranks() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"{"))
    ) as client:
        with pytest.raises(ValueError):
            await HTTPMemoryReranker("https://reranker.invalid", client=client).rerank("q", (_hit(),), 1)
