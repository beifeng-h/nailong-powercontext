"""把 SDD 文档（Markdown + frontmatter）读成领域模型。

约定：
- `spec/specs/*.md`      -> 规格（Spec）
- `spec/decisions/*.md`  -> 架构决策（ADR）

frontmatter 字段见 `docs/architecture.md`。解析失败会抛 `IngestionError`，
并带上文件路径——规格写错是必须立刻暴露的问题，不能静默跳过。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .frontmatter import FrontmatterError, parse_document
from .models import (
    CodeRef,
    Decision,
    DecisionStatus,
    Requirement,
    Spec,
    SpecStatus,
    TestRef,
)


class IngestionError(ValueError):
    """规格/决策文档无法解析。"""


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _as_str_list(value: Any) -> tuple[str, ...]:
    return tuple(str(item) for item in _as_list(value) if item is not None)


def _require(data: dict[str, Any], key: str, path: str) -> Any:
    value = data.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise IngestionError(f"{path}: frontmatter 缺少必填字段 '{key}'")
    return value


def _parse_requirements(raw: Any, path: str) -> tuple[Requirement, ...]:
    out: list[Requirement] = []
    for item in _as_list(raw):
        if not isinstance(item, dict):
            raise IngestionError(f"{path}: requirements 的每一项都必须是映射")
        req_id = str(item.get("id") or "").strip()
        if not req_id:
            raise IngestionError(f"{path}: requirement 缺少 id")
        text = str(item.get("text") or "").strip()
        if not text:
            raise IngestionError(f"{path}: requirement {req_id} 缺少 text")
        out.append(
            Requirement(
                id=req_id,
                text=text,
                key=str(item.get("key") or "").strip(),
                verified_by=_as_str_list(item.get("verified_by")),
            )
        )
    return tuple(out)


def _parse_code_refs(raw: Any, path: str) -> tuple[CodeRef, ...]:
    out: list[CodeRef] = []
    for item in _as_list(raw):
        if isinstance(item, str):
            out.append(CodeRef(file=item))
            continue
        if not isinstance(item, dict):
            raise IngestionError(f"{path}: code_refs 的每一项都必须是映射")
        file = str(item.get("file") or "").strip()
        if not file:
            raise IngestionError(f"{path}: code_ref 缺少 file")
        out.append(
            CodeRef(
                file=file,
                symbol=str(item.get("symbol") or "").strip(),
                note=str(item.get("note") or "").strip(),
            )
        )
    return tuple(out)


def _parse_test_refs(raw: Any, path: str) -> tuple[TestRef, ...]:
    out: list[TestRef] = []
    for item in _as_list(raw):
        if isinstance(item, str):
            out.append(TestRef(file=item))
            continue
        if not isinstance(item, dict):
            raise IngestionError(f"{path}: test_refs 的每一项都必须是映射")
        file = str(item.get("file") or "").strip()
        if not file:
            raise IngestionError(f"{path}: test_ref 缺少 file")
        out.append(
            TestRef(
                file=file,
                test_id=str(item.get("test_id") or "").strip(),
                covers=_as_str_list(item.get("covers")),
                note=str(item.get("note") or "").strip(),
            )
        )
    return tuple(out)


def parse_spec(text: str, path: str = "") -> Spec:
    """把一份规格文档解析成 `Spec`。"""
    try:
        data, body = parse_document(text)
    except FrontmatterError as exc:
        raise IngestionError(f"{path}: {exc}") from exc
    spec_id = str(_require(data, "id", path)).strip()
    title = str(_require(data, "title", path)).strip()
    status_raw = str(data.get("status") or "active").strip()
    try:
        status = SpecStatus(status_raw)
    except ValueError as exc:
        allowed = ", ".join(s.value for s in SpecStatus)
        raise IngestionError(f"{path}: 非法 status '{status_raw}'（可选：{allowed}）") from exc
    return Spec(
        id=spec_id,
        title=title,
        status=status,
        scope=_as_str_list(data.get("scope")),
        tags=_as_str_list(data.get("tags")),
        supersedes=_as_str_list(data.get("supersedes")),
        superseded_by=str(data.get("superseded_by") or "").strip(),
        requirements=_parse_requirements(data.get("requirements"), path),
        code_refs=_parse_code_refs(data.get("code_refs"), path),
        test_refs=_parse_test_refs(data.get("test_refs"), path),
        body=body,
        path=path,
    )


def parse_decision(text: str, path: str = "") -> Decision:
    """把一份决策文档（ADR）解析成 `Decision`。"""
    try:
        data, body = parse_document(text)
    except FrontmatterError as exc:
        raise IngestionError(f"{path}: {exc}") from exc
    decision_id = str(_require(data, "id", path)).strip()
    title = str(_require(data, "title", path)).strip()
    status_raw = str(data.get("status") or "accepted").strip()
    try:
        status = DecisionStatus(status_raw)
    except ValueError as exc:
        allowed = ", ".join(s.value for s in DecisionStatus)
        raise IngestionError(f"{path}: 非法 status '{status_raw}'（可选：{allowed}）") from exc
    return Decision(
        id=decision_id,
        title=title,
        status=status,
        decided_at=str(data.get("decided_at") or "").strip(),
        scope=_as_str_list(data.get("scope")),
        tags=_as_str_list(data.get("tags")),
        superseded_by=str(data.get("superseded_by") or "").strip(),
        body=body,
        path=path,
    )


def load_spec_file(path: Path, root: Path) -> tuple[Spec | None, Decision | None]:
    """按文件所在目录判断它是规格还是决策。"""
    text = path.read_text(encoding="utf-8")
    rel = path.relative_to(root).as_posix()
    if any("decision" in part for part in path.parts):
        return None, parse_decision(text, rel)
    return parse_spec(text, rel), None


def load_tree(spec_root: str | Path) -> tuple[list[Spec], list[Decision]]:
    """读取整个规格目录。"""
    root = Path(spec_root)
    specs: list[Spec] = []
    decisions: list[Decision] = []
    if not root.exists():
        return specs, decisions
    for path in sorted(root.rglob("*.md")):
        spec, decision = load_spec_file(path, root)
        if spec:
            specs.append(spec)
        if decision:
            decisions.append(decision)
    return specs, decisions

