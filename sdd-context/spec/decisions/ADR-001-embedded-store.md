---
id: ADR-001
title: 上下文默认存在嵌入式 SQLite，而不是外部数据库实例
status: accepted
decided_at: 2026-11-03
scope: [store]
tags: [store, sqlite, deployment]
supersedes: []
superseded_by:
---

# ADR-001 上下文默认存在嵌入式 SQLite

## 背景

上下文管理系统要保存规格、决策、代码索引与评审记录。选项有三个：

1. 嵌入式 SQLite（标准库自带，文件即数据库）；
2. 外部数据库实例（OceanBase / MySQL / PostgreSQL）；
3. 纯文件（JSON / Markdown + grep）。

## 决策

**默认使用嵌入式 SQLite**，库文件落在 `.sddctx/context.db`。

理由：

- 这套系统的价值在"检索与体检"，不在"扛并发写"，嵌入式库完全够用；
- 不依赖任何外部实例意味着 `clone` 下来就能跑，评审、演示、CI 都不需要准备环境；
- 标准库自带，没有第三方依赖，`python -m sddctx refresh` 一条命令就能建库；
- 存储层是 `ContextStore` 协议，需要接实例时用 `sddctx/sqlstore.py` 的
  DB-API 适配器替换即可，resolver / drift / assistant 都不用改。

## 后果

- 单机单用户场景最合适；多人共享上下文需要切到外部实例；
- 迁移到外部实例时，schema 由 `sddctx/sqlstore.py` 负责，字段与嵌入式版本一一对应。

