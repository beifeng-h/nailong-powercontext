"""演示：AI 开发助手如何拿到"当前有效"的上下文。

    python scripts/demo_assistant.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sddctx.assistant import AssistantRuntime  # noqa: E402
from sddctx.store import SqliteStore  # noqa: E402

TASK = "给上下文解析加上按改动文件加权排序的能力"


def main() -> int:
    store = SqliteStore(":memory:")
    runtime = AssistantRuntime(store, root=ROOT)
    runtime.refresh()
    packet = runtime.prepare_task(TASK, changed_files=["sddctx/resolver.py"])
    print(packet.prompt)
    print("")
    print("=" * 78)
    print("执行清单")
    print("=" * 78)
    for step in packet.checklist:
        print(f"  [ ] {step}")
    print("")
    print(f"ready = {packet.ready}（没有阻塞项即可开工）")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

