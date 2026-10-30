# Embedding 请求合并与向量缓存

`powercontext.builtin.inference.coalescing.CoalescingEmbeddingModel` 包装现有模型，不改变未使用包装器的路径。包装器暴露原 `profile`，使用 `embed(texts)` 返回原顺序的向量和 `InferenceUsage`；同一包装器在一个事件循环内使用。

待处理和执行中的文本共享 Future。收集窗口结束后，按 `max_batch_size` 将不同文本拆成独立 provider 请求；窗口为零时仍在下一事件循环轮次派发，使同步启动的调用能够合并。不同批次独立完成，某批失败只影响依赖该批的调用。向量数量错误以 `ValueError` 失败，失败文本清除执行中身份并允许后续重试。

每个调用用 `asyncio.shield` 等待共享结果，因此取消该调用不取消其他等待者所需的工作。成功向量进入容量为 `cache_size` 的 LRU；读取更新最近使用顺序，零容量只关闭成功缓存，保留执行中的共享。输入中的重复位置在返回时恢复，不重复请求。

用量按本调用实际等待的不同 provider 批次汇总。同批多个文本只计一次，多个等待者各自保留该批的 request 和 token 数；纯缓存命中和空输入不增加请求。可用的 token 计数按字段求和，没有该字段数据时保留 `None`。

固定依赖云端环境的 8 项公开测试通过，其中原生集成检查六个 scope 同时写入相同的 24 条文本、每批最多六条时恰好调用底层四次，之后缓存查询不新增调用。补充测试通过，覆盖同步零窗口、晚到调用、缓存关闭、取消隔离、局部 provider 失败、错误向量数量和原样 provider 用量。结果验证真实 Memory 集成与离线 provider 合同，未使用在线模型。
