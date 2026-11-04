# 脱敏上下文和业务测试副本

本目录为真实运行记录的派生副本，原始字节保留在本地未修改。来源和原始/派生 SHA-256 见 [MANIFEST.json](MANIFEST.json)。其中 classification/publication 字段描述原审阅时的限制，不代表当前候选已经获得发布授权。

交付的 [context.redacted.json](context.redacted.json) SHA-256 为 `d0e5ae892e6310bdb95e4ab4603aab7cb00775a71ed6b5da7653aec7d8e53281`；其结构和值与实际 [请求](../request.json) 中的 retrieved_context 一致。原始上下文只替换了解释器路径和 cwd 两个字段后用于请求；原始上下文本身不在候选中。

[同轮测试回执](tests/RECEIPT.redacted.json)和四份 stdout/stderr 副本属于模型调用后的固定对照：before 3 项目标失败、6 项回归通过，after 9 项通过。回执内 stdoutSha256/stderrSha256 是原始日志指纹，MANIFEST 的 derived_file_sha256 才核验当前交付日志。部分原日志无需替换，因此其源与派生 hash 可能相同。

完整调用说明见 [上级 README](../README.md)。这些材料不是完整干净环境或官方评测通过的声明。
