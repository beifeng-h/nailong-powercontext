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

"""Batch HTTP scores while retaining original Memory candidate ranks."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
from pydantic import BaseModel, ConfigDict, Field

from powercontext.builtin.artifacts.memory.reranking import MemoryRerankDecision
from powercontext.builtin.inference import InferenceUsage

if TYPE_CHECKING:
    from powercontext.builtin.artifacts.memory.models import MemoryHit


class _Score(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    rank: int = Field(ge=1)
    score: float = Field(allow_inf_nan=False)


class _Scores(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    scores: list[_Score]


class HTTPMemoryReranker:
    """Select globally by service score; callers retain ownership of the client."""

    def __init__(
        self,
        endpoint: str,
        *,
        client: httpx.AsyncClient,
        batch_size: int = 32,
        policy_id: str = "http-cross-encoder-v1",
    ) -> None:
        if type(batch_size) is not int or batch_size <= 0:
            raise ValueError("batch_size must be a positive integer")  # noqa: TRY003
        self.policy_id = policy_id
        self._endpoint = endpoint
        self._client = client
        self._batch_size = batch_size

    async def rerank(
        self, query: str, candidates: tuple[MemoryHit, ...], limit: int, /
    ) -> MemoryRerankDecision:
        """Validate each batch's coverage before one stable global selection."""

        if not candidates or type(limit) is not int or not 1 <= limit <= len(candidates):
            raise ValueError("limit must select between one and all candidates")  # noqa: TRY003
        scores: dict[int, float] = {}
        requests = 0
        for offset in range(0, len(candidates), self._batch_size):
            batch = [
                {"rank": rank, "text": hit.text}
                for rank, hit in enumerate(candidates[offset : offset + self._batch_size], start=offset + 1)
            ]
            response = await self._client.post(self._endpoint, json={"query": query, "candidates": batch})
            requests += 1
            response.raise_for_status()
            result = _Scores.model_validate(response.json())
            ranks = [item.rank for item in result.scores]
            if len(ranks) != len(batch) or set(ranks) != {item["rank"] for item in batch}:
                raise ValueError("scores must cover each requested rank exactly once")  # noqa: TRY003
            scores.update((item.rank, item.score) for item in result.scores)
        return MemoryRerankDecision(
            selected_ranks=tuple(sorted(scores, key=lambda rank: (-scores[rank], rank))[:limit]),
            usage=InferenceUsage(requests=requests),
        )


__all__ = ["HTTPMemoryReranker"]
