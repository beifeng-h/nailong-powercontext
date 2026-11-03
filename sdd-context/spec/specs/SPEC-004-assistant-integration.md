---
id: SPEC-004
title: AI 助手接入契约
status: active
scope: [assistant, resolver, drift]
tags: [assistant, prompt, workflow]
supersedes: []
superseded_by:
requirements:
  - id: REQ-ASSIST-1
    key: assistant.packet_contract
    text: 助手准备任务时必须拿到上下文包、提示词与可执行清单三样东西
    verified_by:
      - tests/test_assistant.py::AssistantTests::test_prepare_task_returns_packet
  - id: REQ-ASSIST-2
    key: assistant.blocking_findings
    text: 存在 error 级问题时助手必须被判定为不可直接开工
    verified_by:
      - tests/test_assistant.py::AssistantTests::test_blocking_finding_marks_not_ready
  - id: REQ-ASSIST-3
    key: assistant.detects_code_change
    text: 代码被实际修改后重新索引必须能发现规格与代码的脱节
    verified_by:
      - tests/test_end_to_end.py::EndToEndTests::test_code_change_is_detected
code_refs:
  - file: sddctx/assistant.py
    symbol: AssistantRuntime.prepare_task
    note: 任务准备入口
  - file: sddctx/assistant.py
    symbol: AssistantRuntime.refresh
    note: 重新索引与导入
test_refs:
  - file: tests/test_assistant.py
    test_id: tests/test_assistant.py::AssistantTests::test_prepare_task_returns_packet
    covers:
      - REQ-ASSIST-1
  - file: tests/test_assistant.py
    test_id: tests/test_assistant.py::AssistantTests::test_blocking_finding_marks_not_ready
    covers:
      - REQ-ASSIST-2
  - file: tests/test_end_to_end.py
    test_id: tests/test_end_to_end.py::EndToEndTests::test_code_change_is_detected
    covers:
      - REQ-ASSIST-3
---

# SPEC-004 AI 助手接入契约

## 接入方式

```python
from sddctx import AssistantRuntime, SqliteStore

store = SqliteStore(".sddctx/context.db")
runtime = AssistantRuntime(store, root=".")
runtime.refresh()                      # 索引代码 + 导入 spec/
packet = runtime.prepare_task("给任务列表加上按状态过滤")
packet.prompt                          # 直接喂给模型
packet.checklist                       # 助手要逐条走完的清单
packet.ready                           # 有没有阻塞项
```

也可以通过 HTTP 把模块挂给外部助手：`python -m sddctx serve` 后调用
`GET /api/context?task=...`。

## 约束

1. 模块不绑定任何模型：它只负责"给出当前有效的上下文 + 明确哪些已经失效"，
   模型由使用方决定。
2. 助手开工前必须先过一遍上下文包；带 error 的上下文包视为阻塞。
3. 助手改完代码必须重新索引并再跑一次体检，否则规格漂移不会被发现。

