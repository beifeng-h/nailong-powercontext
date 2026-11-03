---
id: SPEC-005
title: 命令行与 HTTP 接口契约
status: active
scope: [cli, server]
tags: [cli, http, interface]
supersedes: []
superseded_by:
requirements:
  - id: REQ-API-1
    key: cli.doctor_exit_code
    text: doctor 发现 error 级问题时进程退出码必须为 1，便于接入 CI
    verified_by:
      - tests/test_cli.py::CliTests::test_doctor_exit_code_on_error
  - id: REQ-API-2
    key: server.context_endpoint
    text: HTTP /api/context 必须返回当前有效规格、已失效决策与阻塞项
    verified_by:
      - tests/test_server.py::ServerTests::test_context_endpoint_returns_bundle
code_refs:
  - file: sddctx/cli.py
    symbol: main
    note: 命令行入口
  - file: sddctx/server.py
    symbol: ContextRequestHandler
    note: HTTP 路由
test_refs:
  - file: tests/test_cli.py
    test_id: tests/test_cli.py::CliTests::test_doctor_exit_code_on_error
    covers:
      - REQ-API-1
  - file: tests/test_server.py
    test_id: tests/test_server.py::ServerTests::test_context_endpoint_returns_bundle
    covers:
      - REQ-API-2
---

# SPEC-005 命令行与 HTTP 接口契约

## 命令行

```
python -m sddctx init            # 建库（嵌入式 SQLite）
python -m sddctx index           # 索引代码与测试
python -m sddctx ingest          # 导入 spec/
python -m sddctx refresh         # index + ingest + 体检
python -m sddctx context --task "..." [--format json]
python -m sddctx doctor [--json] [--spec SPEC-001]
python -m sddctx review SPEC-001 # 记录评审基线
python -m sddctx assistant --task "..."
python -m sddctx serve --port 8787
```

`doctor` 在存在 error 级问题时返回退出码 1，`refresh` 同理，可直接接进 CI。

## HTTP

| 路由 | 方法 | 说明 |
| --- | --- | --- |
| `/api/health` | GET | 存活与统计 |
| `/api/specs` | GET | 全部规格 |
| `/api/decisions` | GET | 全部决策 |
| `/api/context?task=...` | GET | 上下文包（`format=markdown` 返回提示词） |
| `/api/doctor` | GET | 体检结果 |
| `/api/refresh` | POST | 重新索引并导入 |

服务默认只监听 `127.0.0.1`，不引入任何 Web 框架。

