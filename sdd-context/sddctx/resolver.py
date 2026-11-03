"""任务 -> 上下文包。

这是"AI 开发助手"真正调用的入口：给它一句开发任务，它还回
当前有效的规格、相关代码、相关测试、仍然有效的决策，以及
哪些决策已经失效、哪些验证已经过期。

匹配用轻量的词元打分（ASCII 词 + 中文二元组），不引入任何模型依赖，
保证离线可跑、结果可解释、同样输入必得同样输出。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Sequence

from .drift import DriftChecker
from .models import (
    CodeRef,
    ContextBundle,
    Decision,
    Finding,
    Spec,
    TestRef,
)

WORD_PATTERN = re.compile(r"[a-z0-9_]{2,}")
CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]+")


def tokenize(text: str) -> set[str]:
    """把文本切成可比较的词元：ASCII 词 + 中文单字与二元组。"""
    lowered = text.lower()
    tokens: set[str] = set(WORD_PATTERN.findall(lowered))
    for run in CJK_PATTERN.findall(lowered):
        tokens.update(run)
        for i in range(len(run) - 1):
            tokens.add(run[i : i + 2])
    return tokens


def _overlap(a: set[str], b: set[str]) -> int:
    return len(a & b)


@dataclass
class ContextResolver:
    """按任务检索上下文。"""

    store: object
    checker: DriftChecker | None = None

    def __init__(self, store: object, checker: DriftChecker | None = None) -> None:
        self.store = store
        self.checker = checker

    # ---------- 打分 ----------
    def score_spec(
        self,
        spec: Spec,
        task_tokens: set[str],
        scope: Sequence[str] = (),
        changed_files: Sequence[str] = (),
    ) -> float:
        score = 0.0
        tag_tokens = {t.lower() for t in spec.tags}
        scope_tokens = {s.lower() for s in spec.scope}
        score += 4.0 * _overlap(tag_tokens, task_tokens)
        score += 3.0 * _overlap(scope_tokens, task_tokens)
        for want in scope:
            if want.lower() in scope_tokens:
                score += 5.0
        score += 3.0 * min(_overlap(tokenize(spec.title), task_tokens), 6)
        req_tokens: set[str] = set()
        for req in spec.requirements:
            req_tokens |= tokenize(req.text)
        score += 1.0 * min(_overlap(req_tokens, task_tokens), 8)
        score += 0.2 * min(_overlap(tokenize(spec.body), task_tokens), 10)
        for ref in list(spec.code_refs) + list(spec.test_refs):
            for changed in changed_files:
                if ref.file == changed:
                    score += 6.0
                elif ref.file.startswith(changed.rstrip("/") + "/"):
                    score += 1.5
        return round(score, 3)

    def _decision_relevant(
        self,
        decision: Decision,
        task_tokens: set[str],
        selected: Iterable[Spec],
    ) -> bool:
        tokens = {s.lower() for s in decision.scope} | {t.lower() for t in decision.tags}
        if tokens & task_tokens:
            return True
        spec_tokens: set[str] = set()
        for spec in selected:
            spec_tokens |= {s.lower() for s in spec.scope}
            spec_tokens |= {t.lower() for t in spec.tags}
        return bool(tokens & spec_tokens)

    # ---------- 主流程 ----------
    def resolve(
        self,
        task: str,
        scope: Sequence[str] = (),
        tags: Sequence[str] = (),
        changed_files: Sequence[str] = (),
        limit: int = 6,
    ) -> ContextBundle:
        task_tokens = tokenize(task)
        for tag in tags:
            task_tokens.add(tag.lower())

        specs = self.store.list_specs()  # type: ignore[attr-defined]
        decisions = self.store.list_decisions()  # type: ignore[attr-defined]

        scored: list[tuple[float, Spec]] = []
        for spec in specs:
            value = self.score_spec(spec, task_tokens, scope, changed_files)
            if value > 0:
                scored.append((value, spec))
        scored.sort(key=lambda item: (-item[0], item[1].id))

        effective: list[Spec] = []
        candidates: list[Spec] = []
        invalidated: list[Spec] = []
        score_map: dict[str, float] = {}
        for value, spec in scored:
            score_map[spec.id] = value
            if spec.status.is_effective:
                effective.append(spec)
            elif spec.status.value == "draft":
                candidates.append(spec)
            else:
                invalidated.append(spec)
        effective = effective[:limit]
        candidates = candidates[:limit]

        selected_ids = {s.id for s in effective}
        relevant_decisions: list[Decision] = []
        invalidated_decisions: list[Decision] = []
        for decision in decisions:
            if not self._decision_relevant(decision, task_tokens, effective):
                continue
            if decision.is_effective:
                relevant_decisions.append(decision)
            else:
                invalidated_decisions.append(decision)

        # 被取代的决策：把"取代它的那份"补进有效决策，助手才知道该听谁的
        by_id = {d.id: d for d in decisions}
        for decision in list(invalidated_decisions):
            successor = by_id.get(decision.superseded_by)
            if successor is not None and successor.is_effective:
                if successor not in relevant_decisions:
                    relevant_decisions.append(successor)

        code_refs: list[CodeRef] = []
        tests: list[TestRef] = []
        seen_code: set[tuple[str, str]] = set()
        seen_test: set[str] = set()
        for spec in effective:
            for ref in spec.code_refs:
                key = (ref.file, ref.symbol)
                if key not in seen_code:
                    seen_code.add(key)
                    code_refs.append(ref)
            for ref in spec.test_refs:
                key = ref.test_id or ref.file
                if key not in seen_test:
                    seen_test.add(key)
                    tests.append(ref)

        findings: list[Finding] = []
        if self.checker is not None:
            targets = selected_ids | {d.id for d in relevant_decisions}
            targets |= {d.id for d in invalidated_decisions}
            findings = [
                f
                for f in self.checker.check(spec_ids=selected_ids)
                if f.target in targets
            ]

        return ContextBundle(
            task=task,
            specs=effective,
            candidates=candidates,
            decisions=relevant_decisions,
            invalidated_decisions=invalidated_decisions,
            invalidated_specs=invalidated,
            code_refs=code_refs,
            tests=tests,
            findings=findings,
            score=score_map,
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )

