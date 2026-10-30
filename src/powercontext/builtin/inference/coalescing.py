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

"""Shared in-flight embedding batches and a bounded successful-vector cache."""

from __future__ import annotations

import asyncio
import math
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from powercontext.builtin.inference.models import EmbeddingResult, EmbeddingVector, InferenceUsage

if TYPE_CHECKING:
    from powercontext.builtin.inference.protocols import EmbeddingModel


@dataclass(frozen=True, eq=False, slots=True)
class _BatchUsage:
    usage: InferenceUsage


@dataclass(frozen=True, slots=True)
class _EmbeddedText:
    vector: EmbeddingVector
    batch: _BatchUsage | None = None


class CoalescingEmbeddingModel:
    """Share embedding work and successful vectors within one event loop.

    Provider usage belongs to a whole batch. Each caller reports every distinct
    batch it waited on once, even when several of its texts shared that batch.
    """

    def __init__(
        self,
        model: EmbeddingModel,
        *,
        max_batch_size: int = 64,
        coalesce_ms: float = 5.0,
        cache_size: int = 1024,
    ) -> None:
        if type(max_batch_size) is not int or max_batch_size < 1:
            raise ValueError("max_batch_size must be a positive integer")  # noqa: TRY003
        if type(cache_size) is not int or cache_size < 0:
            raise ValueError("cache_size must be a non-negative integer")  # noqa: TRY003
        if (
            isinstance(coalesce_ms, bool)
            or not isinstance(coalesce_ms, (int, float))
            or not math.isfinite(coalesce_ms)
            or coalesce_ms < 0
        ):
            raise ValueError("coalesce_ms must be a finite non-negative number")  # noqa: TRY003
        self.profile = model.profile
        self._model = model
        self._max_batch_size = max_batch_size
        self._coalesce_seconds = coalesce_ms / 1000
        self._cache_size = cache_size
        self._cache: OrderedDict[str, EmbeddingVector] = OrderedDict()
        self._inflight: dict[str, asyncio.Future[_EmbeddedText]] = {}
        self._queued: dict[str, asyncio.Future[_EmbeddedText]] = {}
        self._dispatch_handle: asyncio.TimerHandle | None = None
        self._tasks: set[asyncio.Task[None]] = set()

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        """Restore input order while sharing pending and already successful work."""

        if not texts:
            return EmbeddingResult(vectors=())
        resolved: dict[str, _EmbeddedText] = {}
        waiting: dict[str, asyncio.Future[_EmbeddedText]] = {}
        loop = asyncio.get_running_loop()
        for text in texts:
            if text in self._cache:
                resolved[text] = _EmbeddedText(self._cache[text])
                self._cache.move_to_end(text)
                continue
            if text in waiting:
                continue
            future = self._inflight.get(text)
            if future is None:
                future = loop.create_future()
                future.add_done_callback(_retrieve_exception)
                self._inflight[text] = future
                self._queued[text] = future
            waiting[text] = future
        if self._queued and self._dispatch_handle is None:
            # A zero window still dispatches after currently ready callers register.
            self._dispatch_handle = loop.call_later(self._coalesce_seconds, self._dispatch)
        if waiting:
            values = await asyncio.gather(*(asyncio.shield(future) for future in waiting.values()))
            resolved.update(zip(waiting, values, strict=True))
        batches = {value.batch for value in resolved.values() if value.batch is not None}
        usages = tuple(batch.usage for batch in batches)
        return EmbeddingResult(
            vectors=tuple(resolved[text].vector for text in texts),
            usage=InferenceUsage(
                requests=sum(usage.requests for usage in usages),
                input_tokens=_optional_sum(tuple(usage.input_tokens for usage in usages)),
                output_tokens=_optional_sum(tuple(usage.output_tokens for usage in usages)),
            ),
        )

    def _dispatch(self) -> None:
        self._dispatch_handle = None
        queued = tuple(self._queued.items())
        self._queued.clear()
        for start in range(0, len(queued), self._max_batch_size):
            task = asyncio.create_task(self._embed_batch(queued[start : start + self._max_batch_size]))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _embed_batch(self, batch: tuple[tuple[str, asyncio.Future[_EmbeddedText]], ...]) -> None:
        try:
            result = await self._model.embed(tuple(text for text, _future in batch))
            if len(result.vectors) != len(batch):
                raise ValueError("embedding vector count does not match the batch")  # noqa: TRY003
        except (Exception, asyncio.CancelledError) as error:  # noqa: BLE001 - deliver provider failures to its waiters.
            for text, future in batch:
                self._inflight.pop(text, None)
                if not future.done():
                    future.set_exception(error)
            return
        usage = _BatchUsage(result.usage)
        for (text, future), vector in zip(batch, result.vectors, strict=True):
            self._inflight.pop(text, None)
            if self._cache_size:
                self._cache[text] = vector
                self._cache.move_to_end(text)
                while len(self._cache) > self._cache_size:
                    self._cache.popitem(last=False)
            if not future.done():
                future.set_result(_EmbeddedText(vector, usage))


def _optional_sum(values: tuple[int | None, ...]) -> int | None:
    known = tuple(value for value in values if value is not None)
    return sum(known) if known else None


def _retrieve_exception(future: asyncio.Future[_EmbeddedText]) -> None:
    # All callers may cancel while the shared work continues to completion.
    if not future.cancelled():
        future.exception()


__all__ = ["CoalescingEmbeddingModel"]
