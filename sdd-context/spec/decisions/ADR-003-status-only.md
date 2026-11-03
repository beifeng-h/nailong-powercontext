---
id: ADR-003
title: 仅靠 status 字段判断规格有效性
status: superseded
decided_at: 2026-10-20
scope: [drift, ingestion]
tags: [drift, lifecycle]
supersedes: []
superseded_by: ADR-002
---

# ADR-003 仅靠 status 字段判断规格有效性

## 背景

最省事的做法：规格 frontmatter 里写 `status: active`，只有 active 的规格
可以进上下文，其余一律排除。

## 决策

采用该方案，认为状态字段足以表达"当前有效"。

## 为什么被取代

这个方案有个致命漏洞：**规格正文改了，状态往往忘了改**。
于是助手拿着"已经作废的条款"当成硬性要求继续实现，而且没有任何信号提示它。

2026-11-03 由 [ADR-002](ADR-002-validity-by-hash-and-review.md) 取代：
在状态之外引入"内容哈希 + 评审基线"，把"改完没评审"变成可检测的漂移。

> 本决策已失效，不要再依据它修改代码。

