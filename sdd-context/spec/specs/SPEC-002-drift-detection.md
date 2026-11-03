---
id: SPEC-002
title: 上下文有效性体检契约
status: active
scope: [drift, store]
tags: [drift, validity, sdd]
supersedes: []
superseded_by:
requirements:
  - id: REQ-DRIFT-1
    key: drift.detect.missing_symbol
    text: 规格引用的代码符号消失时必须报 error，提示规格与代码已脱节
    verified_by:
      - tests/test_drift.py::DriftTests::test_detect_missing_symbol
  - id: REQ-DRIFT-2
    key: drift.detect.missing_test
    text: 规格引用的验证用例消失时必须报 error，明确先前的验证不再适用
    verified_by:
      - tests/test_drift.py::DriftTests::test_detect_missing_test
  - id: REQ-DRIFT-3
    key: drift.detect.changed_after_review
    text: 规格内容在上次评审之后发生变化时必须报 warning，要求重新确认验证结论
    verified_by:
      - tests/test_drift.py::DriftTests::test_detect_changed_after_review
  - id: REQ-DRIFT-4
    key: drift.detect.conflicting_specs
    text: 两份生效规格对同一需求键定义不一致时必须报 error，禁止助手自行取舍
    verified_by:
      - tests/test_drift.py::DriftTests::test_detect_conflicting_specs
code_refs:
  - file: sddctx/drift.py
    symbol: DriftChecker.check
    note: 体检入口
  - file: sddctx/drift.py
    symbol: DriftChecker._check_spec
    note: 单份规格的漂移检查
test_refs:
  - file: tests/test_drift.py
    test_id: tests/test_drift.py::DriftTests::test_detect_missing_symbol
    covers:
      - REQ-DRIFT-1
  - file: tests/test_drift.py
    test_id: tests/test_drift.py::DriftTests::test_detect_missing_test
    covers:
      - REQ-DRIFT-2
  - file: tests/test_drift.py
    test_id: tests/test_drift.py::DriftTests::test_detect_changed_after_review
    covers:
      - REQ-DRIFT-3
  - file: tests/test_drift.py
    test_id: tests/test_drift.py::DriftTests::test_detect_conflicting_specs
    covers:
      - REQ-DRIFT-4
---

# SPEC-002 上下文有效性体检契约

## 背景

"上下文是否还有效"是这套系统区别于普通文档站的地方。规格写得再漂亮，
只要它指向的代码被重构了、验证它的用例被删了、或者需求在两份生效规格里
说法不一致，把它原样喂给助手就是在制造错误。

## 体检项

| 现象 | 判定 | 代码 |
| --- | --- | --- |
| 规格引用的文件不存在 | error | `SPEC_CODE_FILE_MISSING` |
| 规格引用的符号不存在 | error | `SPEC_CODE_SYMBOL_MISSING` |
| 规格引用的验证用例不存在 | error | `SPEC_TEST_MISSING` |
| 需求的验证用例全部消失 | error | `SPEC_REQ_VERIFY_MISSING` |
| 需求从未有验证用例 | warning | `SPEC_REQ_UNVERIFIED` |
| 规格在上次评审后被修改 | warning | `SPEC_CHANGED_AFTER_REVIEW` |
| 规格从未评审 | warning | `SPEC_NEVER_REVIEWED` |
| 两份生效规格定义同一需求键但内容不同 | error | `SPEC_ACTIVE_CONFLICT` |
| 决策被取代但仍标为 accepted | warning | `DECISION_STATUS_INCONSISTENT` |
| 决策被取代且取代者不存在 | error | `DECISION_SUPERSEDER_MISSING` |

error 视为阻塞项：助手拿到带 error 的上下文包时必须先解决，不允许直接开工。

