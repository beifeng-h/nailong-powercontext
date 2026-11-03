---
id: SPEC-003
title: 规格导入与生命周期契约
status: active
scope: [ingestion, store, frontmatter]
tags: [ingestion, spec, lifecycle]
supersedes: []
superseded_by:
requirements:
  - id: REQ-INGEST-1
    key: ingestion.strict_validation
    text: 规格文档缺少必填字段或字段非法时必须报错并指出文件路径，不得静默跳过
    verified_by:
      - tests/test_ingestion.py::IngestionTests::test_parse_spec_missing_id
  - id: REQ-INGEST-2
    key: ingestion.idempotent
    text: 重复导入同一批规格不得产生重复记录
    verified_by:
      - tests/test_store.py::StoreTests::test_upsert_spec_is_idempotent
  - id: REQ-INGEST-3
    key: ingestion.content_hash
    text: 规格正文变化必须能通过内容哈希被检测到，以便判断先前的验证是否过期
    verified_by:
      - tests/test_store.py::StoreTests::test_content_hash_changes_with_body
  - id: REQ-INGEST-4
    key: ingestion.review_baseline_in_repo
    text: 评审基线必须随仓库持久化，重新 clone 后仍然知道先前的验证是否适用
    verified_by:
      - tests/test_reviews.py::ReviewsTests::test_review_baseline_persists_in_repo
code_refs:
  - file: sddctx/ingestion.py
    symbol: parse_spec
    note: 规格文档解析
  - file: sddctx/store.py
    symbol: SqliteStore.upsert_spec
    note: 规格落库
test_refs:
  - file: tests/test_ingestion.py
    test_id: tests/test_ingestion.py::IngestionTests::test_parse_spec_missing_id
    covers:
      - REQ-INGEST-1
  - file: tests/test_store.py
    test_id: tests/test_store.py::StoreTests::test_upsert_spec_is_idempotent
    covers:
      - REQ-INGEST-2
  - file: tests/test_store.py
    test_id: tests/test_store.py::StoreTests::test_content_hash_changes_with_body
    covers:
      - REQ-INGEST-3
  - file: tests/test_reviews.py
    test_id: tests/test_reviews.py::ReviewsTests::test_review_baseline_persists_in_repo
    covers:
      - REQ-INGEST-4
---

# SPEC-003 规格导入与生命周期契约

## 文档形态

规格与决策都是 Markdown + frontmatter：

- `spec/specs/*.md` 是规格（`id` 形如 `SPEC-001`）；
- `spec/decisions/*.md` 是架构决策（`id` 形如 `ADR-001`）。

frontmatter 支持的字段见 `docs/architecture.md`；解析器是 `sddctx/frontmatter.py`
实现的 YAML 受限子集，不引入第三方依赖。

## 生命周期

```
draft ──评审通过──> active ──被新规格取代──> superseded
  │                   │
  └──评审未通过──> (退回 draft)   └──不再适用──> deprecated
```

- 规格的 `supersedes` 指向被它取代的规格 id；被取代的一方写 `superseded_by`。
- 决策的 `superseded_by` 指向取代它的决策 id。
- 只有 `active` 的规格与 `accepted` 的决策进入"当前有效"集合。

## 严格性

导入期错误必须暴露而不是被吞掉：字段缺失、状态非法、需求缺少 id，
都要带上文件路径抛出 `IngestionError`。

## 评审基线随仓库走

评审基线（某份规格在某个内容哈希上被确认过）写在 `spec/reviews.json`，
是可提交的文件，而不是只存在本地数据库里——否则换个机器或重新 clone，
"先前的验证是否还适用"就没人答得上来了。数据库里那份只是运行时缓存，
`refresh` 时以文件为准。

