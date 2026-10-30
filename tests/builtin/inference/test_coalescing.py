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

"""Caller-visible sharing, cancellation, local failures and provider accounting."""

from __future__ import annotations

import asyncio

import pytest

from powercontext.builtin.artifacts.memory import EmbeddingProfile
from powercontext.builtin.inference import EmbeddingResult, InferenceUsage
from powercontext.builtin.inference.coalescing import CoalescingEmbeddingModel


class _Embedding:
    profile = EmbeddingProfile(profile_id="coalescing-regressions", model="offline", dimension=1)

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        self.calls.append(texts)
        return EmbeddingResult(
            vectors=tuple((float(len(text)),) for text in texts),
            usage=InferenceUsage(requests=2, input_tokens=7, output_tokens=0),
        )


def test_zero_window_shares_synchronously_started_calls_and_reports_distinct_batches() -> None:
    async def scenario() -> None:
        base = _Embedding()
        model = CoalescingEmbeddingModel(base, max_batch_size=6, coalesce_ms=0, cache_size=48)
        texts = tuple(f"text-{index}" for index in range(24))
        results = await asyncio.gather(*(model.embed(texts + texts[:2]) for _ in range(6)))
        assert len(base.calls) == 4
        assert sorted(text for batch in base.calls for text in batch) == sorted(texts)
        for result in results:
            assert result.vectors == tuple((float(len(text)),) for text in texts + texts[:2])
            assert result.usage == InferenceUsage(requests=8, input_tokens=28, output_tokens=0)
        cached = await model.embed(texts)
        assert len(base.calls) == 4
        assert cached.usage.requests == 0

    asyncio.run(scenario())


def test_late_waiter_shares_running_work_when_cache_is_disabled_and_owner_cancels() -> None:
    class Blocked(_Embedding):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
            self.started.set()
            await self.release.wait()
            return await super().embed(texts)

    async def scenario() -> None:
        base = Blocked()
        model = CoalescingEmbeddingModel(base, coalesce_ms=0, cache_size=0)
        owner = asyncio.create_task(model.embed(("shared", "shared")))
        await base.started.wait()
        late = asyncio.create_task(model.embed(("shared",)))
        await asyncio.sleep(0)
        owner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await owner
        base.release.set()
        result = await late
        assert result.vectors == ((6.0,),)
        assert result.usage == InferenceUsage(requests=2, input_tokens=7, output_tokens=0)
        assert base.calls == [("shared",)]
        await model.embed(("shared",))
        assert base.calls == [("shared",), ("shared",)]

    asyncio.run(scenario())


def test_repeated_cache_access_updates_lru_in_input_order() -> None:
    async def scenario() -> None:
        base = _Embedding()
        model = CoalescingEmbeddingModel(base, coalesce_ms=0, cache_size=2)
        await model.embed(("alpha", "beta"))
        cached = await model.embed(("alpha", "beta", "alpha"))
        assert cached.usage.requests == 0
        await model.embed(("gamma",))
        await model.embed(("alpha",))
        assert base.calls == [("alpha", "beta"), ("gamma",)]
        await model.embed(("beta",))
        assert base.calls[-1] == ("beta",)

    asyncio.run(scenario())


@pytest.mark.parametrize("wrong_count", [False, True], ids=["provider-error", "wrong-vector-count"])
def test_failed_batch_can_retry_without_poisoning_independent_batch(wrong_count: bool) -> None:
    class PartialFailure(_Embedding):
        def __init__(self) -> None:
            super().__init__()
            self.failed = False

        async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
            if "bad" in texts and not self.failed:
                self.failed = True
                self.calls.append(texts)
                if wrong_count:
                    return EmbeddingResult(vectors=())
                raise RuntimeError("provider temporarily unavailable")
            return await super().embed(texts)

    async def scenario() -> None:
        base = PartialFailure()
        model = CoalescingEmbeddingModel(base, max_batch_size=1, coalesce_ms=0)
        bad, good = await asyncio.gather(model.embed(("bad",)), model.embed(("good",)), return_exceptions=True)
        assert isinstance(bad, ValueError if wrong_count else RuntimeError)
        assert isinstance(good, EmbeddingResult)
        assert good.vectors == ((4.0,),)
        retried = await model.embed(("bad", "good", "bad"))
        assert retried.vectors == ((3.0,), (4.0,), (3.0,))
        assert retried.usage == InferenceUsage(requests=2, input_tokens=7, output_tokens=0)
        assert base.calls.count(("bad",)) == 2
        assert base.calls.count(("good",)) == 1

    asyncio.run(scenario())
