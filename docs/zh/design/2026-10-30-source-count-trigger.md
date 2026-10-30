# 按新增来源条目数启动原生处理

`RuntimeConfig.memory_source_count_threshold` 与 `topic_memory_source_count_threshold` 默认均为 `None`。启用时必须提供严格正整数，布尔值、字符串和浮点数不能代替整数。

数量判断只读取已持久化的 Source journal head 和相应处理族最后成功提交的 cursor。差值达到门槛，Supervisor 就在原有 intent 中接受一次调用，再交给现有原生 worker。Source 身份重放和 receipt 信任升级不推进 journal，lineage 来源则正常占据一个位置；生成阶段仍沿用已有来源资格过滤。

数量发现使用独立的有界 dirty-scope 扫描，不改时间扫描的 checkpoint。两种条件按 OR 生效；显式 flush 的请求及已经接受的失败重试绕过数量条件。单进程 Supervisor 对启用数量条件的绑定每秒检查元数据，因此不依赖某一写入入口是否发出唤醒通知。

Memory worker 仍只消费一个配置窗口，成功提交 cursor 后按剩余条目数重新判断，未达门槛不会持续排空。Topic Memory worker 保留已有的冻结 target 和分窗 wave，一个已接受的 target 完整执行，不在中间窗口重新施加门槛。失败不推进成功 cursor；已接受请求和 Topic target 的原生持久化负责重启恢复。

固定依赖云端环境的 17 项公开测试通过，实际运行原生 worker、离线 provider 与持久化故障场景。补充测试通过，覆盖按 scope/family 的 cursor 独立计数、单窗后重新判断、未发出 wake 的后续输入及显式请求绕过门槛。
