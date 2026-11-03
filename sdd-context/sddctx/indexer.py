"""代码与测试索引。

索引回答两个问题：
1. 规格里写的 `file.py:some_symbol` 现在还在吗？（代码有没有被改掉/删掉）
2. 规格里写的测试用例现在还在吗？它覆盖的需求有没有变？（先前的验证是否还适用）

只用标准库 `ast` 做静态解析，不执行代码、不需要任何外部服务。
"""

from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from .models import Symbol, TestCase

SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".sddctx",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "build",
    "dist",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
}

COVERS_PATTERN = re.compile(r"#\s*@covers\s+([A-Za-z0-9_\-.]+)")


@dataclass(frozen=True)
class CodeIndex:
    """一次索引的结果。"""

    symbols: tuple[Symbol, ...]
    tests: tuple[TestCase, ...]
    files: tuple[str, ...]

    def has_symbol(self, path: str, symbol: str) -> bool:
        if not symbol:
            return path in self.files
        return any(s.path == path and s.qualname == symbol for s in self.symbols)

    def has_file(self, path: str) -> bool:
        return path in self.files

    def has_test(self, test_id: str) -> bool:
        return any(t.test_id == test_id for t in self.tests)

    def test_covers(self, test_id: str) -> tuple[str, ...]:
        for test in self.tests:
            if test.test_id == test_id:
                return test.covers
        return ()


def is_test_file(rel_path: str) -> bool:
    name = Path(rel_path).name
    return name.startswith("test_") or name.endswith("_test.py")


def _is_test_name(name: str) -> bool:
    return name.startswith("test_") or name.endswith("_test")


def _is_test_class(name: str) -> bool:
    """测试类有两种常见写法：`TestFoo`（pytest）与 `FooTests`（unittest）。"""
    return name.startswith("Test") or name.endswith("Tests") or name.endswith("Test")


def _walk(root: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            if name.endswith(".py"):
                yield Path(dirpath) / name


def _covers_in(source_lines: list[str], start: int, end: int) -> tuple[str, ...]:
    found: list[str] = []
    for line in source_lines[start - 1 : end]:
        for match in COVERS_PATTERN.finditer(line):
            if match.group(1) not in found:
                found.append(match.group(1))
    return tuple(found)


def _collect_symbols(tree: ast.AST) -> list[tuple[str, str, int, int]]:
    """收集模块级与类内的可引用符号。"""
    out: list[tuple[str, str, int, int]] = []

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = f"{prefix}{child.name}"
                out.append((qualname, "function", child.lineno, child.end_lineno or child.lineno))
                visit(child, f"{qualname}.")
            elif isinstance(child, ast.ClassDef):
                qualname = f"{prefix}{child.name}"
                out.append((qualname, "class", child.lineno, child.end_lineno or child.lineno))
                visit(child, f"{qualname}.")
            else:
                visit(child, prefix)

    visit(tree, "")
    return out


def index_python_file(path: Path, rel_path: str) -> tuple[list[Symbol], list[TestCase]]:
    """解析单个 Python 文件，抽取符号与测试用例。"""
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return [], []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [], []

    symbols = [
        Symbol(path=rel_path, qualname=qualname, kind=kind, line=line)
        for qualname, kind, line, _ in _collect_symbols(tree)
    ]

    tests: list[TestCase] = []
    if is_test_file(rel_path):
        lines = source.splitlines()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_test_name(node.name):
                covers = _covers_in(lines, node.lineno, node.end_lineno or node.lineno)
                tests.append(TestCase(path=rel_path, test_id=f"{rel_path}::{node.name}", covers=covers))
            elif isinstance(node, ast.ClassDef) and _is_test_class(node.name):
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_test_name(sub.name):
                        covers = _covers_in(lines, sub.lineno, sub.end_lineno or sub.lineno)
                        test_id = f"{rel_path}::{node.name}::{sub.name}"
                        tests.append(TestCase(path=rel_path, test_id=test_id, covers=covers))
    return symbols, tests


def index_root(root: str | Path) -> CodeIndex:
    """索引整个代码树。"""
    root_path = Path(root).resolve()
    symbols: list[Symbol] = []
    tests: list[TestCase] = []
    files: list[str] = []
    if not root_path.exists():
        return CodeIndex((), (), ())
    for file_path in _walk(root_path):
        rel = file_path.relative_to(root_path).as_posix()
        files.append(rel)
        file_symbols, file_tests = index_python_file(file_path, rel)
        symbols.extend(file_symbols)
        tests.extend(file_tests)
    return CodeIndex(tuple(symbols), tuple(tests), tuple(files))


def merge_covers(tests: Iterable[TestCase], extra: dict[str, tuple[str, ...]]) -> dict[str, tuple[str, ...]]:
    """把规格里声明的 covers 合并到测试索引上。"""
    merged: dict[str, tuple[str, ...]] = {t.test_id: t.covers for t in tests}
    for test_id, covers in extra.items():
        current = list(merged.get(test_id, ()))
        for cover in covers:
            if cover not in current:
                current.append(cover)
        merged[test_id] = tuple(current)
    return merged

