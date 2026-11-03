"""上下文有效性体检。

回答三个问题：
1. 规格里写的代码/测试还在吗？          -> 代码漂移
2. 这份需求现在由谁验证？验证还在吗？    -> 验证漂移
3. 哪些决策已经失效（被取代/被废弃）？   -> 决策失效

体检结果是 `Finding` 列表，CLI 的 `doctor` 命令、HTTP 接口、助手运行时共用它。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import Finding, Severity, Spec


@dataclass
class DriftChecker:
    """基于 store 里的规格 + 代码索引做体检。"""

    store: object

    def __init__(self, store: object) -> None:
        self.store = store

    # ---------- 索引视图 ----------
    def _symbols(self) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for symbol in self.store.list_symbols():  # type: ignore[attr-defined]
            out.setdefault(symbol.path, set()).add(symbol.qualname)
        return out

    def _files(self) -> set[str]:
        return set(self.store.list_files())  # type: ignore[attr-defined]

    def _tests(self) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for test in self.store.list_tests():  # type: ignore[attr-defined]
            out[test.test_id] = set(test.covers)
        return out

    def _coverage(self) -> dict[str, set[str]]:
        """需求 id -> 覆盖它的测试 id 集合（含规格里声明的 covers 与测试里的 @covers 标记）。"""
        coverage: dict[str, set[str]] = {}
        for spec in self.store.list_specs():  # type: ignore[attr-defined]
            for ref in spec.test_refs:
                for req_id in ref.covers:
                    coverage.setdefault(req_id, set()).add(ref.test_id)
        for test in self.store.list_tests():  # type: ignore[attr-defined]
            for req_id in test.covers:
                coverage.setdefault(req_id, set()).add(test.test_id)
        return coverage

    # ---------- 体检 ----------
    def check(self, spec_ids: Iterable[str] | None = None) -> list[Finding]:
        findings: list[Finding] = []
        symbols = self._symbols()
        files = self._files()
        tests = self._tests()
        coverage = self._coverage()
        specs = self.store.list_specs()  # type: ignore[attr-defined]
        wanted = set(spec_ids) if spec_ids is not None else None
        if wanted is not None:
            specs = [s for s in specs if s.id in wanted]

        for spec in specs:
            findings.extend(self._check_spec(spec, symbols, files, tests, coverage))
            findings.extend(self._check_spec_links(spec, specs))

        findings.extend(self._check_conflicts(specs))
        findings.extend(self._check_decisions())
        findings.extend(self._check_orphan_tests(specs))
        findings.sort(key=lambda f: (f.severity.rank, f.target, f.code))
        return findings

    def _check_spec(
        self,
        spec: Spec,
        symbols: dict[str, set[str]],
        files: set[str],
        tests: dict[str, set[str]],
        coverage: dict[str, set[str]],
    ) -> list[Finding]:
        out: list[Finding] = []

        for ref in spec.code_refs:
            if ref.file not in files:
                out.append(
                    Finding(
                        code="SPEC_CODE_FILE_MISSING",
                        severity=Severity.ERROR,
                        target=spec.id,
                        message=f"引用的文件 `{ref.file}` 已不存在，规格与代码已经脱节",
                        detail={"file": ref.file, "symbol": ref.symbol},
                    )
                )
                continue
            if ref.symbol and ref.symbol not in symbols.get(ref.file, set()):
                out.append(
                    Finding(
                        code="SPEC_CODE_SYMBOL_MISSING",
                        severity=Severity.ERROR,
                        target=spec.id,
                        message=f"`{ref.file}` 中的符号 `{ref.symbol}` 不存在，代码已被删除或改名",
                        detail={"file": ref.file, "symbol": ref.symbol},
                    )
                )

        for ref in spec.test_refs:
            if ref.test_id and ref.test_id not in tests:
                out.append(
                    Finding(
                        code="SPEC_TEST_MISSING",
                        severity=Severity.ERROR,
                        target=spec.id,
                        message=f"验证用例 `{ref.test_id}` 不存在，先前的验证结论不再适用",
                        detail={"file": ref.file, "test_id": ref.test_id},
                    )
                )

        for req in spec.requirements:
            missing = [t for t in req.verified_by if t not in tests]
            if missing:
                out.append(
                    Finding(
                        code="SPEC_REQ_VERIFY_MISSING",
                        severity=Severity.ERROR,
                        target=spec.id,
                        message=f"需求 {req.id} 的验证用例已消失：{', '.join(missing)}",
                        detail={"requirement": req.id, "missing": missing},
                    )
                )
                continue
            live = coverage.get(req.id, set()) & set(tests)
            if not live and not req.verified_by:
                out.append(
                    Finding(
                        code="SPEC_REQ_UNVERIFIED",
                        severity=Severity.WARNING,
                        target=spec.id,
                        message=f"需求 {req.id} 没有任何存活的验证用例",
                        detail={"requirement": req.id},
                    )
                )

        review = self.store.get_review(spec.id)  # type: ignore[attr-defined]
        if review is None:
            out.append(
                Finding(
                    code="SPEC_NEVER_REVIEWED",
                    severity=Severity.WARNING,
                    target=spec.id,
                    message="这份规格从未被评审过，先前的验证结论不可引用",
                    detail={},
                )
            )
        elif review.content_hash != spec.content_hash:
            out.append(
                Finding(
                    code="SPEC_CHANGED_AFTER_REVIEW",
                    severity=Severity.WARNING,
                    target=spec.id,
                    message="规格在上次评审之后被修改，先前的验证可能已过期，需要重新确认",
                    detail={
                        "reviewed_hash": review.content_hash,
                        "current_hash": spec.content_hash,
                        "reviewed_at": review.reviewed_at,
                    },
                )
            )
        return out

    def _check_spec_links(self, spec: Spec, all_specs: list[Spec]) -> list[Finding]:
        out: list[Finding] = []
        known = {s.id for s in all_specs}
        for old in spec.supersedes:
            if old not in known:
                out.append(
                    Finding(
                        code="SPEC_SUPERSEDES_MISSING",
                        severity=Severity.WARNING,
                        target=spec.id,
                        message=f"声明取代了 `{old}`，但库中没有这份规格",
                        detail={"supersedes": old},
                    )
                )
        if spec.status.value == "superseded" and not spec.superseded_by:
            out.append(
                Finding(
                    code="SPEC_SUPERSEDE_NO_TARGET",
                    severity=Severity.WARNING,
                    target=spec.id,
                    message="状态是 superseded，但没有写明被哪份规格取代",
                    detail={},
                )
            )
        return out

    def _check_conflicts(self, specs: list[Spec]) -> list[Finding]:
        out: list[Finding] = []
        buckets: dict[str, list[tuple[str, str]]] = {}
        for spec in specs:
            if not spec.is_effective:
                continue
            for req in spec.requirements:
                buckets.setdefault(req.key, []).append((spec.id, req.text))
        for key, entries in buckets.items():
            ids = {sid for sid, _ in entries}
            texts = {text for _, text in entries}
            if len(ids) > 1 and len(texts) > 1:
                detail = {sid: text for sid, text in entries}
                out.append(
                    Finding(
                        code="SPEC_ACTIVE_CONFLICT",
                        severity=Severity.ERROR,
                        target=", ".join(sorted(ids)),
                        message=f"同一需求键 `{key}` 在多份生效规格中定义不一致，开发前必须先定口径",
                        detail=detail,
                    )
                )
        return out

    def _check_decisions(self) -> list[Finding]:
        out: list[Finding] = []
        decisions = self.store.list_decisions()  # type: ignore[attr-defined]
        known = {d.id for d in decisions}
        for decision in decisions:
            if decision.status.value == "superseded":
                out.append(
                    Finding(
                        code="DECISION_SUPERSEDED",
                        severity=Severity.INFO,
                        target=decision.id,
                        message=(
                            f"决策已失效（被 {decision.superseded_by} 取代），不会进入上下文"
                            if decision.superseded_by
                            else "决策已失效，不会进入上下文"
                        ),
                        detail={"superseded_by": decision.superseded_by},
                    )
                )
                if decision.superseded_by and decision.superseded_by not in known:
                    out.append(
                        Finding(
                            code="DECISION_SUPERSEDER_MISSING",
                            severity=Severity.ERROR,
                            target=decision.id,
                            message=f"声明被 `{decision.superseded_by}` 取代，但找不到这份决策",
                            detail={"superseded_by": decision.superseded_by},
                        )
                    )
            if decision.status.value == "accepted" and decision.superseded_by:
                out.append(
                    Finding(
                        code="DECISION_STATUS_INCONSISTENT",
                        severity=Severity.WARNING,
                        target=decision.id,
                        message="状态仍是 accepted，但已声明被取代，助手可能同时依赖两份决策",
                        detail={"superseded_by": decision.superseded_by},
                    )
                )
        return out

    def _check_orphan_tests(self, specs: list[Spec]) -> list[Finding]:
        referenced: set[str] = set()
        for spec in specs:
            for ref in spec.test_refs:
                if ref.test_id:
                    referenced.add(ref.test_id)
        out: list[Finding] = []
        for test in self.store.list_tests():  # type: ignore[attr-defined]
            if test.covers and test.test_id not in referenced:
                out.append(
                    Finding(
                        code="TEST_COVERS_UNREFERENCED",
                        severity=Severity.INFO,
                        target=test.test_id,
                        message=(
                            "这个测试声明覆盖了 "
                            + ", ".join(test.covers)
                            + "，但没有任何规格引用它，覆盖关系对不上"
                        ),
                        detail={"path": test.path, "covers": list(test.covers)},
                    )
                )
        return out

