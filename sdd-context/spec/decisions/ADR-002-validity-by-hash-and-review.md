---
id: ADR-002
title: 规格有效性用"内容哈希 + 评审基线"判定
status: accepted
decided_at: 2026-11-03
scope: [drift, store, ingestion]
tags: [drift, review, lifecycle]
supersedes:
  - ADR-003
superseded_by:
---

# ADR-002 规格有效性用内容哈希 + 评审基线判定

## 背景

规格改了以后，怎么知道"先前那条验证结论"还算不算数？
只靠 `status` 字段不够——人常常改了正文却忘了改状态；
只靠 git 历史又太重，且离开 git 就不成立。

## 决策

规格正文计算内容哈希（sha256 前 16 位）。评审时用
`sddctx review <spec-id>` 记录一条"基线"（哈希 + 时间）。
体检时比对当前哈希与基线：

- 一致 → 先前的验证结论继续适用；
- 不一致 → 报 `SPEC_CHANGED_AFTER_REVIEW`（warning），要求重新确认。

基线写在 `spec/reviews.json`（可提交），不只存在本地数据库里：
评审结论要跟着代码走，换台机器 clone 下来也得知道"上次验到哪儿了"。

同时保留"引用是否还指向活着的代码/测试"的检查：
文件或符号消失报 error，验证用例消失报 error——
这两种情况直接说明上下文已经不可用了。

## 取代

本决策取代 [ADR-003](ADR-003-status-only.md)：仅靠状态字段判断有效性，
无法发现"正文改了但状态没改"这类最常见的脱节。

## 后果

- 评审成为显式动作，团队需要约定"改完规格要重新评审"；
- 哈希只覆盖正文，格式调整不会误报；
- 代价是评审记录要有人维护，靠 `sddctx doctor` 把漏掉的挑出来。

