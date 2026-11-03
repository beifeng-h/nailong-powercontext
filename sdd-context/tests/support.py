"""测试用的文档构造工具。"""

from __future__ import annotations

from typing import Iterable, Sequence

SPEC_TEMPLATE = """
id: {id}
title: {title}
status: {status}
scope: [{scope}]
tags: [{tags}]
supersedes: []
superseded_by: {superseded_by}
requirements:
{requirements}
code_refs:
{code_refs}
test_refs:
{test_refs}
"""

DECISION_TEMPLATE = """
id: {id}
title: {title}
status: {status}
decided_at: 2026-11-03
scope: [{scope}]
tags: [{tags}]
superseded_by: {superseded_by}
"""


def requirement_block(items: Iterable[tuple[str, str, Sequence[str]]]) -> str:
    lines: list[str] = []
    for req_id, text, verified in items:
        lines.append(f"  - id: {req_id}")
        lines.append(f"    text: {text}")
        if verified:
            lines.append("    verified_by:")
            for item in verified:
                lines.append(f"      - {item}")
    return "\n".join(lines)


def code_ref_block(items: Iterable[tuple[str, str, str]]) -> str:
    lines: list[str] = []
    for file, symbol, note in items:
        lines.append(f"  - file: {file}")
        if symbol:
            lines.append(f"    symbol: {symbol}")
        if note:
            lines.append(f"    note: {note}")
    return "\n".join(lines)


def test_ref_block(items: Iterable[tuple[str, str, Sequence[str]]]) -> str:
    lines: list[str] = []
    for file, test_id, covers in items:
        lines.append(f"  - file: {file}")
        if test_id:
            lines.append(f"    test_id: {test_id}")
        if covers:
            lines.append("    covers:")
            for item in covers:
                lines.append(f"      - {item}")
    return "\n".join(lines)


def spec_doc(
    spec_id: str = "SPEC-1",
    title: str = "测试规格",
    status: str = "active",
    scope: Sequence[str] = (),
    tags: Sequence[str] = (),
    superseded_by: str = "",
    requirements: Iterable[tuple[str, str, Sequence[str]]] = (),
    code_refs: Iterable[tuple[str, str, str]] = (),
    test_refs: Iterable[tuple[str, str, Sequence[str]]] = (),
    body: str = "正文内容\n",
) -> str:
    front = SPEC_TEMPLATE.format(
        id=spec_id,
        title=title,
        status=status,
        scope=", ".join(scope),
        tags=", ".join(tags),
        superseded_by=superseded_by,
        requirements=requirement_block(requirements),
        code_refs=code_ref_block(code_refs),
        test_refs=test_ref_block(test_refs),
    )
    return "---\n" + front.strip() + "\n---\n" + body


def decision_doc(
    decision_id: str = "ADR-1",
    title: str = "测试决策",
    status: str = "accepted",
    scope: Sequence[str] = (),
    tags: Sequence[str] = (),
    superseded_by: str = "",
) -> str:
    front = DECISION_TEMPLATE.format(
        id=decision_id,
        title=title,
        status=status,
        scope=", ".join(scope),
        tags=", ".join(tags),
        superseded_by=superseded_by,
    )
    return "---\n" + front.strip() + "\n---\n决策正文\n"

