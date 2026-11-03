"""演示：真实改代码 -> 上下文系统发现脱节 -> 改完规格恢复有效。

脚本会把仓库复制到临时目录再动手，所以不会污染工作区。

    python scripts/demo_drift.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sddctx.assistant import AssistantRuntime  # noqa: E402
from sddctx.models import Severity  # noqa: E402
from sddctx.store import SqliteStore  # noqa: E402

IGNORE = shutil.ignore_patterns(".git", ".sddctx", "__pycache__", "*.pyc", ".venv")


def show(title: str, runtime: AssistantRuntime) -> list[str]:
    findings = runtime.checker.check()
    errors = [f.code for f in findings if f.severity is Severity.ERROR]
    print("")
    print("=" * 78)
    print(title)
    print("=" * 78)
    for finding in findings:
        if finding.severity in (Severity.ERROR, Severity.WARNING):
            print(f"  [{finding.severity.value}] {finding.target}  {finding.code}")
            print(f"          {finding.message}")
    if not errors:
        print("  -> 没有阻塞项")
    print(f"  -> error 数量：{len(errors)}")
    return errors


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "repo"
        shutil.copytree(ROOT, work, ignore=IGNORE)
        store = SqliteStore(":memory:")
        runtime = AssistantRuntime(store, root=work)
        runtime.refresh()

        show("阶段 0：规格与代码一致（基线）", runtime)

        # --- 真实改动 1：把规格引用的符号改名（重构） ---
        target = work / "sddctx" / "drift.py"
        source = target.read_text(encoding="utf-8")
        target.write_text(source.replace("_check_spec", "_check_one_spec"), encoding="utf-8")
        runtime.refresh()
        errors = show(
            "阶段 1：把 DriftChecker._check_spec 改名为 _check_one_spec（规格没改）", runtime
        )
        if "SPEC_CODE_SYMBOL_MISSING" not in errors:
            print("!! 预期应该报出 SPEC_CODE_SYMBOL_MISSING")
            return 1

        # --- 真实改动 2：删掉验证用例 ---
        (work / "tests" / "test_drift.py").unlink()
        runtime.refresh()
        errors = show("阶段 2：删除 tests/test_drift.py（先前的验证不再适用）", runtime)
        if "SPEC_TEST_MISSING" not in errors:
            print("!! 预期应该报出 SPEC_TEST_MISSING")
            return 1

        # --- 助手视角：上下文过期，助手应当被拦住 ---
        packet = runtime.prepare_task("给体检加上新的检查项")
        print("")
        print("=" * 78)
        print("阶段 3：AI 助手准备开工时的判断")
        print("=" * 78)
        print(f"  ready = {packet.ready}")
        for finding in packet.blocking:
            print(f"  [阻塞] {finding.code}：{finding.message}")

        # --- 把规格跟上代码 ---
        spec_file = work / "spec" / "specs" / "SPEC-002-drift-detection.md"
        spec_text = spec_file.read_text(encoding="utf-8")
        spec_file.write_text(
            spec_text.replace("DriftChecker._check_spec", "DriftChecker._check_one_spec"),
            encoding="utf-8",
        )
        runtime.refresh()
        errors = show("阶段 4：规格同步到新符号名后（测试仍缺失，保留一个 error）", runtime)

        shutil.copy2(ROOT / "tests" / "test_drift.py", work / "tests" / "test_drift.py")
        runtime.refresh()
        errors = show("阶段 5：补回测试用例后", runtime)
        if errors:
            print("!! 预期应该没有 error")
            return 1

        print("")
        print("结论：代码改动 -> 规格漂移被检出 -> 规格与测试跟上 -> 上下文恢复有效。")
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

