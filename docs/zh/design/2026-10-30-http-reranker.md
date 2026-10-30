# HTTP 评分重排

`HTTPMemoryReranker` 实现既有 `MemoryReranker`，由调用方提供 `httpx.AsyncClient` 并负责关闭，不新增网络服务或依赖。通过 `memory_reranker` 注入 Runtime 后，原搜索流程根据选中的整数 rank 返回原 Memory hit，正文、条目和版本不变。

每批按 `batch_size` 拆分，rank 始终为完整输入的一基序号。逐批校验响应必须仅含 `scores`，每项仅含严格整数 `rank` 与有限数值 `score`，且恰好覆盖本批全部 rank 一次。所有批次收齐后按分数降序、全局 rank 升序统一选择。usage 记录实际请求数，非成功 HTTP 状态与网络错误保留 httpx 异常，坏 JSON、字段或覆盖错误以 `ValueError` 失败。

固定依赖云端环境的 10 项公开 HTTP 测试通过，补充的类型、状态错误和坏 JSON 测试也已通过。公开测试只证明合同与样例行为，SciFact 正式 Recall@10 和 MRR@10 仍需平台验收。没有读取相关性标注或按文档、query 硬编码。
