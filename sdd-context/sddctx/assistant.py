"""AI 开发助手的上下文宿主。

`sddctx` 是"上下文模块"，这一层是把它接进助手的适配层：
助手在开工前调用 `prepare_task()`，拿到一份带风险提示的上下文包；
干完活之后调用 `refresh()` 把最新代码/规格同步进索引，再跑一次体检。

这里不绑定任何模型：模块只负责"给出当前有效的上下文 + 明确哪些已经失效"，
模型换成谁都行。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from .drift import DriftChecker
from .ingestion import load_tree
from .indexer import index_root
from .models import ContextBundle, Finding, Severity
from .resolver import ContextResolver
from .reviews import load_reviews


@dataclass
class ContextPacket:
    """助手一次任务所拿到的全部东西。"""

    task: str
    bundle: ContextBundle
    prompt: str = ""
    checklist: list[str] = field(default_factory=list)
    blocking: list[Finding] = field(default_factory=list)
    warnings: list[Finding] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        """没有阻塞项才算可以开工。"""
        return not self.blocking

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "ready": self.ready,
            "prompt": self.prompt,
            "checklist": list(self.checklist),
            "blocking": [f.to_dict() for f in self.blocking],
            "warnings": [f.to_dict() for f in self.warnings],
            "bundle": self.bundle.to_dict(),
        }


class AssistantRuntime:
    """把 store / resolver / checker 串起来的助手运行时。"""

    def __init__(self, store: Any, root: str | Path = ".", spec_root: str | Path | None = None) -> None:
        self.store = store
        self.root = Path(root).resolve()
        self.spec_root = Path(spec_root).resolve() if spec_root else self.root / "spec"
        self.checker = DriftChecker(store)
        self.resolver = ContextResolver(store, self.checker)

    # ---------- 索引刷新 ----------
    def refresh(self, now: str = "") -> dict[str, Any]:
        """重新索引代码、重新导入规格。"""
        index = index_root(self.root)
        self.store.replace_files(index.files)
        self.store.replace_symbols(index.symbols)
        self.store.replace_tests(index.tests)
        specs, decisions = load_tree(self.spec_root)
        for spec in specs:
            self.store.upsert_spec(spec, now)
        for decision in decisions:
            self.store.upsert_decision(decision, now)
        # 评审基线跟着仓库走：spec/reviews.json 是真相来源，库里只是缓存
        for review in load_reviews(self.spec_root):
            self.store.set_review(review)
        return {
            "files": len(index.files),
            "symbols": len(index.symbols),
            "tests": len(index.tests),
            "specs": len(specs),
            "decisions": len(decisions),
        }

    # ---------- 任务准备 ----------
    def prepare_task(
        self,
        task: str,
        scope: Sequence[str] = (),
        tags: Sequence[str] = (),
        changed_files: Sequence[str] = (),
    ) -> ContextPacket:
        bundle = self.resolver.resolve(
            task, scope=scope, tags=tags, changed_files=changed_files
        )
        blocking = [f for f in bundle.findings if f.severity is Severity.ERROR]
        warnings = [f for f in bundle.findings if f.severity is Severity.WARNING]
        return ContextPacket(
            task=task,
            bundle=bundle,
            prompt=self.build_prompt(bundle),
            checklist=self.build_checklist(bundle),
            blocking=blocking,
            warnings=warnings,
        )

    # ---------- 提示词与清单 ----------
    def build_prompt(self, bundle: ContextBundle) -> str:
        head = (
            "你是一名 AI 开发助手。以下是从工程上下文管理系统中检索出的当前有效上下文。\n"
            "规则：只以“当前有效的规格/决策”为准；标记为失效的内容禁止依赖；"
            "改动代码前先读完规格里列出的代码位置，改完后必须重跑规格里列出的测试。\n"
        )
        return head + bundle.to_markdown()

    def build_checklist(self, bundle: ContextBundle) -> list[str]:
        steps: list[str] = []
        for spec in bundle.specs:
            steps.append(f"阅读并遵守 {spec.id} {spec.title}")
        for decision in bundle.decisions:
            steps.append(f"遵守决策 {decision.id} {decision.title}")
        for decision in bundle.invalidated_decisions:
            tail = f"（已被 {decision.superseded_by} 取代）" if decision.superseded_by else ""
            steps.append(f"不要依赖已失效决策 {decision.id} {decision.title}{tail}")
        for test in bundle.tests:
            steps.append(f"改动后运行 `{test.test_id or test.file}`")
        steps.append("改动完成后运行 `sddctx doctor`，确认上下文仍然有效")
        return steps

