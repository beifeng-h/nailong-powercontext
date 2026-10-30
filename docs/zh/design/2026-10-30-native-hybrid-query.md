# seekdb 单 statement 混合候选查询

`OceanBaseMemoryHybridIndex` 组合现有全文和向量索引，仅替换 `mode="hybrid"` 的候选读取。单通道请求仍交由原策略处理；索引初始化、增量写入、删除、向量完整性检查及正文回查沿用现有实现。

混合查询是一条 `UNION ALL` statement。全文分支使用 `MATCH ... AGAINST`，按原相关分数和稳定身份排序；向量分支使用 `l2_distance ... APPROXIMATE`。两支分别在数据库内应用 scope、Memory artifact 集合、可选 tag 条件和候选上限。外层按通道、分数或距离及身份排序，把两个有序通道交给现有 RRF 融合，跨通道的相同身份仍由现有融合去重。

旧投影中的 `head_revision` 不作为过滤条件。增量更新可以保留未变条目的旧投影修订，原 backend 在候选前后核对请求的当前 Memory head，`memory_channel_hits` 将命中映射到该已核对的请求引用。修订、停用、恢复仍使用原生事务中的投影更新和真实版本正文，不伪造引用。

带 tag 的混合向量分支也保留 ANN 表达式；单通道带 tag 的既有查询保持不变。在固定 `pylibseekdb==1.3.0.post4` 云端环境，1 项公开测试及多 head/tag 补充测试通过。默认与带 tag 的真实 EXPLAIN 均同时出现 `TEXT RETRIEVAL SCAN`、`VECTOR INDEX`，并通过数据库内 scope、artifact、tag 过滤与候选限额检查。

补充测试通过真实 Runtime 建立多份 Memory artifact、其他 scope 与未请求 artifact，检查多 head、旧投影、稳定身份、去重、tag 筛选及两路索引计划。真实语料 Recall@10、逐查询 MRR 和完整搜索延迟仍须平台验收；一条 statement 或静态 SQL 检查不等于检索质量或端到端加速已经通过。
