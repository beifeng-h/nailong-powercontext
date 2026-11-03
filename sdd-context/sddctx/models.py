"""领域模型：SDD 规格、架构决策、代码/测试引用，以及最终产出的上下文包。

这里的类型是整个模块的"词汇表"：解析（ingestion）、索引（indexer）、存储（store）、
解析任务（resolver）、体检（drift）四个环节都只通过这些结构交换数据，
因此接入外部实例时只需要替换 store，不需要动其它环节。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable


class SpecStatus(str, Enum):
    """规格的生命周期状态。"""

    DRAFT = "draft"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DEPRECATED = "deprecated"

    @property
    def is_effective(self) -> bool:
        """是否"当前有效"——只有 active 的规格能作为开发依据。"""
        return self is SpecStatus.ACTIVE


class DecisionStatus(str, Enum):
    """架构决策（ADR）的状态。"""

    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"

    @property
    def is_effective(self) -> bool:
        return self is DecisionStatus.ACCEPTED


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

    @property
    def rank(self) -> int:
        return {"error": 0, "warning": 1, "info": 2}[self.value]


def _as_tuple(value: Iterable[str] | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(value)


@dataclass(frozen=True)
class Requirement:
    """一条可验证的需求。`verified_by` 指向验证它的测试用例。"""

    id: str
    text: str
    key: str = ""
    verified_by: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.key:
            object.__setattr__(self, "key", self.id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "key": self.key,
            "text": self.text,
            "verified_by": list(self.verified_by),
        }


@dataclass(frozen=True)
class CodeRef:
    """规格指向的代码位置（文件 + 可选符号）。"""

    file: str
    symbol: str = ""
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"file": self.file, "symbol": self.symbol, "note": self.note}


@dataclass(frozen=True)
class TestRef:
    """规格指向的测试位置，以及它覆盖的需求。"""

    file: str
    test_id: str = ""
    covers: tuple[str, ...] = ()
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "test_id": self.test_id,
            "covers": list(self.covers),
            "note": self.note,
        }


def _hash_body(body: str) -> str:
    return hashlib.sha256(body.strip().encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Spec:
    """一份 SDD 规格。"""

    id: str
    title: str
    status: SpecStatus = SpecStatus.ACTIVE
    scope: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    supersedes: tuple[str, ...] = ()
    superseded_by: str = ""
    requirements: tuple[Requirement, ...] = ()
    code_refs: tuple[CodeRef, ...] = ()
    test_refs: tuple[TestRef, ...] = ()
    body: str = ""
    path: str = ""

    @property
    def content_hash(self) -> str:
        return _hash_body(self.body)

    @property
    def is_effective(self) -> bool:
        return self.status.is_effective

    def requirement(self, req_id: str) -> Requirement | None:
        for req in self.requirements:
            if req.id == req_id:
                return req
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status.value,
            "scope": list(self.scope),
            "tags": list(self.tags),
            "supersedes": list(self.supersedes),
            "superseded_by": self.superseded_by,
            "requirements": [r.to_dict() for r in self.requirements],
            "code_refs": [r.to_dict() for r in self.code_refs],
            "test_refs": [r.to_dict() for r in self.test_refs],
            "content_hash": self.content_hash,
            "path": self.path,
        }


@dataclass(frozen=True)
class Decision:
    """一条架构决策（ADR）。"""

    id: str
    title: str
    status: DecisionStatus = DecisionStatus.ACCEPTED
    decided_at: str = ""
    scope: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    superseded_by: str = ""
    body: str = ""
    path: str = ""

    @property
    def content_hash(self) -> str:
        return _hash_body(self.body)

    @property
    def is_effective(self) -> bool:
        return self.status.is_effective

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status.value,
            "decided_at": self.decided_at,
            "scope": list(self.scope),
            "tags": list(self.tags),
            "superseded_by": self.superseded_by,
            "content_hash": self.content_hash,
            "path": self.path,
        }


@dataclass(frozen=True)
class Symbol:
    """代码索引里的一个符号。"""

    path: str
    qualname: str
    kind: str = "function"
    line: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "qualname": self.qualname,
            "kind": self.kind,
            "line": self.line,
        }


@dataclass(frozen=True)
class TestCase:
    """代码索引里的一个测试用例。`covers` 是它声明覆盖的需求 id。"""

    path: str
    test_id: str
    covers: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "test_id": self.test_id, "covers": list(self.covers)}


@dataclass(frozen=True)
class Finding:
    """一条体检结论（上下文是否仍然有效的问题）。"""

    code: str
    severity: Severity
    target: str
    message: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "target": self.target,
            "message": self.message,
            "detail": self.detail,
        }


@dataclass
class ContextBundle:
    """针对一次开发任务组装出来的上下文包。"""

    task: str
    specs: list[Spec] = field(default_factory=list)
    candidates: list[Spec] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    invalidated_decisions: list[Decision] = field(default_factory=list)
    invalidated_specs: list[Spec] = field(default_factory=list)
    code_refs: list[CodeRef] = field(default_factory=list)
    tests: list[TestRef] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    score: dict[str, float] = field(default_factory=dict)
    generated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "generated_at": self.generated_at,
            "specs": [s.to_dict() for s in self.specs],
            "candidates": [s.to_dict() for s in self.candidates],
            "decisions": [d.to_dict() for d in self.decisions],
            "invalidated_decisions": [d.to_dict() for d in self.invalidated_decisions],
            "invalidated_specs": [s.to_dict() for s in self.invalidated_specs],
            "code_refs": [r.to_dict() for r in self.code_refs],
            "tests": [t.to_dict() for t in self.tests],
            "findings": [f.to_dict() for f in self.findings],
            "score": self.score,
        }

    def to_markdown(self) -> str:
        """渲染成可以直接贴进 AI 助手的提示词片段。"""
        out: list[str] = [f"# 开发任务上下文：{self.task}", ""]

        out.append("## 当前有效的规格")
        if self.specs:
            for spec in self.specs:
                out.append(f"### {spec.id} {spec.title}  (status={spec.status.value})")
                if spec.requirements:
                    out.append("必须满足：")
                    for req in spec.requirements:
                        marks = ", ".join(req.verified_by) if req.verified_by else "（暂无验证）"
                        out.append(f"- [{req.id}] {req.text}  <- 验证：{marks}")
                if spec.code_refs:
                    out.append("相关代码：")
                    for ref in spec.code_refs:
                        loc = f"{ref.file}:{ref.symbol}" if ref.symbol else ref.file
                        out.append(f"- `{loc}`" + (f" — {ref.note}" if ref.note else ""))
                out.append("")
        else:
            out.append("_（没有匹配到当前有效的规格，需人工确认需求口径。）_")
            out.append("")

        out.append("## 相关代码与测试")
        if self.code_refs:
            out.append("代码：")
            for ref in self.code_refs:
                loc = f"{ref.file}:{ref.symbol}" if ref.symbol else ref.file
                out.append(f"- `{loc}`" + (f" — {ref.note}" if ref.note else ""))
            out.append("")
        if self.tests:
            out.append("测试（改动后必须重跑）：")
            for test in self.tests:
                out.append(f"- `{test.test_id or test.file}`")
            out.append("")

        out.append("## 待评审的规格（未生效，仅供参考）")
        if self.candidates:
            for spec in self.candidates:
                out.append(f"- {spec.id} {spec.title} (status={spec.status.value})")
        else:
            out.append("- （无）")
        out.append("")

        out.append("## 仍然有效的决策")
        if self.decisions:
            for decision in self.decisions:
                out.append(f"- {decision.id} {decision.title}")
        else:
            out.append("- （无）")
        out.append("")

        out.append("## 已失效、不要依赖的决策")
        if self.invalidated_decisions:
            for decision in self.invalidated_decisions:
                tail = f"，被 {decision.superseded_by} 取代" if decision.superseded_by else ""
                out.append(f"- {decision.id} {decision.title}{tail}")
        else:
            out.append("- （无）")
        out.append("")

        errors = [f for f in self.findings if f.severity is Severity.ERROR]
        warnings = [f for f in self.findings if f.severity is Severity.WARNING]
        out.append("## 上下文风险")
        if errors:
            out.append("阻塞项（必须先解决）：")
            for f in errors:
                out.append(f"- [{f.code}] {f.target}：{f.message}")
        if warnings:
            out.append("提醒：")
            for f in warnings:
                out.append(f"- [{f.code}] {f.target}：{f.message}")
        if not errors and not warnings:
            out.append("- 无")
        out.append("")
        return "\n".join(out)


def dumps(obj: Any) -> str:
    """统一的 JSON 序列化（列表字段用 JSON 存进单列）。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)

